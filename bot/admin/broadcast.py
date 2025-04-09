from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging

from db.database import Database
from aiogram_album import AlbumMessage
from aiogram_album.ttl_cache_middleware import TTLCacheAlbumMiddleware

logger = logging.getLogger(__name__)

router = Router(name="admin_broadcast")
db = Database()

# Добавляем middleware для обработки альбомов
TTLCacheAlbumMiddleware(router=router)


class AdminBroadcastStates(StatesGroup):
    waiting_for_broadcast = State()


@router.callback_query(F.data == "broadcast")
async def request_broadcast_message(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированного доступа к рассылке от пользователя {callback.from_user.id}"
        )
        return

    logger.info(f"Администратор {callback.from_user.id} запросил создание рассылки")
    await state.set_state(AdminBroadcastStates.waiting_for_broadcast)
    await callback.message.answer(
        "📨 Отправьте сообщение для рассылки всем пользователям.\n"
        "Поддерживаются все типы сообщений (текст, фото, видео и т.д.)",
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


@router.message(AdminBroadcastStates.waiting_for_broadcast, F.media_group_id)
async def process_broadcast_album(message: AlbumMessage, state: FSMContext):
    if not db.get_user(message.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированной рассылки от пользователя {message.from_user.id}"
        )
        return

    logger.info(f"Начало рассылки альбома от администратора {message.from_user.id}")

    users = db.get_all_users()
    total_users = len(users)

    # Создаем список InputMedia объектов
    media_group = []
    for msg in message.messages:
        if msg.photo:
            media_group.append(
                types.InputMediaPhoto(
                    media=msg.photo[-1].file_id,
                    caption=msg.caption if msg.caption else None,
                )
            )
        elif msg.video:
            media_group.append(
                types.InputMediaVideo(
                    media=msg.video.file_id,
                    caption=msg.caption if msg.caption else None,
                )
            )
        elif msg.document:
            media_group.append(
                types.InputMediaDocument(
                    media=msg.document.file_id,
                    caption=msg.caption if msg.caption else None,
                )
            )

    # Используем первое сообщение из альбома для отправки уведомления
    first_message = message.messages[0]
    await first_message.answer(
        f"⏳ Начинаю рассылку альбома {total_users} пользователям..."
    )

    success_count = 0
    error_count = 0
    blocked_count = 0

    for user in users:
        try:
            await first_message.bot.send_media_group(
                chat_id=user.user_id, media=media_group
            )
            success_count += 1
            if not user.is_active:
                db.update_user_activity(user.user_id, True)
            logger.debug(f"Альбом успешно отправлен пользователю {user.user_id}")
        except Exception as e:
            error_count += 1
            if "bot was blocked by the user" in str(e):
                blocked_count += 1
                if user.is_active:
                    db.update_user_activity(user.user_id, False)
                logger.info(f"Пользователь {user.user_id} заблокировал бота")
            logger.error(f"Ошибка отправки альбома пользователю {user.user_id}: {e}")

    logger.info(
        f"Рассылка альбома завершена. Успешно: {success_count}, заблокировано: {blocked_count}, других ошибок: {error_count - blocked_count}"
    )

    await first_message.answer(
        f"✅ Рассылка альбома завершена\n"
        f"📊 Статистика:\n"
        f"• Всего пользователей: {total_users}\n"
        f"• Успешно отправлено: {success_count}\n"
        f"• Заблокировали бота: {blocked_count}\n"
        f"• Другие ошибки: {error_count - blocked_count}",
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

    await state.clear()


@router.message(AdminBroadcastStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    if not db.get_user(message.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированной рассылки от пользователя {message.from_user.id}"
        )
        return

    logger.info(f"Начало рассылки от администратора {message.from_user.id}")

    users = db.get_all_users()
    total_users = len(users)

    await message.answer(f"⏳ Начинаю рассылку {total_users} пользователям...")

    success_count = 0
    error_count = 0
    blocked_count = 0

    for user in users:
        try:
            await message.copy_to(user.user_id)
            success_count += 1
            if not user.is_active:
                db.update_user_activity(user.user_id, True)
            logger.debug(f"Сообщение успешно отправлено пользователю {user.user_id}")
        except Exception as e:
            error_count += 1
            if "bot was blocked by the user" in str(e):
                blocked_count += 1
                if user.is_active:
                    db.update_user_activity(user.user_id, False)
                logger.info(f"Пользователь {user.user_id} заблокировал бота")
            logger.error(f"Ошибка отправки сообщения пользователю {user.user_id}: {e}")

    logger.info(
        f"Рассылка завершена. Успешно: {success_count}, заблокировано: {blocked_count}, других ошибок: {error_count - blocked_count}"
    )

    await message.answer(
        f"✅ Рассылка завершена\n"
        f"📊 Статистика:\n"
        f"• Всего пользователей: {total_users}\n"
        f"• Успешно отправлено: {success_count}\n"
        f"• Заблокировали бота: {blocked_count}\n"
        f"• Другие ошибки: {error_count - blocked_count}",
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

    await state.clear()
