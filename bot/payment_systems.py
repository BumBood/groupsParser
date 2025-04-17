import json
import hashlib
import logging
import requests
import uuid
from typing import Dict, Optional, List, Any
from aiogram import Bot
from aiogram.types import LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup
from config.parameters_manager import ParametersManager


class FreeKassa:
    """Класс для работы с платежной системой FreeKassa"""

    def __init__(self, shop_id: int, secret_word_1: str, secret_word_2: str):
        self.shop_id = shop_id
        self.secret_word_1 = secret_word_1
        self.secret_word_2 = secret_word_2
        self.logger = logging.getLogger(__name__)

    def generate_payment_url(self, amount: float, order_id: str) -> Optional[str]:
        """Генерирует ссылку на форму оплаты через SCI"""
        sign = hashlib.md5(
            f"{self.shop_id}:{amount}:{self.secret_word_1}:RUB:{order_id}".encode()
        ).hexdigest()

        link = f"https://pay.fk.money/?m={self.shop_id}&oa={amount}&currency=RUB&o={order_id}&s={sign}"
        self.logger.debug(f"Ссылка на оплату FreeKassa: {link}")

        if requests.get(link).status_code != 200:
            self.logger.error(f"Ошибка при генерации ссылки на оплату: {link}")
            return None

        return link

    def check_payment_signature(
        self, merchant_id: str, amount: str, order_id: str, sign: str
    ) -> bool:
        """Проверяет подпись уведомления о платеже"""
        expected_sign = hashlib.md5(
            f"{merchant_id}:{amount}:{self.secret_word_2}:{order_id}".encode()
        ).hexdigest()

        status = sign.lower() == expected_sign.lower()

        if not status:
            self.logger.error(
                f"Неверная подпись: {sign} != {expected_sign}. Данные: {merchant_id}, {amount}, {order_id}"
            )

        return status


class YooKassa:
    """Класс для работы с платежной системой ЮKassa через Telegram Invoice"""

    def __init__(self, provider_token: str):
        """
        Инициализация с токеном провайдера ЮKassa

        :param provider_token: Платежный токен от ЮKassa для Telegram
        """
        self.provider_token = provider_token
        self.logger = logging.getLogger(__name__)

    async def create_invoice(
        self,
        bot: Bot,
        chat_id: int,
        title: str,
        description: str,
        payload: str,
        currency: str,
        prices: List[LabeledPrice],
        amount: int,
    ) -> Optional[bool]:
        """
        Создает счет на оплату с помощью Telegram Invoice

        :param bot: Экземпляр бота
        :param chat_id: ID чата пользователя
        :param title: Заголовок счета
        :param description: Описание счета
        :param payload: Строка данных платежа (используется для идентификации)
        :param currency: Валюта платежа (по умолчанию RUB)
        :param prices: Список цен с метками, если amount не указан
        :param amount: Сумма в копейках, если не указаны prices
        :return: True, если счет успешно создан, иначе False
        """
        try:
            # Генерируем уникальный payload, если не передан
            if not payload:
                payload = f"payment_{uuid.uuid4().hex}"

            provider_data = {
                "receipt": {
                    "items": [
                        {
                            "description": title,
                            "quantity": 1,
                            "amount": {"value": amount, "currency": currency},
                            "vat_code": 1,
                            "payment_mode" : "full_payment",
                            "payment_subject" : "commodity"
                        }
                    ]
                }
            }

            # Отправляем счет
            await bot.send_invoice(
                chat_id=chat_id,
                title=title,
                description=description,
                payload=payload,
                provider_token=self.provider_token,
                currency=currency,
                prices=prices,
                need_email=True,
                send_email_to_provider=True,
                provider_data=json.dumps(provider_data),
            )
            return True
        except Exception as e:
            self.logger.error(f"Ошибка при создании счета ЮKassa: {e}")
            return False

    def parse_invoice_payload(self, payload: str) -> Dict:
        """
        Парсит данные из payload и возвращает информацию о платеже

        :param payload: Строка данных платежа
        :return: Словарь с информацией о платеже
        """
        try:
            # Разбираем payload на составляющие
            parts = payload.split("_")
            if len(parts) >= 2:
                return {
                    "type": parts[0],
                    "order_id": parts[1] if len(parts) > 1 else None,
                    "user_id": parts[2] if len(parts) > 2 else None,
                }
            return {"type": "unknown", "order_id": None, "user_id": None}
        except Exception as e:
            self.logger.error(f"Ошибка при парсинге payload: {e}")
            return {"type": "error", "order_id": None, "user_id": None}


