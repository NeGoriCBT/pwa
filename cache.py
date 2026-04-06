"""
Модуль для кэширования часто используемых данных
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from functools import wraps

logger = logging.getLogger(__name__)

# Простой in-memory кэш
_cache: Dict[str, Dict[str, Any]] = {}

def get_cache_key(prefix: str, *args, **kwargs) -> str:
    """Генерирует ключ кэша"""
    key_parts = [prefix]
    key_parts.extend(str(arg) for arg in args)
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    return ":".join(key_parts)

def get_cached(key: str, ttl: int = 300) -> Optional[Any]:
    """
    Получает значение из кэша
    
    Args:
        key: Ключ кэша
        ttl: Время жизни кэша в секундах (по умолчанию 5 минут)
    
    Returns:
        Значение из кэша или None, если истек срок или нет в кэше
    """
    if key not in _cache:
        return None
    
    cached_item = _cache[key]
    cached_time = cached_item.get('timestamp')
    
    if cached_time:
        age = (datetime.now() - cached_time).total_seconds()
        if age > ttl:
            # Кэш истек
            del _cache[key]
            return None
    
    return cached_item.get('value')

def set_cached(key: str, value: Any, ttl: int = 300) -> None:
    """
    Сохраняет значение в кэш
    
    Args:
        key: Ключ кэша
        value: Значение для кэширования
        ttl: Время жизни кэша в секундах (по умолчанию 5 минут)
    """
    _cache[key] = {
        'value': value,
        'timestamp': datetime.now(),
        'ttl': ttl
    }

def delete_key(key: str) -> bool:
    """Удаляет конкретный ключ из кэша. Возвращает True если ключ был удалён."""
    if key in _cache:
        del _cache[key]
        return True
    return False


def clear_cache(pattern: Optional[str] = None) -> int:
    """
    Очищает кэш
    
    Args:
        pattern: Если указан, очищает только ключи, начинающиеся с pattern
    
    Returns:
        Количество удаленных записей
    """
    if pattern:
        keys_to_delete = [k for k in _cache.keys() if k.startswith(pattern)]
        for key in keys_to_delete:
            del _cache[key]
        return len(keys_to_delete)
    else:
        count = len(_cache)
        _cache.clear()
        return count

def cached(ttl: int = 300):
    """
    Декоратор для кэширования результатов функции
    
    Args:
        ttl: Время жизни кэша в секундах
    
    Usage:
        @cached(ttl=600)
        def get_user_emotions(user_id: int):
            # ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Генерируем ключ кэша на основе имени функции и аргументов
            cache_key = get_cache_key(func.__name__, *args, **kwargs)
            
            # Пытаемся получить из кэша
            cached_value = get_cached(cache_key, ttl)
            if cached_value is not None:
                logger.debug(f"Кэш попадание для {func.__name__}")
                return cached_value
            
            # Выполняем функцию
            result = func(*args, **kwargs)
            
            # Сохраняем в кэш
            set_cached(cache_key, result, ttl)
            logger.debug(f"Кэш сохранен для {func.__name__}")
            
            return result
        return wrapper
    return decorator

def get_cache_stats() -> Dict[str, Any]:
    """Возвращает статистику кэша"""
    now = datetime.now()
    expired_count = 0
    valid_count = 0
    
    for key, item in _cache.items():
        cached_time = item.get('timestamp')
        if cached_time:
            age = (now - cached_time).total_seconds()
            ttl = item.get('ttl', 300)
            if age > ttl:
                expired_count += 1
            else:
                valid_count += 1
    
    return {
        'total_keys': len(_cache),
        'valid_keys': valid_count,
        'expired_keys': expired_count
    }
