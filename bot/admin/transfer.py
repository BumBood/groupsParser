from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging

from db.database import Database
from bot.utils.pagination import Paginator

logger = logging.getLogger(__name__)

router = Router(name="admin_transfer")
db = Database()


class AdminTransferStates(StatesGroup):
    waiting_for_source_user = State()
    waiting_for_target_user = State()
    waiting_for_confirmation = State()


@router.callback_query(F.data == "transfer_tasks")
async def start_transfer(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        logger.warning(
            f"Попытка несанкционированного доступа к переносу задач от пользователя {callback.from_user.id}"
        )
        return

    logger.info(f"Администратор {callback.from_user.id} начал процесс переноса задач")

    # Показываем список пользователей для выбора источника
    users = db.get_all_users()

    def user_callback(user) -> tuple[str, str]:
        projects_count = len(db.get_user_projects(user.user_id))
        return (
            f"{'👑 ' if user.is_admin else ''}ID: {user.user_id} | "
            f"{user.username or user.full_name or 'Без имени'} "
            f"(проектов: {projects_count})",
            f"select_source_{user.user_id}",
        )

    paginator = Paginator(
        items=users,
        items_per_page=8,
        callback_prefix="source_users",
        item_callback=user_callback,
        return_callback="back_to_admin",
    )

    await callback.message.edit_text(
        "🔄 Перенос задач\n\n"
        "Выберите пользователя-источника (от кого копировать задачи):",
        reply_markup=paginator.get_page_keyboard(0),
    )


@router.callback_query(F.data.startswith("source_users_page_"))
async def handle_source_users_page(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    page = int(callback.data.split("_")[-1])
    users = db.get_all_users()

    def user_callback(user) -> tuple[str, str]:
        projects_count = len(db.get_user_projects(user.user_id))
        return (
            f"{'👑 ' if user.is_admin else ''}ID: {user.user_id} | "
            f"{user.username or user.full_name or 'Без имени'} "
            f"(проектов: {projects_count})",
            f"select_source_{user.user_id}",
        )

    paginator = Paginator(
        items=users,
        items_per_page=8,
        callback_prefix="source_users",
        item_callback=user_callback,
        return_callback="back_to_admin",
    )

    await callback.message.edit_text(
        "🔄 Перенос задач\n\n"
        "Выберите пользователя-источника (от кого копировать задачи):",
        reply_markup=paginator.get_page_keyboard(page),
    )


@router.callback_query(F.data.startswith("select_source_"))
async def select_source_user(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    source_user_id = int(callback.data.replace("select_source_", ""))
    source_user = db.get_user(source_user_id)

    if not source_user:
        await callback.answer("Пользователь не найден")
        return

    # Сохраняем ID пользователя-источника
    await state.update_data(source_user_id=source_user_id)

    # Проверяем, есть ли у пользователя проекты
    user_projects = db.get_user_projects(source_user_id)
    if not user_projects:
        await callback.answer("У этого пользователя нет проектов для переноса")
        await callback.message.edit_text(
            f"❌ У пользователя {source_user.username or source_user.full_name or source_user_id} нет проектов для переноса.",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text="◀️ Назад", callback_data="transfer_tasks"
                        )
                    ]
                ]
            ),
        )
        return

    # Показываем список пользователей для выбора получателя
    users = db.get_all_users()
    # Исключаем пользователя-источника из списка
    users = [u for u in users if u.user_id != source_user_id]

    def user_callback(user) -> tuple[str, str]:
        projects_count = len(db.get_user_projects(user.user_id))
        return (
            f"{'👑 ' if user.is_admin else ''}ID: {user.user_id} | "
            f"{user.username or user.full_name or 'Без имени'} "
            f"(проектов: {projects_count})",
            f"select_target_{user.user_id}",
        )

    paginator = Paginator(
        items=users,
        items_per_page=8,
        callback_prefix="target_users",
        item_callback=user_callback,
        return_callback="transfer_tasks",
    )

    await callback.message.edit_text(
        f"🔄 Перенос задач\n\n"
        f"Выбран источник: {source_user.username or source_user.full_name or source_user_id}\n"
        f"Проектов для переноса: {len(user_projects)}\n\n"
        f"Выберите пользователя-получателя (кому копировать задачи):",
        reply_markup=paginator.get_page_keyboard(0),
    )


