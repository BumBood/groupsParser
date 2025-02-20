import asyncio
import logging
import os
import glob
from typing import Optional
from telethon import TelegramClient
import json
from random import shuffle

class SessionManager:
    def __init__(self, sessions_dir: str = "sessions"):
        self.sessions_dir = sessions_dir
        self.active_sessions = set()
        self.logger = logging.getLogger(__name__)

    async def get_available_session(self) -> Optional[TelegramClient]:
        """Находит и возвращает путь к свободной session-файлу"""
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
                self.active_sessions.add(client.session.filename)

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
        session_name = os.path.basename(client.session.filename)
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
        for session in self.active_sessions:
            self.logger.info(f"Освобождение сессии: {session}")
            asyncio.create_task(self.release_session(session))
