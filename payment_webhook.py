import asyncio
from flask import Flask, request, jsonify
from bot.freekassa import FreeKassa
from config.parameters_manager import ParametersManager
from db.database import Database
import logging
from bot.utils.funcs import add_balance_with_notification, error_notify
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
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

asyncio.new_event_loop()

freekassa = FreeKassa(
    shop_id=int(ParametersManager.get_parameter("shop_id")),
    secret_word_1=str(ParametersManager.get_parameter("secret_word_1")),
    secret_word_2=str(ParametersManager.get_parameter("secret_word_2")),
)

bot = Bot(
    token=ParametersManager.get_parameter("bot_token"),
    default=DefaultBotProperties(parse_mode="HTML"),
)


@app.route("/tracking/payment/notification", methods=["POST"])
async def payment_notification():
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

        merchant_id = data.get("MERCHANT_ID")
        amount = data.get("AMOUNT")
        order_id = data.get("MERCHANT_ORDER_ID")
        sign = data.get("SIGN")

        if not all([merchant_id, amount, order_id, sign]):
            logging.error(
                f"Missing required parameters: {merchant_id}, {amount}, {order_id}, {sign}"
            )
            return jsonify({"error": "Missing required parameters"}), 400

        if not freekassa.check_payment_signature(merchant_id, amount, order_id, sign):
            logging.error(f"Invalid signature: {sign}")
            return jsonify({"error": "Invalid signature"}), 400

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
                return jsonify({"error": "Failed to activate tariff"}), 500

            # Отправляем уведомление пользователю
            tariff = db.get_tariff_plan(tariff_id)
            current_tariff = db.get_user_tariff(user_id)
            if current_tariff and current_tariff.tariff_plan_id != tariff_id:
                current_tariff_plan = db.get_tariff_plan(current_tariff.tariff_plan_id)
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
                f"💰 Покупка тарифа!\n\n"
                f"Пользователь: {user_id}\n"
                f"Тариф: {tariff.name}\n"
                f"Сумма: {amount}₽\n"
                f"Действует до: {user_tariff.end_date.strftime('%d.%m.%Y')}",
                f"Пользователь {user_id} купил тариф {tariff.name}",
                user_id,
            )
        else:
            # Обычное пополнение баланса
            user_id = int(order_id.split("_")[0])
            await add_balance_with_notification(user_id, float(amount), bot)

        return "YES", 200

    except Exception as e:
        logging.error(f"Ошибка при обработке уведомления о платеже: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="185.178.44.180", port=22)
