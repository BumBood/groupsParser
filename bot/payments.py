import logging
from typing import Optional
from aiogram import Bot, Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import LabeledPrice

from bot.payment_systems import PaymentSystems
from bot.utils.funcs import add_balance_with_notification, error_notify
from config.parameters_manager import ParametersManager
from db.database import Database

# Инициализация роутера и зависимостей
router = Router(name="payments")
db = Database()
payment_systems = PaymentSystems()
logger = logging.getLogger(__name__)


# Состояния для FSM
class PaymentStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_payment_method = State()
    waiting_for_payment_confirmation = State()


# Универсальный обработчик платежей, который можно вызывать из других модулей
async def process_payment(
    bot: Bot,
    user_id: int,
    amount: float,
    title: str,
    description: str,
    payload: str,
    payment_method: str = "yookassa",
    photo_url: Optional[str] = None,
) -> bool:
    """
    Универсальный метод для обработки платежей через разные платежные системы

    :param bot: Экземпляр бота
    :param user_id: ID пользователя
    :param amount: Сумма платежа в рублях
    :param title: Заголовок платежа
    :param description: Описание платежа
    :param payload: Идентификатор платежа
    :param payment_method: Метод оплаты ("yookassa" или "freekassa")
    :param photo_url: URL фотографии для счета (только для YooKassa)
    :return: True, если платеж успешно инициирован
    """
    try:
        logger.info(
            f"Инициирование платежа: {payment_method}, пользователь: {user_id}, сумма: {amount}₽"
        )

        if payment_method == "yookassa":
            # Создаем платеж через ЮKassa
            success = await payment_systems.create_yookassa_invoice(
                bot=bot,
                chat_id=user_id,
                title=title,
                description=description,
                payload=payload,
                amount=int(amount), 
                photo_url=photo_url,
            )
            return success

        elif payment_method == "freekassa":
            # Создаем платеж через FreeKassa
            payment_url = payment_systems.create_freekassa_payment(
                amount=amount, order_id=payload
            )

            if payment_url:
                keyboard = types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            types.InlineKeyboardButton(
                                text="💳 Оплатить", url=payment_url
                            )
                        ],
                        [
                            types.InlineKeyboardButton(
                                text="❌ Отменить", callback_data="cancel_payment"
                            )
                        ],
                    ]
                )

                await bot.send_message(
                    user_id,
                    f"💰 Платеж на сумму {amount}₽ создан\n"
                    f"ID платежа: {payload}\n\n"
                    "1. Нажмите кнопку «Оплатить»\n"
                    "2. Оплатите счет удобным способом\n"
                    "3. Деньги автоматически зачислятся на ваш баланс\n\n"
                    f"При ошибках пишите в поддержку: {ParametersManager.get_parameter('support_link')}",
                    reply_markup=keyboard,
                )
                return True
            return False

        else:
            logger.error(f"Неизвестный метод оплаты: {payment_method}")
            return False

    except Exception as e:
        logger.error(f"Ошибка при инициировании платежа: {e}")
        return False


# Обработчик предварительной проверки платежа YooKassa
@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: types.PreCheckoutQuery, bot: Bot):
    """
    Обрабатывает предварительную проверку платежа от Telegram Payments API
    """
    try:
        # Логирование информации о платеже
        logger.info(f"Предварительная проверка платежа: {pre_checkout_query.id}")
        logger.info(
            f"Сумма: {pre_checkout_query.total_amount} {pre_checkout_query.currency}"
        )
        logger.info(f"Данные платежа: {pre_checkout_query.invoice_payload}")

        # Всегда подтверждаем платеж на этапе pre-checkout
        # Основная проверка будет в successful_payment
        await pre_checkout_query.answer(ok=True)

    except Exception as e:
        logger.error(f"Ошибка при предварительной проверке платежа: {e}")
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
        logger.info(f"Успешный платеж: {payment.telegram_payment_charge_id}")
        logger.info(f"Сумма: {payment.total_amount} {payment.currency}")
        logger.info(f"Данные платежа: {payment.invoice_payload}")

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

                    # Уведомляем администраторов
                    await error_notify(
                        bot,
                        f"💰 Покупка тарифа!\n\n"
                        f"Пользователь: {user_id}\n"
                        f"Тариф: {tariff.name}\n"
                        f"Сумма: {amount}₽\n"
                        f"Действует до: {user_tariff.end_date.strftime('%d.%m.%Y')}",
                        f"Пользователь {user_id} купил тариф {tariff.name}",
                        user_id,
                    )
                else:
                    await message.answer(
                        f"❌ Произошла ошибка при активации тарифа. "
                        f"Обратитесь в поддержку: {ParametersManager.get_parameter('support_link')}"
                    )
        else:
            # Неизвестный тип платежа
            logger.warning(f"Неизвестный тип платежа: {payload}")
            await message.answer(
                f"✅ Оплата успешно выполнена!\n\n"
                f"Если у вас возникли вопросы, обратитесь в поддержку: "
                f"{ParametersManager.get_parameter('support_link')}"
            )

    except Exception as e:
        logger.error(f"Ошибка при обработке успешного платежа: {e}")
        await message.answer(
            f"❌ Произошла ошибка при обработке платежа. "
            f"Обратитесь в поддержку: {ParametersManager.get_parameter('support_link')}"
        )
