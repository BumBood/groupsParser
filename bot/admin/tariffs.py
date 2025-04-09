from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.database import Database
from bot.utils.states import AdminStates
from bot.utils.pagination import Paginator

router = Router()
db = Database()

# Константы для пагинации
TARIFFS_PER_PAGE = 3


@router.callback_query(F.data == "tariffs_menu")
async def tariffs_menu(callback: CallbackQuery, state: FSMContext):
    """Меню управления тарифами"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Создать тариф", callback_data="create_tariff")
    builder.button(text="📋 Список тарифов", callback_data="list_tariffs")
    builder.button(text="👥 Назначить тариф", callback_data="assign_tariff")
    builder.button(text="🔙 Назад", callback_data="back_to_admin")
    builder.adjust(2)

    await callback.message.edit_text(
        "🎯 Управление тарифами\n\n" "Выберите действие:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "create_tariff")
async def create_tariff_start(callback: CallbackQuery, state: FSMContext):
    """Начало создания тарифа"""
    await state.set_state(AdminStates.waiting_tariff_name)
    await callback.message.edit_text(
        "Введите название тарифа:",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Отмена", callback_data="tariffs_menu")
        .as_markup(),
    )


@router.message(AdminStates.waiting_tariff_name)
async def process_tariff_name(message: Message, state: FSMContext):
    """Обработка названия тарифа"""
    await state.update_data(tariff_name=message.text)
    await state.set_state(AdminStates.waiting_tariff_price)
    await message.answer(
        "Введите цену тарифа (в копейках):",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Отмена", callback_data="tariffs_menu")
        .as_markup(),
    )


@router.message(AdminStates.waiting_tariff_price)
async def process_tariff_price(message: Message, state: FSMContext):
    """Обработка цены тарифа"""
    try:
        price = int(message.text)
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите корректную цену (положительное целое число):",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="tariffs_menu")
            .as_markup(),
        )
        return

    await state.update_data(tariff_price=price)
    await state.set_state(AdminStates.waiting_tariff_projects)
    await message.answer(
        "Введите максимальное количество проектов:",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Отмена", callback_data="tariffs_menu")
        .as_markup(),
    )


@router.message(AdminStates.waiting_tariff_projects)
async def process_tariff_projects(message: Message, state: FSMContext):
    """Обработка количества проектов"""
    try:
        projects = int(message.text)
        if projects <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите корректное число проектов (положительное целое число):",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="tariffs_menu")
            .as_markup(),
        )
        return

    await state.update_data(tariff_projects=projects)
    await state.set_state(AdminStates.waiting_tariff_chats)
    await message.answer(
        "Введите максимальное количество чатов в проекте:",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Отмена", callback_data="tariffs_menu")
        .as_markup(),
    )


@router.message(AdminStates.waiting_tariff_chats)
async def process_tariff_chats(message: Message, state: FSMContext):
    """Обработка количества чатов и создание тарифа"""
    try:
        chats = int(message.text)
        if chats <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите корректное число чатов (положительное целое число):",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="tariffs_menu")
            .as_markup(),
        )
        return

    data = await state.get_data()
    tariff = db.create_tariff_plan(
        name=data["tariff_name"],
        price=data["tariff_price"],
        max_projects=data["tariff_projects"],
        max_chats_per_project=chats,
    )

    await state.clear()
    await message.answer(
        f"✅ Тариф успешно создан!\n\n"
        f"Название: {tariff.name}\n"
        f"Цена: {tariff.price} коп.\n"
        f"Макс. проектов: {tariff.max_projects}\n"
        f"Макс. чатов в проекте: {tariff.max_chats_per_project}",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Назад", callback_data="tariffs_menu")
        .as_markup(),
    )


@router.callback_query(F.data == "list_tariffs")
async def list_tariffs(callback: CallbackQuery, state: FSMContext):
    """Список всех тарифов (первая страница)"""
    await state.update_data(tariffs_page=0)  # Пагинатор использует 0-based индексацию
    await show_tariffs_page(callback, state)


@router.callback_query(F.data.startswith("tariffs_page_"))
async def tariffs_page_navigation(callback: CallbackQuery, state: FSMContext):
    """Навигация по страницам тарифов"""
    page = int(callback.data.split("_")[-1])
    await state.update_data(tariffs_page=page)
    await show_tariffs_page(callback, state)


async def show_tariffs_page(callback: CallbackQuery, state: FSMContext):
    """Отображение страницы тарифов"""
    data = await state.get_data()
    page = data.get("tariffs_page", 0)  # Пагинатор использует 0-based индексацию

    tariffs = db.get_all_tariff_plans()

    if not tariffs:
        await callback.message.edit_text(
            "📝 Тарифы не найдены",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="tariffs_menu")
            .as_markup(),
        )
        return

    def tariff_callback(tariff) -> tuple[str, str]:
        return (
            f"ID: {tariff.id} | {tariff.name} | {tariff.price} коп.",
            f"edit_tariff_{tariff.id}",
        )

    paginator = Paginator(
        items=tariffs,
        items_per_page=TARIFFS_PER_PAGE,
        callback_prefix="tariffs",
        item_callback=tariff_callback,
        return_callback="tariffs_menu",
    )

    # Формируем текст с информацией о тарифах на текущей странице
    start_idx = page * TARIFFS_PER_PAGE
    end_idx = min(start_idx + TARIFFS_PER_PAGE, len(tariffs))

    text = f"📝 Список тарифов (страница {page + 1}/{paginator.total_pages}):\n\n"

    # Получаем клавиатуру от пагинатора
    keyboard = paginator.get_page_keyboard(page)

    # Добавляем кнопки действий
    keyboard.inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="❌ Удалить тариф", callback_data="delete_tariff"
            ),
            InlineKeyboardButton(
                text="✏️ Редактировать тариф", callback_data="edit_tariff"
            ),
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "delete_tariff")
async def delete_tariff_start(callback: CallbackQuery, state: FSMContext):
    """Начало процесса удаления тарифа"""
    await state.set_state(AdminStates.waiting_tariff_id_for_delete)
    await callback.message.edit_text(
        "Введите ID тарифа для удаления:",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Отмена", callback_data="list_tariffs")
        .as_markup(),
    )


@router.message(AdminStates.waiting_tariff_id_for_delete)
async def process_tariff_id_for_delete(message: Message, state: FSMContext):
    """Обработка ID тарифа для удаления"""
    try:
        tariff_id = int(message.text)
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите корректный ID тарифа:",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="list_tariffs")
            .as_markup(),
        )
        return

    # Получаем тариф
    tariff = db.get_tariff_plan(tariff_id)
    if not tariff:
        await message.answer(
            "❌ Тариф не найден. Попробуйте еще раз:",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="list_tariffs")
            .as_markup(),
        )
        return

    # Удаляем тариф
    success = db.delete_tariff_plan(tariff_id)
    if not success:
        await message.answer(
            "❌ Не удалось удалить тариф. Возможно, он используется пользователями.",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="list_tariffs")
            .as_markup(),
        )
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"✅ Тариф успешно удален!\n\n" f"ID: {tariff_id}\n" f"Название: {tariff.name}",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Назад", callback_data="list_tariffs")
        .as_markup(),
    )


@router.callback_query(F.data == "edit_tariff")
async def edit_tariff_start(callback: CallbackQuery, state: FSMContext):
    """Начало процесса редактирования тарифа"""
    await state.set_state(AdminStates.waiting_tariff_id_for_edit)
    await callback.message.edit_text(
        "Введите ID тарифа для редактирования:",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Отмена", callback_data="list_tariffs")
        .as_markup(),
    )


@router.message(AdminStates.waiting_tariff_id_for_edit)
async def process_tariff_id_for_edit(message: Message, state: FSMContext):
    """Обработка ID тарифа для редактирования"""
    try:
        tariff_id = int(message.text)
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите корректный ID тарифа:",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="list_tariffs")
            .as_markup(),
        )
        return

    # Получаем тариф
    tariff = db.get_tariff_plan(tariff_id)
    if not tariff:
        await message.answer(
            "❌ Тариф не найден. Попробуйте еще раз:",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="list_tariffs")
            .as_markup(),
        )
        return

    # Сохраняем ID тарифа в состоянии
    await state.update_data(edit_tariff_id=tariff_id)

    # Показываем меню редактирования
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Изменить название", callback_data="edit_tariff_name")
    builder.button(text="💰 Изменить цену", callback_data="edit_tariff_price")
    builder.button(
        text="📊 Изменить макс. проектов", callback_data="edit_tariff_projects"
    )
    builder.button(text="💬 Изменить макс. чатов", callback_data="edit_tariff_chats")
    builder.button(text="🔄 Изменить статус", callback_data="edit_tariff_status")
    builder.button(text="🔙 Отмена", callback_data="list_tariffs")
    builder.adjust(2)

    await state.set_state(AdminStates.waiting_tariff_edit_option)
    await message.answer(
        f"Выберите, что хотите изменить в тарифе:\n\n"
        f"ID: {tariff.id}\n"
        f"Название: {tariff.name}\n"
        f"Цена: {tariff.price} коп.\n"
        f"Макс. проектов: {tariff.max_projects}\n"
        f"Макс. чатов в проекте: {tariff.max_chats_per_project}\n"
        f"Статус: {'✅ Активен' if tariff.is_active else '❌ Неактивен'}",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(
    F.data == "edit_tariff_name", AdminStates.waiting_tariff_edit_option
)
async def edit_tariff_name_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования названия тарифа"""
    await state.set_state(AdminStates.waiting_tariff_new_name)
    await callback.message.edit_text(
        "Введите новое название тарифа:",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Отмена", callback_data="list_tariffs")
        .as_markup(),
    )


