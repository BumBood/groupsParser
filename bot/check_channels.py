import copy
import logging
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from config.parameters_manager import ParametersManager
from db.database import Database
from bot.keyboards import start_keyboard

router = Router(name="check_channels")
db = Database()


async def check_subscription(bot: Bot, user_id: int) -> bool:
    """Проверяет подписку пользователя на все необходимые каналы"""
    required_channels = ParametersManager.get_parameter("required_channels")
    if not required_channels:
        return True

    channel_ids = [channel.strip() for channel in required_channels.split(",")]

    for channel_id in channel_ids:
        try:
            chat_member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if chat_member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception as e:
            logging.error(f"Ошибка при проверке подписки на канал {channel_id}: {e}")
            return False

    return True


async def get_subscription_keyboard(bot: Bot) -> types.InlineKeyboardMarkup:
    """Создает клавиатуру с кнопками для подписки на каналы"""
    required_channels = ParametersManager.get_parameter("required_channels")
    if not required_channels:
        return None

    channel_ids = [channel.strip() for channel in required_channels.split(",")]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])

    for channel_id in channel_ids:
        try:
            chat = await bot.get_chat(chat_id=channel_id)
            keyboard.inline_keyboard.append(
                [
                    types.InlineKeyboardButton(
                        text=f"📢 {chat.title}",
                        url=(
                            f"https://t.me/{chat.username}"
                            if chat.username
                            else f"https://t.me/c/{channel_id[4:]}"
                        ),
                    )
                ]
            )
        except Exception as e:
            logging.error(f"Ошибка при получении информации о канале {channel_id}: {e}")

    keyboard.inline_keyboard.append(
        [
            types.InlineKeyboardButton(
                text="✅ Проверить подписку", callback_data="check_subscription"
            )
        ]
    )

    return keyboard


@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: types.CallbackQuery):
    """Обработчик кнопки проверки подписки"""
    is_subscribed = await check_subscription(callback.bot, callback.from_user.id)

    if is_subscribed:
        await callback.message.edit_text(
            "✅ Отлично! Вы подписаны на все необходимые каналы.\n\n"
            "Теперь вы можете пользоваться ботом.",
            reply_markup=None,
        )

        user = db.get_user(callback.from_user.id)

        # Если у пользователя нет тарифа, добавляем пробную подписку
        if not db.get_user_tariff_info(callback.from_user.id)["has_tariff"]:
            # Добавляем пробную подписку (например, на 3 дня)
            db.assign_tariff_to_user(
                user_id=callback.from_user.id,
                tariff_id=1,  # ID пробного тарифа
                duration_days=3
            )
            await callback.message.answer("🎉 Вам добавлена пробная подписка на 3 дня!")

        # Получаем информацию о тарифе пользователя
        tariff_info = db.get_user_tariff_info(callback.from_user.id)

        keyboard = copy.deepcopy(start_keyboard)
        if user.is_admin:
            keyboard.inline_keyboard.append(
                [
                    types.InlineKeyboardButton(
                        text="👑 Админка", callback_data="back_to_admin"
                    )
                ]
            )
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

        return True
    else:
        keyboard = await get_subscription_keyboard(callback.bot)
        await callback.message.edit_text(
            "❌ Вы не подписаны на все необходимые каналы.\n\n"
            "Пожалуйста, подпишитесь на каналы ниже и нажмите кнопку 'Проверить подписку'.",
            reply_markup=keyboard,
        )
        return False
