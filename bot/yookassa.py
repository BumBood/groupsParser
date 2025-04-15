import json
from typing import Dict, Optional, List
import uuid
import logging
from aiogram import Bot
from aiogram.types import LabeledPrice
from config.parameters_manager import ParametersManager


class YooKassa:
    """
    Класс для работы с платежной системой ЮKassa через Telegram Invoice
    """

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
        currency: str = "RUB",
        prices: List[LabeledPrice] = None,
        amount: int = None,
        photo_url: str = None,
        need_name: bool = False,
        need_phone_number: bool = False,
        need_email: bool = False,
        need_shipping_address: bool = False,
        send_phone_number_to_provider: bool = False,
        send_email_to_provider: bool = False,
        is_flexible: bool = False,
        max_tip_amount: int = 0,
        suggested_tip_amounts: List[int] = None,
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
        :param photo_url: URL фотографии для счета
        :return: True, если счет успешно создан, иначе False
        """
        try:
            # Если передана сумма, создаем список цен
            if amount is not None and not prices:
                prices = [LabeledPrice(label=title, amount=amount)]

            # Генерируем уникальный payload, если не передан
            if not payload:
                payload = f"payment_{uuid.uuid4().hex}"

            provider_data = {
                "receipt": {
                    "items": [
                    {
                        "description": title,
                        "quantity": 1,
                        "amount": {
                            "value": amount // 100,
                            "currency": currency
                        },
                        "vat_code": 1
                    }
                    ]
                }
                }            
            
            # Отправляем счет
            await bot.send_invoice(
                    chat_id=chat_id,
                    title=title,
                    description='Пополнение баланса',
                    payload=payload,
                    provider_token=self.provider_token,
                    currency=currency,
                    prices=prices,
                    need_phone_number=True,
                    send_phone_number_to_provider=True,
                    provider_data=json.dumps(provider_data)
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
