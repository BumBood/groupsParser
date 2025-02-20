from time import sleep
from bot.freekassa import FreeKassa
import logging

from config.parameters_manager import ParametersManager


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("parser.txt")],
)
if __name__ == "__main__":
    freekassa = FreeKassa(
        shop_id=int(ParametersManager.get_parameter("shop_id")),
        api_key=str(ParametersManager.get_parameter("api_kassa")),
    )

    for i in range(1, 30):
        try:
            with open("test.txt", "a", encoding="utf-8") as f:
                f.write(
                    f"ID платежной системы: {i}, URL: {freekassa.create_payment(amount=100, currency='RUB', payment_id=f'test_{i}', email='test@test.com', ip='127.0.0.1', payment_system_id=i)['location']}\n"
                )
            sleep(1)
        except Exception as e:
            print(e)
            sleep(1)
