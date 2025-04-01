import asyncio
from instanceBot import InstanceTelegramBot
from dotenv import load_dotenv
import os

if __name__ == "__main__":
    load_dotenv() 
    bot = InstanceTelegramBot(os.getenv("BOT_TOKEN"))
    asyncio.run(bot.start())