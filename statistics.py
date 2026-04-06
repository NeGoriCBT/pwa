"""
Модуль для статистики пользователя
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import logging
from datetime import datetime, timedelta
from database import Database
from security import check_user_consent, check_rate_limit, validate_entry_access
from utils import get_back_to_menu_keyboard

db = Database()
logger = logging.getLogger(__name__)

async def show_user_statistics(query, context):
    """Показывает статистику пользователя"""
    user_id = query.from_user.id
    
    # Проверяем согласие
    if not check_user_consent(user_id):
        await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
        return
    
    # Проверяем rate limiting
    allowed, error_msg = check_rate_limit(user_id, 'command')
    if not allowed:
        await query.answer(error_msg, show_alert=True)
        return
    
    # Получаем все записи пользователя
    entries = db.get_user_entries(user_id)
    
    if not entries:
        from handlers import safe_edit_message
        await safe_edit_message(
            query,
            "📊 *Статистика*\n\n"
            "У вас пока нет записей. Создайте первую запись, чтобы увидеть статистику!",
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    # Подсчитываем статистику
    total_entries = len(entries)
    
    # Записи за последние 7, 30 дней
    now = datetime.now()
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()
    
    entries_week = [e for e in entries if e['timestamp'] >= week_ago]
    entries_month = [e for e in entries if e['timestamp'] >= month_ago]
    
    # Самые частые эмоции
    emotions_before = {}
    emotions_after = {}
    for entry in entries:
        for em in entry.get('emotions_before', []):
            emotion = em.get('emotion', '')
            emotions_before[emotion] = emotions_before.get(emotion, 0) + 1
        for em in entry.get('emotions_after', []):
            emotion = em.get('emotion', '')
            emotions_after[emotion] = emotions_after.get(emotion, 0) + 1
    
    # Топ-3 эмоции до и после
    top_emotions_before = sorted(emotions_before.items(), key=lambda x: x[1], reverse=True)[:3]
    top_emotions_after = sorted(emotions_after.items(), key=lambda x: x[1], reverse=True)[:3]
    
    # Успешные записи (снижение негативных эмоций или появление позитивных)
    from utils import check_success
    successful_entries = sum(1 for e in entries if check_success(e))
    success_rate = (successful_entries / total_entries * 100) if total_entries > 0 else 0
    
    # Формируем текст статистики
    stats_text = (
        f"📊 *Ваша статистика*\n\n"
        f"*Всего записей:* {total_entries}\n"
        f"*За последние 7 дней:* {len(entries_week)}\n"
        f"*За последние 30 дней:* {len(entries_month)}\n\n"
        f"*Успешных записей:* {successful_entries} ({success_rate:.1f}%)\n\n"
    )
    
    if top_emotions_before:
        stats_text += "*Наиболее частые эмоции до анализа:*\n"
        for i, (emotion, count) in enumerate(top_emotions_before, 1):
            stats_text += f"{i}. {emotion}: {count} раз\n"
        stats_text += "\n"
    
    if top_emotions_after:
        stats_text += "*Наиболее частые эмоции после анализа:*\n"
        for i, (emotion, count) in enumerate(top_emotions_after, 1):
            stats_text += f"{i}. {emotion}: {count} раз\n"
    
    keyboard = [
        [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
    ]
    
    from handlers import safe_edit_message
    await safe_edit_message(
        query,
        stats_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
