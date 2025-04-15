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
from datetime import datetime, timedelta

from db.database import Database
from bot.payment_systems import PaymentSystems
from bot.utils.funcs import error_notify
from config.parameters_manager import ParametersManager

router = Router(name="tariffs")
db = Database()
payment_systems = PaymentSystems()

# Путь к директории с логотипами тарифов
TARIFF_LOGOS_DIR = "client/tariff_logos"


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

    # Определяем метод оплаты
    payment_method = None
    if callback.data == "payment_yookassa":
        payment_method = "yookassa"
    elif callback.data == "payment_freekassa":
        payment_method = "freekassa"

    if payment_method:
        # Создаем платеж через централизованный обработчик
        payload = f"tariff_{callback.from_user.id}_{tariff_id}"

        success = await payment_systems.process_payment(
            bot=bot,
            user_id=callback.from_user.id,
            amount=float(amount),
            title=f"Тариф {tariff_name}",
            description=f"Покупка тарифа {tariff_name} на сумму {amount} рублей",
            payload=payload,
            payment_method=payment_method,
        )

        if not success:
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
