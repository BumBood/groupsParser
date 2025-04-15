from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.payment_systems import PaymentSystems
import logging
from bot.database import Database
import time

router = Router()
payment_systems = PaymentSystems()
logger = logging.getLogger(__name__)


class PaymentStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_payment_method = State()
    waiting_for_tariff = State()  # Для выбора тарифа


@router.message(Command("pay"))
async def cmd_pay(message: Message, state: FSMContext):
    await state.update_data(payment_type="deposit")
    await message.answer("Введите сумму платежа в рублях:")
    await state.set_state(PaymentStates.waiting_for_amount)


@router.message(PaymentStates.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            raise ValueError("Сумма должна быть больше 0")

        await state.update_data(amount=amount)
        await message.answer(
            "Выберите способ оплаты:",
            reply_markup=payment_systems.get_payment_methods_keyboard(),
        )
        await state.set_state(PaymentStates.waiting_for_payment_method)
    except ValueError:
        await message.answer("Пожалуйста, введите корректную сумму в рублях")


@router.callback_query(PaymentStates.waiting_for_payment_method)
async def process_payment_method(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    amount = data["amount"]
    payment_type = data.get(
        "payment_type", "deposit"
    )  # По умолчанию пополнение баланса
    order_id = f"{payment_type}_{callback.from_user.id}_{int(time.time())}"

    if callback.data == "payment_yookassa":
        # Для ЮKassa добавляем дополнительную информацию в payload
        if payment_type == "deposit":
            payload = f"deposit_{callback.from_user.id}_{amount}"
        elif payment_type == "tariff":
            tariff_id = data.get("tariff_id")
            payload = f"tariff_{callback.from_user.id}_{tariff_id}"

        success = await payment_systems.create_yookassa_invoice(
            bot=bot,
            chat_id=callback.from_user.id,
            title=(
                "Оплата услуг"
                if payment_type == "deposit"
                else f"Тариф {data.get('tariff_name', '')}"
            ),
            description=f"Оплата на сумму {amount} рублей",
            payload=payload,
            amount=int(amount * 100),  # Конвертируем в копейки
        )
        if not success:
            await callback.message.answer(
                "Произошла ошибка при создании счета. Попробуйте позже."
            )
    elif callback.data == "payment_freekassa":
        payment_url = payment_systems.create_freekassa_payment(amount, order_id)
        if payment_url:
            await callback.message.answer(
                f"Для оплаты перейдите по ссылке:\n{payment_url}"
            )
        else:
            await callback.message.answer(
                "Произошла ошибка при создании платежа. Попробуйте позже."
            )

    await state.clear()
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, bot: Bot):
    payment_info = message.successful_payment
    payload = payment_info.invoice_payload

    # Парсим данные из payload
    payment_data = payment_systems.yookassa.parse_invoice_payload(payload)

    if payment_data["type"] == "deposit":
        # Пополнение баланса
        user_id = int(payment_data["user_id"])
        amount = int(payment_data["amount"])

        # Обновляем баланс пользователя
        db = Database()
        db.update_balance(user_id, amount)
        db.make_payment(user_id, amount)

        await message.answer(
            f"✅ Баланс успешно пополнен на {amount}₽!\n\n"
            f"Текущий баланс: {db.get_user(user_id).balance}₽"
        )
    elif payment_data["type"] == "tariff":
        # Покупка тарифа
        user_id = int(payment_data["user_id"])
        tariff_id = int(payment_data["tariff_id"])

        db = Database()
        tariff = db.get_tariff_plan(tariff_id)

        if tariff:
            # Активируем тариф
            db.activate_tariff(user_id, tariff_id)
            await message.answer(
                f"✅ Тариф {tariff.name} успешно активирован!\n"
                f"Срок действия: 30 дней"
            )
        else:
            await message.answer("❌ Ошибка активации тарифа. Обратитесь в поддержку.")


@router.callback_query(F.data.startswith("select_tariff_"))
async def select_tariff(callback: CallbackQuery, state: FSMContext):
    tariff_id = int(callback.data.split("_")[2])
    db = Database()
    tariff = db.get_tariff_plan(tariff_id)

    if not tariff:
        await callback.message.answer("❌ Тариф не найден")
        return

    await state.update_data(
        amount=tariff.price / 100,  # Конвертируем копейки в рубли
        payment_type="tariff",
        tariff_id=tariff_id,
        tariff_name=tariff.name,
    )

    await callback.message.answer(
        "Выберите способ оплаты:",
        reply_markup=payment_systems.get_payment_methods_keyboard(),
    )
    await state.set_state(PaymentStates.waiting_for_payment_method)
    await callback.answer()
