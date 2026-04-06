"""
Unit тесты для модуля utils
"""
import unittest
from utils import (
    get_main_menu_keyboard,
    get_emotions_keyboard,
    get_intensity_keyboard,
    format_entry_summary,
    check_success
)
from telegram import InlineKeyboardMarkup

class TestUtils(unittest.TestCase):
    """Тесты для функций utils"""
    
    def test_get_main_menu_keyboard(self):
        """Тест: создание главного меню"""
        keyboard = get_main_menu_keyboard()
        self.assertIsInstance(keyboard, InlineKeyboardMarkup)
        self.assertGreater(len(keyboard.inline_keyboard), 0)
    
    def test_get_emotions_keyboard(self):
        """Тест: создание клавиатуры эмоций"""
        keyboard = get_emotions_keyboard()
        self.assertIsInstance(keyboard, InlineKeyboardMarkup)
        self.assertGreater(len(keyboard.inline_keyboard), 0)
    
    def test_get_intensity_keyboard(self):
        """Тест: создание клавиатуры интенсивности"""
        keyboard = get_intensity_keyboard()
        self.assertIsInstance(keyboard, InlineKeyboardMarkup)
        # Должно быть 11 кнопок (0, 10, 20, ..., 100)
        total_buttons = sum(len(row) for row in keyboard.inline_keyboard)
        self.assertGreaterEqual(total_buttons, 10)
    
    def test_format_entry_summary(self):
        """Тест: форматирование сводки записи"""
        entry_data = {
            'situation': 'Тестовая ситуация',
            'emotions_before': [{'emotion': 'тревога', 'intensity': 80}],
            'automatic_thought': 'Тестовая мысль',
            'automatic_thought_confidence': 70,
            'action': 'Тестовое действие',
            'evidence_for': 'Доводы за',
            'evidence_against': 'Доводы против',
            'alternative_thoughts': [],
            'emotions_after': [{'emotion': 'тревога', 'intensity': 50}],
            'note_to_future_self': 'Заметка'
        }
        
        result = format_entry_summary(entry_data)
        self.assertIsInstance(result, str)
        self.assertIn('Тестовая ситуация', result)
        self.assertIn('Тестовая мысль', result)
    
    def test_check_success_with_reduction(self):
        """Тест: проверка успешности записи при снижении эмоций"""
        entry_data = {
            'emotions_before': [{'emotion': 'тревога', 'intensity': 90}],
            'emotions_after': [{'emotion': 'тревога', 'intensity': 50}]  # Снижение на 40%
        }
        
        result = check_success(entry_data)
        self.assertTrue(result)
    
    def test_check_success_with_positive_emotion(self):
        """Тест: проверка успешности записи при появлении позитивной эмоции"""
        entry_data = {
            'emotions_before': [{'emotion': 'тревога', 'intensity': 80}],
            'emotions_after': [
                {'emotion': 'тревога', 'intensity': 70},
                {'emotion': 'радость', 'intensity': 50}
            ]
        }
        
        result = check_success(entry_data)
        self.assertTrue(result)
    
    def test_check_success_no_success(self):
        """Тест: проверка неуспешной записи"""
        entry_data = {
            'emotions_before': [{'emotion': 'тревога', 'intensity': 80}],
            'emotions_after': [{'emotion': 'тревога', 'intensity': 75}]  # Снижение только на 5%
        }
        
        result = check_success(entry_data)
        self.assertFalse(result)

if __name__ == '__main__':
    unittest.main()
