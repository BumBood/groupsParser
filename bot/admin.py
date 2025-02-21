from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.utils.funcs import (
    add_balance_with_notification,
    format_user_mention,
    notify_admins,
)
import re
from config.parameters_manager import ParametersManager
import os
import zipfile
import rarfile
import shutil
import json
from pathlib import Path
import time

from db.database import Database
from aiogram import Bot
from client.session_manager import SessionManager
import logging
from aiogram_album import AlbumMessage
from aiogram_album.ttl_cache_middleware import TTLCacheAlbumMiddleware
from bot.utils.pagination import Paginator

logger = logging.getLogger(__name__)

router = Router(name="admin")
db = Database()

# Добавляем middleware для обработки альбомов
TTLCacheAlbumMiddleware(router=router)


class AdminStates(StatesGroup):
    waiting_for_parameter = State()
    waiting_for_value = State()
    waiting_for_session_file = State()
    waiting_for_json_file = State()
    waiting_for_admin_id = State()
    waiting_for_balance_edit = State()
    waiting_for_archive = State()
    waiting_for_broadcast = State()
    waiting_for_ref_code = State()

async def admin_menu_base(message: types.Message, user_id: int):
    if db.get_user(message.from_user.id).is_admin:
        logger.info(f"Администратор {user_id} открыл админ-панель")
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="📝 Изменить параметры", callback_data="edit_params"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="📱 Просмотр сессий", callback_data="view_sessions"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="📤 Загрузить сессию", callback_data="upload_session"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="💰 Изменить баланс", callback_data="edit_balance"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="👑 Добавить админа", callback_data="add_admin"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="🔄 Перезагрузить сервер", callback_data="reboot_server"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="📨 Рассылка", callback_data="broadcast"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="📊 Источники", callback_data="view_codes"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="📊 История пополнений", callback_data="export_payments"
                    )
                ],
            ]
        )
        await message.answer("🔧 Панель администратора", reply_markup=keyboard)

@router.message(Command("admin"))
async def admin_menu(message: types.Message):
    await admin_menu_base(message, message.from_user.id)


@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: types.CallbackQuery):
    await admin_menu_base(callback.message, callback.from_user.id)


@router.callback_query(F.data == "edit_params")
async def show_parameters(callback: types.CallbackQuery):
    params = ParametersManager._config
    logger.info(
        f"Администратор {callback.from_user.id} просматривает текущие параметры: {params}"
    )
    text = "📋 Текущие параметры:\n\n"
    for param, value in params.items():
        text += f"• {param}: {value}\n"

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✏️ Изменить параметр", callback_data="change_param"
                )
            ],
            [types.InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "change_param")
async def select_parameter(callback: types.CallbackQuery, state: FSMContext):
    logger.info(f"Администратор {callback.from_user.id} начал изменение параметров")
    params = ParametersManager._config
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=param, callback_data=f"param_{param}")]
            for param in params.keys()
        ]
    )
    await callback.message.edit_text(
        "Выберите параметр для изменения:", reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("param_"))
async def enter_new_value(callback: types.CallbackQuery, state: FSMContext):
    param_name = callback.data.replace("param_", "")
    logger.info(
        f"Администратор {callback.from_user.id} выбрал параметр {param_name} для изменения"
    )
    await state.update_data(selected_param=param_name)
    await state.set_state(AdminStates.waiting_for_value)
    current_value = ParametersManager.get_parameter(param_name)
    logger.debug(f"Текущее значение параметра {param_name}: {current_value}")
    await callback.message.edit_text(
        f"Параметр: {param_name}\n"
        f"Текущее значение: {current_value}\n\n"
        "Введите новое значение:"
    )


@router.message(AdminStates.waiting_for_value)
async def save_new_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    param_name = data["selected_param"]
    logger.info(f"Администратор {message.from_user.id} изменяет параметр {param_name}")

    try:
        current_value = ParametersManager.get_parameter(param_name)
        new_value = type(current_value)(message.text)
        ParametersManager.set_parameter(param_name, new_value)
        logger.info(f"Параметр {param_name} успешно изменен на {new_value}")
        await message.answer(
            f"✅ Значение параметра {param_name} обновлено на {new_value}"
        )
    except ValueError:
        logger.error(
            f"Ошибка при изменении параметра {param_name}: неверный формат значения"
        )
        await message.answer("❌ Неверный формат значения")

    await state.clear()
    await admin_menu(message)


