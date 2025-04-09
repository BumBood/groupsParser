from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
import os
import logging

from db.database import Database
from bot.utils.funcs import notify_admins, format_user_mention

logger = logging.getLogger(__name__)

router = Router(name="admin_system")
db = Database()


@router.callback_query(F.data == "reboot_server")
async def confirm_reboot(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированного доступа к перезагрузке сервера от пользователя {callback.from_user.id}"
        )
        return

    logger.info(
        f"Администратор {callback.from_user.id} запросил подтверждение перезагрузки сервера"
    )
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
        logger.warning(
            f"Попытка несанкционированной перезагрузки сервера от пользователя {callback.from_user.id}"
        )
        return

    logger.info(
        f"Администратор {callback.from_user.id} инициировал перезагрузку сервера"
    )
    await callback.message.edit_text("🔄 Сервер перезагружается...")
    await state.clear()

    # Уведомляем всех админов
    await notify_admins(
        callback.bot,
        f"🔄 Сервер перезагружается по команде администратора {format_user_mention(callback.from_user.id, callback.from_user.username)}",
    )

    logger.info("Выполняется команда перезагрузки сервера")
    # Перезагружаем сервер
    os.system("sudo systemctl stop telegram-bot.service")
    os.system("sudo systemctl stop payment-webhook.service")
    os.system("sudo /sbin/reboot")  # Для Linux
    # Альтернатива для Windows: os.system("shutdown /r /t 1")
