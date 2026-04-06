"""
Модуль активной защиты бота
Реализует систему репутации, автоматическую блокировку и эскалацию мер
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
from database import Database
from config import ADMIN_USERNAME

db = Database()
logger = logging.getLogger(__name__)

# Пороги для системы репутации
REPUTATION_THRESHOLDS = {
    'warning': 20,          # Предупреждение
    'restrictions': 50,     # Ограничение функционала
    'temp_block_short': 100,  # Временная блокировка (1-6 часов)
    'temp_block_long': 200,   # Длительная блокировка (24-72 часа)
    'permanent': 300        # Постоянная блокировка
}

# Баллы за разные типы нарушений
VIOLATION_SCORES = {
    'sql_injection': 50,           # Критическое нарушение
    'rate_limit_exceeded': 10,     # Превышение лимита
    'suspicious_chars': 5,         # Подозрительные символы
    'too_many_links': 5,           # Слишком много ссылок
    'suspicious_pattern': 10,      # Подозрительный паттерн
    'multiple_violations': 20      # Множественные нарушения
}

# Длительности блокировок (в часах)
BLOCK_DURATIONS = {
    'critical': 24,      # Критические нарушения
    'multiple': 1,       # Множественные нарушения
    'rate_limit': 0.5,  # Превышение лимита (30 минут)
    'temp_short': 1,    # Временная блокировка (короткая)
    'temp_medium': 6,   # Временная блокировка (средняя)
    'temp_long': 24,    # Временная блокировка (длинная)
    'temp_very_long': 72  # Временная блокировка (очень длинная)
}


def get_protection_level(score: int) -> int:
    """
    Определяет уровень защиты на основе баллов репутации
    Возвращает уровень от 0 до 5
    """
    if score >= REPUTATION_THRESHOLDS['permanent']:
        return 5
    elif score >= REPUTATION_THRESHOLDS['temp_block_long']:
        return 4
    elif score >= REPUTATION_THRESHOLDS['temp_block_short']:
        return 3
    elif score >= REPUTATION_THRESHOLDS['restrictions']:
        return 2
    elif score >= REPUTATION_THRESHOLDS['warning']:
        return 1
    return 0


def add_violation(user_id: int, violation_type: str, details: str = None) -> Dict:
    """
    Добавляет нарушение пользователю и применяет меры защиты
    Возвращает информацию о примененных мерах
    """
    score_delta = VIOLATION_SCORES.get(violation_type, 10)
    new_score = db.update_user_reputation(user_id, score_delta, violation_type)
    protection_level = get_protection_level(new_score)
    
    result = {
        'violation_added': True,
        'new_score': new_score,
        'protection_level': protection_level,
        'action_taken': None,
        'block_duration': None
    }
    
    # Проверяем на критические нарушения (немедленная блокировка)
    if violation_type == 'sql_injection':
        duration = BLOCK_DURATIONS['critical']
        db.auto_block_user(user_id, f"Критическое нарушение: SQL инъекция", duration)
        result['action_taken'] = 'auto_block_critical'
        result['block_duration'] = duration
        result['should_delete_messages'] = True
        logger.warning(f"🚨 Критическое нарушение! Пользователь {user_id} заблокирован на {duration} часов")
        return result
    
    # Проверяем множественные нарушения за короткое время
    recent_violations = db.get_recent_violations_count(user_id, minutes=10)
    if recent_violations >= 3:
        duration = BLOCK_DURATIONS['multiple']
        db.auto_block_user(user_id, f"Множественные нарушения ({recent_violations} за 10 минут)", duration)
        result['action_taken'] = 'auto_block_multiple'
        result['block_duration'] = duration
        result['should_delete_messages'] = True
        logger.warning(f"🚨 Множественные нарушения! Пользователь {user_id} заблокирован на {duration} часов")
        return result
    
    # Применяем меры в зависимости от уровня защиты
    if protection_level >= 5:
        # Постоянная блокировка (требует разблокировки админом)
        db.auto_block_user(user_id, f"Постоянная блокировка (баллы: {new_score})", None)
        result['action_taken'] = 'permanent_block'
        result['should_delete_messages'] = True
        logger.warning(f"🔒 Постоянная блокировка пользователя {user_id} (баллы: {new_score})")
    
    elif protection_level >= 4:
        # Длительная блокировка
        duration = BLOCK_DURATIONS['temp_very_long'] if new_score >= 250 else BLOCK_DURATIONS['temp_long']
        db.auto_block_user(user_id, f"Длительная блокировка (баллы: {new_score})", duration)
        result['action_taken'] = 'temp_block_long'
        result['block_duration'] = duration
        result['should_delete_messages'] = True
        logger.warning(f"⏰ Длительная блокировка пользователя {user_id} на {duration} часов (баллы: {new_score})")
    
    elif protection_level >= 3:
        # Временная блокировка
        duration = BLOCK_DURATIONS['temp_medium'] if new_score >= 150 else BLOCK_DURATIONS['temp_short']
        db.auto_block_user(user_id, f"Временная блокировка (баллы: {new_score})", duration)
        result['action_taken'] = 'temp_block'
        result['block_duration'] = duration
        result['should_delete_messages'] = True
        logger.warning(f"⏰ Временная блокировка пользователя {user_id} на {duration} часов (баллы: {new_score})")
    
    elif protection_level >= 2:
        # Ограничение функционала
        db.set_user_restrictions_level(user_id, 2)
        result['action_taken'] = 'restrictions'
        logger.info(f"⚠️ Ограничения для пользователя {user_id} (баллы: {new_score})")
    
    elif protection_level >= 1:
        # Предупреждение
        db.set_user_restrictions_level(user_id, 1)
        result['action_taken'] = 'warning'
        logger.info(f"⚠️ Предупреждение пользователю {user_id} (баллы: {new_score})")
    
    return result


def check_user_restrictions(user_id: int) -> Tuple[bool, Optional[str]]:
    """
    Проверяет ограничения пользователя
    Возвращает (allowed, message)
    """
    reputation = db.get_user_reputation(user_id)
    level = reputation['restrictions_level']
    
    if level >= 2:
        return False, "⚠️ Ваш функционал ограничен из-за нарушений правил. Попробуйте позже."
    
    return True, None


def get_user_protection_status(user_id: int) -> Dict:
    """
    Получает статус защиты пользователя
    """
    reputation = db.get_user_reputation(user_id)
    is_blocked = db.is_user_blocked(user_id)
    protection_level = get_protection_level(reputation['violation_score'])
    
    blocked_info = None
    if is_blocked:
        blocked_users = db.get_blocked_users()
        user_block = next((u for u in blocked_users if u['user_id'] == user_id), None)
        if user_block:
            blocked_info = {
                'blocked_at': user_block['blocked_at'],
                'reason': user_block['blocked_reason'],
                'auto_blocked': user_block.get('auto_blocked', 0),
                'unblock_at': user_block.get('unblock_at')
            }
    
    return {
        'violation_score': reputation['violation_score'],
        'protection_level': protection_level,
        'restrictions_level': reputation['restrictions_level'],
        'is_blocked': is_blocked,
        'blocked_info': blocked_info,
        'last_violation': reputation['last_violation']
    }


def get_block_message(user_id: int) -> str:
    """
    Получает сообщение о блокировке для пользователя
    """
    status = get_user_protection_status(user_id)
    
    if not status['is_blocked']:
        return None
    
    blocked_info = status['blocked_info']
    if not blocked_info:
        return f"🚫 *Вы заблокированы*\n\nДля разблокировки свяжитесь с администратором: {ADMIN_USERNAME}"
    
    message = "🚫 *Вы заблокированы*\n\n"
    
    if blocked_info.get('auto_blocked'):
        if blocked_info.get('unblock_at'):
            try:
                unblock_time = datetime.fromisoformat(blocked_info['unblock_at'])
                time_left = unblock_time - datetime.now()
                if time_left.total_seconds() > 0:
                    hours = int(time_left.total_seconds() // 3600)
                    minutes = int((time_left.total_seconds() % 3600) // 60)
                    message += f"⏰ *Временная блокировка*\n\n"
                    message += f"Вы будете разблокированы автоматически через {hours}ч {minutes}м.\n\n"
                else:
                    # Время истекло, но пользователь еще не разблокирован
                    message += "⏰ Время блокировки истекло. Ожидайте автоматической разблокировки.\n\n"
            except:
                message += "⏰ Временная блокировка.\n\n"
        else:
            message += "🔒 *Постоянная блокировка*\n\n"
    else:
        message += "🔒 *Блокировка администратором*\n\n"
    
    if blocked_info.get('reason'):
        message += f"*Причина:* {blocked_info['reason']}\n\n"
    
    message += f"Для разблокировки свяжитесь с администратором: {ADMIN_USERNAME}"
    
    return message


def remove_all_restrictions(user_id: int) -> Dict:
    """
    Полностью снимает все ограничения с пользователя:
    - Разблокирует пользователя
    - Сбрасывает репутацию (баллы нарушений) до 0
    - Снимает уровень ограничений до 0
    
    Возвращает информацию о выполненных действиях
    """
    result = {
        'was_blocked': False,
        'had_reputation': False,
        'had_restrictions': False,
        'reputation_before': 0,
        'restrictions_before': 0
    }
    
    # Проверяем текущий статус
    reputation = db.get_user_reputation(user_id)
    was_blocked = db.is_user_blocked(user_id)
    
    result['was_blocked'] = was_blocked
    result['reputation_before'] = reputation['violation_score']
    result['restrictions_before'] = reputation['restrictions_level']
    
    if reputation['violation_score'] > 0:
        result['had_reputation'] = True
    if reputation['restrictions_level'] > 0:
        result['had_restrictions'] = True
    
    # Разблокируем пользователя
    if was_blocked:
        db.unblock_user(user_id)
        logger.info(f"🔓 Пользователь {user_id} разблокирован")
    
    # Сбрасываем репутацию до 0
    if reputation['violation_score'] > 0:
        db.update_user_reputation(user_id, -reputation['violation_score'], None)
        logger.info(f"🔄 Репутация пользователя {user_id} сброшена с {reputation['violation_score']} до 0")
    
    # Снимаем ограничения
    if reputation['restrictions_level'] > 0:
        db.set_user_restrictions_level(user_id, 0)
        logger.info(f"✅ Ограничения пользователя {user_id} сняты (было: {reputation['restrictions_level']})")
    
    logger.info(f"✅ Все ограничения сняты с пользователя {user_id}")
    return result


async def delete_user_messages(bot, user_id: int):
    """
    Удаляет ВСЮ историю сообщений пользователя (и пользователя, и бота) из чата
    """
    try:
        # Получаем все сообщения (и пользователя, и бота)
        messages = db.get_user_messages(user_id)
        deleted_count = 0
        failed_count = 0
        
        if not messages:
            logger.info(f"Нет сохраненных сообщений для удаления у пользователя {user_id}")
            return 0
        
        logger.info(f"Начинаем удаление {len(messages)} сообщений пользователя {user_id}")
        
        # Удаляем сообщения в обратном порядке (от старых к новым)
        # Это помогает избежать проблем с изменением message_id
        for msg in reversed(messages):
            try:
                await bot.delete_message(
                    chat_id=msg['chat_id'],
                    message_id=msg['message_id']
                )
                deleted_count += 1
                # Небольшая задержка, чтобы не превысить rate limit Telegram API
                import asyncio
                await asyncio.sleep(0.05)  # 50ms задержка между удалениями
            except Exception as e:
                # Сообщение может быть уже удалено, слишком старое (>48 часов) или недоступно
                failed_count += 1
                error_msg = str(e).lower()
                if 'message to delete not found' in error_msg or 'bad request' in error_msg:
                    # Сообщение уже удалено или недоступно - это нормально
                    logger.debug(f"Сообщение {msg['message_id']} уже удалено или недоступно")
                else:
                    logger.warning(f"Не удалось удалить сообщение {msg['message_id']}: {e}")
        
        # Очищаем записи из БД после удаления
        db.delete_user_messages(user_id)
        
        logger.info(f"✅ Удалено {deleted_count} сообщений пользователя {user_id} (не удалось: {failed_count})")
        return deleted_count
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении сообщений пользователя {user_id}: {e}", exc_info=True)
        return 0
