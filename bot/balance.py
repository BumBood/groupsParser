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
from bot.payment_systems import PaymentSystems


router = Router(name="balance")
db = Database()
payment_systems = PaymentSystems()

# Для обратной совместимости
freekassa = FreeKassa(
    shop_id=int(ParametersManager.get_parameter("shop_id")),
    secret_word_1=str(ParametersManager.get_parameter("secret_word_1")),
    secret_word_2=str(ParametersManager.get_parameter("secret_word_2")),
)


class DepositStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_payment_method = State()


@router.callback_query(F.data == "deposit")
async def deposit_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(DepositStates.waiting_for_amount)
    await callback.message.edit_text(
        f"💰 Введите сумму пополнения в рублях (минимум {ParametersManager.get_parameter('parse_comments_cost')}₽):\n\n"
        "💳 Доступны платёжные системы FreeKassa и ЮKassa\n"
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

        # Сохраняем сумму в состоянии
        await state.update_data(amount=amount)

        # Показываем выбор способа оплаты
        await message.answer(
            "Выберите способ оплаты:",
            reply_markup=payment_systems.get_payment_methods_keyboard(),
        )

        # Устанавливаем состояние ожидания выбора способа оплаты
        await state.set_state(DepositStates.waiting_for_payment_method)

    except ValueError:
        await message.answer("❌ Введите корректную сумму числом")


@router.callback_query(DepositStates.waiting_for_payment_method)
async def process_payment_method(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    data = await state.get_data()
    amount = data["amount"]
    order_id = f"deposit_{callback.from_user.id}_{int(time.time())}"

    if callback.data == "payment_yookassa":
        # Создаем платеж через ЮKassa
        payload = f"deposit_{callback.from_user.id}_{amount}"

        success = await payment_systems.create_yookassa_invoice(
            bot=bot,
            chat_id=callback.from_user.id,
            title="Пополнение баланса",
            description=f"Пополнение баланса на сумму {amount} рублей",
            payload=payload,
            amount=int(amount),
        )

        if not success:
            await callback.message.answer(
                "❌ Произошла ошибка при создании счета. Попробуйте позже."
            )

    elif callback.data == "payment_freekassa":
        # Создаем платеж через FreeKassa
        payment_url = payment_systems.create_freekassa_payment(amount, order_id)

        if payment_url:
            keyboard = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
                    [
                        types.InlineKeyboardButton(
                            text="❌ Отменить", callback_data="cancel_payment"
                        )
                    ],
                ]
            )

            await callback.message.answer(
                f"💰 Платеж на сумму {amount}₽ создан\n"
                f"ID платежа: {order_id}\n\n"
                "1. Нажмите кнопку «Оплатить»\n"
                "2. Оплатите счет удобным способом\n"
                "3. Деньги автоматически зачислятся на ваш баланс\n\n"
                f"При ошибках пишите в поддержку: {ParametersManager.get_parameter('support_link')}",
                reply_markup=keyboard,
            )
        else:
            await callback.message.answer(
                "❌ Произошла ошибка при создании платежа. Попробуйте позже."
            )

    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Платеж отменен")


# Обработчик предварительной проверки платежа YooKassa
@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: types.PreCheckoutQuery, bot: Bot):
    """
    Обрабатывает предварительную проверку платежа от Telegram Payments API
    """
    try:
        # Логирование информации о платеже
        logging.info(f"Предварительная проверка платежа: {pre_checkout_query.id}")
        logging.info(
            f"Сумма: {pre_checkout_query.total_amount} {pre_checkout_query.currency}"
        )
        logging.info(f"Данные платежа: {pre_checkout_query.invoice_payload}")

        # Всегда подтверждаем платеж на этапе pre-checkout
        # Основная проверка будет в successful_payment
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

    except Exception as e:
        logging.error(f"Ошибка при предварительной проверке платежа: {e}")
        # В случае ошибки отклоняем платеж
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Произошла ошибка, попробуйте позже или обратитесь в поддержку.",
        )


# Обработчик успешного платежа YooKassa
@router.message(F.successful_payment)
async def successful_payment_handler(message: types.Message, bot: Bot):
    """
    Обрабатывает успешный платеж от Telegram Payments API
    """
    try:
        payment = message.successful_payment

        # Логирование информации о платеже
        logging.info(f"Успешный платеж: {payment.telegram_payment_charge_id}")
        logging.info(f"Сумма: {payment.total_amount} {payment.currency}")
        logging.info(f"Данные платежа: {payment.invoice_payload}")

        # Парсим данные платежа
        payload = payment.invoice_payload

        amount = payment.total_amount

        # Обрабатываем разные типы платежей
        if payload.startswith("deposit_"):
            # Платеж на пополнение баланса
            user_id = int(payload.split("_")[1])
            await add_balance_with_notification(user_id, amount, bot)

            # Информируем пользователя
            await message.answer(
                f"✅ Оплата успешно выполнена!\n\n" f"Ваш баланс пополнен на {amount}₽."
            )

        elif payload.startswith("tariff_"):
            # Платеж за тариф
            parts = payload.split("_")
            if len(parts) >= 3:
                user_id = int(parts[1])
                tariff_id = int(parts[2])

                # Активируем тариф для пользователя
                user_tariff = db.assign_tariff_to_user(user_id, tariff_id)

                if user_tariff:
                    # Отправляем уведомление пользователю
                    tariff = db.get_tariff_plan(tariff_id)
                    current_tariff = db.get_user_tariff(user_id)

                    if current_tariff and current_tariff.tariff_plan_id != tariff_id:
                        current_tariff_plan = db.get_tariff_plan(
                            current_tariff.tariff_plan_id
                        )
                        await message.answer(
                            f"✅ Тариф {tariff.name} успешно активирован!\n"
                            f"Предыдущий тариф {current_tariff_plan.name} был заменен.\n"
                            f"Новый тариф действует до: {user_tariff.end_date.strftime('%d.%m.%Y')}",
                        )
                    else:
                        await message.answer(
                            f"✅ Тариф {tariff.name} успешно активирован!\n"
                            f"Действует до: {user_tariff.end_date.strftime('%d.%m.%Y')}",
                        )
                else:
                    await message.answer(
                        f"❌ Произошла ошибка при активации тарифа. "
                        f"Обратитесь в поддержку: {ParametersManager.get_parameter('support_link')}"
                    )
        else:
            # Неизвестный тип платежа
            logging.warning(f"Неизвестный тип платежа: {payload}")
            await message.answer(
                f"✅ Оплата успешно выполнена!\n\n"
                f"Если у вас возникли вопросы, обратитесь в поддержку: "
                f"{ParametersManager.get_parameter('support_link')}"
            )

    except Exception as e:
        logging.error(f"Ошибка при обработке успешного платежа: {e}")
        await message.answer(
            f"❌ Произошла ошибка при обработке платежа. "
            f"Обратитесь в поддержку: {ParametersManager.get_parameter('support_link')}"
        )


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
