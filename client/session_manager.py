import asyncio
import logging
import os
import glob
from typing import Optional, Dict, Tuple, Set
from telethon import TelegramClient, events
import json
from random import shuffle
from collections import defaultdict
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from db.database import Database


class SessionManager:
    """Базовый класс для управления сессиями Telegram"""

    def __init__(self, sessions_dir: str = "sessions"):
        self.sessions_dir = sessions_dir
        self.active_sessions = set()
        self.logger = logging.getLogger(__name__)
        os.makedirs(self.sessions_dir, exist_ok=True)

    async def get_available_session(self) -> Optional[TelegramClient]:
        """Находит и возвращает доступный клиент сессии"""
        self.logger.debug(f"Поиск доступной сессии в директории: {self.sessions_dir}")
        # Получаем список всех .session файлов
        session_files = glob.glob(os.path.join(self.sessions_dir, "*.session"))

        # Если нет сессий, возвращаем None
        if not session_files:
            self.logger.warning("Не найдено ни одного .session файла")
            return None

        shuffle(session_files)

        # Ищем первую свободную сессию
        for session_file in session_files:
            session_name = os.path.splitext(os.path.basename(session_file))[0]
            if session_name not in self.active_sessions:
                self.logger.info(f"Найдена свободная сессия: {session_name}")

                with open(os.path.join(self.sessions_dir, f"{session_name}.json")) as f:
                    session_data = json.load(f)
                client = TelegramClient(
                    os.path.join(self.sessions_dir, session_name),
                    api_id=session_data["app_id"],
                    api_hash=session_data["app_hash"],
                )
                self.logger.info(f"Сессия {session_name} получила задание")
                self.active_sessions.add(session_name)

                await client.connect()
                if await client.is_user_authorized():
                    return client
                else:
                    await client.disconnect()
                    self.active_sessions.remove(session_name)
                    self.logger.warning(f"Сессия {session_name} не авторизована")

        self.logger.warning("Все сессии заняты")
        return None

    async def release_session(self, client: TelegramClient) -> None:
        """Освобождает сессию после использования"""
        if not client:
            return

        session_name = os.path.splitext(os.path.basename(client.session.filename))[0]

        self.logger.debug(f"Освобождение сессии: {session_name}")
        await client.disconnect()
        if session_name in self.active_sessions:
            self.active_sessions.remove(session_name)
            self.logger.info(f"Сессия {session_name} успешно освобождена")

    def get_sessions_info(self) -> list:
        """Возвращает информацию о всех доступных сессиях"""
        sessions_info = []
        session_files = glob.glob(os.path.join(self.sessions_dir, "*.session"))

        for session_file in session_files:
            session_name = os.path.splitext(os.path.basename(session_file))[0]
            json_path = os.path.join(self.sessions_dir, f"{session_name}.json")

            if os.path.exists(json_path):
                try:
                    with open(json_path) as f:
                        session_data = json.load(f)

                    sessions_info.append(
                        {
                            "session_name": session_name,
                            "phone": session_data.get("phone", "Неизвестно"),
                            "username": session_data.get("username", "Неизвестно"),
                            "first_name": session_data.get("first_name", ""),
                            "last_name": session_data.get("last_name", ""),
                            "is_active": session_name in self.active_sessions,
                        }
                    )
                except json.JSONDecodeError:
                    self.logger.error(
                        f"Ошибка чтения JSON файла для сессии {session_name}"
                    )

        return sessions_info

    def __del__(self):
        for session_name in list(self.active_sessions):
            self.logger.info(f"Освобождение сессии: {session_name}")


class HistorySessionManager(SessionManager):
    """Класс для управления сессиями, используемыми для парсинга истории сообщений"""

    def __init__(self, sessions_dir: str = "client/sessions/history"):
        super().__init__(sessions_dir)


