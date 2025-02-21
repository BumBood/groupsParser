import asyncio
import logging
import os
import re

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from client.comments_parser import CommentParser
from config.parameters_manager import ParametersManager
from db.database import Database

router = Router(name="post")
db = Database()
parser = CommentParser("client/sessions")

# Настройка логгера
logger = logging.getLogger(__name__)


class PostStates(StatesGroup):
    waiting_for_post_link = State()


def is_valid_telegram_link(link: str) -> bool:
    pattern = r"https?://t\.me/[a-zA-Z0-9_]+/\d+"
    return bool(re.match(pattern, link))


@router.callback_query(F.data == "collect_comments")
async def get_post_link(callback: types.CallbackQuery, state: FSMContext):
    logger.info(f"Пользователь {callback.from_user.id} запросил парсинг комментариев")
    await callback.message.answer(
        f"Максимальное количество комментариев для бесплатного парсинга: {ParametersManager.get_parameter('free_comments_limit')}\n"
        f"Стоимость платного парсинга: {ParametersManager.get_parameter('parse_comments_cost')}₽\n"
        f"Лимит на парсинг - 50000 комментариев\n\n"
        f"Введите ссылку на пост:"
    )
    await state.set_state(PostStates.waiting_for_post_link)


@router.message(PostStates.waiting_for_post_link)
async def process_post_link(message: types.Message, state: FSMContext):
    logger.info(
        f"Получена ссылка от пользователя {message.from_user.id}: {message.text}"
    )

    if not is_valid_telegram_link(message.text):
        logger.warning(
            f"Неверный формат ссылки от пользователя {message.from_user.id}: {message.text}"
        )
        await message.answer(
            "Неверный формат ссылки. Пожалуйста, отправьте корректную ссылку на пост в Telegram."
        )
        return

    try:
        new_message = await message.answer("⏳ Проверяю пост...")
        # Получаем количество комментариев
        logger.debug(f"Получаем количество комментариев для поста: {message.text}")
        comments_count = await parser.get_comments_count(message.text)

        # Добавляем проверку на отсутствие комментариев
        if comments_count == 0:
            logger.info(f"Пост без комментариев от пользователя {message.from_user.id}")
            await new_message.edit_text(
                "❌ В этом посте нет комментариев.\n"
                "Пожалуйста, отправьте ссылку на пост, содержащий комментарии.",
                reply_markup=types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            types.InlineKeyboardButton(
                                text="📝 Отправить другую ссылку",
                                callback_data="collect_comments",
                            )
                        ]
                    ]
                ),
            )
            await state.clear()
            return

        free_limit = ParametersManager.get_parameter("free_comments_limit")
        parse_cost = ParametersManager.get_parameter("parse_comments_cost")

        logger.info(f"Пост имеет {comments_count} комментариев (лимит: {free_limit})")

        # Сохраняем ссылку в состояние
        await state.update_data(post_link=message.text)

        if comments_count > free_limit:
            user = db.get_user(message.from_user.id)
            logger.info(
                f"Платный парсинг для пользователя {message.from_user.id}. Баланс: {user.balance}"
            )

            text = (
                f"В посте {comments_count} комментариев.\n"
                f"Варианты парсинга:\n"
                f"1. Бесплатно первые {free_limit} комментариев\n"
                f"2. Все комментарии за {parse_cost}₽\n"
                f"Ваш баланс: {user.balance}₽"
            )

            buttons = [
                [
                    types.InlineKeyboardButton(
                        text=f"🆓 Первые {free_limit} комментариев",
                        callback_data="parse_free_limit",
                    )
                ]
            ]

            if user.balance >= parse_cost:
                buttons.append(
                    [
                        types.InlineKeyboardButton(
                            text=f"💰 Все за {parse_cost}₽",
                            callback_data="start_parsing",
                        )
                    ]
                )
            else:
                buttons.append(
                    [
                        types.InlineKeyboardButton(
                            text="💰 Пополнить баланс", callback_data="deposit"
                        )
                    ]
                )

            if user.is_admin:
                buttons.append(
                    [
                        types.InlineKeyboardButton(
                            text="🔓 Парсить как админ", callback_data="start_parsing"
                        )
                    ]
                )

            await new_message.edit_text(
                text, reply_markup=types.InlineKeyboardMarkup(inline_keyboard=buttons)
            )
            return
        else:
            logger.info(f"Бесплатный парсинг для пользователя {message.from_user.id}")
            text = f"В посте {comments_count} комментариев.\nПарсинг бесплатный (лимит: {free_limit})."

        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="🚀 Начать парсинг", callback_data="start_parsing"
                    )
                ]
            ]
        )
        await new_message.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logger.error(
            f"Ошибка при проверке поста для пользователя {message.from_user.id}: {str(e)}",
            exc_info=True,
        )
        await message.answer(f"Произошла ошибка при проверке поста: {str(e)}")
        await state.clear()


