import json
from typing import Optional
import logging
from aiogram import Bot
from aiogram.types import LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup
from bot.yookassa import YooKassa
from bot.freekassa import FreeKassa
from config.parameters_manager import ParametersManager


class PaymentSystems:
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
            prices = [
                LabeledPrice(label=title, amount=amount_kopeks)
            ]
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
                amount=amount_kopeks,
                need_phone_number=True,
                send_phone_number_to_provider=True,
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
