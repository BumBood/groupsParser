import logging
import time
from aiogram import Bot, Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.payment_systems import PaymentSystems
from config.parameters_manager import ParametersManager
from db.database import Database


router = Router(name="balance")
db = Database()
payment_systems = PaymentSystems()


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

    payment_method = None
    if callback.data == "payment_yookassa":
        payment_method = "yookassa"
    elif callback.data == "payment_freekassa":
        payment_method = "freekassa"

    if payment_method:
        # Создаем платеж через централизованный обработчик
        payload = f"deposit_{callback.from_user.id}_{amount}"

        success = await payment_systems.process_payment(
            bot=bot,
            user_id=callback.from_user.id,
            amount=amount,
            title="Пополнение баланса",
            description=f"Пополнение баланса на сумму {amount} рублей",
            payload=payload,
            payment_method=payment_method,
        )

        if not success:
            await callback.message.answer(
                "❌ Произошла ошибка при создании платежа. Попробуйте позже."
            )

    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Платеж отменен")


@router.callback_query(F.data.startswith("deposit_"))
async def auto_deposit(callback: types.CallbackQuery, bot: Bot):
    try:
        amount = int(callback.data.split("_")[1])
        if amount < int(ParametersManager.get_parameter("parse_comments_cost")):
            await callback.message.answer(
                f"❗ Ваша сумма пополнения изменена до минимальной в {ParametersManager.get_parameter('parse_comments_cost')}₽"
            )
            amount = int(ParametersManager.get_parameter("parse_comments_cost"))

        # Используем централизованный обработчик для создания платежа
        payload = f"deposit_{callback.from_user.id}_{int(time.time())}"

        success = await payment_systems.process_payment(
            bot=bot,
            user_id=callback.from_user.id,
            amount=amount,
            title="Быстрое пополнение баланса",
            description=f"Пополнение баланса на сумму {amount} рублей",
            payload=payload,
            payment_method="freekassa",  # Используем FreeKassa для быстрых платежей
        )

        if not success:
            logging.error(f"Ошибка создания платежа: {callback.from_user.id}")
            await callback.message.answer(
                "❌ Ошибка создания платежа. Попробуйте позже."
            )
            return

        await callback.message.delete()
    except Exception as e:
        logging.error(f"Ошибка создания платежа: {e}")
        await callback.message.answer("❌ Произошла ошибка. Попробуйте позже.")


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
        await pre_checkout_query.answer(ok=True)

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

        # Обрабатываем платеж через централизованную систему
        success = await payment_systems.process_successful_payment(payment, bot)

        if success:
            # Определяем тип платежа для пользовательского сообщения
            if payment.invoice_payload.startswith("deposit_"):
                amount = payment.total_amount / 100  # копейки в рубли
                await message.answer(
                    f"✅ Оплата успешно выполнена!\n\n"
                    f"Ваш баланс пополнен на {amount}₽."
                )
            elif payment.invoice_payload.startswith("tariff_"):
                parts = payment.invoice_payload.split("_")
                if len(parts) >= 3:
                    tariff_id = int(parts[2])
                    tariff = db.get_tariff_plan(tariff_id)
                    user_tariff = db.get_user_tariff(message.from_user.id)

                    if user_tariff:
                        await message.answer(
                            f"✅ Тариф {tariff.name} успешно активирован!\n"
                            f"Действует до: {user_tariff.end_date.strftime('%d.%m.%Y')}",
                        )
        else:
            # Если что-то пошло не так
            await message.answer(
                f"❌ Произошла ошибка при обработке платежа. "
                f"Обратитесь в поддержку: {ParametersManager.get_parameter('support_link')}"
            )

    except Exception as e:
        logging.error(f"Ошибка при обработке успешного платежа: {e}")
        await message.answer(
            f"❌ Произошла ошибка при обработке платежа. "
            f"Обратитесь в поддержку: {ParametersManager.get_parameter('support_link')}"
        )
