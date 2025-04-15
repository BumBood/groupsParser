from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    PreCheckoutQuery,
    SuccessfulPayment,
    LabeledPrice,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import logging
import time
from datetime import datetime, timedelta

from bot.yookassa import YooKassa
from bot.utils.funcs import add_balance_with_notification
from config.parameters_manager import ParametersManager
from db.database import Database

router = Router(name="payments")
db = Database()

# Инициализация ЮKassa с токеном провайдера
yookassa = YooKassa(
    provider_token=ParametersManager.get_parameter("yookassa_provider_token")
)


class DepositStates(StatesGroup):
    """Состояния для пополнения баланса"""

    waiting_for_amount = State()


class TariffPurchaseStates(StatesGroup):
    """Состояния для покупки тарифа"""

    waiting_for_tariff = State()
    waiting_for_payment = State()


# Обработчики пополнения баланса
@router.callback_query(F.data == "deposit")
async def deposit_start(callback: CallbackQuery, state: FSMContext):
    """Начало процесса пополнения баланса"""
    await state.set_state(DepositStates.waiting_for_amount)
    await callback.message.edit_text(
        f"💰 Введите сумму пополнения в рублях (минимум {ParametersManager.get_parameter('parse_comments_cost')}₽):\n\n"
        "💳 Оплата происходит через платёжную систему ЮKassa\n"
        "🎉 После оплаты средства автоматически зачислятся на ваш баланс\n\n"
        f"* Если у вас возникли проблемы, напишите в поддержку: {ParametersManager.get_parameter('support_link')}"
    )


@router.message(DepositStates.waiting_for_amount)
async def process_deposit_amount(message: Message, state: FSMContext, bot: Bot):
    """Обработка ввода суммы для пополнения"""
    try:
        amount = int(message.text)
        min_amount = int(ParametersManager.get_parameter("parse_comments_cost"))

        if amount < min_amount:
            await message.answer(f"❌ Минимальная сумма пополнения - {min_amount}₽")
            return

        # Подготовка данных для счета
        title = "Пополнение баланса"
        description = f"Пополнение баланса в боте на сумму {amount}₽"
        payload = f"deposit_{message.from_user.id}_{amount}"

        # Создание счета
        success = await yookassa.create_invoice(
            bot=bot,
            chat_id=message.chat.id,
            title=title,
            description=description,
            payload=payload,
            amount=amount,
            photo_url="https://i.imgur.com/SBnJWog.png",  # Можно заменить на свою картинку
        )

        if not success:
            await message.answer("❌ Ошибка создания платежа. Попробуйте позже.")

        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректную сумму числом")


@router.callback_query(F.data.startswith("deposit_"))
async def auto_deposit(callback: CallbackQuery, bot: Bot):
    """Быстрое пополнение баланса на фиксированную сумму"""
    try:
        amount = int(callback.data.split("_")[1])
        min_amount = int(ParametersManager.get_parameter("parse_comments_cost"))

        if amount < min_amount:
            amount = min_amount
            await callback.message.answer(
                f"❗ Минимальная сумма пополнения - {min_amount}₽"
            )

        # Подготовка данных для счета
        title = "Пополнение баланса"
        description = f"Пополнение баланса в боте на сумму {amount}₽"
        payload = f"deposit_{callback.from_user.id}_{amount}"

        # Создание счета
        success = await yookassa.create_invoice(
            bot=bot,
            chat_id=callback.message.chat.id,
            title=title,
            description=description,
            payload=payload,
            amount=amount,
        )

        if not success:
            await callback.message.answer(
                "❌ Ошибка создания платежа. Попробуйте позже."
            )

        # Удаляем сообщение с меню быстрого пополнения
        await callback.message.delete()
    except Exception as e:
        logging.error(f"Ошибка создания автоматического платежа: {e}")
        await callback.message.answer("❌ Произошла ошибка. Попробуйте позже.")


# Обработчики покупки тарифов
@router.callback_query(F.data == "buy_tariff")
async def show_available_tariffs(callback: CallbackQuery, state: FSMContext):
    """Показывает доступные тарифы для покупки"""
    tariffs = db.get_all_tariff_plans(active_only=True)[1:]  # Исключаем нулевой тариф

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
            text=f"{tariff.name} - {tariff.price}₽/мес",
            callback_data=f"select_tariff_{tariff.id}",
        )
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(1)

    text = "🎯 Доступные тарифы:\n\n"
    for tariff in tariffs:
        text += (
            f"📌 {tariff.name}\n"
            f"💰 Цена: {tariff.price}₽/месяц\n"
            f"📊 Макс. проектов: {tariff.max_projects}\n"
            f"💬 Макс. чатов в проекте: {tariff.max_chats_per_project}\n\n"
        )

    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("select_tariff_"))
