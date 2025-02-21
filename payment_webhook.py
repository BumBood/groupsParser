from flask import Flask, request, jsonify
from bot.freekassa import FreeKassa
from config.parameters_manager import ParametersManager
from db.database import Database
import logging
from bot.utils.funcs import add_balance_with_notification
from aiogram import Bot

app = Flask(__name__)
db = Database()

freekassa = FreeKassa(
    shop_id=int(ParametersManager.get_parameter("shop_id")),
    secret_word_1=str(ParametersManager.get_parameter("secret_word_1")),
    secret_word_2=str(ParametersManager.get_parameter("secret_word_2")),
)

bot = Bot(token=ParametersManager.get_parameter("bot_token"))


@app.route("/payment/notification", methods=["POST"])
async def payment_notification():
    try:
        merchant_id = request.form.get("MERCHANT_ID")
        amount = request.form.get("AMOUNT")
        order_id = request.form.get("MERCHANT_ORDER_ID")
        sign = request.form.get("SIGN")

        if not all([merchant_id, amount, order_id, sign]):
            logging.error(f"Missing required parameters: {merchant_id}, {amount}, {order_id}, {sign}")
            return jsonify({"error": "Missing required parameters"}), 400

        if not freekassa.check_payment_signature(merchant_id, amount, order_id, sign):
            logging.error(f"Invalid signature: {sign}")
            return jsonify({"error": "Invalid signature"}), 400

        user_id = int(order_id.split("_")[0])
        await add_balance_with_notification(user_id, float(amount), bot)

        return "YES", 200

    except Exception as e:
        logging.error(f"Ошибка при обработке уведомления о платеже: {e}")
        
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="185.178.44.180", port=80)
