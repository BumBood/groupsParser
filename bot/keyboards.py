from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

start_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🗣 Собрать комментарии", callback_data="collect_comments"
            )
        ],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="support")],
    ]
)

balance_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="💰 Пополнить", callback_data="deposit")]
    ]
)

# Инлайн-клавиатура для выбора способа оплаты
payment_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[   
        [InlineKeyboardButton(text="💳 ЮKassa", callback_data="payment|yooKassa")],
        [InlineKeyboardButton(text="💲 FreeKassa", callback_data="payment|freeKassa")]
    ]
)
