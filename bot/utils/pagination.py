from typing import List, TypeVar, Callable
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

T = TypeVar('T')

class Paginator:
    """
    Универсальный класс для создания пагинации
    """
    def __init__(
        self,
        items: List[T],
        items_per_page: int,
        callback_prefix: str,
        item_callback: Callable[[T], tuple[str, str]],
    ):
        """
        Args:
            items: Список элементов для пагинации
            items_per_page: Количество элементов на странице
            callback_prefix: Префикс для callback_data
            item_callback: Функция, возвращающая (текст, callback_data) для каждого элемента
        """
        self.items = items
        self.items_per_page = items_per_page
        self.callback_prefix = callback_prefix
        self.item_callback = item_callback
        self.total_pages = (len(items) + items_per_page - 1) // items_per_page

    def get_page_keyboard(self, page: int) -> InlineKeyboardMarkup:
        """Создает клавиатуру для указанной страницы"""
        keyboard = []
        
        # Добавляем элементы текущей страницы
        start_idx = page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.items))
        
        for item in self.items[start_idx:end_idx]:
            text, callback = self.item_callback(item)
            keyboard.append([InlineKeyboardButton(text=text, callback_data=callback)])

        # Добавляем навигационные кнопки
        nav_buttons = []
        
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="◀️", callback_data=f"{self.callback_prefix}_page_{page-1}"
                )
            )
            
        if self.total_pages > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text=f"{page + 1}/{self.total_pages}",
                    callback_data="ignore"
                )
            )
            
        if page < self.total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="▶️", callback_data=f"{self.callback_prefix}_page_{page+1}"
                )
            )

        if nav_buttons:
            keyboard.append(nav_buttons)

        # Добавляем кнопку "Назад"
        keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)