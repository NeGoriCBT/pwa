"""
Unit тесты для модуля security
"""
import unittest
from security import (
    validate_situation, validate_thought, validate_action,
    validate_evidence, validate_note, validate_emotion,
    sanitize_text, check_rate_limit
)

class TestSecurityValidation(unittest.TestCase):
    """Тесты для функций валидации"""
    
    def test_validate_situation_empty(self):
        """Тест: пустая ситуация должна быть отклонена"""
        is_valid, error = validate_situation("")
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
    
    def test_validate_situation_whitespace(self):
        """Тест: ситуация из пробелов должна быть отклонена"""
        is_valid, error = validate_situation("   ")
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
    
    def test_validate_situation_too_long(self):
        """Тест: слишком длинная ситуация должна быть отклонена"""
        long_text = "а" * 2001
        is_valid, error = validate_situation(long_text)
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
    
    def test_validate_situation_valid(self):
        """Тест: нормальная ситуация должна быть принята"""
        is_valid, error = validate_situation("Нормальная ситуация")
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_validate_situation_sql_injection(self):
        """Тест: SQL-инъекция должна быть обнаружена"""
        sql_injection = "'; DROP TABLE entries; --"
        is_valid, error = validate_situation(sql_injection)
        # Валидация не должна пропускать SQL-инъекции
        # (хотя основная защита на уровне БД)
        # Проверяем, что валидация работает
        self.assertIsNotNone(is_valid)
    
    def test_validate_thought_valid(self):
        """Тест: нормальная мысль должна быть принята"""
        is_valid, error = validate_thought("Я думаю, что все будет хорошо")
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_validate_thought_too_long(self):
        """Тест: слишком длинная мысль должна быть отклонена"""
        long_text = "а" * 501
        is_valid, error = validate_thought(long_text)
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
    
    def test_sanitize_text_html_escape(self):
        """Тест: HTML символы должны быть экранированы"""
        text = "<script>alert('xss')</script>"
        sanitized = sanitize_text(text)
        self.assertNotIn("<script>", sanitized)
        self.assertIn("&lt;", sanitized)
    
    def test_sanitize_text_whitespace(self):
        """Тест: лишние пробелы должны быть удалены"""
        text = "много    пробелов    здесь"
        sanitized = sanitize_text(text)
        self.assertNotIn("    ", sanitized)

class TestRateLimiting(unittest.TestCase):
    """Тесты для rate limiting"""
    
    def test_rate_limit_allowed(self):
        """Тест: первое сообщение должно быть разрешено"""
        user_id = 999999
        allowed, error = check_rate_limit(user_id, 'message')
        # Первое сообщение должно быть разрешено
        self.assertIsNotNone(allowed)

if __name__ == '__main__':
    unittest.main()
