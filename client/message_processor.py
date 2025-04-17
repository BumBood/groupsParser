import logging
import asyncio
from typing import Optional, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor

from telethon.tl.types import Message

from aiogram import Bot
from db.database import Database
from db.models import Project, ProjectChat
from bot.utils.tariff_checker import TariffChecker


class MessageProcessor:
    """Класс для обработки и отправки сообщений пользователям"""

    def __init__(self, db: Database, bot: Bot):
        self.db = db
        self.bot = bot
        self.logger = logging.getLogger(__name__)
        # Семафор для ограничения количества одновременных отправок сообщений
        self.send_semaphore = asyncio.Semaphore(10)
        # Кэш проектов и чатов для уменьшения обращений к БД
        self.project_cache = {}
        self.chat_cache = {}
        # Кэш для статусов тарифов пользователей
        self.tariff_status_cache: Dict[int, Tuple[bool, float]] = {}
        # Время жизни кэша в секундах
        self.cache_ttl = 60
        # Время жизни кэша тарифов в секундах (10 минут)
        self.tariff_cache_ttl = 600
        # Время последнего обновления кэша
        self.last_cache_update = 0
        # Число-количество обрабатываемых одновременно сообщений
        self.workers = 20
        # ThreadPoolExecutor для обработки ключевых слов
        self.executor = ThreadPoolExecutor(max_workers=self.workers)

    async def process_message(
        self,
        message: Message,
        project_id: int,
        chat_id: int,
        keywords: Optional[str] = None,
    ) -> bool:
        """Обрабатывает новое сообщение и отправляет его пользователям при соответствии фильтрам"""
        try:
            self.logger.debug(
                f"Начало обработки сообщения для проекта {project_id}, чата {chat_id}"
            )

            # Получаем проект и чат из кэша или БД
            project = await self._get_project(project_id)
            chat = await self._get_chat(chat_id)

            if not project or not project.is_active or not chat or not chat.is_active:
                self.logger.warning(
                    f"Проект или чат неактивен: project_id={project_id}, chat_id={chat_id}"
                )
                return False

            # Выполняем проверку ключевых слов в отдельном потоке через ThreadPoolExecutor
            text = message.text or ""
            self.logger.debug(
                f"Проверка текста сообщения (длина {len(text)}) на соответствие ключевым словам: {keywords}"
            )

            if keywords:
                matches = await asyncio.get_event_loop().run_in_executor(
                    self.executor, self._matches_keywords, text, keywords
                )
                if not matches:
                    self.logger.debug("Сообщение не соответствует ключевым словам")
                    return False
            elif not text:
                self.logger.debug("Пустой текст сообщения, пропускаем")
                return False

            # Проверяем активность тарифа пользователя через кэш
            user_id = project.user_id
            has_active_tariff = await self._check_tariff_active(user_id)

            # Форматируем сообщение для отправки
            self.logger.debug("Форматирование сообщения для отправки")

            if has_active_tariff:
                formatted_message = await self._format_message(message, chat, keywords)
            else:
                # Если тариф не активен, заменяем сообщение на уведомление
                formatted_message = "⚠️ <b>Тут могло быть сообщение, но у вас кончился тариф!</b>\n\nДля получения полных сообщений, пожалуйста, продлите свой тариф."
                self.logger.debug(
                    f"Заменено сообщение для пользователя {user_id} из-за неактивного тарифа"
                )

            # Отправляем сообщение пользователю с использованием семафора
            self.logger.debug(f"Отправка сообщения пользователю {user_id}")

            async with self.send_semaphore:
                # Добавляем повторные попытки отправки сообщения при ошибках
                max_retries = 3
                retry_delay = 1  # секунда

                for attempt in range(max_retries):
                    try:
                        await self.bot.send_message(
                            user_id,
                            formatted_message,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                        self.logger.info(
                            f"Сообщение из чата {chat.chat_title or chat.chat_id} отправлено пользователю {user_id}"
                        )
                        return True
                    except Exception as e:
                        if attempt < max_retries - 1:
                            self.logger.warning(
                                f"Ошибка при отправке сообщения (попытка {attempt+1}/{max_retries}): {str(e)}"
                            )
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Увеличиваем задержку между попытками
                        else:
                            # Последняя попытка не удалась, логируем ошибку
                            self.logger.error(
                                f"Не удалось отправить сообщение после {max_retries} попыток: {str(e)}"
                            )
                            return False

        except Exception as e:
            self.logger.error(f"Ошибка при обработке сообщения: {str(e)}")
            return False

    async def _check_tariff_active(self, user_id: int) -> bool:
        """Проверяет активность тарифа пользователя с использованием кэша"""
        current_time = asyncio.get_event_loop().time()

        # Проверяем кэш
        if user_id in self.tariff_status_cache:
            status, timestamp = self.tariff_status_cache[user_id]
            if current_time - timestamp < self.tariff_cache_ttl:
                return status

        # Если нет в кэше или кэш устарел, проверяем через БД
        is_active = TariffChecker.is_tariff_active(user_id, self.db)

        # Обновляем кэш
        self.tariff_status_cache[user_id] = (is_active, current_time)

        return is_active

    async def _get_project(self, project_id: int) -> Optional[Project]:
        """Получает проект из кэша или БД"""
        # Проверяем кэш
        current_time = asyncio.get_event_loop().time()
        if project_id in self.project_cache:
            project, timestamp = self.project_cache[project_id]
            if current_time - timestamp < self.cache_ttl:
                return project

        # Получаем из БД
        project = self.db.get_project(project_id)
        if project:
            self.project_cache[project_id] = (project, current_time)
        return project

    async def _get_chat(self, chat_id: int) -> Optional[ProjectChat]:
        """Получает чат из кэша или БД"""
        # Проверяем кэш
        current_time = asyncio.get_event_loop().time()
        if chat_id in self.chat_cache:
            chat, timestamp = self.chat_cache[chat_id]
            if current_time - timestamp < self.cache_ttl:
                return chat

        # Получаем из БД
        chat = self.db.get_chat(chat_id)
        if chat:
            self.chat_cache[chat_id] = (chat, current_time)
        return chat

    def _matches_keywords(self, text: str, keywords: Optional[str]) -> bool:
        """Проверяет, соответствует ли текст сообщения ключевым словам"""
        if not keywords or not text:
            # Если ключевые слова не указаны, считаем, что сообщение подходит
            return True

        # Разбиваем ключевые слова на список (разделитель - запятая)
        keyword_list = [k.strip().lower() for k in keywords.split(",") if k.strip()]
        if not keyword_list:
            return True

        # Приводим текст к нижнему регистру для поиска
        text_lower = text.lower()

        # Проверяем наличие хотя бы одного ключевого слова в тексте
        return any(keyword in text_lower for keyword in keyword_list)

    async def _format_message(
        self, message: Message, chat: ProjectChat, keywords: Optional[str] = None
    ) -> str:
        """Форматирует сообщение для отправки пользователю"""

        message_id = message.id

        sender = message.sender
        sender_name = sender.first_name or "Нет имени"
        sender_username = sender.username or "Нет юзернейма"
        sender_id = sender.id

        # Форматируем текст сообщения
        message_text = message.text or message.message or ""

        # Переменная для хранения части текста с ключевым словом
        keyword_text_snippet = ""
        # Выделяем только первое найденное ключевое слово, если они есть
        matching_keywords = []
        if keywords and message_text:
            keyword_list = [k.strip().lower() for k in keywords.split(",") if k.strip()]
            if keyword_list:
                message_text_lower = message_text.lower()
                # Ищем первое вхождение любого ключевого слова
                first_keyword = None
                first_pos = -1

                for keyword in keyword_list:
                    pos = message_text_lower.find(keyword)
                    if pos != -1 and (first_pos == -1 or pos < first_pos):
                        first_pos = pos
                        first_keyword = keyword

                if first_keyword:
                    matching_keywords.append(first_keyword)
                    # Получаем оригинальное написание ключевого слова из текста
                    original_keyword = message_text[
                        first_pos : first_pos + len(first_keyword)
                    ]

                    # Определяем конец фрагмента (ключевое слово + 184 символов после него)
                    end_pos = min(
                        first_pos + len(first_keyword) + 184, len(message_text)
                    )

                    # Формируем фрагмент текста
                    prefix = "..." if first_pos > 0 else ""
                    suffix = "..." if end_pos < len(message_text) else ""

                    # Создаем выделенный фрагмент текста для отображения
                    keyword_text_snippet = f"{prefix}<pre>{original_keyword}{message_text[first_pos + len(first_keyword):end_pos]}</pre>{suffix}"

        # Если ключевые слова не найдены, но есть текст, берем первые 184 символов
        if not keyword_text_snippet and message_text:
            end_pos = min(184, len(message_text))
            suffix = "..." if end_pos < len(message_text) else ""
            keyword_text_snippet = f"<pre>{message_text[:end_pos]}</pre>{suffix}"

        formatted_message = (
            "🔔 Получено сообщение в чате 🤑\n\n"
            f"👤 Отправитель: {sender_name} (@{sender_username})\n\n"
            f"🔑 Сработавшие ключи: {matching_keywords or 'Нет ключей'}\n\n"
            f"🔗 <a href='https://t.me/{message.chat.username}/{message_id}'>Перейти к сообщению</a>\n"
            f"💬 <a href='tg://user?id={sender_id}'>Написать отправителю</a>\n\n"
            f"📰 Сообщение: {keyword_text_snippet}\n\n"
        )
        return formatted_message

    def clear_cache(self):
        """Очищает все кэши"""
        self.project_cache.clear()
        self.chat_cache.clear()
        self.tariff_status_cache.clear()
        self.logger.info("Кэш проектов, чатов и статусов тарифов очищен")
