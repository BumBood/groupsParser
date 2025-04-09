from aiogram import Router

from .menu import router as menu_router
from .sessions import router as sessions_router
from .users import router as users_router
from .parameters import router as parameters_router
from .broadcast import router as broadcast_router
from .statistics import router as statistics_router
from .system import router as system_router
from .transfer import router as transfer_router
from .tariffs import router as tariffs_router

router = Router(name="admin")

# Подключаем все роутеры к основному роутеру админки
router.include_router(menu_router)
router.include_router(sessions_router)
router.include_router(users_router)
router.include_router(parameters_router)
router.include_router(broadcast_router)
router.include_router(statistics_router)
router.include_router(system_router)
router.include_router(transfer_router)
router.include_router(tariffs_router)
