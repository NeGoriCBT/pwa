"""
Модуль для маскирования чувствительных данных в логах
"""
import re

def mask_sensitive_text(text: str, max_visible: int = 10) -> str:
    """
    Маскирует чувствительный текст, оставляя только первые и последние символы
    
    Args:
        text: Текст для маскирования
        max_visible: Максимальное количество видимых символов с каждой стороны
    
    Returns:
        Замаскированный текст
    """
    if not text or len(text) <= max_visible * 2:
        # Если текст короткий, маскируем полностью
        return '*' * min(len(text), 20)
    
    if len(text) <= max_visible * 2 + 10:
        # Для средних текстов показываем начало и конец
        visible_start = text[:max_visible]
        visible_end = text[-max_visible:]
        masked = '*' * (len(text) - max_visible * 2)
        return f"{visible_start}{masked}{visible_end}"
    
    # Для длинных текстов показываем только начало и конец
    visible_start = text[:max_visible]
    visible_end = text[-max_visible:]
    masked_length = min(20, len(text) - max_visible * 2)
    return f"{visible_start}{'*' * masked_length}...{visible_end}"

def mask_user_data_in_log(message: str) -> str:
    """
    Маскирует чувствительные данные пользователя в логах
    
    Ищет паттерны типа:
    - "Текст: ..."
    - "Ситуация: ..."
    - "Мысль: ..."
    - И другие поля с данными пользователя
    """
    # Паттерны для поиска чувствительных данных
    patterns = [
        (r'(Текст|Ситуация|Мысль|Действие|Доводы|Заметка|situation|thought|action|evidence|note)[:=]\s*([^\n]{50,})', 
         lambda m: f"{m.group(1)}: {mask_sensitive_text(m.group(2))}"),
        (r'(text|details|description)[:=]\s*([^\n]{50,})',
         lambda m: f"{m.group(1)}: {mask_sensitive_text(m.group(2))}"),
    ]
    
    masked_message = message
    for pattern, replacement in patterns:
        masked_message = re.sub(pattern, replacement, masked_message, flags=re.IGNORECASE)
    
    return masked_message
