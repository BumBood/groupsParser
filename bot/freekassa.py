import hashlib
import logging

import requests


class FreeKassa:
    def __init__(
        self, shop_id: int, secret_word_1: str, secret_word_2: str
    ):
        self.shop_id = shop_id
        self.secret_word_1 = secret_word_1
        self.secret_word_2 = secret_word_2


    def generate_payment_url(self, amount: float, order_id: str, email: str) -> str:
        """Генерирует ссылку на форму оплаты через SCI"""
        sign = hashlib.md5(
            f"{self.shop_id}:{amount}:{self.secret_word_1}:RUB:{order_id}".encode()
        ).hexdigest()

        link = f"https://pay.freekassa.com/?m={self.shop_id}&oa={amount}&currency=RUB&o={order_id}&s={sign}&em={email}"
        logging.debug(f"Ссылка на оплату: {link}")
        
        if requests.get(link).status_code != 200:
            logging.error(f"Ошибка при генерации ссылки на оплату: {link}")
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
            logging.error(f"Неверная подпись: {sign} != {expected_sign}. Данные: {merchant_id}, {amount}, {order_id}")
            
        return status