@router.message(AdminStates.waiting_tariff_new_name)
async def process_tariff_new_name(message: Message, state: FSMContext):
    """Обработка нового названия тарифа"""
    data = await state.get_data()
    tariff_id = data["edit_tariff_id"]

    # Обновляем название тарифа
    success = db.update_tariff_plan(tariff_id, name=message.text)
    if not success:
        await message.answer(
            "❌ Не удалось обновить название тарифа.",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="list_tariffs")
            .as_markup(),
        )
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"✅ Название тарифа успешно обновлено!\n\n" f"Новое название: {message.text}",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Назад", callback_data="list_tariffs")
        .as_markup(),
    )


@router.callback_query(
    F.data == "edit_tariff_price", AdminStates.waiting_tariff_edit_option
)
async def edit_tariff_price_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования цены тарифа"""
    await state.set_state(AdminStates.waiting_tariff_new_price)
    await callback.message.edit_text(
        "Введите новую цену тарифа (в копейках):",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Отмена", callback_data="list_tariffs")
        .as_markup(),
    )


@router.message(AdminStates.waiting_tariff_new_price)
async def process_tariff_new_price(message: Message, state: FSMContext):
    """Обработка новой цены тарифа"""
    try:
        price = int(message.text)
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите корректную цену (положительное целое число):",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="list_tariffs")
            .as_markup(),
        )
        return

    data = await state.get_data()
    tariff_id = data["edit_tariff_id"]

    # Обновляем цену тарифа
    success = db.update_tariff_plan(tariff_id, price=price)
    if not success:
        await message.answer(
            "❌ Не удалось обновить цену тарифа.",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="list_tariffs")
            .as_markup(),
        )
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"✅ Цена тарифа успешно обновлена!\n\n" f"Новая цена: {price} коп.",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Назад", callback_data="list_tariffs")
        .as_markup(),
    )


@router.callback_query(
    F.data == "edit_tariff_projects", AdminStates.waiting_tariff_edit_option
)
async def edit_tariff_projects_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования количества проектов тарифа"""
    await state.set_state(AdminStates.waiting_tariff_new_projects)
    await callback.message.edit_text(
        "Введите новое максимальное количество проектов:",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Отмена", callback_data="list_tariffs")
        .as_markup(),
    )


