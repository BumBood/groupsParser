from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import os
import zipfile
import rarfile
import shutil
import json
from pathlib import Path
import logging

from db.database import Database
from client.session_manager import (
    SessionManager,
    HistorySessionManager,
    RealTimeSessionManager,
)
from bot.utils.pagination import Paginator

logger = logging.getLogger(__name__)

router = Router(name="admin_sessions")
db = Database()


class AdminSessionStates(StatesGroup):
    waiting_for_archive = State()
    waiting_for_directory_choice = State()


async def validate_sessions(sessions_dir: str) -> tuple[list, list]:
    """
    Проверяет соответствие .session и .json файлов

    Returns:
        tuple[list, list]: (список ошибок, список валидных пар файлов)
    """
    logger.info(f"Начало валидации сессий в директории {sessions_dir}")
    errors = []
    valid_pairs = []

    session_files = set(Path(sessions_dir).glob("*.session"))
    json_files = set(Path(sessions_dir).glob("*.json"))

    logger.debug(f"Найдено .session файлов: {len(session_files)}")
    logger.debug(f"Найдено .json файлов: {len(json_files)}")

    session_names = {f.stem for f in session_files}
    json_names = {f.stem for f in json_files}

    # Проверяем .session файлы без пары
    for name in session_names - json_names:
        error_msg = f"❌ Файл {name}.session не имеет соответствующего .json файла"
        logger.warning(error_msg)
        errors.append(error_msg)

    # Проверяем .json файлы без пары
    for name in json_names - session_names:
        error_msg = f"❌ Файл {name}.json не имеет соответствующего .session файла"
        logger.warning(error_msg)
        errors.append(error_msg)

    # Проверяем валидные пары
    for name in session_names & json_names:
        try:
            with open(f"{sessions_dir}/{name}.json") as f:
                json.load(f)  # Проверяем валидность JSON
            logger.debug(f"Успешно провалидирована пара файлов для сессии {name}")
            valid_pairs.append(name)
        except json.JSONDecodeError:
            error_msg = f"❌ Файл {name}.json содержит невалидный JSON"
            logger.error(error_msg)
            errors.append(error_msg)

    logger.info(
        f"Валидация завершена. Найдено {len(valid_pairs)} валидных пар и {len(errors)} ошибок"
    )
    return errors, valid_pairs


@router.callback_query(F.data == "upload_session")
async def request_archive(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированного доступа к загрузке сессий от пользователя {callback.from_user.id}"
        )
        return

    logger.info(f"Администратор {callback.from_user.id} начал загрузку сессий")
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📁 History (парсинг истории)",
                    callback_data="upload_to_history",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📁 Realtime (мониторинг в реальном времени)",
                    callback_data="upload_to_realtime",
                )
            ],
            [types.InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")],
        ]
    )
    await callback.message.edit_text(
        "📤 Выберите директорию для загрузки сессий:", reply_markup=keyboard
    )
    await state.set_state(AdminSessionStates.waiting_for_directory_choice)


@router.callback_query(
    AdminSessionStates.waiting_for_directory_choice, F.data.startswith("upload_to_")
)
async def handle_directory_choice(callback: types.CallbackQuery, state: FSMContext):
    directory_type = callback.data.replace("upload_to_", "")
    await state.update_data(target_directory=directory_type)

    await callback.message.edit_text(
        f"📤 Отправьте ZIP или RAR архив, содержащий пары файлов .session и .json\n"
        f"⚠️ Существующие сессии с такими же именами будут заменены\n\n"
        f"Выбрана директория: {'История' if directory_type == 'history' else 'Реальное время'}"
    )
    await state.set_state(AdminSessionStates.waiting_for_archive)


@router.message(AdminSessionStates.waiting_for_archive, F.document)
async def handle_archive(message: types.Message, state: FSMContext, bot: Bot):
    user_data = await state.get_data()
    target_directory = user_data.get("target_directory", "history")

    logger.info(
        f"Получен архив с сессиями от администратора {message.from_user.id} для директории {target_directory}"
    )

    if not message.document.file_name.endswith((".zip", ".rar")):
        logger.warning(
            f"Получен неверный формат файла от администратора {message.from_user.id}"
        )
        await message.answer("❌ Отправьте файл с расширением .zip или .rar")
        return

    try:
        logger.debug("Создание временной директории для обработки архива")
        # Создаем временную директорию
        temp_dir = "temp_sessions"
        os.makedirs(temp_dir, exist_ok=True)

        # Скачиваем архив
        archive_path = f"{temp_dir}/archive"
        file = await bot.get_file(message.document.file_id)
        await bot.download_file(file.file_path, archive_path)

        # Распаковываем архив
        extract_dir = f"{temp_dir}/extracted"
        os.makedirs(extract_dir, exist_ok=True)

        if message.document.file_name.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)
        else:
            with rarfile.RarFile(archive_path, "r") as rar_ref:
                rar_ref.extractall(extract_dir)

        # Валидируем файлы
        errors, valid_pairs = await validate_sessions(extract_dir)

        if errors:
            error_text = "Найдены следующие ошибки:\n" + "\n".join(errors)
            await message.answer(error_text)
            return

        if not valid_pairs:
            await message.answer("❌ Не найдено валидных пар файлов session/json")
            return

        # Определяем целевую директорию на основе выбора пользователя
        if target_directory == "history":
            sessions_dir = "client/sessions/history"
        else:
            sessions_dir = "client/sessions/realtime"

        # Создаем целевую директорию, если она не существует
        os.makedirs(sessions_dir, exist_ok=True)

        # Копируем валидные файлы в целевую директорию
        for name in valid_pairs:
            shutil.copy(
                f"{extract_dir}/{name}.session", f"{sessions_dir}/{name}.session"
            )
            shutil.copy(f"{extract_dir}/{name}.json", f"{sessions_dir}/{name}.json")

        await message.answer(
            f"✅ Успешно загружено {len(valid_pairs)} сессий в директорию {target_directory}:\n"
            + "\n".join(f"• {name}" for name in valid_pairs)
        )

    except Exception as e:
        logger.error(f"Ошибка при обработке архива: {str(e)}")
        await message.answer(f"❌ Ошибка при обработке архива: {str(e)}")

    finally:
        # Очищаем временные файлы
        shutil.rmtree(temp_dir, ignore_errors=True)
        await state.clear()
        # Возвращаемся в меню админа
        from .menu import admin_menu

        await admin_menu(message)


