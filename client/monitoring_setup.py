import asyncio
import logging
import glob
import os
import json
from aiogram import Bot

from db.database import Database
from client.session_manager import RealTimeSessionManager
from client.message_processor import MessageProcessor


class MonitoringSystem:
    """Класс для управления системой мониторинга сообщений в реальном времени"""

    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db
        self.logger = logging.getLogger(__name__)
        self.session_manager = None
        self.message_processor = None
        self.running = False
        self.maintenance_task = None
        self.initialized = False

        # Интервал автоматической перезагрузки системы (в часах)
        self.reload_interval = 6  # каждые 6 часов

    async def initialize(self) -> bool:
        """
        Инициализирует и запускает систему мониторинга.
        Возвращает True при успешной инициализации, False в случае ошибки.
        """
        if self.running:
            self.logger.warning("Система мониторинга уже запущена")
            return True

        try:
            self.logger.info("Начало инициализации системы мониторинга...")

            # 1. Создаем процессор сообщений
            self.message_processor = MessageProcessor(self.db, self.bot)
            self.logger.debug("Процессор сообщений создан")

            # 2. Создаем менеджер сессий
            self.session_manager = RealTimeSessionManager(self.db)
            self.logger.debug("Менеджер сессий создан")

            # 3. Инициализируем менеджер сессий, передавая бота для уведомлений о бане
            if not await self.session_manager.initialize(
                self.message_processor, self.bot
            ):
                self.logger.error("Ошибка при инициализации менеджера сессий")
                return False
            self.logger.debug("Менеджер сессий инициализирован")

            # 4. Запускаем мониторинг всех активных проектов
            await self.session_manager.restart_all_active_projects()
            self.logger.debug("Мониторинг активных проектов запущен")

            # Проверяем наличие активных проектов
            active_projects = self.session_manager.active_projects
            self.logger.info(
                f"Запущен мониторинг {len(active_projects)} активных проектов"
            )

            # 5. Запускаем задачу обслуживания
            self.running = True
            self.maintenance_task = asyncio.create_task(self._maintenance_loop())
            self.logger.debug("Задача обслуживания запущена")

            self.initialized = True
            self.logger.info("Система мониторинга успешно инициализирована")
            return True

        except Exception as e:
            self.logger.error(f"Ошибка при инициализации системы мониторинга: {str(e)}")
            # Очищаем состояние в случае ошибки
            await self.stop()
            return False

    async def _maintenance_loop(self):
        """Цикл обслуживания системы мониторинга"""
        self.logger.info("Запущен цикл обслуживания системы мониторинга")

        try:
            while self.running:
                try:
                    # Очищаем кэш обработчика сообщений
                    if self.message_processor:
                        self.message_processor.clear_cache()

                    # Ждем указанный интервал, проверяя флаг выполнения
                    for _ in range(
                        self.reload_interval * 60
                    ):  # Разбиваем на минуты вместо часов
                        if not self.running:
                            self.logger.info(
                                "Обнаружена остановка системы, выходим из цикла обслуживания"
                            )
                            return
                        await asyncio.sleep(60)  # Ждем минуту

                    # Перезагружаем мониторинг проектов, если система еще активна
                    if self.running and self.session_manager:
                        self.logger.info("Плановая перезагрузка системы мониторинга")
                        await self.session_manager.restart_all_active_projects()

                except asyncio.CancelledError:
                    self.logger.info("Задача обслуживания отменена")
                    return
                except Exception as e:
                    self.logger.error(f"Ошибка в цикле обслуживания: {str(e)}")
                    await asyncio.sleep(60)  # Ждем минуту при ошибке
                    # Проверяем, не остановлена ли система во время ожидания
                    if not self.running:
                        return
        except asyncio.CancelledError:
            self.logger.info("Задача обслуживания отменена (внешний обработчик)")
        finally:
            self.logger.info("Цикл обслуживания системы мониторинга остановлен")

    async def stop(self):
        """Останавливает систему мониторинга"""
        if not self.running:
            self.logger.info("Система мониторинга уже остановлена")
            return

        # Устанавливаем флаг остановки
        self.running = False
        self.logger.info("Остановка системы мониторинга...")

        try:
            # Останавливаем задачу обслуживания, если она запущена
            if self.maintenance_task and not self.maintenance_task.done():
                self.logger.debug("Отмена задачи обслуживания")
                # Отменяем задачу и ждем её завершения
                self.maintenance_task.cancel()
                try:
                    # Используем более длительный таймаут и await без shield
                    # для гарантированного завершения
                    await asyncio.wait_for(self.maintenance_task, timeout=2.0)
                    self.logger.debug("Задача обслуживания успешно остановлена")
                except asyncio.TimeoutError:
                    self.logger.error("Таймаут при остановке задачи обслуживания")
                except asyncio.CancelledError:
                    self.logger.debug("Задача обслуживания успешно отменена")
                except Exception as e:
                    self.logger.error(
                        f"Ошибка при остановке задачи обслуживания: {str(e)}"
                    )
                finally:
                    # Удостоверяемся, что задача завершена
                    if not self.maintenance_task.done():
                        self.logger.warning(
                            "Задача обслуживания не завершена, принудительная очистка"
                        )
                    # Очищаем ссылку на задачу в любом случае
                    self.maintenance_task = None
            else:
                self.logger.debug("Задача обслуживания не запущена или уже завершена")

            # Останавливаем менеджер сессий, если он инициализирован
            if self.session_manager:
                self.logger.debug("Останавливаю менеджер сессий")
                try:
                    # Устанавливаем короткий таймаут
                    await asyncio.wait_for(self.session_manager.shutdown(), timeout=3.0)
                except asyncio.TimeoutError:
                    self.logger.error(
                        "Таймаут при остановке менеджера сессий, принудительное закрытие"
                    )

                    # Принудительно очищаем все внутренние структуры
                    if hasattr(self.session_manager, "chat_sessions"):
                        self.session_manager.chat_sessions.clear()
                    if hasattr(self.session_manager, "session_chats"):
                        self.session_manager.session_chats.clear()
                    if hasattr(self.session_manager, "active_projects"):
                        self.session_manager.active_projects.clear()

                    # Принудительно отключаем все клиенты, если они еще существуют
                    if hasattr(self.session_manager, "active_clients"):
                        for session_name, client in list(
                            self.session_manager.active_clients.items()
                        ):
                            try:
                                self.logger.info(
                                    f"Принудительное закрытие клиента {session_name}"
                                )
                                # Устанавливаем флаг остановки для клиента (если он есть)
                                if hasattr(client, "_running"):
                                    client._running = False
                                # Закрываем сеансы и подключения
                                if hasattr(client, "disconnect"):
                                    try:
                                        client.disconnect()
                                    except:
                                        pass
                            except Exception as e:
                                self.logger.error(
                                    f"Ошибка при принудительном закрытии клиента {session_name}: {e}"
                                )
                            finally:
                                try:
                                    # Удаляем клиент из словаря активных клиентов
                                    self.session_manager.active_clients.pop(
                                        session_name, None
                                    )
                                except:
                                    pass
                except Exception as e:
                    self.logger.error(f"Ошибка при остановке менеджера сессий: {e}")

            # Очищаем процессор сообщений, если он существует
            if self.message_processor:
                try:
                    if hasattr(self.message_processor, "clear_cache"):
                        self.message_processor.clear_cache()
                except Exception as e:
                    self.logger.error(
                        f"Ошибка при очистке кэша процессора сообщений: {e}"
                    )

            self.initialized = False
            self.logger.info("Система мониторинга успешно остановлена")
        except Exception as e:
            # Обрабатываем все исключения, но не даем им прервать остановку
            self.logger.error(f"Ошибка при остановке системы мониторинга: {e}")
            self.initialized = False

    async def restart_project(self, project_id: int) -> bool:
        """Перезапускает мониторинг для конкретного проекта"""
        if not self.running or not self.session_manager:
            return False

        # Останавливаем мониторинг проекта
        await self.session_manager.stop_monitoring_project(project_id)

        # Запускаем мониторинг заново
        return await self.session_manager.start_monitoring_project(project_id)

    async def join_chat(self, chat_id: int) -> bool:
        """
        Пытается вступить в чат

        Args:
            chat_id: ID чата в базе данных

        Returns:
            bool: True если удалось вступить в чат,
                 False в случае ошибки
        """
        if not self.running or not self.session_manager:
            return False

        return await self.session_manager.join_chat(chat_id)

    async def add_chat_to_monitoring(self, project_id: int, chat_id: int) -> bool:
        """
        Добавляет чат в мониторинг

        Args:
            project_id: ID проекта
            chat_id: ID чата

        Returns:
            bool: True если удалось успешно вступить в чат и добавить его в мониторинг,
                 False в случае ошибки
        """
        if not self.running or not self.session_manager:
            return False

        return await self.session_manager.start_monitoring_chat(chat_id, project_id)

    async def remove_chat_from_monitoring(self, chat_id: int) -> bool:
        """Удаляет чат из мониторинга"""
        if not self.running or not self.session_manager:
            return False

        return await self.session_manager.stop_monitoring_chat(chat_id)

    async def check_available_sessions(self) -> bool:
        """
        Проверяет наличие доступных сессий для мониторинга.

        Returns:
            bool: True если есть хотя бы одна доступная сессия, иначе False
        """
        if not self.session_manager:
            self.logger.error("Менеджер сессий не инициализирован")
            return False

        # Проверяем наличие файлов сессий в директории
        session_files = glob.glob(
            os.path.join(self.session_manager.sessions_dir, "*.session")
        )
        if not session_files:
            self.logger.warning(
                f"Не найдено сессий в директории {self.session_manager.sessions_dir}"
            )
            return False

        self.logger.info(f"Найдено {len(session_files)} файлов сессий")

        # Проверяем наличие файлов конфигурации
        valid_sessions = 0
        for session_file in session_files:
            session_name = os.path.splitext(os.path.basename(session_file))[0]
            json_file = os.path.join(
                self.session_manager.sessions_dir, f"{session_name}.json"
            )

            if not os.path.exists(json_file):
                self.logger.warning(
                    f"Отсутствует файл конфигурации для сессии {session_name}"
                )
                continue

            try:
                with open(json_file) as f:
                    session_data = json.load(f)

                if "app_id" not in session_data or "app_hash" not in session_data:
                    self.logger.warning(
                        f"Неполная конфигурация для сессии {session_name}"
                    )
                    continue

                valid_sessions += 1
            except Exception as e:
                self.logger.error(
                    f"Ошибка чтения конфигурации сессии {session_name}: {str(e)}"
                )

        if valid_sessions > 0:
            self.logger.info(
                f"Найдено {valid_sessions} доступных сессий для мониторинга"
            )
            return True

        # Если нет валидных сессий, пытаемся создать новую как запасной вариант
        self.logger.warning("Нет валидных сессий, пытаемся создать новую")
        client = await self.session_manager._create_new_session()
        if client:
            # Освобождаем созданную сессию, т.к. мы только проверяем доступность
            session_name = os.path.splitext(os.path.basename(client.session.filename))[
                0
            ]
            await client.disconnect()
            self.logger.info(
                f"Успешно создана и протестирована новая сессия {session_name}"
            )
            return True

        self.logger.error(
            "Не удалось найти или создать доступные сессии для мониторинга"
        )
        return False

    async def get_status(self) -> dict:
        """
        Возвращает текущий статус системы мониторинга

        Returns:
            dict: словарь с информацией о состоянии системы
        """
        status = {
            "initialized": self.initialized,
            "running": self.running,
            "sessions_available": False,
            "active_sessions": 0,
            "active_projects": 0,
            "monitored_chats": 0,
            "error": None,
        }

        try:
            # Проверяем наличие сессий
            if self.session_manager:
                # Количество активных сессий
                if hasattr(self.session_manager, "active_clients"):
                    status["active_sessions"] = len(self.session_manager.active_clients)

                # Количество активных проектов
                if hasattr(self.session_manager, "active_projects"):
                    status["active_projects"] = len(
                        self.session_manager.active_projects
                    )

                    # Количество мониторимых чатов
                    monitored_chats = 0
                    for project_chats in self.session_manager.active_projects.values():
                        monitored_chats += len(project_chats)
                    status["monitored_chats"] = monitored_chats

                # Проверяем доступность сессий
                session_files = glob.glob(
                    os.path.join(self.session_manager.sessions_dir, "*.session")
                )
                if session_files:
                    status["sessions_available"] = True

        except Exception as e:
            status["error"] = str(e)
            self.logger.error(f"Ошибка при получении статуса системы мониторинга: {e}")

        return status


# Функции для совместимости с предыдущей версией API
async def setup_monitoring_system(bot: Bot, db: Database):
    """
    Настраивает и запускает систему мониторинга сообщений в реальном времени

    Args:
        bot: Экземпляр бота aiogram для отправки сообщений пользователям
        db: Экземпляр базы данных
    """
    monitoring_system = MonitoringSystem(bot, db)
    return monitoring_system if await monitoring_system.initialize() else None


async def shutdown_monitoring_system(monitoring_system):
    """
    Останавливает систему мониторинга сообщений в реальном времени

    Args:
        monitoring_system: Экземпляр системы мониторинга
    """
    await monitoring_system.stop()
