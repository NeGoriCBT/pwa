"""
Модуль для поиска и фильтрации записей
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ContextTypes
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from database import Database
from security import (
    check_user_consent, check_rate_limit, validate_entry_access, escape_markdown,
    validate_search_query, detect_suspicious_activity,
)
from utils import get_back_to_menu_keyboard
from states import States

db = Database()
logger = logging.getLogger(__name__)

async def show_search_menu(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает меню поиска"""
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
    
    from handlers import request_password_for_action
    if await request_password_for_action(query, context, 'show_search_menu', section='search'):
        return
    
    keyboard = [
        [InlineKeyboardButton("🔍 Поиск по тексту", callback_data='search_text')],
        [InlineKeyboardButton("📅 Поиск по дате", callback_data='search_date')],
        [InlineKeyboardButton("😊 Фильтр по эмоциям", callback_data='search_emotions')],
        [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
    ]
    
    from handlers import safe_edit_message
    await safe_edit_message(
        query,
        "🔍 *Поиск и фильтрация записей*\n\n"
        "Выберите способ поиска:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_search_text(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает поиск по тексту"""
    user_id = query.from_user.id
    
    db.save_user_state(user_id, States.WAITING_SEARCH_QUERY, {'search_type': 'text'})
    
    from handlers import safe_edit_message
    await safe_edit_message(
        query,
        "🔍 *Поиск по тексту*\n\n"
        "Введите ключевые слова для поиска в записях:",
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_search_date(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает поиск по дате"""
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
    
    # Сохраняем состояние для выбора даты
    from states import States
    db.save_user_state(user_id, States.WAITING_SEARCH_DATE, {'search_type': 'date', 'entry_type': 'thoughts'})
    
    from utils import create_calendar
    from handlers import safe_edit_message
    await safe_edit_message(
        query,
        "📅 *Поиск по дате*\n\n"
        "Выберите дату для поиска записей:",
        reply_markup=create_calendar(prefix='search'),
        parse_mode='Markdown'
    )

async def handle_search_emotions(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает фильтр по эмоциям"""
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
    
    # Получаем список всех эмоций из записей пользователя (с кэшированием)
    from cache import get_cached, set_cached
    
    cache_key = f"user_emotions:{user_id}"
    cached_emotions = get_cached(cache_key, ttl=600)  # Кэш на 10 минут
    
    if cached_emotions is not None:
        all_emotions = cached_emotions
    else:
        entries = db.get_user_entries(user_id)
        all_emotions = set()
        
        for entry in entries:
            # Эмоции до анализа
            emotions_before = entry.get('emotions_before', [])
            if isinstance(emotions_before, str):
                import json
                try:
                    emotions_before = json.loads(emotions_before) if emotions_before else []
                except:
                    emotions_before = []
            
            for em in emotions_before:
                if isinstance(em, dict):
                    all_emotions.add(em.get('emotion', ''))
                elif isinstance(em, str):
                    all_emotions.add(em)
            
            # Эмоции после анализа
            emotions_after = entry.get('emotions_after', [])
            if isinstance(emotions_after, str):
                try:
                    emotions_after = json.loads(emotions_after) if emotions_after else []
                except:
                    emotions_after = []
            
            for em in emotions_after:
                if isinstance(em, dict):
                    all_emotions.add(em.get('emotion', ''))
                elif isinstance(em, str):
                    all_emotions.add(em)
        
        # Убираем пустые значения
        all_emotions = {e for e in all_emotions if e}
        
        # Сохраняем в кэш
        set_cached(cache_key, all_emotions, ttl=600)
    
    if not all_emotions:
        from handlers import safe_edit_message
        await safe_edit_message(
            query,
            "😊 *Фильтр по эмоциям*\n\n"
            "У вас пока нет записей с эмоциями. Создайте записи, чтобы использовать фильтр.",
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    # Создаем клавиатуру с эмоциями
    keyboard = []
    emotions_list = sorted(list(all_emotions))
    
    # Группируем по 2 кнопки в ряд
    for i in range(0, len(emotions_list), 2):
        row = []
        row.append(InlineKeyboardButton(emotions_list[i], callback_data=f'search_emotion_{emotions_list[i]}'))
        if i + 1 < len(emotions_list):
            row.append(InlineKeyboardButton(emotions_list[i + 1], callback_data=f'search_emotion_{emotions_list[i + 1]}'))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='search')])
    
    from handlers import safe_edit_message
    await safe_edit_message(
        query,
        "😊 *Фильтр по эмоциям*\n\n"
        "Выберите эмоцию для поиска записей:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_search_emotion_choice(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, emotion: str) -> None:
    """Обрабатывает выбор эмоции для поиска"""
    user_id = query.from_user.id
    
    # Получаем все записи пользователя
    entries = db.get_user_entries(user_id)
    matched_entries = []
    
    for entry in entries:
        # Проверяем эмоции до анализа
        emotions_before = entry.get('emotions_before', [])
        if isinstance(emotions_before, str):
            import json
            try:
                emotions_before = json.loads(emotions_before) if emotions_before else []
            except:
                emotions_before = []
        
        found = False
        for em in emotions_before:
            if isinstance(em, dict):
                if em.get('emotion', '').lower() == emotion.lower():
                    found = True
                    break
            elif isinstance(em, str) and em.lower() == emotion.lower():
                found = True
                break
        
        # Проверяем эмоции после анализа
        if not found:
            emotions_after = entry.get('emotions_after', [])
            if isinstance(emotions_after, str):
                try:
                    emotions_after = json.loads(emotions_after) if emotions_after else []
                except:
                    emotions_after = []
            
            for em in emotions_after:
                if isinstance(em, dict):
                    if em.get('emotion', '').lower() == emotion.lower():
                        found = True
                        break
                elif isinstance(em, str) and em.lower() == emotion.lower():
                    found = True
                    break
        
        if found:
            matched_entries.append(entry)
    
    if not matched_entries:
        from handlers import safe_edit_message
        await safe_edit_message(
            query,
            f"❌ Записи с эмоцией '{emotion}' не найдены.",
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    # Показываем результаты (первые 20)
    keyboard = []
    for entry in matched_entries[:20]:
        date_str = datetime.fromisoformat(entry['timestamp']).strftime('%d.%m.%Y %H:%M')
        situation_preview = entry['situation'][:30] + '...' if len(entry.get('situation', '')) > 30 else entry.get('situation', '')
        text = f"{date_str}: {situation_preview}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"entry_{entry['id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 В меню", callback_data='menu')])
    
    from handlers import safe_edit_message
    await safe_edit_message(
        query,
        f"😊 *Найдено записей с эмоцией '{emotion}': {len(matched_entries)}*\n\n"
        f"Выберите запись для просмотра:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    logger.info(f"Пользователь {user_id} выполнил поиск по эмоции '{emotion}': найдено {len(matched_entries)} записей")

async def handle_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает поисковый запрос"""
    user_id = update.effective_user.id
    raw_text = update.message.text
    query_text = raw_text.lower().strip()
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_SEARCH_QUERY:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    is_valid, error_msg = validate_search_query(raw_text)
    if not is_valid:
        detect_suspicious_activity(user_id, 'invalid_search_query', error_msg)
        await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=get_back_to_menu_keyboard())
        return
    if detect_suspicious_activity(user_id, 'search_query_input', raw_text):
        from handlers import process_suspicious_input_and_notify_admin
        await process_suspicious_input_and_notify_admin(update, context, user_id, "Поисковый запрос", raw_text)
        return
    
    search_type = state_info['data'].get('search_type', 'text')
    db.clear_user_state(user_id)
    
    # Получаем все записи пользователя
    entries = db.get_user_entries(user_id)
    
    # Фильтруем записи
    matched_entries = []
    if search_type == 'text':
        for entry in entries:
            # Ищем в ситуации, мысли, действии, доводах, заметке
            search_fields = [
                entry.get('situation', ''),
                entry.get('automatic_thought', ''),
                entry.get('action', ''),
                entry.get('evidence_for', ''),
                entry.get('evidence_against', ''),
                entry.get('note_to_future_self', '')
            ]
            
            # Проверяем, содержит ли хотя бы одно поле запрос
            if any(query_text in str(field).lower() for field in search_fields):
                matched_entries.append(entry)
    
    if not matched_entries:
        await update.message.reply_text(
            "❌ Записи не найдены.",
            reply_markup=get_back_to_menu_keyboard()
        )
        return
    
    # Показываем результаты (первые 20)
    keyboard = []
    for entry in matched_entries[:20]:
        date_str = datetime.fromisoformat(entry['timestamp']).strftime('%d.%m.%Y %H:%M')
        situation_preview = entry['situation'][:30] + '...' if len(entry.get('situation', '')) > 30 else entry.get('situation', '')
        text = f"{date_str}: {situation_preview}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"entry_{entry['id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 В меню", callback_data='menu')])
    
    await update.message.reply_text(
        f"🔍 *Найдено записей: {len(matched_entries)}*\n\n"
        f"Выберите запись для просмотра:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    logger.info(f"Пользователь {user_id} выполнил поиск: найдено {len(matched_entries)} записей")