@router.message(AdminStates.waiting_tariff_new_projects)
async def process_tariff_new_projects(message: Message, state: FSMContext):
    """Обработка нового количества проектов тарифа"""
    try:
        projects = int(message.text)
        if projects <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите корректное число проектов (положительное целое число):",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="list_tariffs")
            .as_markup(),
        )
        return

    data = await state.get_data()
    tariff_id = data["edit_tariff_id"]

    # Обновляем количество проектов тарифа
    success = db.update_tariff_plan(tariff_id, max_projects=projects)
    if not success:
        await message.answer(
            "❌ Не удалось обновить количество проектов тарифа.",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="list_tariffs")
            .as_markup(),
        )
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"✅ Максимальное количество проектов тарифа успешно обновлено!\n\n"
        f"Новое значение: {projects}",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Назад", callback_data="list_tariffs")
        .as_markup(),
    )


@router.callback_query(
    F.data == "edit_tariff_chats", AdminStates.waiting_tariff_edit_option
)
async def edit_tariff_chats_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования количества чатов тарифа"""
    await state.set_state(AdminStates.waiting_tariff_new_chats)
    await callback.message.edit_text(
        "Введите новое максимальное количество чатов в проекте:",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Отмена", callback_data="list_tariffs")
        .as_markup(),
    )


@router.message(AdminStates.waiting_tariff_new_chats)
async def process_tariff_new_chats(message: Message, state: FSMContext):
    """Обработка нового количества чатов тарифа"""
    try:
        chats = int(message.text)
        if chats <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите корректное число чатов (положительное целое число):",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="list_tariffs")
            .as_markup(),
        )
        return

    data = await state.get_data()
    tariff_id = data["edit_tariff_id"]

    # Обновляем количество чатов тарифа
    success = db.update_tariff_plan(tariff_id, max_chats_per_project=chats)
    if not success:
        await message.answer(
            "❌ Не удалось обновить количество чатов тарифа.",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="list_tariffs")
            .as_markup(),
        )
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"✅ Максимальное количество чатов в проекте тарифа успешно обновлено!\n\n"
        f"Новое значение: {chats}",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Назад", callback_data="list_tariffs")
        .as_markup(),
    )


@router.callback_query(
    F.data == "edit_tariff_status", AdminStates.waiting_tariff_edit_option
)
async def edit_tariff_status(callback: CallbackQuery, state: FSMContext):
    """Изменение статуса тарифа"""
    data = await state.get_data()
    tariff_id = data["edit_tariff_id"]

    # Получаем текущий тариф
    tariff = db.get_tariff_plan(tariff_id)
    if not tariff:
        await callback.message.edit_text(
            "❌ Тариф не найден.",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="list_tariffs")
            .as_markup(),
        )
        await state.clear()
        return

    # Инвертируем статус
    new_status = not tariff.is_active

    # Обновляем статус тарифа
    success = db.update_tariff_plan(tariff_id, is_active=new_status)
    if not success:
        await callback.message.edit_text(
            "❌ Не удалось обновить статус тарифа.",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="list_tariffs")
            .as_markup(),
        )
        await state.clear()
        return

    await state.clear()
    await callback.message.edit_text(
        f"✅ Статус тарифа успешно обновлен!\n\n"
        f"Новый статус: {'✅ Активен' if new_status else '❌ Неактивен'}",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Назад", callback_data="list_tariffs")
        .as_markup(),
    )


@router.callback_query(F.data == "assign_tariff")
async def assign_tariff_start(callback: CallbackQuery, state: FSMContext):
    """Начало назначения тарифа"""
    await state.set_state(AdminStates.waiting_user_id)
    await callback.message.edit_text(
        "Введите ID пользователя:",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Отмена", callback_data="tariffs_menu")
        .as_markup(),
    )


@router.message(AdminStates.waiting_user_id)
async def process_user_id(message: Message, state: FSMContext):
    """Обработка ID пользователя"""
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите корректный ID пользователя:",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="tariffs_menu")
            .as_markup(),
        )
        return

    user = db.get_user(user_id)
    if not user:
        await message.answer(
            "❌ Пользователь не найден. Попробуйте еще раз:",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="tariffs_menu")
            .as_markup(),
        )
        return

    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminStates.waiting_tariff_id)

    # Получаем список доступных тарифов
    tariffs = db.get_all_tariff_plans(active_only=True)

    if not tariffs:
        await message.answer(
            "❌ Нет доступных тарифов для назначения",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="tariffs_menu")
            .as_markup(),
        )
        await state.clear()
        return

    text = "Выберите ID тарифа для назначения:\n\n"
    for tariff in tariffs:
        text += (
            f"ID: {tariff.id}\n"
            f"Название: {tariff.name}\n"
            f"Цена: {tariff.price} коп.\n"
            f"Макс. проектов: {tariff.max_projects}\n"
            f"Макс. чатов в проекте: {tariff.max_chats_per_project}\n\n"
        )

    await message.answer(
        text,
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Отмена", callback_data="tariffs_menu")
        .as_markup(),
    )


@router.message(AdminStates.waiting_tariff_id)
async def process_tariff_id(message: Message, state: FSMContext):
    """Обработка ID тарифа и назначение тарифа пользователю"""
    try:
        tariff_id = int(message.text)
    except ValueError:
        await message.answer(
            "❌ Пожалуйста, введите корректный ID тарифа:",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="tariffs_menu")
            .as_markup(),
        )
        return

    data = await state.get_data()
    user_id = data["target_user_id"]

    # Получаем тариф
    tariff = db.get_tariff_plan(tariff_id)
    if not tariff:
        await message.answer(
            "❌ Тариф не найден. Попробуйте еще раз:",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Отмена", callback_data="tariffs_menu")
            .as_markup(),
        )
        return

    # Получаем пользователя
    user = db.get_user(user_id)
    if not user:
        await message.answer(
            "❌ Пользователь не найден",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="tariffs_menu")
            .as_markup(),
        )
        await state.clear()
        return

    # Проверяем текущий тариф пользователя
    current_tariff = db.get_user_tariff(user_id)
    if current_tariff:
        current_tariff_plan = db.get_tariff_plan(current_tariff.tariff_plan_id)
        await message.answer(
            f"⚠️ У пользователя уже есть активный тариф: {current_tariff_plan.name}\n"
            f"Он будет заменен на новый тариф: {tariff.name}\n\n"
            f"Продолжить?",
            reply_markup=InlineKeyboardBuilder()
            .button(
                text="✅ Да",
                callback_data=f"confirm_admin_tariff_{user_id}_{tariff_id}",
            )
            .button(text="❌ Нет", callback_data="tariffs_menu")
            .as_markup(),
        )
        await state.clear()
        return

    # Назначаем тариф пользователю
    user_tariff = db.assign_tariff_to_user(user_id, tariff_id)
    if not user_tariff:
        await message.answer(
            "❌ Не удалось назначить тариф",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="tariffs_menu")
            .as_markup(),
        )
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"✅ Тариф успешно назначен пользователю!\n\n"
        f"Пользователь: {user.full_name or user.username or user_id}\n"
        f"Тариф: {tariff.name}\n"
        f"Действует до: {user_tariff.end_date.strftime('%d.%m.%Y')}",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Назад", callback_data="tariffs_menu")
        .as_markup(),
    )


@router.callback_query(F.data.startswith("confirm_admin_tariff_"))
async def confirm_admin_tariff_assignment(callback: CallbackQuery):
    """Подтверждение назначения тарифа через админ-панель"""
    _, user_id, tariff_id = callback.data.split("_")
    user_id = int(user_id)
    tariff_id = int(tariff_id)

    # Получаем пользователя и тариф
    user = db.get_user(user_id)
    tariff = db.get_tariff_plan(tariff_id)

    if not user or not tariff:
        await callback.message.edit_text(
            "❌ Пользователь или тариф не найдены",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="tariffs_menu")
            .as_markup(),
        )
        return

    # Назначаем тариф пользователю
    user_tariff = db.assign_tariff_to_user(user_id, tariff_id)
    if not user_tariff:
        await callback.message.edit_text(
            "❌ Не удалось назначить тариф",
            reply_markup=InlineKeyboardBuilder()
            .button(text="🔙 Назад", callback_data="tariffs_menu")
            .as_markup(),
        )
        return

    await callback.message.edit_text(
        f"✅ Тариф успешно назначен пользователю!\n\n"
        f"Пользователь: {user.full_name or user.username or user_id}\n"
        f"Тариф: {tariff.name}\n"
        f"Действует до: {user_tariff.end_date.strftime('%d.%m.%Y')}",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Назад", callback_data="tariffs_menu")
        .as_markup(),
    )


@router.callback_query(F.data == "tariffs_menu")
async def back_to_tariffs_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в меню тарифов"""
    await state.clear()
    await tariffs_menu(callback, state)


@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    """Игнорирование нажатия на неактивные кнопки пагинации"""
    await callback.answer()
