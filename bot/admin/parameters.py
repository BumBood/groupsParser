from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging

from db.database import Database
from config.parameters_manager import ParametersManager

logger = logging.getLogger(__name__)

router = Router(name="admin_parameters")
db = Database()


class AdminParameterStates(StatesGroup):
    waiting_for_value = State()


@router.callback_query(F.data == "edit_params")
async def show_parameters(callback: types.CallbackQuery):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    params = ParametersManager._config
    logger.info(
        f"Администратор {callback.from_user.id} просматривает текущие параметры: {params}"
    )
    text = "📋 Текущие параметры:\n\n"
    for param, value in params.items():
        text += f"• {param}: {value}\n"

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✏️ Изменить параметр", callback_data="change_param"
                )
            ],
            [types.InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "change_param")
async def select_parameter(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    logger.info(f"Администратор {callback.from_user.id} начал изменение параметров")
    params = ParametersManager._config
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text=param, callback_data=f"param_{param}")]
            for param in params.keys()
        ]
    )
    await callback.message.edit_text(
        "Выберите параметр для изменения:", reply_markup=keyboard
    )


@router.callback_query(F.data.startswith("param_"))
async def enter_new_value(callback: types.CallbackQuery, state: FSMContext):
    if not db.get_user(callback.from_user.id).is_admin:
        return

    param_name = callback.data.replace("param_", "")
    logger.info(
        f"Администратор {callback.from_user.id} выбрал параметр {param_name} для изменения"
    )
    await state.update_data(selected_param=param_name)
    await state.set_state(AdminParameterStates.waiting_for_value)
    current_value = ParametersManager.get_parameter(param_name)
    logger.debug(f"Текущее значение параметра {param_name}: {current_value}")
    await callback.message.edit_text(
        f"Параметр: {param_name}\n"
        f"Текущее значение: {current_value}\n\n"
        "Введите новое значение:"
    )


@router.message(AdminParameterStates.waiting_for_value)
async def save_new_value(message: types.Message, state: FSMContext):
    if not db.get_user(message.from_user.id).is_admin:
        return

    data = await state.get_data()
    param_name = data["selected_param"]
    logger.info(f"Администратор {message.from_user.id} изменяет параметр {param_name}")

    try:
        current_value = ParametersManager.get_parameter(param_name)
        new_value = type(current_value)(message.text)
        ParametersManager.set_parameter(param_name, new_value)
        logger.info(f"Параметр {param_name} успешно изменен на {new_value}")
        await message.answer(
            f"✅ Значение параметра {param_name} обновлено на {new_value}"
        )
    except ValueError:
        logger.error(
            f"Ошибка при изменении параметра {param_name}: неверный формат значения"
        )
        await message.answer("❌ Неверный формат значения")

    await state.clear()

    # Возвращаемся в меню админа
    from .menu import admin_menu

    await admin_menu(message)
