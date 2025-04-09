from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

start_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📊 Проекты", callback_data="projects_menu")],
        [
            InlineKeyboardButton(
                text="📥 Парсинг истории", callback_data="parse_history"
            )
        ],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")],
        [InlineKeyboardButton(text="🎯 Купить тариф", callback_data="buy_tariff")],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="support")],
    ]
)

balance_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить", callback_data="deposit")]
    ]
)
