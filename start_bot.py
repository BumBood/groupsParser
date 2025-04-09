import asyncio
from instanceBot import InstanceTelegramBot

if __name__ == "__main__":
    from config.parameters_manager import ParametersManager

    bot = InstanceTelegramBot(ParametersManager.get_parameter("bot_token"))
    asyncio.run(bot.start())
