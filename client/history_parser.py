import asyncio
import logging
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any, AsyncGenerator
from concurrent.futures import ThreadPoolExecutor

from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChatAdminRequiredError, ChannelPrivateError

from client.session_manager import HistorySessionManager


class HistoryParser:
    """Класс для парсинга истории сообщений из чатов Telegram"""

    def __init__(self, sessions_dir: str = "client/sessions/history"):
        self.session_manager = HistorySessionManager(sessions_dir)
        self.logger = logging.getLogger(__name__)
        # Число параллельных задач для обработки сообщений
        self.max_workers = 5
        # ThreadPoolExecutor для тяжелых операций
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        # Размер пакета сообщений для обработки
        self.batch_size = 100
        # Максимальное количество задач на получение сообщений
        self.max_concurrent_tasks = 3
        # Семафор для ограничения количества задач
        self.semaphore = asyncio.Semaphore(self.max_concurrent_tasks)

    async def parse_history(
        self, chat_id: str, limit: Optional[int] = None, keywords: Optional[str] = None
    ) -> AsyncGenerator[Tuple[int, Optional[Dict[str, List[Any]]]], None]:
        """
        Парсит историю сообщений из чата Telegram

        Args:
            chat_id: ID чата или юзернейм канала/группы
            limit: Ограничение по количеству сообщений (None - без ограничения)
            keywords: Ключевые слова для фильтрации сообщений (через запятую)

        Yields:
            Tuple[int, Optional[Dict]]: Прогресс (0-100%) и словарь с данными
        """
        self.logger.info(f"Начало парсинга истории чата: {chat_id}")

        # Получаем свободную сессию
        client = await self.session_manager.get_available_session()
        if not client:
            self.logger.error("Не удалось получить свободную сессию")
            yield 100, None
            return

        try:
            # Проверяем доступность чата
            try:
                entity = await client.get_entity(chat_id)
            except (ValueError, ChannelPrivateError) as e:
                self.logger.error(
                    f"Ошибка при получении информации о чате {chat_id}: {str(e)}"
                )
                yield 100, None
                return

            # Получаем общее количество сообщений (для расчета прогресса)
            try:
                total_messages = await client.get_messages(entity, limit=0)
                total_count = total_messages.total

                if limit and limit < total_count:
                    total_count = limit

                self.logger.info(f"Всего сообщений в чате: {total_count}")

                if total_count == 0:
                    self.logger.warning(f"В чате {chat_id} нет сообщений")
                    yield 100, {"Сообщения": []}
                    return
            except Exception as e:
                self.logger.error(
                    f"Ошибка при получении количества сообщений: {str(e)}"
                )
                yield 100, None
                return

            # Подготавливаем ключевые слова
            keyword_list = []
            if keywords:
                keyword_list = [
                    k.strip().lower() for k in keywords.split(",") if k.strip()
                ]

            # Парсим сообщения пакетами для оптимизации
            messages_data = []
            processed_count = 0
            last_progress = 0

            # Функция для фильтрации сообщений по ключевым словам
            def filter_by_keywords(message_text, keywords):
                if not keywords:
                    return True
                message_text_lower = message_text.lower()
                return any(keyword in message_text_lower for keyword in keywords)

            # Обрабатываем сообщения пакетами для улучшения производительности
            offset_id = 0
            while True:
                async with self.semaphore:
                    # Если достигли лимита, прекращаем загрузку
                    if limit and processed_count >= limit:
                        break

                    # Определяем размер текущего пакета
                    current_limit = min(self.batch_size, total_count - processed_count)
                    if limit:
                        current_limit = min(current_limit, limit - processed_count)

                    if current_limit <= 0:
                        break

                    # Получаем пакет сообщений
                    messages_batch = await client.get_messages(
                        entity, limit=current_limit, offset_id=offset_id
                    )

                    if not messages_batch:
                        break

                    # Обновляем offset_id для следующего пакета
                    if messages_batch:
                        offset_id = messages_batch[-1].id

                    # Создаем задачи на обработку сообщений
                    batch_tasks = []
                    for message in messages_batch:
                        batch_tasks.append(self._process_message(message, keyword_list))

                    # Ожидаем завершения всех задач в пакете
                    batch_results = await asyncio.gather(*batch_tasks)

                    # Добавляем только сообщения, прошедшие фильтрацию
                    for result in batch_results:
                        if result:
                            messages_data.append(result)

                    # Обновляем счетчик обработанных сообщений
                    processed_count += len(messages_batch)

                    # Обновляем прогресс
                    progress = min(int(processed_count / total_count * 100), 100)
                    if progress - last_progress >= 5:
                        last_progress = progress
                        yield progress, None

            # Сортируем сообщения по дате (от новых к старым)
            loop = asyncio.get_event_loop()
            messages_data = await loop.run_in_executor(
                self.executor,
                lambda: sorted(
                    messages_data,
                    key=lambda x: datetime.strptime(x["Дата"], "%d.%m.%Y %H:%M:%S"),
                    reverse=True,
                ),
            )

            # Формируем результат
            result = {
                "Сообщения": messages_data,
                "Информация": [
                    {
                        "Название чата": getattr(entity, "title", chat_id),
                        "Всего сообщений": total_count,
                        "Отфильтровано": len(messages_data),
                        "Ключевые слова": keywords or "Не указаны",
                        "Дата парсинга": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                    }
                ],
            }

            yield 100, result

        except FloodWaitError as e:
            self.logger.warning(f"Ограничение на запросы, ожидание {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
            yield 100, None
        except Exception as e:
            self.logger.error(f"Ошибка при парсинге истории: {str(e)}")
            yield 100, None
        finally:
            # Освобождаем сессию
            await self.session_manager.release_session(client)

    async def _process_message(self, message, keyword_list):
        """Обрабатывает отдельное сообщение и возвращает его данные, если оно проходит фильтр"""
        try:
            # Получаем отправителя
            sender_name = "Неизвестный отправитель"
            sender_username = None

            try:
                if message.sender:
                    sender = await message.get_sender()
                    sender_name = getattr(sender, "first_name", "") or ""
                    if hasattr(sender, "last_name") and sender.last_name:
                        sender_name += f" {sender.last_name}"
                    sender_username = getattr(sender, "username", None)
            except Exception as e:
                self.logger.warning(
                    f"Ошибка при получении информации об отправителе: {str(e)}"
                )

            # Получаем текст сообщения
            message_text = message.text or message.message or ""

            # Фильтруем по ключевым словам, если они указаны
            loop = asyncio.get_event_loop()
            if keyword_list:
                matches = await loop.run_in_executor(
                    self.executor,
                    lambda: any(
                        keyword in message_text.lower() for keyword in keyword_list
                    ),
                )
                if not matches:
                    return None

            # Формируем запись о сообщении
            return {
                "ID сообщения": message.id,
                "Дата": message.date.strftime("%d.%m.%Y %H:%M:%S"),
                "Отправитель": sender_name,
                "Username": f"@{sender_username}" if sender_username else "",
                "Текст": message_text,
            }

        except Exception as e:
            self.logger.error(f"Ошибка при обработке сообщения: {str(e)}")
            return None

    def save_to_excel(self, data: Dict[str, List[Any]], filename: str) -> bool:
        """Сохраняет результаты парсинга в Excel файл"""
        if not data or "Сообщения" not in data:
            self.logger.error("Нет данных для сохранения в Excel")
            return False

        try:
            # Создаем DataFrame для сообщений
            df_messages = pd.DataFrame(data["Сообщения"])

            # Создаем DataFrame для информации
            df_info = pd.DataFrame(data["Информация"])

            # Создаем writer для записи в Excel
            with pd.ExcelWriter(filename, engine="xlsxwriter") as writer:
                # Записываем сообщения на лист "Сообщения"
                df_messages.to_excel(writer, sheet_name="Сообщения", index=False)

                # Записываем информацию на лист "Информация"
                df_info.to_excel(writer, sheet_name="Информация", index=False)

                # Настраиваем ширину столбцов
                for sheet_name in writer.sheets:
                    worksheet = writer.sheets[sheet_name]
                    for i, col in enumerate(
                        df_messages.columns
                        if sheet_name == "Сообщения"
                        else df_info.columns
                    ):
                        max_width = (
                            max(
                                (
                                    df_messages[col].astype(str).map(len).max()
                                    if sheet_name == "Сообщения"
                                    else df_info[col].astype(str).map(len).max()
                                ),
                                len(col),
                            )
                            + 2
                        )
                        worksheet.set_column(i, i, max_width)

            self.logger.info(f"Данные успешно сохранены в файл {filename}")
            return True

        except Exception as e:
            self.logger.error(f"Ошибка при сохранении данных в Excel: {str(e)}")
            return False
