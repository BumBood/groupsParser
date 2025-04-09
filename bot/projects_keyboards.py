from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List
from db.models import Project, ProjectChat


def main_projects_keyboard() -> InlineKeyboardMarkup:
    """Основная клавиатура для раздела проектов"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Мои проекты", callback_data="projects_list"
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Создать проект", callback_data="create_project"
                )
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")],
        ]
    )


def projects_list_keyboard(projects: List[Project]) -> InlineKeyboardMarkup:
    """Клавиатура со списком проектов пользователя"""
    keyboard = []

    # Добавляем кнопки для каждого проекта
    for project in projects:
        status_emoji = "🟢" if project.is_active else "🔴"
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{status_emoji} {project.name}",
                    callback_data=f"project|{project.id}",
                )
            ]
        )

    # Добавляем кнопки навигации
    keyboard.append(
        [
            InlineKeyboardButton(text="➕ Создать", callback_data="create_project"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="projects_menu"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def project_manage_keyboard(project: Project) -> InlineKeyboardMarkup:
    """Клавиатура для управления конкретным проектом"""
    status_text = "🔴 Остановить" if project.is_active else "🟢 Запустить"
    status_callback = f"toggle_project|{project.id}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=status_text, callback_data=status_callback)],
            [
                InlineKeyboardButton(
                    text="📋 Чаты проекта", callback_data=f"project_chats|{project.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Добавить чат", callback_data=f"add_chat|{project.id}"
                ),
                InlineKeyboardButton(
                    text="➕➕ Добавить несколько",
                    callback_data=f"add_multiple_chats|{project.id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗑️ Удалить проект",
                    callback_data=f"delete_project|{project.id}",
                ),
                InlineKeyboardButton(
                    text="✏️ Редактировать", callback_data=f"edit_project|{project.id}"
                ),
            ],
            [InlineKeyboardButton(text="🔙 К проектам", callback_data="projects_list")],
        ]
    )


def chats_list_keyboard(
    chats: List[ProjectChat], project_id: int
) -> InlineKeyboardMarkup:
    """Клавиатура со списком чатов проекта"""
    keyboard = []

    # Добавляем кнопки для каждого чата
    for chat in chats:
        status_emoji = "🟢" if chat.is_active else "🔴"
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{status_emoji} {chat.chat_title or chat.chat_id}",
                    callback_data=f"chat|{chat.id}",
                )
            ]
        )

    # Добавляем кнопки навигации
    keyboard.append(
        [
            InlineKeyboardButton(
                text="➕ Добавить", callback_data=f"add_chat|{project_id}"
            ),
            InlineKeyboardButton(
                text="➕➕ Добавить несколько",
                callback_data=f"add_multiple_chats|{project_id}",
            ),
        ]
    )
    keyboard.append(
        [
            InlineKeyboardButton(
                text="🔙 Назад", callback_data=f"project|{project_id}"
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def chat_manage_keyboard(chat: ProjectChat) -> InlineKeyboardMarkup:
    """Клавиатура для управления конкретным чатом"""
    status_text = "🔴 Остановить" if chat.is_active else "🟢 Запустить"
    status_callback = f"toggle_chat|{chat.id}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔑 Ключевые слова", callback_data=f"chat_keywords|{chat.id}"
                )
            ],
            [InlineKeyboardButton(text=status_text, callback_data=status_callback)],
            [
                InlineKeyboardButton(
                    text="🗑️ Удалить чат", callback_data=f"delete_chat|{chat.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 К чатам", callback_data=f"project_chats|{chat.project_id}"
                )
            ],
        ]
    )


def cancel_keyboard(callback_data: str = "projects_menu") -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой отмены"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data=callback_data)],
        ]
    )


def confirm_keyboard(
    confirm_callback: str, cancel_callback: str
) -> InlineKeyboardMarkup:
    """Клавиатура с подтверждением действия"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить", callback_data=confirm_callback
                ),
                InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_callback),
            ],
        ]
    )


def parse_history_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для парсинга истории сообщений"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📥 Начать парсинг", callback_data="start_parse_history"
                )
            ],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="projects_menu")],
        ]
    )
