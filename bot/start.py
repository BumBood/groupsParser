import copy
import logging
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from bot.funcs import notify_admins
from db.database import Database

from .keyboards import start_keyboard

router = Router(name="start")
db = Database()


@router.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    args = message.text.split()[1] if len(message.text.split()) > 1 else None

    user, is_new = db.get_or_create_user(message.from_user.id)
    await state.clear()
    logging.info(f"Пользователь {message.from_user.id} /start")

    keyboard = copy.deepcopy(start_keyboard)

    if args:
        # Получаем ссылку и увеличиваем счетчик кликов
        ref_link = db.get_or_create_referral_link(args)
        clicks = db.increment_referral_clicks(ref_link.code)

        # Уведомляем админов о новом пользователе
        await notify_admins(
            message.bot,
            f"Пользователь @username присоединился по ссылке с меткой: {args}\n"
            f"Всего кликов по этой ссылке: {clicks}",
        )

    if is_new:
        # Уведомляем админов о новом пользователе
        await notify_admins(
            message.bot,
            f"🆕 Новый пользователь!\n"
            f"ID: <code>{message.from_user.id}</code>\n"
            f"Имя: {message.from_user.first_name}\n"
            f"Username: @{message.from_user.username}",
        )

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
