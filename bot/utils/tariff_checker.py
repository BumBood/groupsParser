import logging
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from db.database import Database
from typing import Optional, List, Dict, Set, Tuple

logger = logging.getLogger(__name__)


class TariffChecker:
    """Класс для проверки сроков действия тарифов пользователей"""

    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db
        self.running = False
        self.task = None
        self.message_processor = None
        # Словарь для отслеживания отправленных уведомлений
        # user_id -> set(notification_types)
        self.notifications_sent: Dict[int, Set[str]] = {}
        # Словарь для отслеживания времени истечения тарифов
        # user_id -> datetime
        self.tariff_expired_times: Dict[int, datetime] = {}
        # Интервал между проверками (30 минут)
        self.check_interval = 30 * 60
        # Интервал для сброса истории уведомлений (24 часа)
        self.reset_notifications_interval = 24 * 60 * 60

    async def start(self, message_processor=None):
        """Запускает периодическую проверку тарифов"""
        if self.running:
            logger.warning("Попытка запустить уже запущенную систему проверки тарифов")
            return

        self.message_processor = message_processor
        self.running = True
        self.task = asyncio.create_task(self._check_loop())
        logger.info("Запущена система проверки тарифов")

    async def stop(self):
        """Останавливает периодическую проверку тарифов"""
        if not self.running:
            logger.warning("Попытка остановить не запущенную систему проверки тарифов")
            return

        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Система проверки тарифов остановлена")
        # Очищаем историю уведомлений при остановке
        self.notifications_sent.clear()
        self.tariff_expired_times.clear()

    async def _check_loop(self):
        """Основной цикл проверки тарифов"""
        last_reset_time = asyncio.get_event_loop().time()

        while self.running:
            try:
                current_time = asyncio.get_event_loop().time()

                # Сбрасываем историю уведомлений каждые 24 часа
                if current_time - last_reset_time >= self.reset_notifications_interval:
                    self.notifications_sent.clear()
                    last_reset_time = current_time
                    logger.info("Очищена история отправленных уведомлений о тарифах")

                # Проверяем тарифы
                await self._check_expiring_tariffs()

                # Проверка каждые 30 минут
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка при проверке тарифов: {str(e)}")
                await asyncio.sleep(
                    300
                )  # При ошибке ждем 5 минут перед повторной попыткой

    async def _check_expiring_tariffs(self):
        """Проверяет срок действия тарифов и отправляет уведомления"""
        now = datetime.now()
        one_day_ahead = now + timedelta(days=1)
        one_hour_ahead = now + timedelta(hours=1)

        # Получаем все активные тарифы
        active_tariffs = self.db.get_all_active_user_tariffs()
        logger.info(f"Проверка {len(active_tariffs)} активных тарифов")

        # Получаем неактивные тарифы для проверки тех, которые истекли 24 часа назад
        inactive_tariffs = self.db.get_inactive_user_tariffs()

        # Проверяем неактивные тарифы для отправки уведомления через 24 часа после истечения
        for user_id, expired_time in list(self.tariff_expired_times.items()):
            # Если прошло 24 часа с момента истечения тарифа
            if now - expired_time >= timedelta(hours=24):
                # Проверяем, не отправляли ли мы уже уведомление через 24 часа после истечения
                if not self._was_notification_sent(user_id, "post_expired"):
                    await self._send_post_expired_notification(user_id)
                    self._mark_notification_sent(user_id, "post_expired")
                # Удаляем из словаря, так как уже отправили
                del self.tariff_expired_times[user_id]

        for tariff in active_tariffs:
            # Проверяем, не истёк ли уже тариф
            if tariff.end_date <= now:
                # Тариф истёк, деактивируем его
                self.db.deactivate_user_tariff(tariff.user_id)

                # Запоминаем время истечения тарифа
                self.tariff_expired_times[tariff.user_id] = now

                # Проверяем, не отправляли ли мы уже уведомление об истечении
                if not self._was_notification_sent(tariff.user_id, "expired"):
                    await self._send_expired_notification(tariff.user_id)
                    self._mark_notification_sent(tariff.user_id, "expired")
                continue

            # Получаем разницу во времени для более точной проверки
            time_diff = tariff.end_date - now
            hours_left = time_diff.total_seconds() / 3600

            # Проверяем истекающие через день тарифы (от 23 до 24 часов)
            if 23 <= hours_left <= 24:
                if not self._was_notification_sent(tariff.user_id, "day"):
                    await self._send_expiring_soon_notification(
                        tariff.user_id, hours_left, "день"
                    )
                    self._mark_notification_sent(tariff.user_id, "day")

            # Проверяем истекающие через час тарифы (от 0.5 до 1 часа)
            elif 0.5 <= hours_left <= 1:
                if not self._was_notification_sent(tariff.user_id, "hour"):
                    await self._send_expiring_soon_notification(
                        tariff.user_id, hours_left * 60, "час"
                    )
                    self._mark_notification_sent(tariff.user_id, "hour")

    def _was_notification_sent(self, user_id: int, notification_type: str) -> bool:
        """Проверяет, было ли отправлено уведомление данного типа пользователю"""
        return (
            user_id in self.notifications_sent
            and notification_type in self.notifications_sent[user_id]
        )

    def _mark_notification_sent(self, user_id: int, notification_type: str):
        """Отмечает, что уведомление данного типа было отправлено пользователю"""
        if user_id not in self.notifications_sent:
            self.notifications_sent[user_id] = set()
        self.notifications_sent[user_id].add(notification_type)
        logger.debug(
            f"Отмечено уведомление типа {notification_type} для пользователя {user_id}"
        )

    async def _send_expiring_soon_notification(
        self, user_id: int, time_left: float, period: str
    ):
        """Отправляет уведомление о скором истечении тарифа"""
        try:
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text="🔍  Продлить подписку",
                            callback_data="buy_tariff",
                        )
                    ]
                ]
            )

            await self.bot.send_message(
                user_id,
                f"⚠️ <b>Внимание!</b>\n\n"
                f"Ваш тариф истекает через {period}.\n"
                f"Не ждите!\n\n"
                f"🔍  Продли подписку прямо сейчас чтобы получать уведомления о новых лидах (заявках) по вашим ключевым словам.",
                reply_markup=keyboard,
            )
            logger.info(
                f"Отправлено уведомление о скором истечении тарифа (через {period}) пользователю {user_id}"
            )
        except Exception as e:
            logger.error(
                f"Ошибка при отправке уведомления о истечении тарифа пользователю {user_id}: {str(e)}"
            )

    async def _send_expired_notification(self, user_id: int):
        """Отправляет уведомление об истечении тарифа"""
        try:
            await self.bot.send_message(
                user_id,
                f"❌ <b>Тариф истёк!</b>\n\n"
                f"Ваш тариф истёк. Теперь вы не будете получать полные уведомления о ключевых словах. "
                f"Чтобы возобновить работу, пожалуйста, продлите свой тариф.",
            )
            logger.info(
                f"Отправлено уведомление об истечении тарифа пользователю {user_id}"
            )
        except Exception as e:
            logger.error(
                f"Ошибка при отправке уведомления об истечении тарифа пользователю {user_id}: {str(e)}"
            )

    async def _send_post_expired_notification(self, user_id: int):
        """Отправляет уведомление через 24 часа после истечения тарифа"""
        try:
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text="Продлить тариф",
                            callback_data="buy_tariff",
                        )
                    ]
                ]
            )

            await self.bot.send_message(
                user_id,
                "Вы пропускаете сотни заявок в день, и мне очень грустно от этого 😢\n\n"
                "Десятки заказчиков ежедневно публикуют объявления по апшим ключевым словам 🙌\n\n"
                "Получите к ним доступ присоединившись к нашему сервису прямо сейчас 🙂",
                reply_markup=keyboard,
            )
            logger.info(
                f"Отправлено уведомление через 24 часа после истечения тарифа пользователю {user_id}"
            )
        except Exception as e:
            logger.error(
                f"Ошибка при отправке уведомления через 24 часа после истечения тарифа пользователю {user_id}: {str(e)}"
            )

    @staticmethod
    def is_tariff_active(user_id: int, db: Database) -> bool:
        """Проверяет, активен ли тариф у пользователя"""
        user_tariff = db.get_user_tariff(user_id)

        if not user_tariff:
            return False

        # Проверяем, не истёк ли срок действия тарифа
        if user_tariff.end_date <= datetime.now() or not user_tariff.is_active:
            # Деактивируем тариф, если он истёк, но ещё активен в БД
            if user_tariff.is_active:
                db.deactivate_user_tariff(user_id)
            return False

        return True

    @staticmethod
    def can_create_project(user_id: int, db: Database) -> tuple[bool, str]:
        """
        Проверяет, может ли пользователь создать новый проект согласно его тарифу

        Args:
            user_id: ID пользователя
            db: Экземпляр базы данных

        Returns:
            Кортеж (может_создать: bool, сообщение: str)
        """
        # Проверяем активность тарифа
        if not TariffChecker.is_tariff_active(user_id, db):
            return False, "Ваш тариф неактивен или истёк"

        # Получаем информацию о тарифе пользователя
        tariff_info = db.get_user_tariff_info(user_id)

        if not tariff_info.get("has_tariff", False):
            return False, "У вас нет активного тарифа"

        # Получаем количество активных проектов
        current_projects = tariff_info.get("current_projects", 0)
        max_projects = tariff_info.get("max_projects", 0)

        # Проверяем, не превышен ли лимит проектов
        if current_projects >= max_projects:
            return False, f"Достигнут лимит проектов ({max_projects}) для вашего тарифа"

        return True, "Можно создать проект"

    @staticmethod
    def can_add_chat_to_project(
        user_id: int, project_id: int, db: Database
    ) -> tuple[bool, str]:
        """
        Проверяет, может ли пользователь добавить новый чат в проект согласно его тарифу

        Args:
            user_id: ID пользователя
            project_id: ID проекта
            db: Экземпляр базы данных

        Returns:
            Кортеж (может_добавить: bool, сообщение: str)
        """
        # Проверяем активность тарифа
        if not TariffChecker.is_tariff_active(user_id, db):
            return False, "Ваш тариф неактивен или истёк"

        # Получаем информацию о тарифе пользователя
        tariff_info = db.get_user_tariff_info(user_id)

        if not tariff_info.get("has_tariff", False):
            return False, "У вас нет активного тарифа"

        # Получаем максимальное количество чатов в проекте
        max_chats_per_project = tariff_info.get("max_chats_per_project", 0)

        # Получаем проект и проверяем, принадлежит ли он пользователю
        project = db.get_project(project_id)
        if not project or project.user_id != user_id:
            return False, "Проект не найден или у вас нет к нему доступа"

        # Получаем количество активных чатов в проекте
        chats = db.get_project_chats(project_id, active_only=True)
        current_chats = len(chats)

        # Проверяем, не превышен ли лимит чатов в проекте
        if current_chats >= max_chats_per_project:
            return (
                False,
                f"Достигнут лимит чатов ({max_chats_per_project}) в проекте для вашего тарифа",
            )

        return True, "Можно добавить чат"
