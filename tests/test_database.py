"""
Unit тесты для модуля database
"""
import unittest
import os
import tempfile
from database import Database

class TestDatabase(unittest.TestCase):
    """Тесты для функций базы данных"""
    
    def setUp(self):
        """Создаем временную БД для тестов"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db = Database(db_name=self.temp_db.name)
    
    def tearDown(self):
        """Удаляем временную БД"""
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)
    
    def test_save_and_get_entry(self):
        """Тест: сохранение и получение записи"""
        user_id = 12345
        entry_data = {
            'situation': 'Тестовая ситуация',
            'emotions_before': [],
            'automatic_thought': 'Тестовая мысль',
            'automatic_thought_confidence': 80,
            'action': 'Тестовое действие',
            'evidence_for': 'Доводы за',
            'evidence_against': 'Доводы против',
            'alternative_thoughts': [],
            'emotions_after': [],
            'note_to_future_self': 'Тестовая заметка'
        }
        
        # Сохраняем запись
        entry_id = self.db.save_entry(user_id, entry_data)
        self.assertIsNotNone(entry_id)
        self.assertGreater(entry_id, 0)
        
        # Получаем записи
        entries = self.db.get_user_entries(user_id)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['id'], entry_id)
        self.assertEqual(entries[0]['situation'], 'Тестовая ситуация')
    
    def test_get_user_entries_empty(self):
        """Тест: получение записей несуществующего пользователя"""
        entries = self.db.get_user_entries(99999)
        self.assertEqual(len(entries), 0)
    
    def test_sql_injection_protection(self):
        """Тест: защита от SQL-инъекций"""
        user_id = 12345
        malicious_input = "'; DROP TABLE entries; --"
        
        entry_data = {
            'situation': malicious_input,
            'emotions_before': [],
            'automatic_thought': malicious_input,
            'automatic_thought_confidence': 50,
            'action': '',
            'evidence_for': '',
            'evidence_against': '',
            'alternative_thoughts': [],
            'emotions_after': [],
            'note_to_future_self': ''
        }
        
        # Пытаемся сохранить с SQL-инъекцией
        entry_id = self.db.save_entry(user_id, entry_data)
        self.assertIsNotNone(entry_id)
        
        # Проверяем, что таблица все еще существует
        entries = self.db.get_user_entries(user_id)
        self.assertGreaterEqual(len(entries), 1)
        
        # Проверяем, что данные сохранились (не выполнилась инъекция)
        self.assertEqual(entries[0]['situation'], malicious_input)

if __name__ == '__main__':
    unittest.main()