class PaymentSystems:
    """Центральный класс для управления всеми платежными системами"""

    def __init__(self):
        self.yookassa = YooKassa(
            provider_token=ParametersManager.get_parameter("yookassa_provider_token")
        )
        self.freekassa = FreeKassa(
            shop_id=ParametersManager.get_parameter("shop_id"),
            secret_word_1=ParametersManager.get_parameter("secret_word_1"),
            secret_word_2=ParametersManager.get_parameter("secret_word_2"),
        )
        self.logger = logging.getLogger(__name__)

    def get_payment_methods_keyboard(self) -> InlineKeyboardMarkup:
        """Создает клавиатуру с выбором способа оплаты"""
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💳 ЮKassa (в Telegram)", callback_data="payment_yookassa"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💳 FreeKassa", callback_data="payment_freekassa"
                    )
                ],
            ]
        )
        return keyboard

    async def create_yookassa_invoice(
        self,
        bot: Bot,
        chat_id: int,
        title: str,
        description: str,
        payload: str,
        amount: int,
    ) -> bool:
        """Создает счет на оплату через ЮKassa"""
        try:
            amount_kopeks = int(amount * 100)
            prices = [LabeledPrice(label=title, amount=amount_kopeks)]
            currency = "RUB"

            # Конвертируем в копейки
            return await self.yookassa.create_invoice(
                bot=bot,
                chat_id=chat_id,
                title=title,
                description=description,
                payload=payload,
                currency=currency,
                prices=prices,
                amount=amount,
            )
        except Exception as e:
            self.logger.error(f"Ошибка при создании счета ЮKassa: {e}")
            return False

    def create_freekassa_payment(self, amount: float, order_id: str) -> Optional[str]:
        """Создает ссылку на оплату через FreeKassa"""
        try:
            return self.freekassa.generate_payment_url(amount, order_id)
        except Exception as e:
            self.logger.error(f"Ошибка при создании платежа FreeKassa: {e}")
            return None

    def verify_freekassa_payment(
        self, merchant_id: str, amount: str, order_id: str, sign: str
    ) -> bool:
        """Проверяет подпись платежа FreeKassa"""
        try:
            return self.freekassa.check_payment_signature(
                merchant_id=merchant_id, amount=amount, order_id=order_id, sign=sign
            )
        except Exception as e:
            self.logger.error(f"Ошибка при проверке платежа FreeKassa: {e}")
            return False

    # Универсальный обработчик платежей, который можно вызывать из других модулей
    async def process_payment(
        self,
        bot: Bot,
        user_id: int,
        amount: float,
        title: str,
        description: str,
        payload: str,
        payment_method: str = "yookassa",
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
        :return: True, если платеж успешно инициирован
        """
        try:
            self.logger.info(
                f"Инициирование платежа: {payment_method}, пользователь: {user_id}, сумма: {amount}₽"
            )

            if payment_method == "yookassa":
                # Создаем платеж через ЮKassa
                success = await self.create_yookassa_invoice(
                    bot=bot,
                    chat_id=user_id,
                    title=title,
                    description=description,
                    payload=payload,
                    amount=int(amount),
                )
                return success

            elif payment_method == "freekassa":
                # Создаем платеж через FreeKassa
                payment_url = self.create_freekassa_payment(
                    amount=amount, order_id=payload
                )

                if payment_url:
                    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="💳 Оплатить", url=payment_url)],
                            [
                                InlineKeyboardButton(
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
                self.logger.error(f"Неизвестный метод оплаты: {payment_method}")
                return False

        except Exception as e:
            self.logger.error(f"Ошибка при инициировании платежа: {e}")
            return False

    # Обработка событий платежей
    async def process_successful_payment(self, payment: Any, bot: Bot) -> bool:
        """
        Обрабатывает успешный платеж от Telegram Payments API

        :param payment: Объект payment из successful_payment хендлера
        :param bot: Экземпляр бота
        :return: True, если платеж успешно обработан
        """
        try:
            from bot.utils.funcs import add_balance_with_notification, error_notify
            from db.database import Database

            db = Database()

            # Логирование информации о платеже
            self.logger.info(f"Успешный платеж: {payment.telegram_payment_charge_id}")
            self.logger.info(f"Сумма: {payment.total_amount} {payment.currency}")
            self.logger.info(f"Данные платежа: {payment.invoice_payload}")

            # Парсим данные платежа
            payload = payment.invoice_payload
            amount = payment.total_amount / 100  # переводим копейки в рубли

            # Обрабатываем разные типы платежей
            if payload.startswith("deposit_"):
                # Платеж на пополнение баланса
                user_id = int(payload.split("_")[1])
                await add_balance_with_notification(user_id, amount, bot)
                return True

            elif payload.startswith("tariff_"):
                # Платеж за тариф
                parts = payload.split("_")
                if len(parts) >= 3:
                    user_id = int(parts[1])
                    tariff_id = int(parts[2])

                    # Активируем тариф для пользователя
                    user_tariff = db.assign_tariff_to_user(user_id, tariff_id)

                    if user_tariff:
                        # Отправляем уведомление администраторам
                        tariff = db.get_tariff_plan(tariff_id)
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
                        return True

            return False

        except Exception as e:
            self.logger.error(f"Ошибка при обработке успешного платежа: {e}")
            return False

    async def process_freekassa_webhook(self, data: Dict) -> bool:
        """
        Обрабатывает уведомление о платеже от FreeKassa

        :param data: Данные запроса от FreeKassa
        :return: True, если платеж успешно обработан
        """
        try:
            from bot.utils.funcs import add_balance_with_notification, error_notify
            from db.database import Database
            from aiogram import Bot
            from aiogram.client.default import DefaultBotProperties

            db = Database()
            bot = Bot(
                token=ParametersManager.get_parameter("bot_token"),
                default=DefaultBotProperties(parse_mode="HTML"),
            )

            # Получаем необходимые данные из запроса
            merchant_id = data.get("MERCHANT_ID")
            amount = data.get("AMOUNT")
            order_id = data.get("MERCHANT_ORDER_ID")
            sign = data.get("SIGN")

            if not all([merchant_id, amount, order_id, sign]):
                self.logger.error(
                    f"Missing required parameters: {merchant_id}, {amount}, {order_id}, {sign}"
                )
                return False

            # Проверяем подпись платежа
            if not self.verify_freekassa_payment(merchant_id, amount, order_id, sign):
                self.logger.error(f"Invalid signature: {sign}")
                return False

            # Проверяем тип платежа по order_id
            if order_id.startswith("tariff_"):
                # Платеж за тариф
                _, user_id, tariff_id, _ = order_id.split("_")
                user_id = int(user_id)
                tariff_id = int(tariff_id)

                # Активируем тариф для пользователя
                user_tariff = db.assign_tariff_to_user(user_id, tariff_id)
                if not user_tariff:
                    await error_notify(
                        bot,
                        f"Произошла ошибка при активации тарифа. Обратитесь в поддержку: {ParametersManager.get_parameter('support_link')}",
                        f"У пользователя {user_id} произошла ошибка при активации тарифа {tariff_id}",
                        user_id,
                    )
                    return False

                # Отправляем уведомление пользователю
                tariff = db.get_tariff_plan(tariff_id)
                current_tariff = db.get_user_tariff(user_id)
                if current_tariff and current_tariff.tariff_plan_id != tariff_id:
                    current_tariff_plan = db.get_tariff_plan(
                        current_tariff.tariff_plan_id
                    )
                    await bot.send_message(
                        user_id,
                        f"✅ Тариф {tariff.name} успешно активирован!\n"
                        f"Предыдущий тариф {current_tariff_plan.name} был заменен.\n"
                        f"Новый тариф действует до: {user_tariff.end_date.strftime('%d.%m.%Y')}",
                    )
                else:
                    await bot.send_message(
                        user_id,
                        f"✅ Тариф {tariff.name} успешно активирован!\n"
                        f"Действует до: {user_tariff.end_date.strftime('%d.%m.%Y')}",
                    )

                # Уведомляем администраторов
                await error_notify(
                    bot,
                    f"💰 Покупка тарифа через FreeKassa!\n\n"
                    f"Пользователь: {user_id}\n"
                    f"Тариф: {tariff.name}\n"
                    f"Сумма: {amount}₽\n"
                    f"Действует до: {user_tariff.end_date.strftime('%d.%m.%Y')}",
                    f"Пользователь {user_id} купил тариф {tariff.name} через FreeKassa",
                    user_id,
                )
            else:
                # Обычное пополнение баланса
                # Формат: <user_id>_<timestamp>
                user_id = int(order_id.split("_")[0])
                await add_balance_with_notification(user_id, float(amount), bot)

                # Дополнительное логгирование
                self.logger.info(
                    f"Баланс пользователя {user_id} пополнен на {amount}₽ через FreeKassa"
                )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при обработке уведомления о платеже: {e}")
            return False
