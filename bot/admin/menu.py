from aiogram import Router, F, types
from aiogram.filters import Command
from db.database import Database

router = Router(name="admin_menu")
db = Database()


async def admin_menu_base(message: types.Message, user_id: int):
    if db.get_user(user_id).is_admin:
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                # Управление пользователями и балансом
                [
                    types.InlineKeyboardButton(
                        text="👥 Пользователи", callback_data="view_users_stats"
                    ),
                    types.InlineKeyboardButton(
                        text="💰 Изменить баланс", callback_data="edit_balance"
                    ),
                ],
                # Управление администраторами и параметрами
                [
                    types.InlineKeyboardButton(
                        text="👑 Добавить админа", callback_data="add_admin"
                    ),
                    types.InlineKeyboardButton(
                        text="📝 Изменить параметры", callback_data="edit_params"
                    ),
                ],
                # Статистика и отчеты
                [
                    types.InlineKeyboardButton(
                        text="📊 Источники", callback_data="view_codes"
                    ),
                    types.InlineKeyboardButton(
                        text="💸 История пополнений", callback_data="export_payments"
                    ),
                ],
                # Коммуникация и система
                [
                    types.InlineKeyboardButton(
                        text="📨 Рассылка", callback_data="broadcast"
                    ),
                    types.InlineKeyboardButton(
                        text="🔄 Перезагрузка", callback_data="reboot_server"
                    ),
                ],
                # Перенос задач между пользователями
                [
                    types.InlineKeyboardButton(
                        text="🔀 Перенос задач", callback_data="transfer_tasks"
                    ),
                    types.InlineKeyboardButton(
                        text="⬆️ Загрузить сессии", callback_data="upload_session"
                    ),
                ],
                # Управление тарифами
                [
                    types.InlineKeyboardButton(
                        text="🎯 Управление тарифами", callback_data="tariffs_menu"
                    ),
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
