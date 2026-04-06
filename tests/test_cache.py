"""
Unit тесты для модуля cache
"""
import unittest
import time
from cache import get_cached, set_cached, clear_cache, get_cache_stats

class TestCache(unittest.TestCase):
    """Тесты для функций кэширования"""
    
    def setUp(self):
        """Очищаем кэш перед каждым тестом"""
        clear_cache()
    
    def test_set_and_get_cache(self):
        """Тест: сохранение и получение из кэша"""
        set_cached('test_key', 'test_value', ttl=60)
        value = get_cached('test_key', ttl=60)
        self.assertEqual(value, 'test_value')
    
    def test_cache_expiration(self):
        """Тест: истечение срока кэша"""
        set_cached('test_key', 'test_value', ttl=1)
        time.sleep(2)  # Ждем истечения TTL
        value = get_cached('test_key', ttl=1)
        self.assertIsNone(value)
    
    def test_cache_clear(self):
        """Тест: очистка кэша"""
        set_cached('test_key', 'test_value')
        clear_cache()
        value = get_cached('test_key')
        self.assertIsNone(value)
    
    def test_cache_stats(self):
        """Тест: статистика кэша"""
        set_cached('key1', 'value1', ttl=60)
        set_cached('key2', 'value2', ttl=60)
        stats = get_cache_stats()
        self.assertEqual(stats['total_keys'], 2)
        self.assertEqual(stats['valid_keys'], 2)

if __name__ == '__main__':
    unittest.main()