@router.callback_query(F.data.startswith("target_users_page_"))
async def handle_target_users_page(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    data = await state.get_data()
    source_user_id = data.get("source_user_id")
    source_user = db.get_user(source_user_id)
    user_projects = db.get_user_projects(source_user_id)

    page = int(callback.data.split("_")[-1])
    users = db.get_all_users()
    # Исключаем пользователя-источника из списка
    users = [u for u in users if u.user_id != source_user_id]

    def user_callback(user) -> tuple[str, str]:
        projects_count = len(db.get_user_projects(user.user_id))
        return (
            f"{'👑 ' if user.is_admin else ''}ID: {user.user_id} | "
            f"{user.username or user.full_name or 'Без имени'} "
            f"(проектов: {projects_count})",
            f"select_target_{user.user_id}",
        )

    paginator = Paginator(
        items=users,
        items_per_page=8,
        callback_prefix="target_users",
        item_callback=user_callback,
        return_callback="transfer_tasks",
    )

    await callback.message.edit_text(
        f"🔄 Перенос задач\n\n"
        f"Выбран источник: {source_user.username or source_user.full_name or source_user_id}\n"
        f"Проектов для переноса: {len(user_projects)}\n\n"
        f"Выберите пользователя-получателя (кому копировать задачи):",
        reply_markup=paginator.get_page_keyboard(page),
    )


@router.callback_query(F.data.startswith("select_target_"))
async def select_target_user(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    data = await state.get_data()
    source_user_id = data.get("source_user_id")
    source_user = db.get_user(source_user_id)

    target_user_id = int(callback.data.replace("select_target_", ""))
    target_user = db.get_user(target_user_id)

    if not target_user:
        await callback.answer("Пользователь не найден")
        return

    # Сохраняем ID пользователя-получателя
    await state.update_data(target_user_id=target_user_id)

    # Получаем проекты и чаты пользователя-источника
    source_projects = db.get_user_projects(source_user_id)

    # Формируем список проектов для отображения
    projects_text = "\n".join(
        f"• {project.name} (ID: {project.id})" for project in source_projects[:5]
    )

    if len(source_projects) > 5:
        projects_text += f"\n... и еще {len(source_projects) - 5} проектов"

    # Запрашиваем подтверждение переноса
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✅ Подтвердить перенос", callback_data="confirm_transfer"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="◀️ Назад к выбору источника", callback_data="transfer_tasks"
                )
            ],
            [
                types.InlineKeyboardButton(
                    text="🔙 К админ-панели", callback_data="back_to_admin"
                )
            ],
        ]
    )

    await callback.message.edit_text(
        f"🔄 Перенос задач - Подтверждение\n\n"
        f"От пользователя: {source_user.username or source_user.full_name or source_user_id}\n"
        f"Пользователю: {target_user.username or target_user.full_name or target_user_id}\n\n"
        f"Будут перенесены следующие проекты:\n{projects_text}\n\n"
        f"⚠️ Внимание: все проекты будут скопированы получателю. "
        f"Проекты источника останутся без изменений.",
        reply_markup=keyboard,
    )

    await state.set_state(AdminTransferStates.waiting_for_confirmation)


@router.callback_query(F.data == "confirm_transfer")
async def confirm_transfer(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    data = await state.get_data()
    source_user_id = data.get("source_user_id")
    target_user_id = data.get("target_user_id")

    if not source_user_id or not target_user_id:
        await callback.answer("Ошибка: не выбраны пользователи")
        await state.clear()
        return

    source_user = db.get_user(source_user_id)
    target_user = db.get_user(target_user_id)

    try:
        # Получаем проекты пользователя-источника
        source_projects = db.get_user_projects(source_user_id)

        # Счетчики для статистики
        projects_copied = 0
        chats_copied = 0

        # Копируем каждый проект и его чаты
        for project in source_projects:
            # Получаем чаты проекта
            project_chats = db.get_project_chats(project.id)

            # Создаем копию проекта для целевого пользователя
            new_project = db.create_project(
                user_id=target_user_id,
                name=project.name,
                description=project.description,
                is_active=True,  # Активируем проект сразу
            )
            projects_copied += 1

            # Копируем чаты к новому проекту
            for chat in project_chats:
                db.create_project_chat(
                    project_id=new_project.id,
                    user_id=target_user_id,
                    name=chat.name,
                    chat_id=chat.chat_id,
                    access_hash=chat.access_hash,
                    is_active=True,  # Активируем чат сразу
                )
                chats_copied += 1

        logger.info(
            f"Администратор {callback.from_user.id} выполнил перенос задач от пользователя {source_user_id} "
            f"пользователю {target_user_id}. Перенесено проектов: {projects_copied}, чатов: {chats_copied}"
        )

        await callback.message.edit_text(
            f"✅ Перенос задач успешно выполнен\n\n"
            f"От пользователя: {source_user.username or source_user.full_name or source_user_id}\n"
            f"Пользователю: {target_user.username or target_user.full_name or target_user_id}\n\n"
            f"📊 Статистика:\n"
            f"• Скопировано проектов: {projects_copied}\n"
            f"• Скопировано чатов: {chats_copied}\n\n"
            f"Все проекты и чаты были автоматически активированы.",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text="◀️ Назад к админ-панели", callback_data="back_to_admin"
                        )
                    ]
                ]
            ),
        )

    except Exception as e:
        logger.error(f"Ошибка при переносе задач: {e}")
        await callback.message.edit_text(
            f"❌ Произошла ошибка при переносе задач:\n{str(e)}",
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

    finally:
        await state.clear()
