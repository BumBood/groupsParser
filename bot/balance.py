import logging
from aiogram import Bot, Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import time
from bot.freekassa import FreeKassa
from bot.utils.funcs import add_balance_with_notification
from config.parameters_manager import ParametersManager
from db.database import Database
import os
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


@router.callback_query(F.data == "deposit")
async def deposit_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(DepositStates.waiting_for_amount)
    await callback.message.edit_text(
        f"💰 Введите сумму пополнения в рублях (минимум {ParametersManager.get_parameter('parse_comments_cost')}₽):\n\n"
        "💳 Оплата происходит через платёжную систему FreeKassa\n"
        "🎉 После оплаты средства автоматически зачислятся на ваш баланс\n\n"
        f"* Если у вас возникли проблемы, напишите в поддержку: {ParametersManager.get_parameter('support_link')}"
    )


@router.message(DepositStates.waiting_for_amount)
async def process_deposit_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount < int(ParametersManager.get_parameter("parse_comments_cost")):
            await message.answer(
                f"❌ Минимальная сумма пополнения - {ParametersManager.get_parameter('parse_comments_cost')}₽"
            )
            return

        try:
            order_id = f"{message.from_user.id}_{int(time.time())}"

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
                f"ID платежа: {order_id}\n\n"
                "1. Нажмите кнопку «Оплатить»\n"
                "2. Оплатите счет удобным способом\n"
                "3. Деньги автоматически зачислятся на ваш баланс\n\n"
                f"При ошибках пишите в поддержку: {ParametersManager.get_parameter('support_link')}",
                reply_markup=keyboard,
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
        if amount < int(ParametersManager.get_parameter("parse_comments_cost")):
            await callback.message.answer(
                f"❗ Ваша сумма пополнения изменена до минимальной в {ParametersManager.get_parameter('parse_comments_cost')}₽"
            )
            amount = int(ParametersManager.get_parameter("parse_comments_cost"))

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
