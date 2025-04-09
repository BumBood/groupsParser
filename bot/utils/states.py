from aiogram.fsm.state import State, StatesGroup


class ProjectStates(StatesGroup):
    """Состояния для работы с проектами"""

    # Создание проекта
    create_name = State()
    create_description = State()

    # Редактирование проекта
    edit_name = State()
    edit_description = State()

    # Удаление проекта
    delete_confirm = State()


class ChatStates(StatesGroup):
    """Состояния для работы с чатами проекта"""

    # Добавление чата
    add_chat_id = State()
    add_chat_title = State()
    add_keywords = State()

    # Добавление нескольких чатов
    add_multiple_chats = State()
    add_multiple_keywords = State()

    # Редактирование ключевых слов
    edit_keywords = State()

    # Удаление чата
    delete_confirm = State()


class HistoryParseStates(StatesGroup):
    """Состояния для парсинга истории сообщений"""

    # Ввод информации о чате
    enter_chat_id = State()
    enter_limit = State()
    enter_keywords = State()

    # Процесс парсинга
    parsing = State()


class AdminStates(StatesGroup):
    """Состояния для работы в админ-панели"""

    # Состояния для создания тарифа
    waiting_tariff_name = State()
    waiting_tariff_price = State()
    waiting_tariff_projects = State()
    waiting_tariff_chats = State()

    # Состояния для удаления тарифа
    waiting_tariff_id_for_delete = State()

    # Состояния для редактирования тарифа
    waiting_tariff_id_for_edit = State()
    waiting_tariff_edit_option = State()
    waiting_tariff_new_name = State()
    waiting_tariff_new_price = State()
    waiting_tariff_new_projects = State()
    waiting_tariff_new_chats = State()

    # Состояния для назначения тарифа пользователю
    waiting_user_id = State()
    waiting_tariff_id = State()
