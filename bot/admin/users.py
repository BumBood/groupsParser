from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging

from db.database import Database
from bot.utils.pagination import Paginator
from bot.utils.funcs import add_balance_with_notification, format_user_mention

logger = logging.getLogger(__name__)

router = Router(name="admin_users")
db = Database()


class AdminUserStates(StatesGroup):
    waiting_for_admin_id = State()
    waiting_for_balance_edit = State()
    waiting_for_user_balance_edit = State()
    waiting_for_ref_code = State()


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
    await state.set_state(AdminUserStates.waiting_for_balance_edit)


@router.message(
    AdminUserStates.waiting_for_balance_edit, F.text.regexp(r"^-?\d+ -?\d+$")
)
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
    await state.set_state(AdminUserStates.waiting_for_admin_id)
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


@router.message(AdminUserStates.waiting_for_admin_id)
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


@router.callback_query(F.data == "view_users_stats")
async def show_users_statistics(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    total_users = len(db.get_all_users())
    active_users = len([u for u in db.get_all_users() if u.is_active])
    inactive_users = total_users - active_users

    text = (
        f"📊 Статистика пользователей:\n\n"
        f"👥 Всего запустили: {total_users}\n"
        f"❌ Неактивные: {inactive_users}\n"
        f"✅ Активные: {active_users}"
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="👑 Администраторы", callback_data="view_admins_list"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="💰 Пользователи с балансом",
                    callback_data="view_users_with_balance",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="📋 Все пользователи", callback_data="view_all_users"
                )
            ],
            [types.InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(
    F.data.startswith(("view_admins_list", "view_users_with_balance", "view_all_users"))
)
async def show_users_list(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    users = db.get_all_users()

    if callback.data == "view_admins_list":
        users = [u for u in users if u.is_admin]
        title = "👑 Список администраторов"
    elif callback.data == "view_users_with_balance":
        users = [u for u in users if u.balance > 0]
        title = "💰 Пользователи с балансом"
    else:
        title = "📋 Все пользователи"

    def user_callback(user) -> tuple[str, str]:
        return (
            f"{'👑 ' if user.is_admin else ''}{user.username or user.full_name or user.user_id} ({user.balance}₽)",
            f"user_profile_{user.user_id}",
        )

    paginator = Paginator(
        items=users,
        items_per_page=10,
        callback_prefix="users",
        item_callback=user_callback,
        return_callback="view_users_stats",
    )

    await callback.message.edit_text(title, reply_markup=paginator.get_page_keyboard(0))


@router.callback_query(F.data.startswith("users_page_"))
async def handle_users_page(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    page = int(callback.data.split("_")[-1])

    # Определяем, какой список пользователей нужно показать
    # Получаем последний callback_data из истории сообщения
    message_text = callback.message.text
    users = db.get_all_users()

    if message_text.startswith("👑"):  # Список администраторов
        users = [u for u in users if u.is_admin]
        title = "👑 Список администраторов"
    elif message_text.startswith("💰"):  # Пользователи с балансом
        users = [u for u in users if u.balance > 0]
        title = "💰 Пользователи с балансом"
    else:  # Все пользователи
        title = "📋 Все пользователи"

    def user_callback(user) -> tuple[str, str]:
        return (
            f"{'👑 ' if user.is_admin else ''}{user.username or user.full_name or user.user_id} ({user.balance}₽)",
            f"user_profile_{user.user_id}",
        )

    paginator = Paginator(
        items=users,
        items_per_page=10,
        callback_prefix="users",
        item_callback=user_callback,
        return_callback="view_users_stats",
    )

    await callback.message.edit_text(
        title, reply_markup=paginator.get_page_keyboard(page)
    )


@router.callback_query(F.data.startswith("user_profile_"))
async def show_user_profile(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    user_id = int(callback.data.replace("user_profile_", ""))
    user = db.get_user(user_id)

    if not user:
        await callback.answer("Пользователь не найден")
        return

    text = (
        f"👤 Профиль пользователя:\n\n"
        f"ID: {user.user_id}\n"
        f"Username: @{user.username}\n"
        f"Имя: {user.full_name}\n"
        f"Баланс: {user.balance}₽\n"
        f"Статус: {'Администратор' if user.is_admin else 'Пользователь'}\n"
        f"Метка: {user.referrer_code}\n"
        f"Активный: {'🟢 Да' if user.is_active else '🔴 Нет'}"
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="💰 Изменить баланс",
                    callback_data=f"edit_user_balance_{user.user_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="👑 Права администратора",
                    callback_data=f"toggle_admin_{user.user_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="◀️ Назад", callback_data="view_users_stats"
                )
            ],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("edit_user_balance_"))
async def request_new_balance(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    user_id = int(callback.data.replace("edit_user_balance_", ""))
    user = db.get_user(user_id)

    if not user:
        await callback.answer("Пользователь не найден")
        await state.clear()
        return

    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminUserStates.waiting_for_user_balance_edit)

    await callback.message.edit_text(
        f"💰 Введите пополнение для пользователя {user.username or user.user_id}\n"
        f"Текущий баланс: {user.balance}₽",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="◀️ Назад", callback_data=f"user_profile_{user_id}"
                    )
                ]
            ]
        ),
    )