@router.callback_query(F.data == "view_sessions")
async def view_sessions(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированного доступа к просмотру сессий от пользователя {callback.from_user.id}"
        )
        return

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📁 History (парсинг истории)",
                    callback_data="view_history_sessions",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📁 Realtime (мониторинг в реальном времени)",
                    callback_data="view_realtime_sessions",
                )
            ],
            [types.InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")],
        ]
    )

    await callback.message.edit_text(
        "📱 Выберите тип сессий для просмотра:", reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("view_"))
async def handle_view_sessions_type(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    session_type = callback.data.replace("view_", "").replace("_sessions", "")
    logger.info(
        f"Администратор {callback.from_user.id} запросил просмотр сессий типа {session_type}"
    )

    # Выбираем директорию в зависимости от типа сессий
    if session_type == "history":
        session_manager = HistorySessionManager()
    else:
        session_manager = RealTimeSessionManager(db)

    sessions = session_manager.get_sessions_info()

    if not sessions:
        logger.info(f"Сессии типа {session_type} не найдены")
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="◀️ Назад", callback_data="view_sessions"
                    )
                ]
            ]
        )
        await callback.message.edit_text(
            f"📱 Сессии в директории {session_type} не найдены",
            reply_markup=keyboard,
        )
        return

    def session_callback(session: dict) -> tuple[str, str]:
        return (
            f"+{session['phone']}",
            f"session_info_{session_type}_{session['session_name']}",
        )

    paginator = Paginator(
        items=sessions,
        items_per_page=4,
        callback_prefix=f"{session_type}_sessions",
        item_callback=session_callback,
        return_callback="view_sessions",
    )

    await callback.message.edit_text(
        f"📱 Список сессий ({session_type}):",
        reply_markup=paginator.get_page_keyboard(0),
    )


@router.callback_query(
    F.data.startswith("history_sessions_page_")
    | F.data.startswith("realtime_sessions_page_")
)
async def handle_sessions_page(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    parts = callback.data.split("_")
    session_type = parts[0]  # history или realtime
    page = int(parts[-1])

    if session_type == "history":
        session_manager = HistorySessionManager()
    else:
        session_manager = RealTimeSessionManager(db)

    sessions = session_manager.get_sessions_info()

    def session_callback(session: dict) -> tuple[str, str]:
        return (
            f"+{session['phone']}",
            f"session_info_{session_type}_{session['session_name']}",
        )

    paginator = Paginator(
        items=sessions,
        items_per_page=4,
        callback_prefix=f"{session_type}_sessions",
        item_callback=session_callback,
        return_callback="view_sessions",
    )

    await callback.message.edit_text(
        f"📱 Список сессий ({session_type}):",
        reply_markup=paginator.get_page_keyboard(page),
    )


@router.callback_query(F.data.startswith("session_info_"))
async def show_session_info(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    # Извлекаем тип сессии и имя сессии
    parts = callback.data.replace("session_info_", "").split("_", 1)
    session_type = parts[0]  # history или realtime
    session_name = parts[1]

    if session_type == "history":
        session_manager = HistorySessionManager()
    else:
        session_manager = RealTimeSessionManager(db)

    sessions = session_manager.get_sessions_info()

    session = next((s for s in sessions if s["session_name"] == session_name), None)
    if not session:
        await callback.answer("Сессия не найдена")
        return

    text = (
        f"📱 Информация о сессии:\n\n"
        f"📞 Телефон: {session['phone']}\n"
        f"👤 Username: @{session['username']}\n"
        f"📝 Имя: {session['first_name']} {session['last_name']}\n"
        f"🔑 Файл: {session['session_name']}\n"
        f"📁 Директория: {session_type}"
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🗑 Удалить сессию",
                    callback_data=f"delete_session_{session_type}_{session_name}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="◀️ К списку", callback_data=f"view_{session_type}_sessions"
                )
            ],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("delete_session_"))
async def delete_session(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    # Извлекаем тип сессии и имя сессии
    parts = callback.data.replace("delete_session_", "").split("_", 1)
    session_type = parts[0]  # history или realtime
    session_name = parts[1]

    if session_type == "history":
        session_path = f"client/sessions/history/{session_name}"
    else:
        session_path = f"client/sessions/realtime/{session_name}"

    try:
        # Удаляем файлы сессии
        if os.path.exists(f"{session_path}.session"):
            os.remove(f"{session_path}.session")
        if os.path.exists(f"{session_path}.json"):
            os.remove(f"{session_path}.json")

        await callback.answer("✅ Сессия успешно удалена")
        await callback.message.edit_text(
            f"✅ Сессия {session_name} успешно удалена из директории {session_type}",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text="◀️ К списку сессий",
                            callback_data=f"view_{session_type}_sessions",
                        )
                    ]
                ]
            ),
        )

    except Exception as e:
        logger.error(f"Ошибка при удалении сессии {session_name}: {e}")
        await callback.answer("❌ Ошибка при удалении сессии")
