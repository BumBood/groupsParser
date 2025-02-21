import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import time

from bot.freekassa import FreeKassa
from bot.utils.funcs import add_balance_with_notification
from config.parameters_manager import ParametersManager
from db.database import Database


router = Router(name="balance")
db = Database()

freekassa = FreeKassa(
    shop_id=int(ParametersManager.get_parameter("shop_id")),
    api_key=str(ParametersManager.get_parameter("api_kassa")),
)


class DepositStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_email = State()
    waiting_for_payment = State()


@router.callback_query(F.data == "deposit")
async def deposit_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(DepositStates.waiting_for_amount)
    await callback.message.answer(
        "💰 Введите сумму пополнения в рублях (минимум 100₽):"
    )


@router.message(DepositStates.waiting_for_amount)
async def process_deposit_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount < 100:
            await message.answer("❌ Минимальная сумма пополнения - 100₽")
            return

        # Сохраняем сумму и запрашиваем email
        await state.update_data(amount=amount)
        await state.set_state(DepositStates.waiting_for_email)
        await message.answer("📧 Введите ваш email для чека об оплате:")

    except ValueError:
        await message.answer("❌ Введите корректную сумму числом")


@router.message(DepositStates.waiting_for_email)
async def process_deposit_email(message: types.Message, state: FSMContext):
    email = message.text.strip().lower()

    # Простая проверка формата email
    if "@" not in email or "." not in email:
        await message.answer("❌ Введите корректный email адрес")
        return

    try:
        data = await state.get_data()
        amount = data["amount"]

        # Создаем платеж в FreeKassa
        payment = freekassa.create_payment(
            amount=amount,
            currency="RUB",
            payment_id=f"{message.from_user.id}_{int(time.time())}",
            email=email,
            ip="127.0.0.1",  # Можно получать реальный IP
        )

        logging.debug(f"Платеж создан: {payment}")

        if not payment.get("location"):
            logging.error(f"Ошибка создания платежа: {payment}")
            await message.answer("❌ Ошибка создания платежа. Попробуйте позже.")
            await state.clear()
            return

        # Сохраняем данные платежа в состояние
        await state.update_data(
            order_id=payment["orderId"], created_at=int(time.time())
        )
        await state.set_state(DepositStates.waiting_for_payment)

        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="💳 Оплатить", url=payment["location"]
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="🔄 Проверить статус", callback_data="check_payment"
                    )
                ],
                [
                    types.InlineKeyboardButton(
                        text="❌ Отменить", callback_data="cancel_payment"
                    )
                ],
            ]
        )

        await message.answer(
            f"💰 Платеж на сумму {amount}₽ создан\n"
            f"ID платежа: {payment['orderId']}\n"
            f"Email для чека: {email}\n\n"
            "1. Нажмите кнопку «Оплатить»\n"
            "2. Оплатите счет удобным способом\n"
            "3. Вернитесь в бот и нажмите «Проверить статус»",
            reply_markup=keyboard,
        )

    except Exception as e:
        logging.error(f"Ошибка создания платежа: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте позже.")
        await state.clear()


@router.callback_query(F.data == "check_payment")
async def check_payment(callback: types.CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        order_id = data.get("order_id")
        amount = data.get("amount")
        created_at = data.get("created_at")

        if not order_id:
            await callback.message.edit_text("❌ Платеж не найден")
            await state.clear()
            return

        # Проверяем, не истекло ли время платежа
        if time.time() - created_at > 1800:
            await callback.message.edit_text("❌ Время ожидания платежа истекло")
            await state.clear()
            return

        # Проверяем статус платежа через FreeKassa API
        payment_status = freekassa.check_order_status(order_id=order_id)
        logging.debug(f"Статус платежа: {payment_status}")

        payment_successful = (
            payment_status.get("type") == "success"
            and payment_status.get("orders", [{}])[0].get("status") == 1
        )

        if payment_successful:
            await add_balance_with_notification(
                callback.from_user.id, amount, callback.bot
            )
            await callback.message.edit_text(f"Платеж {order_id} успешно оплачен")
            await state.clear()
        else:
            keyboard = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text="🔄 Проверить снова", callback_data="check_payment"
                        )
                    ],
                    [
                        types.InlineKeyboardButton(
                            text="❌ Отменить", callback_data="cancel_payment"
                        )
                    ],
                ]
            )
            try:
                await callback.message.edit_text(
                    "⏳ Платеж пока не получен\n"
                    "Если вы только что оплатили, подождите немного и нажмите «Проверить снова»",
                    reply_markup=keyboard,
                )
            except Exception as e:
                if "message is not modified" not in str(e):
                    raise
                await callback.answer("Статус платежа не изменился")

    except Exception as e:
        logging.error(f"Ошибка проверки платежа: {e}")
        await callback.message.answer("❌ Ошибка проверки платежа. Попробуйте позже.")
        await state.clear()


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Платеж отменен")
