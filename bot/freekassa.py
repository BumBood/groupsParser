import hashlib
import hmac
import logging
import time
from typing import Optional
import requests


class FreeKassa:
    def __init__(
        self, shop_id: int, api_key: str, base_url: str = "https://api.fk.life/v1"
    ):
        self.shop_id = shop_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _generate_signature(self, params: dict) -> str:
        """Генерирует подпись для запроса."""
        # Сортируем параметры по ключам
        sorted_params = dict(sorted(params.items()))
        # Объединяем значения через |
        values = "|".join(str(v) for v in sorted_params.values())
        # Создаем HMAC SHA256 подпись
        signature = hmac.new(
            self.api_key.encode(), values.encode(), hashlib.sha256
        ).hexdigest()
        return signature

    def _make_request(self, endpoint: str, params: dict) -> dict:
        """Выполняет запрос к API."""
        # Добавляем обязательные параметры
        params.update({"shopId": self.shop_id, "nonce": int(time.time())})

        # Генерируем подпись
        params["signature"] = self._generate_signature(params)

        url = f"{self.base_url}/{endpoint}"
        response = requests.post(url, json=params)

        if response.status_code == 200:
            return response.json()
        else:
            logging.error(
                f"Ошибка при выполнении запроса: {response.status_code}, ответ: {response.text}"
            )
            response.raise_for_status()

    def get_available_payment_systems(self) -> dict:
        """
        Получает список доступных платежных систем.

        Returns:
            dict: Список платежных систем с информацией о каждой
        """
        return self._make_request("currencies", {})

    def create_payment(
        self,
        amount: float,
        currency: str,
        payment_id: str,
        email: str,
        ip: str,
        phone: Optional[str] = None,
        payment_system_id = 1,
    ) -> dict:
        """
        Создает новый платеж и возвращает ссылку на оплату.

        Args:
            amount: Сумма платежа
            currency: Валюта (RUB, USD, EUR и т.д.)
            payment_id: ID платежа в вашей системе
            email: Email плательщика
            ip: IP плательщика
            phone: Телефон плательщика (опционально)
        """
        # Получаем список доступных платежных систем

        # Находим первую доступную платежную систему для указанной валюты

        params = {
            "paymentId": payment_id,
            "i": payment_system_id,
            "email": email,
            "ip": ip,
            "amount": amount,
            "currency": currency,
        }

        if phone:
            params["tel"] = phone

        return self._make_request("orders/create", params)

    def check_order_status(
        self, order_id: Optional[int] = None, payment_id: Optional[str] = None
    ) -> dict:
        """
        Проверяет статус заказа.

        Args:
            order_id: ID заказа в системе FreeKassa
            payment_id: ID заказа в вашей системе
        """
        params = {}
        if order_id:
            params["orderId"] = int(order_id)
        if payment_id:
            params["paymentId"] = str(payment_id)

        return self._make_request("orders", params)

    def get_order_status_text(self, status: int) -> str:
        """Возвращает текстовое описание статуса заказа."""
        statuses = {0: "Новый", 1: "Оплачен", 6: "Возврат", 8: "Ошибка", 9: "Отмена"}
        return statuses.get(status, "Неизвестный статус")


if __name__ == "__main__":
    freekassa = FreeKassa(shop_id=1, api_key="1234567890")
    print(freekassa.get_available_payment_systems())
