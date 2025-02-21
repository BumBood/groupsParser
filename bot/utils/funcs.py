from aiogram import Bot


import logging

from db.database import Database

db = Database()


async def notify_admins(bot: Bot, message: str):
    """Отправляет сообщение всем администраторам"""
    admins = db.get_admins()
    for admin in admins:
        try:
            await bot.send_message(admin.user_id, message)
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения админу {admin.user_id}: {e}")


async def add_balance_with_notification(user_id: int, amount: int, bot: Bot):
    db.update_balance(user_id, amount)
    db.make_payment(user_id, amount)
    
    logging.info(f"Пользователь {user_id} пополнил баланс на {amount}")
    
    user = db.get_user(user_id)

    admin_text = ("💰 Пополнили баланс!\n\n"
                f"Юзернейм: {user.username}\n"
                f"Сумма пополнения: {amount}₽\n"
                f"ID: <code>{user_id}</code>\n"
                f"Пришел по метке: {user.referrer_code}")

    await notify_admins(bot, admin_text)
    await bot.send_message(user_id, f"Баланс пополнен на {amount} ₽")


def format_user_mention(user_id: int, username: str = None) -> str:
    if username:
        return f"@{username}"
    return f"<code>{user_id}</code>"
