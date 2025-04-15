import asyncio
from flask import Flask, request, jsonify
from bot.payment_systems import PaymentSystems
from config.parameters_manager import ParametersManager
from db.database import Database
import logging
import json

app = Flask(__name__)
db = Database()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("payment_webhook.log")],
)
logger = logging.getLogger(__name__)

# Создаем новый цикл событий для асинхронных операций
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Инициализация платежных систем
payment_systems = PaymentSystems()


@app.route("/tracking/payment/notification", methods=["POST"])
def payment_notification():
    """
    Обработчик уведомлений о платежах от FreeKassa
    """
    try:
        logging.info(f"Content-Type: {request.content_type}")
        logging.info(f"Form данные: {request.form}")

        # Получаем и парсим данные
        if request.is_json:
            data = request.get_json()
        else:
            # Получаем первый ключ из form-data, который содержит JSON строку
            json_str = next(iter(request.form))
            data = json.loads(json_str)
            logging.info(f"Распарсенные данные: {data}")

        # Обрабатываем платеж через централизованную систему
        async def process_payment():
            success = await payment_systems.process_freekassa_webhook(data)
            return success

        success = loop.run_until_complete(process_payment())

        if success:
            return "YES", 200
        else:
            return jsonify({"error": "Failed to process payment"}), 500

    except Exception as e:
        logging.error(f"Ошибка при обработке уведомления о платеже: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6500)
