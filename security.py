"""
Модуль безопасности для бота
Включает валидацию, rate limiting, санитизацию данных
"""
import re
import html
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict
from database import Database

db = Database()
logger = logging.getLogger(__name__)

# Лимиты для валидации
MAX_SITUATION_LENGTH = 2000
MAX_THOUGHT_LENGTH = 500
MAX_ACTION_LENGTH = 1000
MAX_EVIDENCE_LENGTH = 1500
MAX_NOTE_LENGTH = 1000
MAX_EMOTION_LENGTH = 50

# Rate limiting настройки
RATE_LIMITS = {
    'message': {'max': 30, 'window': 60},  # 30 сообщений в минуту
    'command': {'max': 10, 'window': 60},  # 10 команд в минуту
    'entry_creation': {'max': 5, 'window': 300},  # 5 записей в 5 минут
    'download': {'max': 3, 'window': 300},  # 3 скачивания в 5 минут
    'delete': {'max': 2, 'window': 600},  # 2 удаления в 10 минут
}

# Таймауты сессий (в секундах)
SESSION_TIMEOUT = 3600  # 1 час


def validate_text(text: str, max_length: int, field_name: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует текст
    Возвращает (is_valid, error_message)
    """
    if not text or not text.strip():
        return False, f"{field_name} не может быть пустым"
    
    if len(text) > max_length:
        return False, f"{field_name} слишком длинный (максимум {max_length} символов)"
    
    # Проверка на потенциально вредоносный контент (базовая)
    if len(text) > 100 and text.count('http') > 5:
        return False, f"{field_name} содержит слишком много ссылок"
    
    return True, None


def sanitize_text(text: str) -> str:
    """
    Санитизирует текст для безопасного отображения
    """
    # Удаляем лишние пробелы
    text = ' '.join(text.split())
    
    # Экранируем HTML символы (для безопасности)
    text = html.escape(text)
    
    # Ограничиваем длину
    if len(text) > 5000:
        text = text[:5000] + "..."
    
    return text


def validate_situation(text: str) -> Tuple[bool, Optional[str]]:
    """Валидация ситуации"""
    return validate_text(text, MAX_SITUATION_LENGTH, "Ситуация")


def validate_thought(text: str) -> Tuple[bool, Optional[str]]:
    """Валидация автоматической мысли"""
    return validate_text(text, MAX_THOUGHT_LENGTH, "Автоматическая мысль")


def validate_action(text: str) -> Tuple[bool, Optional[str]]:
    """Валидация действия"""
    return validate_text(text, MAX_ACTION_LENGTH, "Действие")


def validate_evidence(text: str) -> Tuple[bool, Optional[str]]:
    """Валидация доводов"""
    return validate_text(text, MAX_EVIDENCE_LENGTH, "Доводы")


def validate_note(text: str) -> Tuple[bool, Optional[str]]:
    """Валидация заметки"""
    return validate_text(text, MAX_NOTE_LENGTH, "Заметка")


def validate_emotion(text: str) -> Tuple[bool, Optional[str]]:
    """Валидация эмоции"""
    return validate_text(text, MAX_EMOTION_LENGTH, "Эмоция")


def validate_password(password: str) -> Tuple[bool, Optional[str]]:
    """Валидация пароля: минимум 4, максимум 100 символов"""
    if not password or not password.strip():
        return False, "Пароль не может быть пустым"
    p = password.strip()
    if len(p) < 4:
        return False, "Пароль должен быть не менее 4 символов"
    if len(p) > 100:
        return False, "Пароль должен быть не более 100 символов"
    return True, None


def validate_exposure_situation(text: str) -> Tuple[bool, Optional[str]]:
    """Валидация названия ситуации в дневнике экспозиций"""
    return validate_text(text, MAX_SITUATION_LENGTH, "Название ситуации")


def validate_exposure_expectation(text: str) -> Tuple[bool, Optional[str]]:
    """Валидация ожидания/страха в экспозиции"""
    return validate_text(text, MAX_EVIDENCE_LENGTH, "Ожидание")


def validate_exposure_reality_description(text: str) -> Tuple[bool, Optional[str]]:
    """Валидация описания реальности"""
    return validate_text(text, MAX_EVIDENCE_LENGTH, "Описание реальности")


def validate_exposure_summary(text: str) -> Tuple[bool, Optional[str]]:
    """Валидация итогового резюме экспозиции"""
    return validate_text(text, MAX_NOTE_LENGTH, "Итоговое резюме")


def validate_search_query(text: str) -> Tuple[bool, Optional[str]]:
    """Валидация поискового запроса"""
    return validate_text(text, 500, "Поисковый запрос")


def validate_intensity(intensity: int) -> Tuple[bool, Optional[str]]:
    """Валидация интенсивности"""
    if not isinstance(intensity, int):
        return False, "Интенсивность должна быть числом"
    
    if intensity < 0 or intensity > 100:
        return False, "Интенсивность должна быть от 0 до 100"
    
    return True, None


def check_rate_limit(user_id: int, action_type: str) -> Tuple[bool, Optional[str]]:
    """
    Проверяет rate limit для пользователя
    Возвращает (is_allowed, error_message)
    """
    if action_type not in RATE_LIMITS:
        return True, None
    
    limit_config = RATE_LIMITS[action_type]
    max_actions = limit_config['max']
    window_seconds = limit_config['window']
    
    if not db.check_rate_limit(user_id, action_type, max_actions, window_seconds):
        # Превышение rate limit - подозрительная активность
        db.log_suspicious_activity(
            user_id, 
            f'rate_limit_exceeded_{action_type}',
            f'Превышен rate limit: {max_actions} действий за {window_seconds} секунд'
        )
        return False, f"Слишком много запросов. Попробуйте через {window_seconds // 60} минут."
    
    # Логируем действие
    db.log_rate_limit(user_id, action_type)
    
    return True, None


def check_user_consent(user_id: int) -> bool:
    """Проверяет, дал ли пользователь согласие"""
    return db.check_user_consent(user_id)


def save_user_consent(user_id: int, consent_given: bool, ip_address: Optional[str] = None):
    """Сохраняет согласие пользователя"""
    db.save_user_consent(user_id, consent_given, ip_address)


def has_user_password(user_id: int) -> bool:
    """Проверяет, установлен ли пароль у пользователя"""
    return db.has_user_password(user_id)


def is_password_verification_enabled(user_id: int) -> bool:
    """Проверяет, включена ли проверка пароля (пароль есть и не отключён)"""
    return db.is_password_verification_enabled(user_id)


def hash_password(user_id: int, password: str) -> str:
    """Хеширует пароль для хранения"""
    import hashlib
    salt = str(user_id).encode()
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000).hex()


def save_user_password(user_id: int, password: str):
    """Сохраняет пароль пользователя (хешированный)"""
    password_hash = hash_password(user_id, password)
    db.save_user_password_hash(user_id, password_hash)


def check_user_password(user_id: int, password: str) -> bool:
    """Проверяет пароль пользователя"""
    return db.check_user_password(user_id, password)


def check_session_timeout(user_id: int) -> bool:
    """
    Проверяет, не истекла ли сессия пользователя
    Возвращает True если сессия активна
    """
    state_info = db.get_user_state(user_id)
    if not state_info:
        return True  # Нет активной сессии
    
    # Если есть состояние, проверяем его актуальность
    # (в данном случае просто возвращаем True, так как состояния очищаются при завершении)
    return True


def cleanup_old_data():
    """Очищает старые данные (вызывать периодически)"""
    db.cleanup_old_rate_limits(days=1)


def validate_date(date_str: str) -> Tuple[bool, Optional[str], Optional[datetime]]:
    """
    Валидирует дату
    Возвращает (is_valid, error_message, datetime_object)
    """
    try:
        date_obj = datetime.fromisoformat(date_str)
        now = datetime.now()
        
        # Не допускаем будущие даты для записей
        if date_obj > now:
            return False, "Дата не может быть в будущем", None
        
        # Не допускаем слишком старые даты (больше 10 лет назад)
        if date_obj < now - timedelta(days=3650):
            return False, "Дата слишком старая", None
        
        return True, None, date_obj
    except (ValueError, TypeError):
        return False, "Неверный формат даты", None


def escape_markdown(text: str) -> str:
    """
    Экранирует специальные символы Markdown для безопасного отображения
    """
    # Список специальных символов Markdown
    special_chars = ['*', '_', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    
    return text


def validate_entry_access(user_id: int, entry_id: int) -> bool:
    """
    Проверяет, имеет ли пользователь доступ к записи
    """
    entries = db.get_user_entries(user_id)
    return any(entry['id'] == entry_id for entry in entries)


def detect_suspicious_activity(user_id: int, activity_type: str, details: str = None) -> Optional[Dict]:
    """
    Обнаруживает подозрительную активность и логирует её
    Применяет активную защиту (блокировки, ограничения)
    Возвращает True если активность подозрительная
    """
    suspicious = False
    description = details or ""
    violation_type = None
    
    # Проверка на множественные подозрительные активности за короткое время
    # Это КРИТИЧЕСКОЕ нарушение - множественные попытки подозрительной активности
    recent_violations = db.get_recent_violations_count(user_id, minutes=10)
    if recent_violations >= 2:
        suspicious = True
        violation_type = 'multiple_violations'
        description += f"Множественные подозрительные активности ({recent_violations} за 10 минут). "
    
    # Проверка на превышение rate limit
    for action_type, limit_config in RATE_LIMITS.items():
        if not db.check_rate_limit(user_id, action_type, limit_config['max'], limit_config['window']):
            suspicious = True
            violation_type = 'rate_limit_exceeded'
            description += f"Превышен rate limit для {action_type}. "
    
    # Проверка на подозрительные паттерны в тексте
    if details:
        # Попытка SQL инъекции (КРИТИЧЕСКОЕ нарушение)
        sql_patterns = ['DROP TABLE', 'DELETE FROM', 'INSERT INTO', 'UPDATE SET', 'UNION SELECT', 
                       'DROP DATABASE', 'TRUNCATE', 'ALTER TABLE', 'EXEC', 'EXECUTE']
        if any(pattern.lower() in details.lower() for pattern in sql_patterns):
            suspicious = True
            violation_type = 'sql_injection'
            description += "Обнаружена попытка SQL инъекции. "
        
        # Слишком много спецсимволов (исключаем обычную пунктуацию: ! , . : " ')
        # В дневниках КПТ нормальны восклицания, запятые, кавычки в прямой речи
        suspicious_chars = re.findall(r'[!@#$%^&*()_+\-=\[\]{};\'\\:"|,.<>?]', details)
        # Считаем только «технические» символы: без ! , . : " '
        technical_chars = [c for c in suspicious_chars if c not in '!,.:"\'']
        tech_ratio = len(technical_chars) / len(details) if details else 0
        if tech_ratio > 0.25:
            suspicious = True
            if not violation_type:
                violation_type = 'suspicious_chars'
            description += "Подозрительное количество спецсимволов. "
        
        # Слишком много ссылок
        elif details.count('http') > 3:
            suspicious = True
            if not violation_type:
                violation_type = 'too_many_links'
            description += "Слишком много ссылок в тексте. "
        
        # Общий подозрительный паттерн
        elif not violation_type:
            violation_type = 'suspicious_pattern'
    
    # Если активность типа situation_input повторяется часто - это подозрительно
    # Требуем >= 2 нарушений, чтобы один ложный срабатывание не блокировал легитимные записи
    if activity_type == 'situation_input' and recent_violations >= 2:
        suspicious = True
        if not violation_type:
            violation_type = 'suspicious_pattern'
        description += "Повторяющиеся попытки ввода ситуации. "
    
    if suspicious:
        # Логируем активность
        db.log_suspicious_activity(user_id, activity_type, description)
        
        # Маскируем чувствительные данные в логах
        try:
            from log_masking import mask_user_data_in_log
            log_message = f"Подозрительная активность залогирована: user_id={user_id}, type={activity_type}, details={description}"
            logger.warning(mask_user_data_in_log(log_message))
        except:
            logger.warning(f"Подозрительная активность залогирована: user_id={user_id}, type={activity_type}")
        
        # Применяем активную защиту
        try:
            from active_protection import add_violation
            protection_result = add_violation(user_id, violation_type or 'suspicious_pattern', description)
            
            if protection_result['action_taken']:
                logger.info(f"🛡️ Активная защита применена: {protection_result['action_taken']} для пользователя {user_id}")
            
            # Возвращаем результат для обработки удаления сообщений
            return protection_result
        except Exception as e:
            logger.error(f"Ошибка при применении активной защиты: {e}", exc_info=True)
            return {'violation_added': True, 'should_delete_messages': False}
    
    return None


def perform_security_check() -> Dict:
    """
    Выполняет регулярную проверку безопасности
    """
    from datetime import datetime
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'checks': []
    }
    
    # Проверка 1: Количество подозрительных активностей
    suspicious_count = db.get_total_suspicious_count()
    if suspicious_count > 100:
        results['checks'].append({
            'type': 'suspicious_activities',
            'status': 'warning',
            'message': f'Обнаружено {suspicious_count} подозрительных активностей'
        })
    else:
        results['checks'].append({
            'type': 'suspicious_activities',
            'status': 'ok',
            'message': f'Подозрительных активностей: {suspicious_count}'
        })
    
    # Проверка 2: Количество пользователей без согласия
    total_users = len(db.get_all_user_ids())
    users_with_consent = len([row[0] for row in db.get_all_user_ids() if db.check_user_consent(row[0])])
    users_without_consent = total_users - users_with_consent
    
    if users_without_consent > 0:
        results['checks'].append({
            'type': 'user_consents',
            'status': 'info',
            'message': f'Пользователей без согласия: {users_without_consent}'
        })
    
    # Проверка 3: Размер базы данных
    import os
    db_size = os.path.getsize('cognitive_diary.db') if os.path.exists('cognitive_diary.db') else 0
    db_size_mb = db_size / (1024 * 1024)
    
    if db_size_mb > 100:
        results['checks'].append({
            'type': 'database_size',
            'status': 'warning',
            'message': f'Размер БД: {db_size_mb:.2f} MB'
        })
    else:
        results['checks'].append({
            'type': 'database_size',
            'status': 'ok',
            'message': f'Размер БД: {db_size_mb:.2f} MB'
        })
    
    # Сохраняем результаты проверки
    for check in results['checks']:
        db.save_security_check(
            check['type'],
            check['status'],
            check['message']
        )
    
    return results
