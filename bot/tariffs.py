from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
import time
import logging
import os

from db.database import Database
from bot.freekassa import FreeKassa
from config.parameters_manager import ParametersManager
from bot.utils.funcs import error_notify
from bot.payment_systems import PaymentSystems

router = Router(name="tariffs")
db = Database()
payment_systems = PaymentSystems()

# Для обратной совместимости
freekassa = FreeKassa(
    shop_id=int(ParametersManager.get_parameter("shop_id")),
    secret_word_1=str(ParametersManager.get_parameter("secret_word_1")),
    secret_word_2=str(ParametersManager.get_parameter("secret_word_2")),
)


class TariffPurchaseStates(StatesGroup):
    waiting_for_tariff = State()
    waiting_for_payment = State()
    waiting_for_payment_method = State()  # Новое состояние для выбора способа оплаты


@router.callback_query(F.data == "buy_tariff")
async def show_available_tariffs(callback: CallbackQuery, state: FSMContext):
    """Показывает доступные тарифы для покупки"""
    tariffs = db.get_all_tariff_plans(active_only=True)[
        1:
    ]  # Получаем только активные тарифы, исключая нулевой

    if not tariffs:
        await callback.message.edit_text(
            "❌ В данный момент нет доступных тарифов для покупки.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔙 Назад", callback_data="back_to_menu"
                        )
                    ]
                ]
            ),
        )
        return

    builder = InlineKeyboardBuilder()
    for tariff in tariffs:
        builder.button(
            text=f"{tariff.name} - {tariff.price/100}₽/мес",
            callback_data=f"select_tariff_{tariff.id}",
        )
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(1)

    text = "🎯 Доступные тарифы:\n\n"
    for tariff in tariffs:
        text += (
            f"📌 {tariff.name}\n"
            f"💰 Цена: {tariff.price/100}₽/месяц\n"
            f"📊 Макс. проектов: {tariff.max_projects}\n"
            f"💬 Макс. чатов в проекте: {tariff.max_chats_per_project}\n\n"
        )

    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("select_tariff_"))
async def select_tariff(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора тарифа"""
    tariff_id = int(callback.data.split("_")[2])
    tariff = db.get_tariff_plan(tariff_id)

    if not tariff:
        await callback.message.edit_text(
            "❌ Тариф не найден.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_tariff")]
                ]
            ),
        )
        return

    # Проверяем текущий тариф пользователя
    current_tariff = db.get_user_tariff(callback.from_user.id)
    if current_tariff:
        current_tariff_plan = db.get_tariff_plan(current_tariff.tariff_plan_id)
        await callback.message.edit_text(
            f"⚠️ У вас уже есть активный тариф: {current_tariff_plan.name}\n"
            f"Он будет заменен на новый тариф: {tariff.name}\n\n"
            f"Продолжить?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Да", callback_data=f"confirm_tariff_{tariff_id}"
                        )
                    ],
                    [InlineKeyboardButton(text="❌ Нет", callback_data="buy_tariff")],
                ]
            ),
        )
        return

    # Сохраняем данные о тарифе
    amount = tariff.price / 100  # Конвертируем копейки в рубли
    await state.update_data(tariff_id=tariff_id, amount=amount, tariff_name=tariff.name)

    # Показываем выбор способа оплаты
    await callback.message.edit_text(
        f"🎯 Тариф: {tariff.name}\n"
        f"💰 Цена: {amount}₽/месяц\n\n"
        "Выберите способ оплаты:",
        reply_markup=payment_systems.get_payment_methods_keyboard(),
    )

    # Устанавливаем состояние ожидания выбора способа оплаты
    await state.set_state(TariffPurchaseStates.waiting_for_payment_method)


@router.callback_query(TariffPurchaseStates.waiting_for_payment_method)
async def process_payment_method(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Обработка выбора способа оплаты для тарифа"""
    data = await state.get_data()
    tariff_id = data.get("tariff_id")
    amount = data.get("amount")
    tariff_name = data.get("tariff_name")

    if not tariff_id or not amount:
        await callback.message.edit_text(
            "❌ Произошла ошибка. Попробуйте выбрать тариф снова.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_tariff")]
                ]
            ),
        )
        await state.clear()
        return

    # Формируем order_id для платежа
    order_id = f"tariff_{callback.from_user.id}_{tariff_id}_{int(time.time())}"

    if callback.data == "payment_yookassa":
        # Создаем платеж через ЮKassa
        payload = f"tariff_{callback.from_user.id}_{tariff_id}"

        success = await payment_systems.create_yookassa_invoice(
            bot=bot,
            chat_id=callback.from_user.id,
            title=f"Тариф {tariff_name}",
            description=f"Покупка тарифа {tariff_name} на сумму {amount} рублей",
            payload=payload,
            amount=int(amount * 100),  # Конвертируем в копейки
        )

        if not success:
            await callback.message.edit_text(
                "❌ Произошла ошибка при создании счета. Попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔙 Назад", callback_data="buy_tariff"
                            )
                        ]
                    ]
                ),
            )

    elif callback.data == "payment_freekassa":
        # Создаем платеж через FreeKassa
        payment_url = payment_systems.create_freekassa_payment(
            amount=amount,
            order_id=order_id,
        )

        if payment_url:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
                    [
                        InlineKeyboardButton(
                            text="❌ Отменить", callback_data="cancel_tariff_payment"
                        )
                    ],
                ]
            )

            await callback.message.edit_text(
                f"💰 Платеж на сумму {amount}₽ создан\n"
                f"ID платежа: {order_id.replace('tariff_', '')}\n\n"
                "1. Нажмите кнопку «Оплатить»\n"
                "2. Оплатите счет удобным способом\n"
                "3. Тариф будет автоматически активирован\n\n"
                f"При ошибках пишите в поддержку: {ParametersManager.get_parameter('support_link')}",
                reply_markup=keyboard,
            )
        else:
            await callback.message.edit_text(
                "❌ Произошла ошибка при создании платежа. Попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔙 Назад", callback_data="buy_tariff"
                            )
                        ]
                    ]
                ),
            )

    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "cancel_tariff_payment")
async def cancel_tariff_payment(callback: CallbackQuery, state: FSMContext):
    """Отмена покупки тарифа"""
    await state.clear()
    await callback.message.edit_text(
        "❌ Покупка тарифа отменена",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_tariff")]
            ]
        ),
    )


@router.callback_query(F.data.startswith("confirm_tariff_"))
async def confirm_tariff_selection(callback: CallbackQuery, state: FSMContext):
    """Подтверждение выбора тарифа при замене существующего"""
    tariff_id = int(callback.data.split("_")[2])
    tariff = db.get_tariff_plan(tariff_id)

    if not tariff:
        await callback.message.edit_text(
            "❌ Тариф не найден.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_tariff")]
                ]
            ),
        )
        return

    # Сохраняем данные о тарифе
    amount = tariff.price / 100  # Конвертируем копейки в рубли
    await state.update_data(tariff_id=tariff_id, amount=amount, tariff_name=tariff.name)

    # Показываем выбор способа оплаты
    await callback.message.edit_text(
        f"🎯 Тариф: {tariff.name}\n"
        f"💰 Цена: {amount}₽/месяц\n\n"
        "Выберите способ оплаты:",
        reply_markup=payment_systems.get_payment_methods_keyboard(),
    )

    # Устанавливаем состояние ожидания выбора способа оплаты
    await state.set_state(TariffPurchaseStates.waiting_for_payment_method)
