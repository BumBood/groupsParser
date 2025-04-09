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

    # Получаем информацию о тарифе пользователя
    tariff_info = db.get_user_tariff_info(message.from_user.id)

    # Формируем текст сообщения
    message_text = f"Привет, {message.from_user.first_name}!\n\nВаш баланс: {user.balance} ₽\nВаш ID: <code>{message.from_user.id}</code>"

    # Добавляем информацию о тарифе
    if tariff_info["has_tariff"]:
        message_text += (
            f"\n\n📊 Ваш тариф: {tariff_info['tariff_name']}\n"
            f"📅 Действует до: {tariff_info['end_date']}\n"
            f"⏳ Осталось дней: {tariff_info['days_left']}\n"
            f"📁 Проекты: {tariff_info['current_projects']}/{tariff_info['max_projects']}\n"
            f"💬 Чаты: {tariff_info['current_chats']}/{tariff_info['max_chats_per_project'] * tariff_info['max_projects']}"
        )
    else:
        message_text += "\n\n❌ У вас нет активного тарифа"

    await message.answer(
        text=message_text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(F.data == "support")
async def support_callback(callback: types.CallbackQuery):
    await callback.message.answer(
        f"Ссылка на поддержку: {ParametersManager.get_parameter('support_link')}"
    )


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()

    user = db.get_user(callback.from_user.id)
    keyboard = copy.deepcopy(start_keyboard)

    if user.is_admin:
        keyboard.inline_keyboard.append(
            [
                types.InlineKeyboardButton(
                    text="👑 Админка", callback_data="back_to_admin"
                )
            ]
        )

    # Получаем информацию о тарифе пользователя
    tariff_info = db.get_user_tariff_info(callback.from_user.id)

    # Формируем текст сообщения
    message_text = f"Привет, {callback.from_user.first_name}!\n\nВаш баланс: {user.balance} ₽\nВаш ID: <code>{callback.from_user.id}</code>"

    # Добавляем информацию о тарифе
    if tariff_info["has_tariff"]:
        message_text += (
            f"\n\n📊 Ваш тариф: {tariff_info['tariff_name']}\n"
            f"📅 Действует до: {tariff_info['end_date']}\n"
            f"⏳ Осталось дней: {tariff_info['days_left']}\n"
            f"📁 Проекты: {tariff_info['current_projects']}/{tariff_info['max_projects']}\n"
            f"💬 Чаты: {tariff_info['current_chats']}/{tariff_info['max_chats_per_project'] * tariff_info['max_projects']}"
        )
    else:
        message_text += "\n\n❌ У вас нет активного тарифа"

    await callback.message.answer(
        text=message_text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
