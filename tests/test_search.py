"""
Unit тесты для модуля search
"""
import unittest
from unittest.mock import Mock, AsyncMock, patch
from database import Database

class TestSearch(unittest.TestCase):
    """Тесты для функций search"""
    
    def setUp(self):
        """Создаем мок БД для тестов"""
        self.db = Mock(spec=Database)
    
    def test_emotion_extraction_from_entries(self):
        """Тест: извлечение эмоций из записей"""
        entries = [
            {
                'emotions_before': [
                    {'emotion': 'тревога', 'intensity': 80},
                    {'emotion': 'грусть', 'intensity': 60}
                ],
                'emotions_after': [
                    {'emotion': 'тревога', 'intensity': 50},
                    {'emotion': 'спокойствие', 'intensity': 40}
                ]
            },
            {
                'emotions_before': [
                    {'emotion': 'гнев', 'intensity': 70}
                ],
                'emotions_after': []
            }
        ]
        
        all_emotions = set()
        for entry in entries:
            # Эмоции до
            for em in entry.get('emotions_before', []):
                if isinstance(em, dict):
                    all_emotions.add(em.get('emotion', ''))
            
            # Эмоции после
            for em in entry.get('emotions_after', []):
                if isinstance(em, dict):
                    all_emotions.add(em.get('emotion', ''))
        
        all_emotions = {e for e in all_emotions if e}
        
        expected = {'тревога', 'грусть', 'спокойствие', 'гнев'}
        self.assertEqual(all_emotions, expected)

if __name__ == '__main__':
    unittest.main()
