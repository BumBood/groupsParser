import copy
import logging
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from bot.utils.funcs import notify_admins
from config.parameters_manager import ParametersManager
from db.database import Database

from .keyboards import start_keyboard

router = Router(name="start")
db = Database()


@router.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    args = message.text.split()[1] if len(message.text.split()) > 1 else None

    user, is_new = db.get_or_create_or_update_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.first_name,
        referrer_code=args,
    )

    await state.clear()
    logging.info(f"Пользователь {message.from_user.id} /start")

    keyboard = copy.deepcopy(start_keyboard)

    if args:
        # Получаем ссылку и увеличиваем счетчик кликов
        db.get_or_create_referral_link(args)

    if is_new:
        # Уведомляем админов о новом пользователе
        admin_message = (
            f"🆕 Новый пользователь!\n"
            f"ID: <code>{message.from_user.id}</code>\n"
            f"Имя: {message.from_user.first_name}\n"
            f"Username: @{message.from_user.username}"
        )

        if args:
            # Получаем статистику внутри одной сессии
            stats = db.get_link_statistics(args)
            if stats:
                admin_message += (
                    f"\nМетка: {args}, всего кликов: {stats['users_count']}"
                )

        await notify_admins(message.bot, admin_message)

    if user.is_admin:
        keyboard.inline_keyboard.append(
            [
                types.InlineKeyboardButton(
                    text="👑 Админка", callback_data="back_to_admin"
                )
            ]
        )

    await message.answer(
        text=f"Привет, {message.from_user.first_name}!\n\nВаш баланс: {user.balance} ₽\nВаш ID: <code>{message.from_user.id}</code>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )

@router.callback_query(F.data == "support")
async def support_callback(callback: types.CallbackQuery):
    await callback.message.answer(f"Ссылка на поддержку: {ParametersManager.get_parameter('support_link')}")