async def select_tariff(callback: CallbackQuery, state: FSMContext, bot: Bot):
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
    if current_tariff and current_tariff.tariff_plan_id != 1:  # Не нулевой тариф
        current_plan = db.get_tariff_plan(current_tariff.tariff_plan_id)
        await callback.message.edit_text(
            f"⚠️ У вас уже есть активный тариф: {current_plan.name}\n"
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

    # Создаем платеж через Юкассу
    amount = tariff.price
    timestamp = int(time.time())
    payload = f"tariff_{callback.from_user.id}_{tariff_id}_{timestamp}"

    # Создание счета
    success = await yookassa.create_invoice(
        bot=bot,
        chat_id=callback.message.chat.id,
        title=f"Тариф {tariff.name}",
        description=f"Покупка тарифа {tariff.name} на 30 дней",
        payload=payload,
        amount=tariff.price,
        photo_url="https://i.imgur.com/nVDuuOD.png",  # Можно заменить на свою картинку
    )

    if not success:
        await callback.message.edit_text(
            "❌ Ошибка создания платежа. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_tariff")]
                ]
            ),
        )
        return

    # Отображаем сообщение об успешном создании счета
    await callback.message.edit_text(
        f"💰 Счет на покупку тарифа {tariff.name} создан\n"
        f"Сумма: {amount}₽\n\n"
        f"Для оплаты воспользуйтесь счетом выше\n"
        f"После успешной оплаты тариф будет активирован автоматически\n\n"
        f"При ошибках пишите в поддержку: {ParametersManager.get_parameter('support_link')}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 Назад к тарифам", callback_data="buy_tariff"
                    )
                ]
            ]
        ),
    )


@router.callback_query(F.data.startswith("confirm_tariff_"))
async def confirm_tariff_selection(callback: CallbackQuery, bot: Bot):
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

    # Создаем платеж через Юкассу
    amount = tariff.price
    timestamp = int(time.time())
    payload = f"tariff_{callback.from_user.id}_{tariff_id}_{timestamp}"

    # Создание счета
    success = await yookassa.create_invoice(
        bot=bot,
        chat_id=callback.message.chat.id,
        title=f"Тариф {tariff.name}",
        description=f"Покупка тарифа {tariff.name} на 30 дней",
        payload=payload,
        amount=tariff.price,
        photo_url="https://i.imgur.com/nVDuuOD.png",  # Можно заменить на свою картинку
    )

    if not success:
        await callback.message.edit_text(
            "❌ Ошибка создания платежа. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_tariff")]
                ]
            ),
        )
        return

    # Отображаем сообщение об успешном создании счета
    await callback.message.edit_text(
        f"💰 Счет на покупку тарифа {tariff.name} создан\n"
        f"Сумма: {amount}₽\n\n"
        f"Для оплаты воспользуйтесь счетом выше\n"
        f"После успешной оплаты тариф будет активирован автоматически\n\n"
        f"При ошибках пишите в поддержку: {ParametersManager.get_parameter('support_link')}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 Назад к тарифам", callback_data="buy_tariff"
                    )
                ]
            ]
        ),
    )


# Обработчики событий оплаты Telegram
@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery, bot: Bot):
    """Обработка запроса предварительной проверки платежа"""
    try:
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except Exception as e:
        logging.error(f"Ошибка обработки pre_checkout_query: {e}")
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Ошибка во время обработки платежа. Пожалуйста, попробуйте позже.",
        )


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot):
    """Обработка успешного платежа"""
    payment = message.successful_payment
    payload = payment.invoice_payload

    # Парсим данные из payload
    payment_data = yookassa.parse_invoice_payload(payload)

    if payment_data["type"] == "deposit":
        # Пополнение баланса
        user_id = payment_data["user_id"]
        amount = payment_data["amount"]

        # Пополняем баланс пользователя
        db.update_balance(user_id, amount)

        # Создаем запись о платеже
        db.make_payment(user_id, amount)

        # Отправляем уведомление пользователю
        await message.answer(
            f"✅ Баланс успешно пополнен на {amount}₽!\n\n"
            f"Текущий баланс: {db.get_user(user_id).balance}₽"
        )

    elif payment_data["type"] == "tariff":
        # Покупка тарифа
        user_id = payment_data["user_id"]
        tariff_id = payment_data["tariff_id"]

        # Получаем информацию о тарифе
        tariff = db.get_tariff_plan(tariff_id)

        if tariff:
            # Назначаем тариф пользователю на 30 дней
            db.assign_tariff_to_user(user_id, tariff_id, duration_days=30)

            # Отправляем уведомление пользователю
            await message.answer(
                f"✅ Тариф {tariff.name} успешно активирован!\n\n"
                f"Тариф действует до: {(datetime.now() + timedelta(days=30)).strftime('%d.%m.%Y')}\n\n"
                f"Максимум проектов: {tariff.max_projects}\n"
                f"Максимум чатов в проекте: {tariff.max_chats_per_project}"
            )
        else:
            await message.answer(
                "❌ Ошибка при активации тарифа. Обратитесь в поддержку."
            )

    else:
        # Неизвестный тип платежа
        logging.error(f"Неизвестный тип платежа: {payment_data}")
        await message.answer("✅ Платеж успешно обработан!")
