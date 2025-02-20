from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.funcs import add_balance_with_notification, format_user_mention, notify_admins
from config.parameters_manager import ParametersManager
import os
import zipfile
import rarfile
import shutil
import json
from pathlib import Path

from db.database import Database
from aiogram import Bot
from client.session_manager import SessionManager

router = Router(name="admin")
db = Database()


class AdminStates(StatesGroup):
    waiting_for_parameter = State()
    waiting_for_value = State()
    waiting_for_session_file = State()
    waiting_for_json_file = State()
    waiting_for_admin_id = State()
    waiting_for_balance_edit = State()
    waiting_for_archive = State()


@router.message(Command("admin"))
async def admin_menu(message: types.Message):
    if db.get_user(message.from_user.id).is_admin:
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
            ]
        )
        await message.answer("🔧 Панель администратора", reply_markup=keyboard)


@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: types.CallbackQuery):
    if db.get_user(callback.from_user.id).is_admin:
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
            ]
        )
        await callback.message.edit_text(
            "🔧 Панель администратора", reply_markup=keyboard
        )


@router.callback_query(F.data == "edit_params")
async def show_parameters(callback: types.CallbackQuery):
    params = ParametersManager._config
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
    await state.update_data(selected_param=param_name)
    await state.set_state(AdminStates.waiting_for_value)
    current_value = ParametersManager.get_parameter(param_name)
    await callback.message.edit_text(
        f"Параметр: {param_name}\n"
        f"Текущее значение: {current_value}\n\n"
        "Введите новое значение:"
    )


@router.message(AdminStates.waiting_for_value)
async def save_new_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    param_name = data["selected_param"]

    try:
        current_value = ParametersManager.get_parameter(param_name)
        new_value = type(current_value)(message.text)
        ParametersManager.set_parameter(param_name, new_value)
        await message.answer(
            f"✅ Значение параметра {param_name} обновлено на {new_value}"
        )
    except ValueError:
        await message.answer("❌ Неверный формат значения")

    await state.clear()
    await admin_menu(message)


@router.callback_query(F.data == "upload_session")
async def request_archive(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        return
        
    await state.set_state(AdminStates.waiting_for_archive)
    await callback.message.edit_text(
        "📤 Отправьте ZIP или RAR архив, содержащий пары файлов .session и .json\n"
        "⚠️ Существующие сессии с такими же именами будут заменены"
    )


@router.message(AdminStates.waiting_for_archive, F.document)
async def handle_archive(message: types.Message, state: FSMContext, bot: Bot):
    if not message.document.file_name.endswith(('.zip', '.rar')):
        await message.answer("❌ Отправьте файл с расширением .zip или .rar")
        return

    try:
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
        
        if message.document.file_name.endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        else:
            with rarfile.RarFile(archive_path, 'r') as rar_ref:
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
            
        # Копируем валидные файлы в целевую директорию
        sessions_dir = "client/sessions"
        for name in valid_pairs:
            shutil.copy(f"{extract_dir}/{name}.session", f"{sessions_dir}/{name}.session")
            shutil.copy(f"{extract_dir}/{name}.json", f"{sessions_dir}/{name}.json")
            
        await message.answer(
            f"✅ Успешно загружено {len(valid_pairs)} сессий:\n" +
            "\n".join(f"• {name}" for name in valid_pairs)
        )
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при обработке архива: {str(e)}")
        
    finally:
        # Очищаем временные файлы
        shutil.rmtree(temp_dir, ignore_errors=True)
        await state.clear()
        await admin_menu(message)


@router.callback_query(F.data == "view_sessions")
async def view_sessions(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    session_manager = SessionManager("client/sessions")
    sessions = session_manager.get_sessions_info()

    if not sessions:
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

    text = "📱 Список сессий:\n\n"
    for session in sessions:
        status = "🔴 Активна" if session["is_active"] else "⚪️ Нет задач"
        text += (
            f"• {status}\n"
            f"📞 Телефон: {session['phone']}\n"
            f"👤 Username: @{session['username']}\n"
            f"📝 Имя: {session['first_name']} {session['last_name']}\n"
            f"🔑 Файл: {session['session_name']}\n\n"
        )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "edit_balance")
async def edit_balance(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        return

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
        return

    await state.clear()

    user_id, new_balance = map(int, message.text.split())
    user = db.get_user(user_id)

    if not user:
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

    await add_balance_with_notification(user_id, new_balance, bot)

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
        return

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
        await message.answer(
            "❌ Пожалуйста, введите корректный ID пользователя (только цифры)"
        )
        return

    user_id = int(message.text)
    user = db.get_user(user_id)

    if not user:
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
        return

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
        return

    await callback.message.edit_text("🔄 Сервер перезагружается...")
    await state.clear()

    # Уведомляем всех админов
    await notify_admins(
        callback.bot,
        f"🔄 Сервер перезагружается по команде администратора {format_user_mention(callback.from_user.id, callback.from_user.username)}",
    )

    # Перезагружаем сервер
    os.system("sudo /sbin/reboot")  # Для Linux
    # Альтернатива для Windows: os.system("shutdown /r /t 1")


async def validate_sessions(sessions_dir: str) -> tuple[list, list]:
    """
    Проверяет соответствие .session и .json файлов
    
    Returns:
        tuple[list, list]: (список ошибок, список валидных пар файлов)
    """
    errors = []
    valid_pairs = []
    
    session_files = set(Path(sessions_dir).glob("*.session"))
    json_files = set(Path(sessions_dir).glob("*.json"))
    
    session_names = {f.stem for f in session_files}
    json_names = {f.stem for f in json_files}
    
    # Проверяем .session файлы без пары
    for name in session_names - json_names:
        errors.append(f"❌ Файл {name}.session не имеет соответствующего .json файла")
        
    # Проверяем .json файлы без пары    
    for name in json_names - session_names:
        errors.append(f"❌ Файл {name}.json не имеет соответствующего .session файла")
        
    # Проверяем валидные пары
    for name in session_names & json_names:
        try:
            with open(f"{sessions_dir}/{name}.json") as f:
                json.load(f)  # Проверяем валидность JSON
            valid_pairs.append(name)
        except json.JSONDecodeError:
            errors.append(f"❌ Файл {name}.json содержит невалидный JSON")
            
    return errors, valid_pairs
