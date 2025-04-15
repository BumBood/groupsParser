import logging
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from bot.utils.funcs import notify_admins
from bot.utils.tariff_checker import TariffChecker
from bot.start import router as start_router
from bot.projects import router as projects_router
from bot.project_chats import router as project_chats_router
from bot.history_parse import router as history_parse_router
from bot.admin import router as admin_router
from bot.balance import router as balance_router
from bot.tariffs import router as tariffs_router
from bot.check_channels import router as check_channels_router
from bot.payments import router as payments_router
from config.parameters_manager import ParametersManager
from db.database import Database
from client.monitoring_setup import MonitoringSystem
from datetime import datetime


class InstanceTelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.bot = Bot(
            token=self.token, default=DefaultBotProperties(parse_mode="HTML")
        )
        self.dp = Dispatcher()
        self.db = Database()
        self.monitoring_system = None
        self.tariff_checker = None
        self._setup_logging()
        self._include_routers()

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")],
        )
        self.logger = logging.getLogger(__name__)

    def _include_routers(self):
        """Подключает все роутеры к диспетчеру"""
        self.dp.include_router(start_router)
        self.dp.include_router(projects_router)
        self.dp.include_router(project_chats_router)
        self.dp.include_router(history_parse_router)
        self.dp.include_router(admin_router)
        self.dp.include_router(balance_router)
        self.dp.include_router(tariffs_router)
        self.dp.include_router(check_channels_router)
        self.dp.include_router(payments_router)
        self.logger.info("Роутеры успешно подключены")

    async def _setup_monitoring(self):
        """Настраивает и запускает систему мониторинга проектов"""
        try:
            self.logger.info("Инициализация системы мониторинга...")
            self.monitoring_system = MonitoringSystem(self.bot, self.db)

            # Проверяем наличие сессий перед инициализацией
            sessions_available = await self.monitoring_system.check_available_sessions()
            if not sessions_available:
                self.logger.error("Не найдены доступные сессии для системы мониторинга")
                self.logger.info(
                    "Система мониторинга будет работать в ограниченном режиме"
                )
                # Продолжаем, но предупреждаем пользователя

            # Делаем систему мониторинга доступной через объект бота
            self.bot.monitoring_system = self.monitoring_system

            # Инициализируем систему мониторинга
            if not await self.monitoring_system.initialize():
                self.logger.error("Не удалось инициализировать систему мониторинга")
                # Оставляем объект мониторинга доступным для проверок,
                # но в неинициализированном состоянии
                return

            # Еще раз проверяем доступность сессий, после инициализации
            sessions_available = await self.monitoring_system.check_available_sessions()
            if not sessions_available:
                self.logger.error("После инициализации сессии все еще недоступны")
                self.logger.warning("Мониторинг чатов временно недоступен")
            else:
                self.logger.info(f"Доступны сессии для мониторинга чатов")

            self.logger.info("Система мониторинга успешно запущена")
        except Exception as e:
            self.logger.error(f"Ошибка при инициализации системы мониторинга: {e}")
            # Оставляем объект, даже если произошла ошибка,
            # чтобы можно было проверить его наличие в коде

    async def _setup_tariff_checker(self, message_processor=None):
        """Настраивает и запускает систему проверки тарифов"""
        try:
            self.logger.info("Инициализация системы проверки тарифов...")
            self.tariff_checker = TariffChecker(self.bot, self.db)

            # Запускаем проверку тарифов
            await self.tariff_checker.start(message_processor)

            # Делаем систему проверки тарифов доступной через объект бота
            self.bot.tariff_checker = self.tariff_checker

            # Выполняем первичную проверку тарифов сразу после запуска
            asyncio.create_task(self._perform_initial_tariff_check())

            self.logger.info("Система проверки тарифов успешно запущена")
        except Exception as e:
            self.logger.error(f"Ошибка при инициализации системы проверки тарифов: {e}")

    async def _perform_initial_tariff_check(self):
        """Выполняет первичную проверку тарифов при запуске бота"""
        try:
            self.logger.info("Выполняется первичная проверка тарифов...")
            # Небольшая задержка, чтобы бот успел инициализироваться полностью
            await asyncio.sleep(10)

            # Получаем все активные тарифы
            active_tariffs = self.db.get_all_active_user_tariffs()
            self.logger.info(f"Найдено {len(active_tariffs)} активных тарифов")

            # Проверяем и деактивируем истекшие тарифы
            now = datetime.now()
            deactivated_count = 0

            for tariff in active_tariffs:
                if tariff.end_date <= now:
                    self.db.deactivate_user_tariff(tariff.user_id)
                    deactivated_count += 1

                    # Отправляем уведомление о деактивации
                    try:
                        await self.bot.send_message(
                            tariff.user_id,
                            f"❌ <b>Тариф истёк!</b>\n\n"
                            f"Ваш тариф истёк. Теперь вы не будете получать полные уведомления о ключевых словах. "
                            f"Чтобы возобновить работу, пожалуйста, продлите свой тариф.",
                        )
                    except Exception as e:
                        self.logger.error(
                            f"Ошибка при отправке уведомления пользователю {tariff.user_id}: {e}"
                        )

            self.logger.info(
                f"Первичная проверка тарифов завершена. Деактивировано {deactivated_count} тарифов"
            )
        except Exception as e:
            self.logger.error(f"Ошибка при выполнении первичной проверки тарифов: {e}")

    async def start(self):
        """Запускает бота"""
        try:
            self.logger.info("Бот запускается...")
            # Загружаем параметры
            ParametersManager._load_config()
            self.logger.info("Параметры загружены")

            # Запускаем систему мониторинга
            await self._setup_monitoring()

            # Запускаем систему проверки тарифов
            message_processor = getattr(
                self.monitoring_system, "message_processor", None
            )
            await self._setup_tariff_checker(message_processor)

            # Запускаем бота
            await notify_admins(self.bot, "Бот запущен")

            # Устанавливаем таймаут для всех HTTP-запросов
            self.bot.session._timeout = 10.0  # 10 секунд таймаут

            # Запускаем поллинг бота с обработкой исключений
            try:
                await self.dp.start_polling(self.bot)
            except Exception as e:
                self.logger.error(f"Ошибка при поллинге бота: {e}")
                # Даже при ошибке поллинга продолжаем выполнение блока finally
                # для корректного закрытия ресурсов
        except Exception as e:
            self.logger.error(f"Ошибка при запуске бота: {e}")
            raise
        finally:
            self.logger.info("Выполняется завершение работы бота...")

            await self.monitoring_system.stop()

            if self.tariff_checker:
                await self.tariff_checker.stop()
                self.logger.info("Система проверки тарифов остановлена")

            self.logger.info("Система мониторинга остановлена")

            # Отправляем уведомление о выключении
            await notify_admins(self.bot, "Бот выключен")

            # Закрываем сессию бота с увеличенным таймаутом

            # Освобождаем все циклические ссылки
            self.bot.session.close()

            self.logger.info("Бот успешно остановлен")