@router.message(
    AdminUserStates.waiting_for_user_balance_edit, F.text.regexp(r"^-?\d+$")
)
async def process_new_balance(message: types.Message, state: FSMContext, bot: Bot):
    if not db.get_user(message.from_user.id).is_admin:
        return

    data = await state.get_data()
    user_id = data["target_user_id"]
    new_balance = int(message.text)

    user = db.get_user(user_id)
    if not user:
        await message.answer("❌ Пользователь не найден")
        await state.clear()
        return

    await add_balance_with_notification(user_id, new_balance, bot)
    logger.info(f"Баланс пользователя {user_id} изменен на {new_balance}")

    await message.answer(
        f"✅ Баланс пользователя {user.username or user_id} успешно изменен\n"
        f"Баланс: {user.balance + new_balance}₽\n",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="◀️ К профилю", callback_data=f"user_profile_{user_id}"
                    )
                ]
            ]
        ),
    )
    await state.clear()


@router.message(AdminUserStates.waiting_for_user_balance_edit)
async def invalid_balance(message: types.Message):
    await message.answer("❌ Пожалуйста, введите корректное число")


@router.callback_query(F.data.startswith("toggle_admin_"))
async def toggle_admin_status(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    user_id = int(callback.data.replace("toggle_admin_", ""))
    user = db.get_user(user_id)

    if not user:
        await callback.answer("Пользователь не найден")
        return

    # Меняем статус администратора на противоположный
    new_admin_status = not user.is_admin
    db.set_admin(user_id, new_admin_status)

    status_text = (
        "назначен администратором"
        if new_admin_status
        else "снят с должности администратора"
    )
    logger.info(
        f"Пользователь {user_id} {status_text} администратором {callback.from_user.id}"
    )

    await callback.answer(f"✅ Пользователь {status_text}")

    # Обновляем информацию в профиле пользователя
    text = (
        f"👤 Профиль пользователя:\n\n"
        f"ID: {user.user_id}\n"
        f"Username: @{user.username}\n"
        f"Имя: {user.full_name}\n"
        f"Баланс: {user.balance}₽\n"
        f"Статус: {'Администратор' if new_admin_status else 'Пользователь'}\n"
        f"Активный: {'🟢 Да' if user.is_active else '🔴 Нет'}"
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="💰 Изменить баланс",
                    callback_data=f"edit_user_balance_{user.user_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="👑 Права администратора",
                    callback_data=f"toggle_admin_{user.user_id}",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="◀️ Назад", callback_data="view_users_stats"
                )
            ],
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard)