@router.callback_query(F.data == "start_parsing")
async def start_parsing(callback: types.CallbackQuery, state: FSMContext):
    logger.info(f"Начало парсинга для пользователя {callback.from_user.id}")

    data = await state.get_data()
    post_link = data.get("post_link")

    if not post_link:
        logger.error(
            f"Ссылка на пост не найдена для пользователя {callback.from_user.id}"
        )
        await callback.message.answer("Ошибка: ссылка на пост не найдена")
        await state.clear()
        return

    await callback.message.edit_text("⏳ Начинаю парсинг комментариев...")

    # Создаем уникальное имя файла
    file_path = f"comments_{callback.from_user.id}.xlsx"

    # Запускаем парсинг асинхронно
    asyncio.create_task(process_parsing(callback, post_link, file_path))

    # Очищаем состояние сразу
    await state.clear()


@router.callback_query(F.data == "parse_free_limit")
async def start_parsing_with_limit(callback: types.CallbackQuery, state: FSMContext):
    logger.info(
        f"Начало бесплатного парсинга с лимитом для пользователя {callback.from_user.id}"
    )

    data = await state.get_data()
    post_link = data.get("post_link")

    if not post_link:
        logger.error(
            f"Ссылка на пост не найдена для пользователя {callback.from_user.id}"
        )
        await callback.message.answer("Ошибка: ссылка на пост не найдена")
        await state.clear()
        return

    await callback.message.edit_text("⏳ Начинаю парсинг комментариев...")

    # Создаем уникальное имя файла
    file_path = f"comments_{callback.from_user.id}.xlsx"

    # Запускаем парсинг асинхронно
    asyncio.create_task(process_parsing(callback, post_link, file_path, True))

    # Очищаем состояние
    await state.clear()


async def process_parsing(
    callback: types.CallbackQuery,
    post_link: str,
    file_path: str,
    use_limit: bool = False,
):
    free_limit = ParametersManager.get_parameter("free_comments_limit")

    try:
        logger.debug(f"Начало парсинга комментариев для поста: {post_link}")

        last_progress = 0
        df_dict = None

        async for progress, data in parser.parse_comments(
            post_link, limit=free_limit if use_limit else None
        ):
            # Обновляем сообщение только если прогресс изменился на 5% или больше
            if progress - last_progress >= 5:
                await callback.message.edit_text(
                    f"⏳ Парсинг комментариев: {progress}%"
                )
                last_progress = progress

            if data is not None:
                df_dict = data
        
        # Сохраняем в Excel
        logger.debug(f"Сохранение результатов в файл: {file_path}")
        parser.save_to_excel(df_dict, file_path)

        # Отправляем файл
        logger.debug(f"Отправка файла пользователю {callback.from_user.id}")
        with open(file_path, "rb"):
            await callback.message.delete()
            await callback.message.answer_document(
                types.FSInputFile(file_path, filename="comments.xlsx"),
                caption="✅ Парсинг завершен!",
            )

        # Списываем средства, если необходимо
        comments_count = len(df_dict["Комментарии"])
        if comments_count > free_limit:
            parse_cost = ParametersManager.get_parameter("parse_comments_cost")
            logger.info(
                f"Списание {parse_cost} с баланса пользователя {callback.from_user.id}"
            )
            db.update_balance(callback.from_user.id, -parse_cost)

        logger.info(
            f"Парсинг успешно завершен для пользователя {callback.from_user.id}"
        )
    except Exception as e:
        logger.error(
            f"Ошибка при парсинге для пользователя {callback.from_user.id}: {str(e)}",
            exc_info=True,
        )
        await callback.message.edit_text(f"❌ Ошибка при парсинге: {str(e)}")
    finally:
        # Удаляем файл после отправки
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.debug(f"Файл {file_path} успешно удален")
            except Exception as e:
                logger.error(f"Ошибка при удалении файла {file_path}: {str(e)}")
