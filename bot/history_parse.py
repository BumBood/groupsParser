import logging
import os
import asyncio
from datetime import datetime
from typing import Optional
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from db.database import Database
from client.history_parser import HistoryParser
from bot.projects_keyboards import (
    parse_history_keyboard,
    cancel_keyboard,
    main_projects_keyboard,
)
from bot.utils.states import HistoryParseStates

router = Router(name="history_parse")
db = Database()
history_parser = HistoryParser()

# Создание директории для результатов
RESULTS_DIR = "parse_results"
os.makedirs(RESULTS_DIR, exist_ok=True)


# Вход в меню парсинга истории
@router.callback_query(F.data == "parse_history")
async def parse_history_menu(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для входа в меню парсинга истории"""
    await state.clear()

    await callback.message.edit_text(
        "📥 <b>Парсинг истории сообщений</b>\n\n"
        "Здесь вы можете собрать историю сообщений из любого чата, "
        "доступного через наши пользовательские сессии.\n\n",
        reply_markup=parse_history_keyboard(),
        parse_mode="HTML",
    )


# Начало парсинга истории
@router.callback_query(F.data == "start_parse_history")
async def start_parse_history(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для начала парсинга истории"""
    await state.set_state(HistoryParseStates.enter_chat_id)

    await callback.message.edit_text(
        "📥 <b>Парсинг истории сообщений</b>\n\n"
        "Введите ID чата или юзернейм канала/группы для сбора сообщений.\n\n"
        "<i>Например: @channel_name или -1001234567890</i>",
        reply_markup=cancel_keyboard("parse_history"),
        parse_mode="HTML",
    )


# Ввод ID чата для парсинга
@router.message(HistoryParseStates.enter_chat_id)
async def enter_chat_id(message: types.Message, state: FSMContext):
    """Обработчик для ввода ID чата"""
    chat_id = message.text.strip()

    # Простая валидация формата
    if not (chat_id.startswith("@") or chat_id.startswith("-100") or chat_id.isdigit()):
        await message.answer(
            "⚠️ Неверный формат ID чата. Пожалуйста, введите корректный ID.\n\n"
            "<i>Например: @channel_name или -1001234567890</i>",
            parse_mode="HTML",
        )
        return

    await state.update_data(chat_id=chat_id)
    await state.set_state(HistoryParseStates.enter_limit)

    await message.answer(
        f"📥 <b>Парсинг истории сообщений</b>\n\n"
        f"ID чата: <code>{chat_id}</code>\n\n"
        f"Введите ограничение на количество сообщений для сбора "
        f"или отправьте '0' для сбора всей доступной истории.\n\n"
        f"<i>Рекомендуется указать разумное ограничение (например, 1000-5000), "
        f"иначе процесс может занять длительное время.</i>",
        reply_markup=cancel_keyboard("parse_history"),
        parse_mode="HTML",
    )


# Ввод ограничения на количество сообщений
@router.message(HistoryParseStates.enter_limit)
async def enter_limit(message: types.Message, state: FSMContext):
    """Обработчик для ввода ограничения на количество сообщений"""
    try:
        limit = int(message.text.strip())
        if limit < 0:
            raise ValueError("Limit must be non-negative")

        limit = None if limit == 0 else limit
    except ValueError:
        await message.answer("⚠️ Пожалуйста, введите положительное целое число или 0.")
        return

    await state.update_data(limit=limit)
    await state.set_state(HistoryParseStates.enter_keywords)

    limit_text = "Без ограничений" if limit is None else str(limit)

    await message.answer(
        f"📥 <b>Парсинг истории сообщений</b>\n\n"
        f"Ограничение: {limit_text}\n\n"
        f"Введите ключевые слова для фильтрации сообщений (через запятую) "
        f"или отправьте '-' чтобы получить все сообщения:",
        reply_markup=cancel_keyboard("parse_history"),
        parse_mode="HTML",
    )


# Ввод ключевых слов и запуск парсинга
@router.message(HistoryParseStates.enter_keywords)
async def enter_keywords_and_start(message: types.Message, state: FSMContext):
    """Обработчик для ввода ключевых слов и запуска парсинга"""
    keywords = None if message.text == "-" else message.text

    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get("chat_id")
    limit = data.get("limit")

    await state.set_state(HistoryParseStates.parsing)

    # Отправляем сообщение о начале парсинга
    status_message = await message.answer(
        f"🔄 <b>Начинается парсинг...</b>\n\n"
        f"ID чата: <code>{chat_id}</code>\n"
        f"Ограничение: {limit if limit is not None else 'Без ограничений'}\n"
        f"Ключевые слова: {keywords or 'Без фильтрации'}\n\n"
        f"Прогресс: 0%",
        parse_mode="HTML",
    )

    # Запускаем парсинг
    result = None
    try:
        async for progress, data in history_parser.parse_history(
            chat_id=chat_id, limit=limit, keywords=keywords
        ):
            # Обновляем сообщение с прогрессом каждые 10%
            if progress % 10 == 0 or progress == 100:
                try:
                    await status_message.edit_text(
                        f"🔄 <b>Идет парсинг...</b>\n\n"
                        f"ID чата: <code>{chat_id}</code>\n"
                        f"Ограничение: {limit if limit is not None else 'Без ограничений'}\n"
                        f"Ключевые слова: {keywords or 'Без фильтрации'}\n\n"
                        f"Прогресс: {progress}%",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logging.error(f"Ошибка при обновлении сообщения с прогрессом: {e}")

            # Если получили финальные данные
            if progress == 100 and data:
                result = data

    except Exception as e:
        logging.error(f"Ошибка при парсинге истории: {e}")
        await status_message.edit_text(
            f"❌ <b>Ошибка при парсинге истории</b>\n\n" f"Произошла ошибка: {str(e)}",
            reply_markup=parse_history_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()
        return

    # Если парсинг завершился успешно
    if result:
        # Сохраняем результаты в Excel файл
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        user_id = message.from_user.id

        # Создаем папку для пользователя, если её нет
        user_dir = os.path.join(RESULTS_DIR, str(user_id))
        os.makedirs(user_dir, exist_ok=True)

        filename = os.path.join(
            user_dir, f"parse_{chat_id.replace('@', '')}_{timestamp}.xlsx"
        )

        try:
            history_parser.save_to_excel(result, filename)

            # Отправляем файл пользователю
            with open(filename, "rb") as file:
                await message.answer_document(
                    types.BufferedInputFile(
                        file.read(), filename=os.path.basename(filename)
                    ),
                    caption=f"📊 <b>Результаты парсинга</b>\n\n"
                    f"Чат: <code>{chat_id}</code>\n"
                    f"Всего сообщений: {result['Информация'][0]['Всего сообщений']}\n"
                    f"Отфильтровано: {result['Информация'][0]['Отфильтровано']}\n"
                    f"Ключевые слова: {keywords or 'Без фильтрации'}",
                    parse_mode="HTML",
                )

            await status_message.edit_text(
                f"✅ <b>Парсинг завершен!</b>\n\n"
                f"ID чата: <code>{chat_id}</code>\n"
                f"Собрано сообщений: {len(result['Сообщения'])}\n"
                f"Результаты отправлены файлом Excel.",
                reply_markup=parse_history_keyboard(),
                parse_mode="HTML",
            )

        except Exception as e:
            logging.error(f"Ошибка при сохранении результатов: {e}")
            await status_message.edit_text(
                f"⚠️ <b>Парсинг завершен, но возникла ошибка при сохранении</b>\n\n"
                f"Ошибка: {str(e)}",
                reply_markup=parse_history_keyboard(),
                parse_mode="HTML",
            )
    else:
        await status_message.edit_text(
            f"❌ <b>Не удалось выполнить парсинг</b>\n\n"
            f"Возможно, бот не имеет доступа к чату или чат не существует.",
            reply_markup=parse_history_keyboard(),
            parse_mode="HTML",
        )

    await state.clear()
