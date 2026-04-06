"""
Unit тесты для модуля handlers
"""
import unittest
from unittest.mock import Mock, AsyncMock, patch
from telegram import Update, Message, User, Chat, CallbackQuery
from telegram.ext import ContextTypes
from handlers import add_cancel_button
from utils import get_intensity_keyboard, get_main_menu_keyboard
from telegram import InlineKeyboardMarkup

class TestHandlers(unittest.TestCase):
    """Тесты для функций handlers"""
    
    def test_add_cancel_button_with_keyboard(self):
        """Тест: добавление кнопки отмены к клавиатуре"""
        keyboard = get_intensity_keyboard()
        result = add_cancel_button(keyboard)
        
        self.assertIsInstance(result, InlineKeyboardMarkup)
        self.assertGreater(len(result.inline_keyboard), 0)
        
        # Проверяем, что последняя кнопка - это кнопка отмены
        last_row = result.inline_keyboard[-1]
        self.assertEqual(len(last_row), 1)
        self.assertEqual(last_row[0].callback_data, 'cancel_entry')
        self.assertIn('Отменить', last_row[0].text)
    
    def test_add_cancel_button_preserves_original(self):
        """Тест: оригинальная клавиатура сохраняется при добавлении кнопки"""
        keyboard = get_intensity_keyboard()
        original_length = len(keyboard.inline_keyboard)
        
        result = add_cancel_button(keyboard)
        
        # Новая клавиатура должна содержать все оригинальные кнопки + кнопку отмены
        self.assertEqual(len(result.inline_keyboard), original_length + 1)

if __name__ == '__main__':
    unittest.main()