@router.callback_query(F.data == "upload_session")
async def request_archive(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированного доступа к загрузке сессий от пользователя {callback.from_user.id}"
        )
        return

    logger.info(f"Администратор {callback.from_user.id} начал загрузку сессий")
    await state.set_state(AdminStates.waiting_for_archive)
    await callback.message.edit_text(
        "📤 Отправьте ZIP или RAR архив, содержащий пары файлов .session и .json\n"
        "⚠️ Существующие сессии с такими же именами будут заменены"
    )


@router.message(AdminStates.waiting_for_archive, F.document)
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
        status = "🔴" if session["is_active"] else "⚪️"
        return f"{status} {session['phone']}", f"session_info_{session['session_name']}"

    paginator = Paginator(
        items=sessions,
        items_per_page=4,
        callback_prefix="sessions",
        item_callback=session_callback,
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
        status = "🔴" if session["is_active"] else "⚪️"
        return f"{status} {session['phone']}", f"session_info_{session['session_name']}"

    paginator = Paginator(
        items=sessions,
        items_per_page=4,
        callback_prefix="sessions",
        item_callback=session_callback,
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

    status = "🔴 Активна" if session["is_active"] else "⚪️ Нет задач"
    text = (
        f"📱 Информация о сессии:\n\n"
        f"• {status}\n"
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


@router.callback_query(F.data == "edit_balance")
async def edit_balance(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированного доступа к изменению баланса от пользователя {callback.from_user.id}"
        )
        return

    logger.info(
        f"Администратор {callback.from_user.id} запросил изменение баланса пользователя"
    )
    await callback.message.answer(
        "💰 Введите ID пользователя и новый баланс в формате:\n"
        "<code>user_id сумма</code>",
        parse_mode="HTML",
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
    await state.set_state(AdminStates.waiting_for_balance_edit)


@router.message(AdminStates.waiting_for_balance_edit, F.text.regexp(r"^-?\d+ -?\d+$"))
async def process_balance_edit(message: types.Message, state: FSMContext, bot: Bot):
    if not db.get_user(message.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированного изменения баланса от пользователя {message.from_user.id}"
        )
        return

    await state.clear()
    user_id, new_balance = map(int, message.text.split())
    logger.info(
        f"Администратор {message.from_user.id} изменяет баланс пользователя {user_id} на {new_balance}"
    )

    user = db.get_user(user_id)
    if not user:
        logger.warning(
            f"Попытка изменения баланса несуществующего пользователя {user_id}"
        )
        await message.answer(
            "❌ Пользователь не найден",
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

    logger.info(f"Текущий баланс пользователя {user_id}: {user.balance}")
    await add_balance_with_notification(user_id, new_balance, bot)
    logger.info(f"Баланс пользователя {user_id} успешно изменен на {new_balance}")

    await message.answer(
        f"✅ Баланс пользователя {user_id} успешно изменен на {new_balance} ₽",
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


@router.callback_query(F.data == "add_admin")
async def request_admin_id(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированного доступа к добавлению админа от пользователя {callback.from_user.id}"
        )
        return

    logger.info(
        f"Администратор {callback.from_user.id} запросил добавление нового администратора"
    )
    await state.set_state(AdminStates.waiting_for_admin_id)
    await callback.message.answer(
        "👑 Введите ID пользователя, которого хотите назначить администратором:",
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


@router.message(AdminStates.waiting_for_admin_id)
async def process_admin_add(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        logger.warning(
            f"Получен некорректный ID пользователя от администратора {message.from_user.id}: {message.text}"
        )
        await message.answer(
            "❌ Пожалуйста, введите корректный ID пользователя (только цифры)"
        )
        return

    user_id = int(message.text)
    logger.info(
        f"Администратор {message.from_user.id} пытается назначить пользователя {user_id} администратором"
    )

    user = db.get_user(user_id)
    if not user:
        logger.warning(
            f"Попытка назначения администратором несуществующего пользователя {user_id}"
        )
        await message.answer(
            "❌ Пользователь не найден",
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

    if user.is_admin:
        logger.info(f"Пользователь {user_id} уже является администратором")
        await message.answer(
            "❌ Этот пользователь уже является администратором",
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

    db.set_admin(user_id, True)
    logger.info(f"Пользователь {user_id} успешно назначен администратором")
    await state.clear()

    await message.answer(
        f"✅ Пользователь {user_id} успешно назначен администратором",
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


@router.callback_query(F.data == "reboot_server")
async def confirm_reboot(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированного доступа к перезагрузке сервера от пользователя {callback.from_user.id}"
        )
        return

    logger.info(
        f"Администратор {callback.from_user.id} запросил подтверждение перезагрузки сервера"
    )
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Подтвердить", callback_data="confirm_reboot"
                ),
                types.InlineKeyboardButton(
                    text="❌ Отмена", callback_data="back_to_admin"
                ),
            ]
        ]
    )
    await callback.message.edit_text(
        "⚠️ Вы уверены, что хотите перезагрузить сервер?",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "confirm_reboot")
async def reboot_server(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированной перезагрузки сервера от пользователя {callback.from_user.id}"
        )
        return

    logger.info(
        f"Администратор {callback.from_user.id} инициировал перезагрузку сервера"
    )
    await callback.message.edit_text("🔄 Сервер перезагружается...")
    await state.clear()

    # Уведомляем всех админов
    await notify_admins(
        callback.bot,
        f"🔄 Сервер перезагружается по команде администратора {format_user_mention(callback.from_user.id, callback.from_user.username)}",
    )

    logger.info("Выполняется команда перезагрузки сервера")
    # Перезагружаем сервер
    os.system("sudo /sbin/reboot")  # Для Linux
    # Альтернатива для Windows: os.system("shutdown /r /t 1")


@router.callback_query(F.data == "broadcast")
async def request_broadcast_message(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированного доступа к рассылке от пользователя {callback.from_user.id}"
        )
        return

    logger.info(f"Администратор {callback.from_user.id} запросил создание рассылки")
    await state.set_state(AdminStates.waiting_for_broadcast)
    await callback.message.answer(
        "📨 Отправьте сообщение для рассылки всем пользователям.\n"
        "Поддерживаются все типы сообщений (текст, фото, видео и т.д.)",
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


@router.message(AdminStates.waiting_for_broadcast, F.media_group_id)
async def process_broadcast_album(message: AlbumMessage, state: FSMContext):
    if not db.get_user(message.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированной рассылки от пользователя {message.from_user.id}"
        )
        return

    logger.info(f"Начало рассылки альбома от администратора {message.from_user.id}")

    # Получаем всех пользователей из базы
    users = db.get_all_users()
    total_users = len(users)

    await message[0].answer(
        f"⏳ Начинаю рассылку альбома {total_users} пользователям..."
    )

    success_count = 0
    error_count = 0

    media_group = [msg.as_input_media() for msg in message]

    for user in users:
        try:
            # Отправляем альбом каждому пользователю
            await message[0].bot.send_media_group(
                chat_id=user.user_id, media=media_group
            )
            success_count += 1
            logger.debug(f"Альбом успешно отправлен пользователю {user.user_id}")
        except Exception as e:
            error_count += 1
            logger.error(f"Ошибка отправки альбома пользователю {user.user_id}: {e}")

    logger.info(
        f"Рассылка альбома завершена. Успешно: {success_count}, ошибок: {error_count}"
    )

    await message[0].answer(
        f"✅ Рассылка альбома завершена\n"
        f"📊 Статистика:\n"
        f"• Всего пользователей: {total_users}\n"
        f"• Успешно отправлено: {success_count}\n"
        f"• Ошибок: {error_count}",
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

    await state.clear()


@router.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    """Обработка одиночных сообщений для рассылки"""
    if not db.get_user(message.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированной рассылки от пользователя {message.from_user.id}"
        )
        return

    logger.info(f"Начало рассылки от администратора {message.from_user.id}")

    # Получаем всех пользователей из базы
    users = db.get_all_users()
    total_users = len(users)

    await message.answer(f"⏳ Начинаю рассылку {total_users} пользователям...")

    success_count = 0
    error_count = 0

    for user in users:
        try:
            # Копируем исходное сообщение каждому пользователю
            await message.copy_to(user.user_id)
            success_count += 1
            logger.debug(f"Сообщение успешно отправлено пользователю {user.user_id}")
        except Exception as e:
            error_count += 1
            logger.error(f"Ошибка отправки сообщения пользователю {user.user_id}: {e}")

    logger.info(f"Рассылка завершена. Успешно: {success_count}, ошибок: {error_count}")

    await message.answer(
        f"✅ Рассылка завершена\n"
        f"📊 Статистика:\n"
        f"• Всего пользователей: {total_users}\n"
        f"• Успешно отправлено: {success_count}\n"
        f"• Ошибок: {error_count}",
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

    await state.clear()


@router.callback_query(F.data == "view_codes")
async def view_codes(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    codes = db.get_all_referral_links_statistics()

    text = "📊 Список источников:"
    keyboard = [
        [
            types.InlineKeyboardButton(
                text="➕ Создать ссылку", callback_data="create_ref_link"
            )
        ]
    ]

    if not codes:
        keyboard.append(
            [types.InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
        )
        await callback.message.edit_text(
            text + "\n\n📱 Источники не найдены",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard),
        )
        return

    def code_callback(code: dict) -> tuple[str, str]:
        return (
            f"📊 {code['code']} ({code['users_count']})",
            f"code_info_{code['code']}",
        )

    paginator = Paginator(
        items=codes,
        items_per_page=5,
        callback_prefix="codes",
        item_callback=code_callback,
    )

    keyboard = paginator.get_page_keyboard(0)
    # Добавляем кнопку создания ссылки в начало клавиатуры
    keyboard.inline_keyboard.insert(
        0,
        [
            types.InlineKeyboardButton(
                text="➕ Создать ссылку", callback_data="create_ref_link"
            )
        ],
    )

    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("codes_page_"))
async def handle_codes_page(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    page = int(callback.data.split("_")[-1])
    codes = db.get_all_referral_links_statistics()

    def code_callback(code: dict) -> tuple[str, str]:
        return (
            f"📊 {code['code']} ({code['users_count']})",
            f"code_info_{code['code']}",
        )

    paginator = Paginator(
        items=codes,
        items_per_page=5,
        callback_prefix="codes",
        item_callback=code_callback,
    )

    await callback.message.edit_text(
        "📊 Список источников:", reply_markup=paginator.get_page_keyboard(page)
    )


@router.callback_query(F.data.startswith("code_info_"))
async def show_code_info(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    code = callback.data.replace("code_info_", "")
    code_data = db.get_link_statistics(code)

    if not code_data:
        await callback.answer("Источник не найден")
        return

    bot_info = await callback.bot.get_me()
    bot_username = bot_info.username

    text = (
        f"📊 Статистика источника {code}:\n\n"
        f"👥 Всего пользователей: {code_data['users_count']}\n"
        f"💰 Сумма пополнений: {code_data['total_payments']} ₽\n\n"
        f"🔗 Ссылка источника: https://t.me/{bot_username}?start={code_data['code']}"
    )

    keyboard = []

    keyboard.append(
        [types.InlineKeyboardButton(text="◀️ К источникам", callback_data="view_codes")]
    )

    await callback.message.edit_text(
        text, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data == "create_ref_link")
async def create_ref_link(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    await state.set_state(AdminStates.waiting_for_ref_code)
    await callback.message.edit_text(
        "📝 Введите метку источника (например: vk_com, telegram_ads):",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="◀️ Назад", callback_data="view_codes")]
            ]
        ),
    )


@router.message(AdminStates.waiting_for_ref_code)
async def process_ref_code(message: types.Message, state: FSMContext):
    if not db.get_user(message.from_user.id).is_admin:
        return

    code = message.text.strip()
    if not code:
        await message.answer("❌ Метка источника не может быть пустой")
        return

    # Проверяем, что код содержит только безопасные для URL символы
    if not re.match("^[a-zA-Z0-9_-]+$", code):
        await message.answer(
            "❌ Метка источника может содержать только латинские буквы, цифры, дефис и нижнее подчеркивание"
        )
        return

    ref_link = db.create_referral_link(code)
    bot_info = await message.bot.get_me()
    bot_username = bot_info.username

    await message.answer(
        f"✅ Реферальная ссылка создана!\n\n"
        f"🔗 https://t.me/{bot_username}?start={ref_link.code}\n\n"
        f"📊 Статистика будет доступна в разделе 'Источники'",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="📊 К источникам", callback_data="view_codes"
                    )
                ]
            ]
        ),
    )
    await state.clear()


@router.callback_query(F.data == "export_payments")
async def export_payments(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированного доступа к экспорту платежей от пользователя {callback.from_user.id}"
        )
        return

    logger.info(
        f"Администратор {callback.from_user.id} запросил выгрузку истории пополнений"
    )

    try:
        # Создаем временный файл
        filename = f"payments_history_{int(time.time())}.csv"

        with open(filename, "w", encoding="utf-8-sig") as f:
            # Записываем заголовки
            f.write("ID пользователя;Сумма;Дата\n")

            # Получаем все платежи
            payments = db.get_all_payments()
            for payment in payments:
                print(payment)
                f.write(
                    f"{payment.user_id};{payment.amount};{payment.created_at}\n"
                )

        # Отправляем файл
        await callback.message.answer_document(
            types.FSInputFile(filename, filename=filename),
            caption="✅ История пополнений выгружена!",
        )

        # Удаляем временный файл
        os.remove(filename)

        logger.info("Выгрузка истории пополнений успешно завершена")

    except Exception as e:
        logger.error(f"Ошибка при выгрузке истории пополнений: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при выгрузке истории пополнений",
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
