from aiogram import Router, F, types
import re
import os
import time
import logging

from db.database import Database
from bot.utils.pagination import Paginator
from .users import AdminUserStates

logger = logging.getLogger(__name__)

router = Router(name="admin_statistics")
db = Database()


@router.callback_query(F.data == "viewcodes")
async def viewcodes(callback: types.CallbackQuery):
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
        return_callback="back_to_admin",
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
        return_callback="back_to_admin",
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

    # Добавляем кнопку удаления только если у метки нет пользователей
    if code_data["users_count"] == 0:
        keyboard.append(
            [
                types.InlineKeyboardButton(
                    text="🗑 Удалить метку", callback_data=f"delete_ref_link_{code}"
                )
            ]
        )

    keyboard.append(
        [types.InlineKeyboardButton(text="◀️ К источникам", callback_data="viewcodes")]
    )

    await callback.message.edit_text(
        text, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data == "create_ref_link")
async def create_ref_link(callback: types.CallbackQuery, state):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    

    await state.set_state(AdminUserStates.waiting_for_ref_code)
    await callback.message.edit_text(
        "📝 Введите метку источника (например: vk_com, telegram_ads):",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="◀️ Назад", callback_data="viewcodes")]
            ]
        ),
    )


@router.message(
    F.text.regexp("^[a-zA-Z0-9_-]+$"), AdminUserStates.waiting_for_ref_code
)
async def process_ref_code(message: types.Message, state):
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
                        text="📊 К источникам", callback_data="viewcodes"
                    )
                ]
            ]
        ),
    )
    await state.clear()


@router.callback_query(F.data.startswith("delete_ref_link_"))
async def delete_ref_link(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    code = callback.data.replace("delete_ref_link_", "")

    if db.delete_referral_link(code):
        await callback.answer("✅ Метка успешно удалена")
        await viewcodes(callback)
    else:
        await callback.answer("❌ Не удалось удалить метку")


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
                f.write(f"{payment.user_id};{payment.amount};{payment.created_at}\n")

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
