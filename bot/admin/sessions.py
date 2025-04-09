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
from client.session_manager import SessionManager
from bot.utils.pagination import Paginator

logger = logging.getLogger(__name__)

router = Router(name="admin_sessions")
db = Database()


class AdminSessionStates(StatesGroup):
    waiting_for_archive = State()


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
    await state.set_state(AdminSessionStates.waiting_for_archive)
    await callback.message.edit_text(
        "📤 Отправьте ZIP или RAR архив, содержащий пары файлов .session и .json\n"
        "⚠️ Существующие сессии с такими же именами будут заменены"
    )


@router.message(AdminSessionStates.waiting_for_archive, F.document)
async def handle_archive(message: types.Message, state: FSMContext, bot: Bot):
    logger.info(f"Получен архив с сессиями от администратора {message.from_user.id}")

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

        # Создаем целевую директорию, если она не существует
        sessions_dir = "client/sessions"
        os.makedirs(sessions_dir, exist_ok=True)

        # Копируем валидные файлы в целевую директорию
        for name in valid_pairs:
            shutil.copy(
                f"{extract_dir}/{name}.session", f"{sessions_dir}/{name}.session"
            )
            shutil.copy(f"{extract_dir}/{name}.json", f"{sessions_dir}/{name}.json")

        await message.answer(
            f"✅ Успешно загружено {len(valid_pairs)} сессий:\n"
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

    logger.info(f"Администратор {callback.from_user.id} запросил просмотр сессий")
    session_manager = SessionManager("client/sessions")
    sessions = session_manager.get_sessions_info()

    if not sessions:
        logger.info("Сессии не найдены")
        await callback.message.edit_text(
            "📱 Сессии не найдены",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text="◀️ Назад", callback_data="back_to_admin"
                        )
                    ]
                ]
            ),
        )
        return

    def session_callback(session: dict) -> tuple[str, str]:
        return f"+{session['phone']}", f"session_info_{session['session_name']}"

    paginator = Paginator(
        items=sessions,
        items_per_page=4,
        callback_prefix="sessions",
        item_callback=session_callback,
        return_callback="back_to_admin",
    )

    await callback.message.edit_text(
        "📱 Список сессий:", reply_markup=paginator.get_page_keyboard(0)
    )


@router.callback_query(F.data.startswith("sessions_page_"))
async def handle_sessions_page(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    page = int(callback.data.split("_")[-1])
    session_manager = SessionManager("client/sessions")
    sessions = session_manager.get_sessions_info()

    def session_callback(session: dict) -> tuple[str, str]:
        return f"+{session['phone']}", f"session_info_{session['session_name']}"

    paginator = Paginator(
        items=sessions,
        items_per_page=4,
        callback_prefix="sessions",
        item_callback=session_callback,
        return_callback="back_to_admin",
    )

    await callback.message.edit_text(
        "📱 Список сессий:", reply_markup=paginator.get_page_keyboard(page)
    )


@router.callback_query(F.data.startswith("session_info_"))
async def show_session_info(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    session_name = callback.data.replace("session_info_", "")
    session_manager = SessionManager("client/sessions")
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
        f"🔑 Файл: {session['session_name']}"
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="🗑 Удалить сессию",
                    callback_data=f"delete_session_{session_name}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="◀️ К списку", callback_data="view_sessions"
                )
            ],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("delete_session_"))
async def delete_session(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    session_name = callback.data.replace("delete_session_", "")
    session_path = f"client/sessions/{session_name}"

    try:
        # Удаляем файлы сессии
        if os.path.exists(f"{session_path}.session"):
            os.remove(f"{session_path}.session")
        if os.path.exists(f"{session_path}.json"):
            os.remove(f"{session_path}.json")

        await callback.answer("✅ Сессия успешно удалена")
        await view_sessions(callback, None)

    except Exception as e:
        logger.error(f"Ошибка при удалении сессии {session_name}: {e}")
        await callback.answer("❌ Ошибка при удалении сессии")
