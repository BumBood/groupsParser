import logging
from aiogram import Bot, Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import time
from bot.freekassa import FreeKassa
from bot.utils.funcs import add_balance_with_notification
from config.parameters_manager import ParametersManager
from db.database import Database
from bot.keyboards import payment_keyboard
import os
from aiogram.types import LabeledPrice, PreCheckoutQuery, Message
import json


router = Router(name="balance")
db = Database()

freekassa = FreeKassa(
    shop_id=int(ParametersManager.get_parameter("shop_id")),
    secret_word_1=str(ParametersManager.get_parameter("secret_word_1")),
    secret_word_2=str(ParametersManager.get_parameter("secret_word_2")),
)


class DepositStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_payment = State()


@router.callback_query(F.data == "deposit")
async def deposit_start(callback: types.CallbackQuery):
    await callback.message.edit_text("💰 Выберите способ оплаты", reply_markup=payment_keyboard)


@router.callback_query(F.data.startswith("payment|"))
async def payment(callback: types.CallbackQuery, state: FSMContext):
    temp_data = callback.data.split("|")[1]

    if temp_data == "freeKassa":
        method = "FreeKassa"
        await state.update_data(payment_method=method)

    elif temp_data == "yooKassa":
        method = "ЮKassa"
        await state.update_data(payment_method=method)

    await state.set_state(DepositStates.waiting_for_amount)
    await callback.message.answer(
        f"💰 Введите сумму пополнения в рублях (минимум {ParametersManager.get_parameter('parse_comments_cost')}₽):\n\n"
        f"💳 Оплата происходит через платёжную систему {method}\n"
        "🎉 После оплаты средства автоматически зачислятся на ваш баланс\n\n"
        f"* Если вашего способа оплаты нет здесь, напишите в поддержку: {ParametersManager.get_parameter('support_link')}"
    )

@router.message(DepositStates.waiting_for_amount)
async def process_deposit_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount < int(ParametersManager.get_parameter('parse_comments_cost')):
            await message.answer(f"❌ Минимальная сумма пополнения - {ParametersManager.get_parameter('parse_comments_cost')}₽")
            return
        

        try:
            data = await state.get_data()

            order_id = f"{message.from_user.id}_{int(time.time())}"

            if data['payment_method'] == "FreeKassa":
                # Создаем платеж в FreeKassa
                payment = freekassa.generate_payment_url(
                    amount=amount,
                    order_id=order_id,
                )

                logging.debug(f"Платеж создан: {payment}")

                if not payment:
                    logging.error(f"Ошибка создания платежа: {message.from_user.id}")
                    await message.answer("❌ Ошибка создания платежа. Попробуйте позже.")
                    await state.clear()
                    return

                keyboard = types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(text="💳 Оплатить", url=payment)],
                        [
                            types.InlineKeyboardButton(
                                text="❌ Отменить", callback_data="cancel_payment"
                            )
                        ],
                    ]
                )

                await message.answer(
                    f"💰 Платеж на сумму {amount}₽ создан\n"
                    f"ID платежа: {message.from_user.id}_{int(time.time())}\n\n"
                    "1. Нажмите кнопку «Оплатить»\n"
                    "2. Оплатите счет удобным способом\n"
                    "3. Деньги автоматически зачислятся на ваш баланс\n\n"
                    f"При ошибках пишите в поддержку: {ParametersManager.get_parameter('support_link')}",
                    reply_markup=keyboard,
                )

            elif data['payment_method'] == "ЮKassa":
                # Проверка максимальной суммы для ЮKassa
                if amount > 100000:  # ЮKassa имеет ограничение в 100000 рублей
                    await message.answer("❌ Максимальная сумма пополнения - 100000₽")
                    return
                
                # Создаем платеж в ЮKassa
                amount_kopeks = int(amount * 100)
                label = "Пополнение баланса"
                if amount_kopeks <= 0:
                    await message.answer("❌ Сумма должна быть положительным числом")
                    return

                prices = [LabeledPrice(label=label, amount=amount_kopeks)]

                currency = "RUB"

                provider_data = {
                "receipt": {
                    "items": [
                    {
                        "description": label,
                        "quantity": "1.00",
                        "amount": {
                            "value": f"{amount_kopeks / 100:.2f}",
                            "currency": currency
                        },
                        "vat_code": 1
                    }
                    ]
                }
                }

                await message.answer_invoice(
                    title=label,
                    description='Пополнение баланса для покупки комментариев',
                    payload=order_id,
                    provider_token=os.getenv('YOOKASSA_TOKEN'),
                    currency=currency,
                    prices=prices,
                    need_phone_number=True,
                    send_phone_number_to_provider=True,
                    provider_data=json.dumps(provider_data)
                )

                await state.clear()


        except Exception as e:
            logging.error(f"Ошибка создания платежа: {e}")
            await message.answer("❌ Произошла ошибка. Попробуйте позже.")
            await state.clear()

    except ValueError:
        await message.answer("❌ Введите корректную сумму числом")


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Платеж отменен")


@router.callback_query(F.data.startswith("deposit_"))
async def auto_deposit(callback: types.CallbackQuery):
    try:
        amount = int(callback.data.split("_")[1])
        if amount < int(ParametersManager.get_parameter('parse_comments_cost')):
            await callback.message.answer(f"❗ Ваша сумма пополнения изменена до минимальной в {ParametersManager.get_parameter('parse_comments_cost')}₽")
            amount = int(ParametersManager.get_parameter('parse_comments_cost'))

        # Создаем платеж в FreeKassa
        payment = freekassa.generate_payment_url(
            amount=amount,
            order_id=f"{callback.from_user.id}_{int(time.time())}",
        )

        logging.debug(f"Платеж создан: {payment}")

        if not payment:
            logging.error(f"Ошибка создания платежа: {callback.from_user.id}")
            await callback.message.answer(
                "❌ Ошибка создания платежа. Попробуйте позже."
            )
            return

        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="💳 Оплатить", url=payment)],
                [
                    types.InlineKeyboardButton(
                        text="❌ Отменить", callback_data="cancel_payment"
                    )
                ],
            ]
        )

        await callback.message.answer(
            f"💰 Платеж на сумму {amount}₽ создан\n"
            f"ID платежа: {callback.from_user.id}_{int(time.time())}\n\n"
            "1. Нажмите кнопку «Оплатить»\n"
            "2. Оплатите счет удобным способом\n"
            "3. Деньги автоматически зачислятся на ваш баланс\n\n"
            f"При ошибках пишите в поддержку: {ParametersManager.get_parameter('support_link')}",
            reply_markup=keyboard,
        )

        await callback.message.delete()
    except Exception as e:
        logging.error(f"Ошибка создания платежа: {e}")
        await callback.message.answer("❌ Произошла ошибка. Попробуйте позже.")
        

# Метод для обработки платежа юКассы
@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    try:
        await pre_checkout_query.answer(ok=True)  # всегда отвечаем утвердительно
    except Exception as e:
        logging.error(f"Ошибка при обработке апдейта типа PreCheckoutQuery: {e}")


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot):
    try:
        user_id = message.from_user.id
        amount = message.successful_payment.total_amount / 100
        await add_balance_with_notification(user_id, float(amount), bot)
    except Exception as e:
        logging.error(f"Ошибка при обработке успешного платежа: {e}")
        await message.answer("❌ Произошла ошибка при зачислении средств. Пожалуйста, обратитесь в поддержку.")