class RealTimeSessionManager:
    """Класс для управления сессиями, используемыми для парсинга в реальном времени"""

    def __init__(self, db: Database, sessions_dir: str = "client/sessions/realtime"):
        self.db = db
        self.sessions_dir = sessions_dir
        self.logger = logging.getLogger(__name__)
        # Сохраняем активные клиенты в формате {session_name: client}
        self.active_clients: Dict[str, TelegramClient] = {}
        # Отслеживаем сессии для каждого чата {chat_id: session_name}
        self.chat_sessions: Dict[int, str] = {}
        # Отслеживаем чаты для каждой сессии {session_name: set(chat_ids)}
        self.session_chats: Dict[str, Set[int]] = defaultdict(set)
        # Сохраняем активные проекты в формате {project_id: set(chat_ids)}
        self.active_projects: Dict[int, Set[int]] = defaultdict(set)
        # Обработчик сообщений
        self.message_processor = None
        # Флаг работы системы
        self.running = False
        # Бот для отправки уведомлений
        self.bot = None

    async def initialize(self, message_processor, bot=None):
        """Инициализация менеджера сессий реального времени"""
        self.message_processor = message_processor
        self.bot = bot
        # Создаем директорию для сессий, если её нет
        os.makedirs(self.sessions_dir, exist_ok=True)

        # Запускаем систему
        self.running = True

        # Проверяем, что все необходимые компоненты инициализированы
        if not self.message_processor:
            self.logger.error("Не удалось инициализировать обработчик сообщений!")
            return False

        self.logger.info("Менеджер сессий инициализирован")
        return True

    async def _handle_new_message(
        self, event, project_id: int, chat_id: int, keywords: Optional[str]
    ):
        """Обработчик новых сообщений, асинхронно обрабатывает их"""
        try:
            # Проверяем, активен ли проект и чат
            project = self.db.get_project(project_id)
            chat = self.db.get_chat(chat_id)

            if not project or not project.is_active or not chat or not chat.is_active:
                # Отключаем мониторинг неактивных чатов
                asyncio.create_task(self.stop_monitoring_chat(chat_id))
                return

            # Проверяем, инициализирован ли обработчик сообщений
            if not self.message_processor:
                self.logger.error("Обработчик сообщений не инициализирован!")
                return

            # Создаем задачу для асинхронной обработки сообщения
            asyncio.create_task(
                self._process_message(event.message, project_id, chat_id, keywords)
            )
            self.logger.debug("Создана задача для обработки сообщения")

        except Exception as e:
            self.logger.error(f"Ошибка при обработке нового сообщения: {str(e)}")

    async def _process_message(self, message, project_id, chat_id, keywords):
        """Обрабатывает одно сообщение асинхронно"""
        try:
            message_id = getattr(message, "id", "unknown")
            self.logger.info(
                f"Начало обработки сообщения #{message_id} для проекта {project_id}, чата {chat_id}"
            )
            result = await self.message_processor.process_message(
                message, project_id, chat_id, keywords
            )
            self.logger.info(
                f"Завершена обработка сообщения #{message_id}, результат: {result}"
            )
            return result
        except Exception as e:
            self.logger.error(
                f"Ошибка при обработке сообщения #{getattr(message, 'id', 'unknown')}: {str(e)}"
            )
            return False

    async def start_monitoring_project(self, project_id: int) -> bool:
        """Запускает мониторинг сообщений для проекта"""
        project = self.db.get_project(project_id)
        if not project or not project.is_active:
            self.logger.warning(f"Проект {project_id} не найден или неактивен")
            return False

        # Получаем все активные чаты проекта
        chats = self.db.get_project_chats(project_id, active_only=True)
        if not chats:
            self.logger.warning(f"В проекте {project_id} нет активных чатов")
            return False

        self.logger.info(
            f"Запуск мониторинга для проекта {project_id} ({project.name}) с {len(chats)} чатами"
        )

        # Запускаем мониторинг для каждого чата
        monitored_chats = 0
        for chat in chats:
            try:
                success = await self.start_monitoring_chat(chat.id, project_id)
                if success:
                    monitored_chats += 1
                else:
                    self.logger.warning(
                        f"Не удалось запустить мониторинг чата {chat.id} ({chat.chat_title})"
                    )
            except Exception as e:
                self.logger.error(
                    f"Ошибка при запуске мониторинга чата {chat.id}: {str(e)}"
                )

        success_rate = f"{monitored_chats}/{len(chats)}"
        self.logger.info(
            f"Мониторинг запущен для {success_rate} чатов проекта {project_id}"
        )

        # Возвращаем True, если хотя бы для одного чата запущен мониторинг
        return monitored_chats > 0

    async def stop_monitoring_project(self, project_id: int) -> bool:
        """Останавливает мониторинг сообщений для проекта"""
        if project_id not in self.active_projects:
            return False

        # Останавливаем мониторинг всех чатов проекта параллельно
        chat_ids = list(self.active_projects[project_id])
        tasks = [self.stop_monitoring_chat(chat_id) for chat_id in chat_ids]
        await asyncio.gather(*tasks)

        # Удаляем проект из активных
        if project_id in self.active_projects:
            del self.active_projects[project_id]

        return True

    async def _get_or_select_session_for_chat(
        self, chat_id: str
    ) -> Tuple[Optional[TelegramClient], Optional[str]]:
        """Выбирает подходящую сессию для чата"""
        # Проверяем, есть ли уже сессия для этого чата
        if chat_id in self.chat_sessions:
            session_name = self.chat_sessions[chat_id]
            if session_name in self.active_clients:
                return self.active_clients[session_name], session_name

        # Если есть активные клиенты, выбираем сессию с наименьшим количеством чатов
        if self.active_clients:
            # Находим сессию с наименьшим количеством чатов
            best_session = min(
                self.active_clients.keys(), key=lambda s: len(self.session_chats[s])
            )
            return self.active_clients[best_session], best_session

        # Если нет активных клиентов, создаем новую сессию
        client = await self._create_new_session()
        if client:
            session_name = os.path.splitext(os.path.basename(client.session.filename))[
                0
            ]
            return client, session_name

        # Если не удалось создать сессию, возвращаем None
        return None, None

    async def _create_new_session(self) -> Optional[TelegramClient]:
        """Создает новую сессию для мониторинга"""
        session_files = glob.glob(os.path.join(self.sessions_dir, "*.session"))

        if not session_files:
            self.logger.warning(
                f"Не найдено ни одного .session файла в директории: {self.sessions_dir}"
            )
            return None

        self.logger.info(f"Найдено {len(session_files)} .session файлов")
        shuffle(session_files)

        for session_file in session_files:
            session_name = os.path.splitext(os.path.basename(session_file))[0]

            # Пропускаем уже активные сессии
            if session_name in self.active_clients:
                self.logger.debug(f"Сессия {session_name} уже активна, пропускаем")
                continue

            # Проверяем наличие JSON-файла конфигурации
            json_path = os.path.join(self.sessions_dir, f"{session_name}.json")
            if not os.path.exists(json_path):
                self.logger.warning(
                    f"Отсутствует файл конфигурации для сессии {session_name}"
                )
                continue

            try:
                with open(json_path) as f:
                    session_data = json.load(f)

                # Проверяем наличие необходимых данных
                if "app_id" not in session_data or "app_hash" not in session_data:
                    self.logger.warning(
                        f"В конфигурации сессии {session_name} отсутствуют необходимые поля"
                    )
                    continue

                self.logger.debug(
                    f"Пытаемся подключиться используя сессию {session_name}"
                )
                client = TelegramClient(
                    os.path.join(self.sessions_dir, session_name),
                    api_id=session_data["app_id"],
                    api_hash=session_data["app_hash"],
                )

                await client.connect()
                if await client.is_user_authorized():
                    # Сохраняем клиент в словаре активных
                    self.active_clients[session_name] = client
                    self.logger.info(
                        f"Сессия {session_name} активирована для мониторинга"
                    )
                    return client
                else:
                    await client.disconnect()
                    self.logger.warning(f"Сессия {session_name} не авторизована")
            except json.JSONDecodeError:
                self.logger.error(
                    f"Ошибка при чтении JSON файла для сессии {session_name}"
                )
            except Exception as e:
                self.logger.error(
                    f"Ошибка при создании сессии {session_name}: {str(e)}"
                )

        self.logger.warning(
            "Не удалось создать новую сессию для мониторинга. Проверьте файлы сессий и их конфигурацию."
        )
        return None

    async def join_chat(self, chat_id: int) -> bool:
        """
        Пытается вступить в чат

        Args:
            chat_id: ID чата в базе данных

        Returns:
            bool: True если удалось вступить в чат или бот уже состоит в нем,
                 False в случае ошибки
        """
        chat = self.db.get_chat(chat_id)
        if not chat:
            self.logger.warning(f"Чат {chat_id} не найден в базе данных")
            return False

        chat_info = f"id:{chat_id}, title:{chat.chat_title}, chat_id:{chat.chat_id}"
        self.logger.info(f"Попытка подключения к чату: {chat_info}")

        # Получаем подходящую сессию
        client, session_name = await self._get_or_select_session_for_chat(chat.chat_id)
        if not client or not session_name:
            self.logger.error(f"Не удалось получить сессию для чата {chat_info}")
            return False

        try:
            # Пытаемся получить информацию о чате
            self.logger.info(f"Получение данных о чате {chat_info}...")
            try:
                chat_entity = await client.get_entity(chat.chat_id)
                self.logger.info(
                    f"Получены данные о чате: {chat_entity.id} ({type(chat_entity).__name__})"
                )
            except Exception as e:
                self.logger.error(
                    f"Ошибка при получении данных о чате {chat_info}: {str(e)}"
                )
                return False

            # Проверяем, является ли пользователь участником чата
            try:
                dialog = await client.get_dialogs()
                chat_ids = [d.entity.id for d in dialog]

                # Выводим отладочную информацию о диалогах
                self.logger.debug(f"Сессия {session_name} имеет {len(dialog)} диалогов")
            except Exception as e:
                self.logger.error(
                    f"Ошибка при получении диалогов для сессии {session_name}: {str(e)}"
                )
                return False

            # Если сессия уже является участником чата
            if chat_entity.id in chat_ids:
                self.logger.info(
                    f"Сессия {session_name} уже является участником чата {chat_info}"
                )
                return True

            # Пытаемся вступить в группу/канал
            self.logger.info(
                f"Вступаем в чат {chat_info} используя сессию {session_name}..."
            )

            try:
                if hasattr(chat_entity, "username") and chat_entity.username:
                    # Если у чата есть юзернейм, используем его для вступления
                    self.logger.info(f"Вступаем по username: @{chat_entity.username}")
                    await client(JoinChannelRequest(channel=chat_entity))
                else:
                    # Если это приватный чат, пытаемся использовать инвайт-ссылку
                    if chat.invite_link:
                        invite_hash = chat.invite_link.split("/")[-1]
                        self.logger.info(f"Вступаем по инвайт-ссылке: {invite_hash}")
                        await client(ImportChatInviteRequest(hash=invite_hash))
                    else:
                        self.logger.warning(
                            f"Нет возможности вступить в чат {chat_info}: отсутствует юзернейм и инвайт-ссылка"
                        )
                        return False

                self.logger.info(f"Успешно вступили в чат {chat_info}")
                return True

            except Exception as join_error:
                self.logger.error(
                    f"Ошибка при вступлении в чат {chat_info}: {str(join_error)}"
                )
                return False

        except Exception as e:
            self.logger.error(
                f"Не удалось получить информацию о чате {chat_info}: {str(e)}"
            )
            return False

    async def start_monitoring_chat(self, chat_id: int, project_id: int) -> bool:
        """
        Запускает мониторинг сообщений для конкретного чата

        Args:
            chat_id: ID чата в базе данных
            project_id: ID проекта

        Returns:
            bool: True если удалось успешно вступить в чат и добавить его в мониторинг,
                 False в случае ошибки или невозможности вступить в чат
        """
        chat = self.db.get_chat(chat_id)
        project = self.db.get_project(project_id)

        # Проверка наличия и активности чата и проекта
        if not chat:
            self.logger.warning(f"Чат с ID {chat_id} не найден в базе данных")
            return False

        if not project:
            self.logger.warning(f"Проект с ID {project_id} не найден в базе данных")
            return False

        if not chat.is_active:
            self.logger.warning(
                f"Чат {chat_id} ({chat.chat_title}) не активен, мониторинг не запущен"
            )
            return False

        if not project.is_active:
            self.logger.warning(
                f"Проект {project_id} ({project.name}) не активен, мониторинг не запущен"
            )
            return False

        chat_info = f"id:{chat_id}, title:{chat.chat_title}, chat_id:{chat.chat_id}"
        self.logger.info(
            f"Запуск мониторинга для чата {chat_info} в проекте {project_id} ({project.name})"
        )

        # Пропускаем, если чат уже мониторится
        if chat_id in self.chat_sessions:
            self.logger.info(
                f"Чат {chat_info} уже мониторится сессией {self.chat_sessions[chat_id]}"
            )

            # Добавляем чат в активные проекты, если его там нет
            if project_id not in self.active_projects:
                self.active_projects[project_id] = set()

            if chat_id not in self.active_projects[project_id]:
                self.active_projects[project_id].add(chat_id)
                self.logger.info(
                    f"Чат {chat_info} добавлен в активные для проекта {project_id}"
                )

            return True

        # Вступаем в чат, если еще не состоим в нем
        if not await self.join_chat(chat_id):
            self.logger.error(f"Не удалось вступить в чат {chat_info}")
            return False

        # Получаем подходящую сессию
        client, session_name = await self._get_or_select_session_for_chat(chat.chat_id)
        if not client or not session_name:
            self.logger.error(
                f"Не удалось получить сессию для мониторинга чата {chat_info}"
            )
            return False

        try:
            # Проверяем, есть ли у чата ключевые слова для фильтрации
            keywords_info = (
                f"ключевые слова: {chat.keywords}" if chat.keywords else "все сообщения"
            )
            self.logger.info(
                f"Настройка мониторинга для чата {chat_info}, {keywords_info}"
            )

            # Создаем уникальный обработчик для этого чата
            handler_id = client.add_event_handler(
                lambda event: self._handle_new_message(
                    event, project_id, chat_id, chat.keywords
                ),
                events.NewMessage(chats=chat.chat_id),
            )

            # Сохраняем связь чат -> сессия и сессия -> чат
            self.chat_sessions[chat_id] = session_name
            self.session_chats[session_name].add(chat_id)

            # Добавляем чат в активные для проекта
            if project_id not in self.active_projects:
                self.active_projects[project_id] = set()
            self.active_projects[project_id].add(chat_id)

            self.logger.info(
                f"Запущен мониторинг чата {chat_info} для проекта {project_id} ({project.name})"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Ошибка при запуске мониторинга чата {chat_info}: {str(e)}"
            )
            return False

    async def stop_monitoring_chat(self, chat_id: int) -> bool:
        """Останавливает мониторинг сообщений для конкретного чата"""
        # Проверяем, мониторится ли чат
        if chat_id not in self.chat_sessions:
            return False

        session_name = self.chat_sessions[chat_id]
        client = self.active_clients.get(session_name)

        if client:
            # Удаляем все обработчики событий для этого чата
            client.remove_event_handler(None, events.NewMessage(chats=chat_id))

        # Удаляем запись о сессии для чата
        del self.chat_sessions[chat_id]

        # Удаляем чат из списка чатов сессии
        if session_name in self.session_chats:
            self.session_chats[session_name].discard(chat_id)

            # Если сессия больше не используется, освобождаем её
            if (
                not self.session_chats[session_name]
                and session_name in self.active_clients
            ):
                await self._release_session(session_name)

        # Удаляем чат из всех проектов
        for project_id in list(self.active_projects.keys()):
            self.active_projects[project_id].discard(chat_id)

            # Если в проекте не осталось активных чатов, удаляем проект
            if not self.active_projects[project_id]:
                del self.active_projects[project_id]

        self.logger.info(f"Остановлен мониторинг чата {chat_id}")
        return True

    async def _release_session(self, session_name: str) -> None:
        """Освобождает сессию по имени"""
        if session_name in self.active_clients:
            client = self.active_clients[session_name]

            try:
                await client.disconnect()
            except Exception as e:
                self.logger.error(
                    f"Ошибка при отключении сессии {session_name}: {str(e)}"
                )

            del self.active_clients[session_name]
            self.logger.info(f"Сессия {session_name} освобождена")

    async def restart_all_active_projects(self):
        """Перезапускает мониторинг для всех активных проектов"""
        try:
            # Получаем все активные проекты
            projects = self.db.get_all_active_projects()

            if not projects:
                self.logger.info("Нет активных проектов для запуска мониторинга")
                return

            self.logger.info(
                f"Запуск мониторинга для {len(projects)} активных проектов"
            )

            # Останавливаем все текущие мониторинги
            await self.shutdown()

            # Запускаем мониторинги для всех активных проектов
            total_chats = 0
            monitored_chats = 0

            for project in projects:
                # Получаем все активные чаты проекта
                active_chats = self.db.get_project_chats(project.id, active_only=True)

                if not active_chats:
                    self.logger.info(
                        f"В проекте {project.id} ({project.name}) нет активных чатов"
                    )
                    continue

                total_chats += len(active_chats)
                self.logger.info(
                    f"Запуск мониторинга {len(active_chats)} чатов в проекте {project.id} ({project.name})"
                )

                # Запускаем мониторинг для каждого активного чата
                for chat in active_chats:
                    success = await self.start_monitoring_chat(chat.id, project.id)
                    if success:
                        monitored_chats += 1
                    else:
                        self.logger.warning(
                            f"Не удалось запустить мониторинг чата {chat.id} ({chat.chat_title})"
                        )

            self.logger.info(
                f"Запущен мониторинг {monitored_chats} из {total_chats} чатов в {len(projects)} активных проектах"
            )

        except Exception as e:
            self.logger.error(f"Ошибка при перезапуске активных проектов: {str(e)}")

    async def shutdown(self):
        """Завершает работу всех активных сессий"""
        self.logger.info("Завершение работы менеджера сессий...")
        # Останавливаем обработку сообщений
        self.running = False

        # Отключаем все активные сессии
        disconnect_tasks = []
        for session_name in list(self.active_clients.keys()):
            client = self.active_clients.get(session_name)
            if client:
                disconnect_tasks.append(self._disconnect_client(client, session_name))

        # Ждем завершения всех задач отключения с таймаутом
        if disconnect_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*disconnect_tasks, return_exceptions=True),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                self.logger.warning("Превышен таймаут при отключении сессий")

        # Очищаем все словари
        self.chat_sessions.clear()
        self.session_chats.clear()
        self.active_projects.clear()
        self.active_clients.clear()

        self.logger.info("Менеджер сессий успешно остановлен")

    async def _disconnect_client(self, client, session_name):
        """Безопасно отключает клиент Telethon"""
        try:
            # Telethon иногда зависает при отключении, используем wait_for
            await asyncio.wait_for(client.disconnect(), timeout=2.0)
            self.logger.info(f"Сессия {session_name} отключена")
        except asyncio.TimeoutError:
            self.logger.warning(f"Таймаут при отключении сессии {session_name}")
            # Принудительно закрываем соединения клиента
            try:
                # Прямое закрытие соединений, если disconnect зависает
                if hasattr(client, "_sender") and hasattr(client._sender, "connection"):
                    if client._sender.connection and hasattr(
                        client._sender.connection, "conn"
                    ):
                        conn = client._sender.connection.conn
                        if hasattr(conn, "close"):
                            conn.close()
                            self.logger.info(
                                f"Соединение сессии {session_name} принудительно закрыто"
                            )

                # Принудительное закрытие всех транспортов
                if (
                    hasattr(client, "_sender")
                    and hasattr(client._sender, "_connection")
                    and client._sender._connection
                ):
                    if (
                        hasattr(client._sender._connection, "_send_loop_handle")
                        and client._sender._connection._send_loop_handle
                    ):
                        client._sender._connection._send_loop_handle.cancel()

                    if (
                        hasattr(client._sender._connection, "_recv_loop_handle")
                        and client._sender._connection._recv_loop_handle
                    ):
                        client._sender._connection._recv_loop_handle.cancel()

                # Прямое завершение сокета, если он доступен
                if hasattr(client, "_sender") and hasattr(
                    client._sender, "_connection"
                ):
                    transport = getattr(client._sender._connection, "_transport", None)
                    if transport and hasattr(transport, "close"):
                        transport.close()
                        self.logger.info(
                            f"Транспорт сессии {session_name} принудительно закрыт"
                        )
            except Exception as e:
                self.logger.error(
                    f"Ошибка при принудительном закрытии соединения {session_name}: {str(e)}"
                )
        except Exception as e:
            self.logger.error(f"Ошибка при отключении сессии {session_name}: {str(e)}")
        finally:
            # Удаляем из активных клиентов
            if session_name in self.active_clients:
                del self.active_clients[session_name]


class MonitoringSystem:
    """Система мониторинга сообщений из Telegram чатов в реальном времени"""

    def __init__(self, db: Database, bot=None):
        self.db = db
        self.bot = bot
        self.session_manager = RealTimeSessionManager(db)
        self.message_processor = None
        self.logger = logging.getLogger(__name__)
        self.is_running = False

    async def initialize(self, message_processor):
        """Инициализация системы мониторинга"""
        self.message_processor = message_processor
        # Инициализируем менеджер сессий
        return await self.session_manager.initialize(message_processor, self.bot)
