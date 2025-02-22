import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
from bot.utils.funcs import notify_admins
from bot.start import router as start_router
from bot.parse_post import router as post_router
from config.parameters_manager import ParametersManager
from bot.admin import router as admin_router
from bot.balance import router as balance_router


class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
        self.dp = Dispatcher()
        self._setup_logging()
        self._include_routers()

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")],
        )
        self.logger = logging.getLogger(__name__)

    def _include_routers(self):
        """Подключает все роутеры к диспетчеру"""
        self.dp.include_router(start_router)
        self.dp.include_router(post_router)
        self.dp.include_router(admin_router)
        self.dp.include_router(balance_router)
        self.logger.info("Роутеры успешно подключены")

    async def start(self):
        """Запускает бота"""
        try:
            self.logger.info("Бот запускается...")
            # Загружаем параметры
            ParametersManager._load_config()
            self.logger.info("Параметры загружены")
            # Запускаем бота
            await notify_admins(self.bot, "Бот запущен")
            await self.dp.start_polling(self.bot)
        except Exception as e:
            self.logger.error(f"Ошибка при запуске бота: {e}")
            raise
        finally:
            await notify_admins(self.bot, "Бот выключен")
            await self.bot.session.close()


if __name__ == "__main__":
    load_dotenv()  # загружаем переменные из .env
    bot = TelegramBot(ParametersManager.get_parameter("bot_token"))
    asyncio.run(bot.start())
