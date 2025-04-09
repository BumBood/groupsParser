from typing import Optional
from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from db.database import Database
from client.monitoring_setup import MonitoringSystem
from bot.projects_keyboards import (
    chats_list_keyboard,
    chat_manage_keyboard,
    project_manage_keyboard,
    cancel_keyboard,
    confirm_keyboard,
)
from bot.utils.states import ChatStates

router = Router(name="project_chats")
db = Database()


# Просмотр списка чатов проекта
@router.callback_query(F.data.startswith("project_chats|"))
async def list_project_chats(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для просмотра списка чатов проекта"""
    project_id = int(callback.data.split("|")[1])
    project = db.get_project(project_id)

    if not project:
        await callback.message.edit_text(
            "⚠️ Проект не найден.", reply_markup=cancel_keyboard("projects_list")
        )
        return

    # Проверяем, принадлежит ли проект пользователю
    if project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому проекту.", show_alert=True)
        return

    chats = db.get_project_chats(project_id)

    if not chats:
        await callback.message.edit_text(
            f"📋 <b>Чаты проекта</b>: {project.name}\n\n"
            f"У этого проекта пока нет добавленных чатов. "
            f"Добавьте чаты для начала мониторинга.",
            reply_markup=chats_list_keyboard([], project_id),
            parse_mode="HTML",
        )
        return

    chats_text = "\n".join(
        [
            f"{'🟢' if chat.is_active else '🔴'} <b>{chat.chat_title or chat.chat_id}</b>"
            for chat in chats
        ]
    )

    await callback.message.edit_text(
        f"📋 <b>Чаты проекта</b>: {project.name}\n\n"
        f"{chats_text}\n\n"
        f"Выберите чат для управления:",
        reply_markup=chats_list_keyboard(chats, project_id),
        parse_mode="HTML",
    )


# Добавление чата - начало
@router.callback_query(F.data.startswith("add_chat|"))
async def add_chat_start(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для начала добавления чата в проект"""
    project_id = int(callback.data.split("|")[1])
    project = db.get_project(project_id)

    if not project:
        await callback.message.edit_text(
            "⚠️ Проект не найден.", reply_markup=cancel_keyboard("projects_list")
        )
        return

    # Проверяем, принадлежит ли проект пользователю
    if project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому проекту.", show_alert=True)
        return

    await state.set_state(ChatStates.add_chat_id)
    await state.update_data(project_id=project_id)

    await callback.message.edit_text(
        f"➕ <b>Добавление чата в проект</b>: {project.name}\n\n"
        f"Введите ссылку на канал/группу или юзернейм.\n\n"
        f"<i>Например: @channel_name или https://t.me/channel_name</i>",
        reply_markup=cancel_keyboard(f"project_chats|{project_id}"),
        parse_mode="HTML",
    )


# Добавление чата - ввод ID или ссылки
@router.message(ChatStates.add_chat_id)
async def add_chat_id(message: types.Message, state: FSMContext):
    """Обработчик для ввода ID чата или ссылки"""
    chat_id_or_link = message.text.strip()

    # Получаем данные из состояния
    data = await state.get_data()
    project_id = data.get("project_id")

    # Преобразуем ссылку в формат, понятный Telegram
    chat_id = chat_id_or_link
    if chat_id_or_link.startswith("https://t.me/"):
        if "/+" in chat_id_or_link:
            # Приватная ссылка-приглашение
            await message.answer(
                "⚠️ <b>Ошибка:</b> Приватные ссылки-приглашения пока не поддерживаются.\n\n"
                "Используйте публичные каналы или группы.",
                parse_mode="HTML",
                reply_markup=cancel_keyboard(f"project_chats|{project_id}"),
            )
            return
        else:
            # Публичный канал или группа
            username = chat_id_or_link.split("/")[-1]
            chat_id = "@" + username

    # Определяем предполагаемое название чата из юзернейма
    suggested_title = chat_id.replace("@", "")

    await state.update_data(chat_id=chat_id, suggested_title=suggested_title)
    await state.set_state(ChatStates.add_chat_title)

    await message.answer(
        f"➕ <b>Добавление чата</b>\n\n"
        f"Чат: <code>{chat_id}</code>\n\n"
        f"Введите название чата (для отображения в списке):",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML",
    )


# Добавление чата - ввод названия
@router.message(ChatStates.add_chat_title)
async def add_chat_title(message: types.Message, state: FSMContext):
    """Обработчик для ввода названия чата"""
    chat_title = message.text.strip()

    if len(chat_title) > 50:
        await message.answer(
            "⚠️ Название чата слишком длинное. Пожалуйста, используйте не более 50 символов."
        )
        return

    await state.update_data(chat_title=chat_title)
    await state.set_state(ChatStates.add_keywords)

    await message.answer(
        f"➕ <b>Добавление чата</b>\n\n"
        f"Название: <b>{chat_title}</b>\n\n"
        f"Введите ключевые слова для фильтрации сообщений (через запятую)"
        f"или отправьте '-' чтобы получать все сообщения. ВАЖНО: пробел ТОЖЕ входит в ключевое слово:",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML",
    )


# Добавление чата - ввод ключевых слов
@router.message(ChatStates.add_keywords)
async def add_chat_keywords(message: types.Message, state: FSMContext):
    """Обработчик для ввода ключевых слов"""
    keywords = None if message.text == "-" else message.text

    # Получаем данные из состояния
    data = await state.get_data()
    project_id = data.get("project_id")
    chat_id = data.get("chat_id")
    chat_title = data.get("chat_title")

    project = db.get_project(project_id)
    if not project:
        await message.answer(
            "⚠️ Проект не найден.", reply_markup=cancel_keyboard("projects_list")
        )
        await state.clear()
        return

    # Получаем мониторинговую систему из бота
    monitoring_system = message.bot.monitoring_system

    # Проверяем наличие доступных сессий перед добавлением чата
    if monitoring_system and not await monitoring_system.check_available_sessions():
        await message.answer(
            "⚠️ <b>Ошибка:</b> Нет доступных сессий для мониторинга.\n\n"
            "Чтобы добавить чат, необходимо сначала добавить хотя бы одну "
            "активную сессию Telegram в систему. Обратитесь к администратору.",
            reply_markup=project_manage_keyboard(project),
            parse_mode="HTML",
        )
        await state.clear()
        return

    # Добавляем чат в БД (по умолчанию чат активный)
    chat = db.add_chat_to_project(
        project_id=project_id,
        chat_id=chat_id,
        chat_title=chat_title,
        keywords=keywords,
        is_active=True,
    )

    await state.clear()

    if not chat:
        await message.answer(
            "⚠️ <b>Ошибка:</b> Не удалось добавить чат в проект.\n\n"
            "Возможно, этот чат уже добавлен в этот проект.",
            reply_markup=project_manage_keyboard(project),
            parse_mode="HTML",
        )
        return

    # Если проект активен, пытаемся сразу вступить в чат и начать мониторинг
    if project.is_active and monitoring_system:
        # Пытаемся вступить в чат
        join_success = await monitoring_system.join_chat(chat.id)
        if join_success:
            # Если успешно вступили, запускаем мониторинг
            monitor_success = await monitoring_system.add_chat_to_monitoring(
                project_id, chat.id
            )
            if monitor_success:
                await message.answer(
                    "✅ <b>Чат успешно добавлен и мониторинг запущен!</b>\n\n"
                    f"Чат: <b>{chat.chat_title}</b>\n"
                    f"Ключевые слова: {keywords or 'Все сообщения'}\n"
                    f"Статус: 🟢 Активен (мониторинг работает)",
                    reply_markup=chat_manage_keyboard(chat, project_id),
                    parse_mode="HTML",
                )
            else:
                await message.answer(
                    "⚠️ <b>Чат добавлен, но не удалось запустить мониторинг</b>\n\n"
                    f"Чат: <b>{chat.chat_title}</b>\n"
                    f"Ключевые слова: {keywords or 'Все сообщения'}\n"
                    f"Статус: 🟢 Активен (мониторинг не работает)",
                    reply_markup=chat_manage_keyboard(chat, project_id),
                    parse_mode="HTML",
                )
        else:
            await message.answer(
                "⚠️ <b>Чат добавлен, но не удалось вступить в чат</b>\n\n"
                f"Чат: <b>{chat.chat_title}</b>\n"
                f"Ключевые слова: {keywords or 'Все сообщения'}\n"
                f"Статус: 🟢 Активен (не удалось вступить)\n\n"
                f"Убедитесь, что бот имеет доступ к чату и правильно указан юзернейм/ссылка.",
                reply_markup=chat_manage_keyboard(chat, project_id),
                parse_mode="HTML",
            )
    else:
        # Если проект неактивен или система мониторинга недоступна
        status_text = (
            "🟢 Активен (проект неактивен)"
            if not project.is_active
            else "🟢 Активен (система мониторинга недоступна)"
        )
        await message.answer(
            f"✅ <b>Чат успешно добавлен!</b>\n\n"
            f"Чат: <b>{chat.chat_title}</b>\n"
            f"Ключевые слова: {keywords or 'Все сообщения'}\n"
            f"Статус: {status_text}",
            reply_markup=chat_manage_keyboard(chat, project_id),
            parse_mode="HTML",
        )


# Добавление нескольких чатов - начало
@router.callback_query(F.data.startswith("add_multiple_chats|"))
async def add_multiple_chats_start(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для начала добавления нескольких чатов в проект"""
    project_id = int(callback.data.split("|")[1])
    project = db.get_project(project_id)

    if not project:
        await callback.message.edit_text(
            "⚠️ Проект не найден.", reply_markup=cancel_keyboard("projects_list")
        )
        return

    # Проверяем, принадлежит ли проект пользователю
    if project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому проекту.", show_alert=True)
        return

    await state.set_state(ChatStates.add_multiple_chats)
    await state.update_data(project_id=project_id)

    await callback.message.edit_text(
        f"➕➕ <b>Добавление нескольких чатов в проект</b>: {project.name}\n\n"
        f"Введите ссылки на каналы/группы или юзернеймы, каждый с новой строки.\n\n"
        f"<i>Например:\n"
        f"@channel1\n"
        f"https://t.me/channel2\n"
        f"@group3</i>",
        reply_markup=cancel_keyboard(f"project_chats|{project_id}"),
        parse_mode="HTML",
    )


# Добавление нескольких чатов - обработка списка
@router.message(ChatStates.add_multiple_chats)
async def add_multiple_chats_process(message: types.Message, state: FSMContext):
    """Обработчик для ввода списка чатов"""
    chats_list_raw = message.text.strip().split("\n")

    # Фильтруем пустые строки
    chats_list_raw = [chat.strip() for chat in chats_list_raw if chat.strip()]

    if not chats_list_raw:
        await message.answer(
            "⚠️ Список чатов пуст. Пожалуйста, введите хотя бы один чат.",
            reply_markup=cancel_keyboard(),
        )
        return

    # Обрабатываем ссылки в формате Telegram
    chats_list = []
    for chat_id_or_link in chats_list_raw:
        if chat_id_or_link.startswith("https://t.me/"):
            # Публичный канал или группа
            username = chat_id_or_link.split("/")[-1]
            chat_id = f"@{username}"
            chats_list.append({"chat_id": chat_id, "title": username})
        else:
            # Просто юзернейм или ID
            chat_id = chat_id_or_link
            title = chat_id.replace("@", "")
            chats_list.append({"chat_id": chat_id, "title": title})

    if not chats_list:
        await message.answer(
            "⚠️ Нет корректных чатов для добавления. Пожалуйста, используйте публичные каналы или группы.",
            reply_markup=cancel_keyboard(),
        )
        return

    # Получаем данные из состояния
    await state.update_data(chats_list=chats_list)
    await state.set_state(ChatStates.add_multiple_keywords)

    await message.answer(
        f"➕➕ <b>Добавление {len(chats_list)} чатов</b>\n\n"
        f"Введите ключевые слова для фильтрации сообщений (через запятую)"
        f"или отправьте '-' чтобы получать все сообщения. ВАЖНО: пробел ТОЖЕ входит в ключевое слово:",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML",
    )


# Добавление нескольких чатов - указание ключевых слов и завершение
@router.message(ChatStates.add_multiple_keywords)
async def add_multiple_chats_keywords(message: types.Message, state: FSMContext):
    """Обработчик для ввода ключевых слов для множественного добавления чатов"""
    keywords = None if message.text == "-" else message.text

    # Получаем данные из состояния
    data = await state.get_data()
    project_id = data.get("project_id")
    chats_data = data.get("chats_list", [])

    project = db.get_project(project_id)
    if not project:
        await message.answer(
            "⚠️ Проект не найден.", reply_markup=cancel_keyboard("projects_list")
        )
        await state.clear()
        return

    # Получаем мониторинговую систему из бота
    monitoring_system = message.bot.monitoring_system

    # Проверяем наличие доступных сессий перед добавлением чатов
    if monitoring_system and not await monitoring_system.check_available_sessions():
        await message.answer(
            "⚠️ <b>Ошибка:</b> Нет доступных сессий для мониторинга.\n\n"
            "Чтобы добавить чаты, необходимо сначала добавить хотя бы одну "
            "активную сессию Telegram в систему. Обратитесь к администратору.",
            reply_markup=project_manage_keyboard(project),
            parse_mode="HTML",
        )
        await state.clear()
        return

    # Добавляем чаты в проект
    added_chats = []
    failed_chats = []

    for chat_info in chats_data:
        chat = db.add_chat_to_project(
            project_id=project_id,
            chat_id=chat_info["chat_id"],
            chat_title=chat_info["title"],
            keywords=keywords,
        )
        if chat:
            added_chats.append(chat)
        else:
            failed_chats.append(chat_info["chat_id"])

    await state.clear()

    if not added_chats:
        await message.answer(
            "⚠️ <b>Ошибка:</b> Не удалось добавить ни один чат в проект.\n\n"
            "Возможно, эти чаты уже добавлены в этот проект.",
            reply_markup=project_manage_keyboard(project),
            parse_mode="HTML",
        )
        return

    # Если проект активен и система мониторинга доступна,
    # пытаемся начать мониторинг добавленных чатов
    activated_chats = 0
    if project.is_active and monitoring_system:
        for chat in added_chats:
            # Пытаемся вступить в чат
            join_success = await monitoring_system.join_chat(chat.id)
            if join_success:
                # Запускаем мониторинг
                monitor_success = await monitoring_system.add_chat_to_monitoring(
                    project_id, chat.id
                )
                if monitor_success:
                    activated_chats += 1

    # Формируем текст результата
    result_text = f"✅ <b>Добавлено чатов:</b> {len(added_chats)}"
    if failed_chats:
        result_text += f"\n❌ <b>Не удалось добавить:</b> {len(failed_chats)}"

    if project.is_active and monitoring_system:
        result_text += (
            f"\n\n🔍 <b>Запущен мониторинг:</b> {activated_chats} из {len(added_chats)}"
        )

    await message.answer(
        f"{result_text}\n\n"
        f"Ключевые слова: {keywords or 'Все сообщения'}\n\n"
        f"Вы можете просмотреть и редактировать добавленные чаты в списке чатов проекта.",
        reply_markup=project_manage_keyboard(project),
        parse_mode="HTML",
    )


# Просмотр информации о чате
@router.callback_query(F.data.startswith("chat|"))
async def view_chat(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для просмотра информации о чате"""
    chat_id = int(callback.data.split("|")[1])
    chat = db.get_chat(chat_id)

    if not chat:
        await callback.message.edit_text(
            "⚠️ Чат не найден.", reply_markup=cancel_keyboard("projects_list")
        )
        return

    # Получаем проект и проверяем права доступа
    project = db.get_project(chat.project_id)
    if not project or project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому чату.", show_alert=True)
        return

    status = "🟢 Активен" if chat.is_active and project.is_active else "🔴 Не активен"
    if not project.is_active:
        status += " (проект остановлен)"

    await callback.message.edit_text(
        f"📱 <b>Чат</b>: {chat.chat_title}\n\n"
        f"ID: <code>{chat.chat_id}</code>\n"
        f"Проект: <b>{project.name}</b>\n"
        f"Статус: {status}\n"
        f"Ключевые слова: {chat.keywords or 'Все сообщения'}\n\n"
        f"Выберите действие:",
        reply_markup=chat_manage_keyboard(chat),
        parse_mode="HTML",
    )


# Включение/выключение чата
@router.callback_query(F.data.startswith("toggle_chat|"))
async def toggle_chat(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для включения/выключения чата"""
    params = callback.data.split("|")
    chat_id = int(params[1])
    project_id = int(params[2])

    chat = db.get_chat(chat_id)
    project = db.get_project(project_id)

    if not chat or not project:
        await callback.message.edit_text(
            "⚠️ Чат или проект не найден.", reply_markup=cancel_keyboard("projects_list")
        )
        return

    # Проверяем, принадлежит ли проект пользователю
    if project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому проекту.", show_alert=True)
        return

    # Переключаем статус чата
    updated_chat = db.toggle_chat_status(chat_id)

    # Получаем мониторинговую систему из бота
    monitoring_system = callback.bot.monitoring_system

    if updated_chat:
        # Обновляем мониторинг чата в зависимости от его статуса
        if project.is_active:
            if updated_chat.is_active:
                # Чат активирован - пытаемся запустить мониторинг
                if monitoring_system:
                    # Сначала пытаемся вступить в чат
                    join_success = await monitoring_system.join_chat(chat.id)
                    if join_success:
                        # Запускаем мониторинг
                        monitor_success = (
                            await monitoring_system.add_chat_to_monitoring(
                                project_id, chat.id
                            )
                        )
                        if monitor_success:
                            await callback.answer(
                                "Чат активирован и мониторинг запущен!", show_alert=True
                            )
                        else:
                            await callback.answer(
                                "Чат активирован, но не удалось запустить мониторинг.",
                                show_alert=True,
                            )
                    else:
                        await callback.answer(
                            "Чат активирован, но не удалось вступить в чат. "
                            "Проверьте настройки доступа.",
                            show_alert=True,
                        )
                else:
                    await callback.answer(
                        "Чат активирован, но система мониторинга недоступна.",
                        show_alert=True,
                    )
            else:
                # Чат деактивирован - останавливаем мониторинг
                if monitoring_system:
                    await monitoring_system.remove_chat_from_monitoring(chat_id)
                    await callback.answer(
                        "Чат и мониторинг деактивированы.", show_alert=True
                    )
                else:
                    await callback.answer(
                        "Чат деактивирован. Система мониторинга недоступна.",
                        show_alert=True,
                    )
        else:
            # Проект неактивен
            status = "активирован" if updated_chat.is_active else "деактивирован"
            await callback.answer(
                f"Чат {status}, но проект неактивен.", show_alert=True
            )

        # Обновляем сообщение
        chat_status = "🟢 Активен" if updated_chat.is_active else "🔴 Остановлен"
        await callback.message.edit_text(
            f"👁‍🗨 <b>Чат: {updated_chat.chat_title or updated_chat.chat_id}</b>\n\n"
            f"ID: <code>{updated_chat.chat_id}</code>\n"
            f"Статус: {chat_status}\n"
            f"Ключевые слова: {updated_chat.keywords or 'Все сообщения'}\n\n"
            f"Выберите действие:",
            reply_markup=chat_manage_keyboard(updated_chat, project_id),
            parse_mode="HTML",
        )
    else:
        await callback.answer("Не удалось изменить статус чата.", show_alert=True)


# Редактирование ключевых слов - начало
@router.callback_query(F.data.startswith("chat_keywords|"))
async def edit_keywords_start(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для начала редактирования ключевых слов"""
    chat_id = int(callback.data.split("|")[1])
    chat = db.get_chat(chat_id)

    if not chat:
        await callback.message.edit_text(
            "⚠️ Чат не найден.", reply_markup=cancel_keyboard("projects_list")
        )
        return

    # Получаем проект и проверяем права доступа
    project = db.get_project(chat.project_id)
    if not project or project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому чату.", show_alert=True)
        return

    await state.set_state(ChatStates.edit_keywords)
    await state.update_data(chat_id=chat_id)

    await callback.message.edit_text(
        f"🔑 <b>Редактирование ключевых слов</b>\n\n"
        f"Чат: <b>{chat.chat_title}</b>\n"
        f"Текущие ключевые слова: {chat.keywords or 'Все сообщения'}\n\n"
        f"Введите новые ключевые слова для фильтрации сообщений (через запятую) "
        f"или отправьте '-' чтобы получать все сообщения. ВАЖНО: пробел ТОЖЕ входит в ключевое слово:",
        reply_markup=cancel_keyboard(f"chat|{chat_id}"),
        parse_mode="HTML",
    )


# Редактирование ключевых слов - сохранение
@router.message(ChatStates.edit_keywords)
async def edit_keywords_save(message: types.Message, state: FSMContext):
    """Обработчик для сохранения измененных ключевых слов"""
    keywords = None if message.text == "-" else message.text

    # Получаем данные из состояния
    data = await state.get_data()
    chat_id = data.get("chat_id")
    project_id = data.get("project_id")

    chat = db.get_chat(chat_id)
    project = db.get_project(project_id)

    if not chat or not project:
        await message.answer(
            "⚠️ Чат или проект не найден.",
            reply_markup=cancel_keyboard("projects_list"),
        )
        await state.clear()
        return

    # Получаем мониторинговую систему из бота
    monitoring_system = message.bot.monitoring_system

    # Обновляем ключевые слова в БД
    updated_chat = db.update_chat(chat_id=chat_id, keywords=keywords)

    await state.clear()

    if updated_chat:
        # Если чат и проект активны, перезапускаем мониторинг с новыми ключевыми словами
        if updated_chat.is_active and project.is_active and monitoring_system:
            # Останавливаем текущий мониторинг
            await monitoring_system.remove_chat_from_monitoring(chat_id)
            # Запускаем мониторинг с новыми параметрами
            monitor_success = await monitoring_system.add_chat_to_monitoring(
                project.id, chat_id
            )
            if monitor_success:
                await message.answer(
                    "✅ <b>Ключевые слова обновлены!</b>\n\n"
                    f"Чат: <b>{updated_chat.chat_title or updated_chat.chat_id}</b>\n"
                    f"Новые ключевые слова: {keywords or 'Все сообщения'}\n\n"
                    f"Мониторинг перезапущен с новыми параметрами.",
                    reply_markup=chat_manage_keyboard(updated_chat, project_id),
                    parse_mode="HTML",
                )
            else:
                await message.answer(
                    "✅ <b>Ключевые слова обновлены!</b>\n\n"
                    f"Чат: <b>{updated_chat.chat_title or updated_chat.chat_id}</b>\n"
                    f"Новые ключевые слова: {keywords or 'Все сообщения'}\n\n"
                    f"⚠️ Не удалось перезапустить мониторинг с новыми параметрами.",
                    reply_markup=chat_manage_keyboard(updated_chat, project_id),
                    parse_mode="HTML",
                )
        else:
            status_info = ""
            if not updated_chat.is_active:
                status_info = "Чат неактивен, мониторинг не запущен."
            elif not project.is_active:
                status_info = "Проект неактивен, мониторинг не запущен."
            elif not monitoring_system:
                status_info = "Система мониторинга недоступна."

            await message.answer(
                f"✅ <b>Ключевые слова обновлены!</b>\n\n"
                f"Чат: <b>{updated_chat.chat_title or updated_chat.chat_id}</b>\n"
                f"Новые ключевые слова: {keywords or 'Все сообщения'}\n\n"
                f"{status_info}",
                reply_markup=chat_manage_keyboard(updated_chat, project_id),
                parse_mode="HTML",
            )
    else:
        await message.answer(
            "⚠️ <b>Ошибка:</b> Не удалось обновить ключевые слова.",
            reply_markup=chat_manage_keyboard(chat, project_id),
            parse_mode="HTML",
        )


# Удаление чата - запрос подтверждения
@router.callback_query(F.data.startswith("delete_chat|"))
async def delete_chat_confirm(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для запроса подтверждения удаления чата"""
    chat_id = int(callback.data.split("|")[1])
    chat = db.get_chat(chat_id)

    if not chat:
        await callback.message.edit_text(
            "⚠️ Чат не найден.", reply_markup=cancel_keyboard("projects_list")
        )
        return

    # Получаем проект и проверяем права доступа
    project = db.get_project(chat.project_id)
    if not project or project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому чату.", show_alert=True)
        return

    await state.set_state(ChatStates.delete_confirm)
    await state.update_data(chat_id=chat_id)

    await callback.message.edit_text(
        f"🗑️ <b>Удаление чата</b>\n\n"
        f"Вы уверены, что хотите удалить чат <b>{chat.chat_title}</b> из проекта <b>{project.name}</b>?\n\n"
        f"Это действие нельзя отменить!",
        reply_markup=confirm_keyboard(
            confirm_callback=f"confirm_delete_chat|{chat_id}|{project.id}",
            cancel_callback=f"chat|{chat_id}",
        ),
        parse_mode="HTML",
    )


# Удаление чата - подтверждение
@router.callback_query(F.data.startswith("confirm_delete_chat|"))
async def delete_chat_execute(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для подтверждения удаления чата"""
    params = callback.data.split("|")
    chat_id = int(params[1])
    project_id = int(params[2])

    chat = db.get_chat(chat_id)
    project = db.get_project(project_id)

    if not chat or not project:
        await callback.message.edit_text(
            "⚠️ Чат или проект не найден.",
            reply_markup=cancel_keyboard("projects_list"),
        )
        await state.clear()
        return

    # Проверяем, принадлежит ли проект пользователю
    if project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому проекту.", show_alert=True)
        await state.clear()
        return

    # Получаем мониторинговую систему из бота
    monitoring_system = callback.bot.monitoring_system

    # Если чат активен, останавливаем мониторинг перед удалением
    if monitoring_system and chat.is_active:
        await monitoring_system.remove_chat_from_monitoring(chat_id)

    # Удаляем чат
    success = db.delete_chat(chat_id)

    await state.clear()

    if success:
        await callback.message.edit_text(
            f"✅ <b>Чат успешно удален!</b>\n\n"
            f"Чат <b>{chat.chat_title or chat.chat_id}</b> был удален из проекта "
            f"<b>{project.name}</b> и мониторинг остановлен.",
            reply_markup=cancel_keyboard(f"project_chats|{project_id}"),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            "⚠️ <b>Ошибка:</b> Не удалось удалить чат.",
            reply_markup=cancel_keyboard(f"project_chats|{project_id}"),
            parse_mode="HTML",
        )
