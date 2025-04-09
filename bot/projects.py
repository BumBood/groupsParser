import logging
from typing import Optional, Dict
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from db.database import Database
from bot.projects_keyboards import (
    main_projects_keyboard,
    projects_list_keyboard,
    project_manage_keyboard,
    cancel_keyboard,
    confirm_keyboard,
)
from bot.utils.states import ProjectStates
from bot.utils.tariff_checker import TariffChecker

router = Router(name="projects")
db = Database()


# Вход в меню проектов
@router.callback_query(F.data == "projects_menu")
async def projects_menu(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для входа в меню проектов"""
    await state.clear()

    await callback.message.edit_text(
        "📊 <b>Управление проектами</b>\n\n"
        "Здесь вы можете создавать проекты для мониторинга сообщений "
        "в различных чатах в реальном времени.",
        reply_markup=main_projects_keyboard(),
        parse_mode="HTML",
    )


# Список проектов
@router.callback_query(F.data == "projects_list")
async def list_projects(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для просмотра списка проектов"""
    user_id = callback.from_user.id
    projects = db.get_user_projects(user_id)

    if not projects:
        await callback.message.edit_text(
            "📊 <b>Список проектов</b>\n\n"
            "У вас пока нет созданных проектов. Создайте новый проект, чтобы начать мониторинг сообщений.",
            reply_markup=projects_list_keyboard([]),
            parse_mode="HTML",
        )
        return

    projects_text = "\n".join(
        [
            f"{'🟢' if p.is_active else '🔴'} <b>{p.name}</b> ({len(db.get_project_chats(p.id))} чатов)"
            for p in projects
        ]
    )

    await callback.message.edit_text(
        f"📊 <b>Список проектов</b>\n\n"
        f"{projects_text}\n\n"
        f"Выберите проект для управления:",
        reply_markup=projects_list_keyboard(projects),
        parse_mode="HTML",
    )


# Создание проекта - начало
@router.callback_query(F.data == "create_project")
async def create_project_start(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для начала создания проекта"""
    await state.set_state(ProjectStates.create_name)

    await callback.message.edit_text(
        "📝 <b>Создание проекта</b>\n\n" "Введите название для нового проекта:",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML",
    )


# Создание проекта - ввод названия
@router.message(ProjectStates.create_name)
async def create_project_name(message: types.Message, state: FSMContext):
    """Обработчик для ввода названия проекта"""
    if len(message.text) > 50:
        await message.answer(
            "⚠️ Название проекта слишком длинное. Пожалуйста, используйте не более 50 символов."
        )
        return

    await state.update_data(name=message.text)
    await state.set_state(ProjectStates.create_description)

    await message.answer(
        "📝 <b>Создание проекта</b>\n\n"
        f"Название: <b>{message.text}</b>\n\n"
        f"Теперь введите описание проекта (или отправьте '-' чтобы пропустить):",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML",
    )


# Создание проекта - ввод описания
@router.message(ProjectStates.create_description)
async def create_project_description(message: types.Message, state: FSMContext):
    """Обработчик для ввода описания проекта"""
    description = None if message.text == "-" else message.text

    # Получаем данные из состояния
    data = await state.get_data()
    name = data.get("name")

    # Проверяем ограничения тарифа перед созданием проекта
    can_create, tariff_message = TariffChecker.can_create_project(
        message.from_user.id, db
    )
    if not can_create:
        await message.answer(
            f"⚠️ <b>Невозможно создать проект:</b> {tariff_message}\n\n"
            f"Для увеличения лимитов приобретите тариф выше.",
            reply_markup=main_projects_keyboard(),
            parse_mode="HTML",
        )
        await state.clear()
        return

    # Создаем проект в БД (по умолчанию проект активный)
    project = db.create_project(
        user_id=message.from_user.id, name=name, description=description, is_active=True
    )

    await state.clear()

    # Уведомление о создании проекта
    await message.answer(
        "✅ <b>Проект успешно создан!</b>\n\n"
        f"Название: <b>{project.name}</b>\n"
        f"Описание: {project.description or 'Не указано'}\n"
        f"Статус: 🟢 Активен\n\n"
        f"Теперь вы можете добавить чаты для мониторинга.",
        reply_markup=project_manage_keyboard(project),
        parse_mode="HTML",
    )


# Просмотр проекта
@router.callback_query(F.data.startswith("project|"))
async def view_project(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для просмотра информации о проекте"""
    project_id = int(callback.data.split("|")[1])
    project = db.get_project(project_id)

    if not project:
        await callback.message.edit_text(
            "⚠️ Проект не найден.", reply_markup=main_projects_keyboard()
        )
        return

    # Проверяем, принадлежит ли проект пользователю
    if project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому проекту.", show_alert=True)
        return

    chats_count = len(db.get_project_chats(project_id))
    status = "🟢 Активен" if project.is_active else "🔴 Остановлен"

    await callback.message.edit_text(
        f"📊 <b>Проект: {project.name}</b>\n\n"
        f"Статус: {status}\n"
        f"Описание: {project.description or 'Не указано'}\n"
        f"Количество чатов: {chats_count}\n\n"
        f"Выберите действие:",
        reply_markup=project_manage_keyboard(project),
        parse_mode="HTML",
    )


# Редактирование проекта - начало
@router.callback_query(F.data.startswith("edit_project|"))
async def edit_project_start(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для начала редактирования проекта"""
    project_id = int(callback.data.split("|")[1])
    project = db.get_project(project_id)

    if not project:
        await callback.message.edit_text(
            "⚠️ Проект не найден.", reply_markup=main_projects_keyboard()
        )
        return

    # Проверяем, принадлежит ли проект пользователю
    if project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому проекту.", show_alert=True)
        return

    await state.set_state(ProjectStates.edit_name)
    await state.update_data(project_id=project_id)

    await callback.message.edit_text(
        f"✏️ <b>Редактирование проекта</b>\n\n"
        f"Текущее название: <b>{project.name}</b>\n\n"
        f"Введите новое название проекта (или отправьте '-' чтобы оставить без изменений):",
        reply_markup=cancel_keyboard(f"project|{project_id}"),
        parse_mode="HTML",
    )


# Редактирование проекта - ввод названия
@router.message(ProjectStates.edit_name)
async def edit_project_name(message: types.Message, state: FSMContext):
    """Обработчик для ввода нового названия проекта"""
    data = await state.get_data()
    project_id = data.get("project_id")
    project = db.get_project(project_id)

    if not project:
        await message.answer(
            "⚠️ Проект не найден.", reply_markup=main_projects_keyboard()
        )
        await state.clear()
        return

    if message.text != "-":
        if len(message.text) > 50:
            await message.answer(
                "⚠️ Название проекта слишком длинное. Пожалуйста, используйте не более 50 символов."
            )
            return

        await state.update_data(name=message.text)
    else:
        await state.update_data(name=project.name)

    await state.set_state(ProjectStates.edit_description)

    await message.answer(
        f"✏️ <b>Редактирование проекта</b>\n\n"
        f"Название: <b>{message.text if message.text != '-' else project.name}</b>\n\n"
        f"Текущее описание: {project.description or 'Не указано'}\n\n"
        f"Введите новое описание проекта (или отправьте '-' чтобы оставить без изменений):",
        reply_markup=cancel_keyboard(f"project|{project_id}"),
        parse_mode="HTML",
    )


# Редактирование проекта - ввод описания
@router.message(ProjectStates.edit_description)
async def edit_project_description(message: types.Message, state: FSMContext):
    """Обработчик для ввода нового описания проекта"""
    data = await state.get_data()
    project_id = data.get("project_id")
    name = data.get("name")

    project = db.get_project(project_id)
    if not project:
        await message.answer(
            "⚠️ Проект не найден.", reply_markup=main_projects_keyboard()
        )
        await state.clear()
        return

    description = project.description if message.text == "-" else message.text

    # Обновляем проект в БД
    updated_project = db.update_project(
        project_id=project_id, name=name, description=description
    )

    await state.clear()

    if updated_project:
        await message.answer(
            "✅ <b>Проект успешно обновлен!</b>\n\n"
            f"Название: <b>{updated_project.name}</b>\n"
            f"Описание: {updated_project.description or 'Не указано'}\n\n",
            reply_markup=project_manage_keyboard(updated_project),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "⚠️ Не удалось обновить проект.", reply_markup=main_projects_keyboard()
        )


# Включение/выключение проекта
@router.callback_query(F.data.startswith("toggle_project|"))
async def toggle_project(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для включения/выключения проекта"""
    project_id = int(callback.data.split("|")[1])
    project = db.get_project(project_id)

    if not project:
        await callback.message.edit_text(
            "⚠️ Проект не найден.", reply_markup=main_projects_keyboard()
        )
        return

    # Проверяем, принадлежит ли проект пользователю
    if project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому проекту.", show_alert=True)
        return

    # Переключаем статус проекта
    updated_project = db.toggle_project_status(project_id)

    if not updated_project:
        await callback.answer("Не удалось изменить статус проекта.", show_alert=True)
        return

    # Получаем все чаты проекта
    project_chats = db.get_project_chats(project_id)
    chats_count = len(project_chats)

    # Получаем мониторинговую систему из бота
    monitoring_system = callback.bot.monitoring_system

    # Если система мониторинга доступна, обновляем статус чатов
    if monitoring_system:
        # Если проект активирован - запускаем мониторинг
        if updated_project.is_active:
            active_chats = db.get_project_chats(project_id, active_only=True)

            if active_chats:
                activated_count = 0

                for chat in active_chats:
                    # Сначала пробуем вступить в чат
                    join_success = await monitoring_system.join_chat(chat.id)

                    # Если удалось вступить, активируем мониторинг
                    if join_success:
                        monitor_success = (
                            await monitoring_system.add_chat_to_monitoring(
                                project_id, chat.id
                            )
                        )
                        if monitor_success:
                            activated_count += 1

                if activated_count > 0:
                    await callback.answer(
                        f"Проект активирован. Запущен мониторинг {activated_count} из {len(active_chats)} чатов.",
                        show_alert=True,
                    )
                else:
                    await callback.answer(
                        "Проект активирован, но не удалось запустить мониторинг чатов.",
                        show_alert=True,
                    )
            else:
                await callback.answer(
                    "Проект активирован, но нет активных чатов для мониторинга.",
                    show_alert=True,
                )

        # Если проект деактивирован - останавливаем мониторинг
        else:
            stopped_count = 0

            for chat in project_chats:
                if await monitoring_system.remove_chat_from_monitoring(chat.id):
                    stopped_count += 1

            await callback.answer(
                f"Проект остановлен. Отключен мониторинг {stopped_count} чатов.",
                show_alert=True,
            )
    else:
        status = "активирован" if updated_project.is_active else "остановлен"
        await callback.answer(
            f"Проект {status}, но система мониторинга недоступна.", show_alert=True
        )

    # Обновляем сообщение
    status_text = "🟢 Активен" if updated_project.is_active else "🔴 Остановлен"

    await callback.message.edit_text(
        f"📊 <b>Проект: {updated_project.name}</b>\n\n"
        f"Статус: {status_text}\n"
        f"Описание: {updated_project.description or 'Не указано'}\n"
        f"Количество чатов: {chats_count}\n\n"
        f"Выберите действие:",
        reply_markup=project_manage_keyboard(updated_project),
        parse_mode="HTML",
    )


# Удаление проекта - запрос подтверждения
@router.callback_query(F.data.startswith("delete_project|"))
async def delete_project_confirm(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для запроса подтверждения удаления проекта"""
    project_id = int(callback.data.split("|")[1])
    project = db.get_project(project_id)

    if not project:
        await callback.message.edit_text(
            "⚠️ Проект не найден.", reply_markup=main_projects_keyboard()
        )
        return

    # Проверяем, принадлежит ли проект пользователю
    if project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому проекту.", show_alert=True)
        return

    await state.set_state(ProjectStates.delete_confirm)
    await state.update_data(project_id=project_id)

    chats_count = len(db.get_project_chats(project_id))

    await callback.message.edit_text(
        f"🗑️ <b>Удаление проекта</b>\n\n"
        f"Вы уверены, что хотите удалить проект <b>{project.name}</b>?\n\n"
        f"Будут удалены все настройки проекта и {chats_count} связанных чатов.\n"
        f"Это действие нельзя отменить!",
        reply_markup=confirm_keyboard(
            confirm_callback=f"confirm_delete_project|{project_id}",
            cancel_callback=f"project|{project_id}",
        ),
        parse_mode="HTML",
    )


# Удаление проекта - подтверждение
@router.callback_query(F.data.startswith("confirm_delete_project|"))
async def delete_project_execute(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для подтверждения удаления проекта"""
    project_id = int(callback.data.split("|")[1])
    project = db.get_project(project_id)

    if not project:
        await callback.message.edit_text(
            "⚠️ Проект не найден.", reply_markup=main_projects_keyboard()
        )
        await state.clear()
        return

    # Проверяем, принадлежит ли проект пользователю
    if project.user_id != callback.from_user.id:
        await callback.answer("У вас нет доступа к этому проекту.", show_alert=True)
        await state.clear()
        return

    # Удаляем проект
    success = db.delete_project(project_id)

    await state.clear()

    if success:
        await callback.message.edit_text(
            f"✅ <b>Проект успешно удален!</b>\n\n"
            f"Проект <b>{project.name}</b> и все связанные с ним чаты были удалены.",
            reply_markup=main_projects_keyboard(),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            "⚠️ Не удалось удалить проект.", reply_markup=main_projects_keyboard()
        )
