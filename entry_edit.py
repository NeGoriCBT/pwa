"""
Модуль для редактирования существующих записей
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import logging
from database import Database
from states import States
from security import (
    validate_situation, validate_thought, validate_action, validate_evidence,
    validate_note, sanitize_text, escape_markdown, validate_entry_access,
    check_rate_limit, check_user_consent, detect_suspicious_activity,
)
from utils import get_back_to_menu_keyboard

db = Database()
logger = logging.getLogger(__name__)

# Состояния для редактирования
class EditStates:
    EDITING_ENTRY = "editing_entry"
    EDITING_SITUATION = "editing_situation"
    EDITING_AUTOMATIC_THOUGHT = "editing_automatic_thought"
    EDITING_ACTION = "editing_action"
    EDITING_EVIDENCE_FOR = "editing_evidence_for"
    EDITING_EVIDENCE_AGAINST = "editing_evidence_against"
    EDITING_NOTE = "editing_note"

async def show_edit_entry_menu(query, context, entry_id):
    """Показывает меню редактирования записи"""
    user_id = query.from_user.id
    
    # Проверяем доступ
    if not validate_entry_access(user_id, entry_id):
        await query.answer("Доступ запрещен", show_alert=True)
        return
    
    entries = db.get_user_entries(user_id)
    entry = next((e for e in entries if e['id'] == entry_id), None)
    
    if not entry:
        await query.answer("Запись не найдена", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("📝 Редактировать ситуацию", callback_data=f'edit_situation_{entry_id}')],
        [InlineKeyboardButton("💭 Редактировать автоматическую мысль", callback_data=f'edit_thought_{entry_id}')],
        [InlineKeyboardButton("🎬 Редактировать действие", callback_data=f'edit_action_{entry_id}')],
        [InlineKeyboardButton("✅ Редактировать доводы 'за'", callback_data=f'edit_evidence_for_{entry_id}')],
        [InlineKeyboardButton("❌ Редактировать доводы 'против'", callback_data=f'edit_evidence_against_{entry_id}')],
        [InlineKeyboardButton("📌 Редактировать заметку", callback_data=f'edit_note_{entry_id}')],
        [InlineKeyboardButton("🔙 Назад к записи", callback_data=f'entry_{entry_id}')],
        [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
    ]
    
    from handlers import safe_edit_message
    await safe_edit_message(
        query,
        "✏️ *Редактирование записи*\n\n"
        "Выберите, что вы хотите отредактировать:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_edit_field(query, context, data):
    """Обрабатывает выбор поля для редактирования"""
    user_id = query.from_user.id
    
    # Парсим данные: edit_situation_123 -> field='situation', entry_id=123
    parts = data.split('_')
    if len(parts) < 3:
        await query.answer("Ошибка", show_alert=True)
        return
    
    field = parts[1]  # situation, thought, action, etc.
    entry_id = int(parts[2])
    
    # Проверяем доступ
    if not validate_entry_access(user_id, entry_id):
        await query.answer("Доступ запрещен", show_alert=True)
        return
    
    # Сохраняем состояние редактирования
    edit_data = {
        'entry_id': entry_id,
        'field': field
    }
    
    # Определяем состояние в зависимости от поля
    state_map = {
        'situation': EditStates.EDITING_SITUATION,
        'thought': EditStates.EDITING_AUTOMATIC_THOUGHT,
        'action': EditStates.EDITING_ACTION,
        'evidence_for': EditStates.EDITING_EVIDENCE_FOR,
        'evidence_against': EditStates.EDITING_EVIDENCE_AGAINST,
        'note': EditStates.EDITING_NOTE
    }
    
    state = state_map.get(field)
    if not state:
        await query.answer("Неизвестное поле", show_alert=True)
        return
    
    db.save_user_state(user_id, state, edit_data)
    
    # Получаем текущее значение
    entries = db.get_user_entries(user_id)
    entry = next((e for e in entries if e['id'] == entry_id), None)
    
    if not entry:
        await query.answer("Запись не найдена", show_alert=True)
        return
    
    field_names = {
        'situation': 'ситуацию',
        'thought': 'автоматическую мысль',
        'action': 'действие',
        'evidence_for': "доводы 'за'",
        'evidence_against': "доводы 'против'",
        'note': 'заметку'
    }
    
    field_key = {
        'situation': 'situation',
        'thought': 'automatic_thought',
        'action': 'action',
        'evidence_for': 'evidence_for',
        'evidence_against': 'evidence_against',
        'note': 'note_to_future_self'
    }
    
    current_value = entry.get(field_key[field], '')
    field_name = field_names[field]
    
    from handlers import safe_edit_message
    await safe_edit_message(
        query,
        f"✏️ *Редактирование {field_name}*\n\n"
        f"*Текущее значение:*\n{escape_markdown(current_value)}\n\n"
        f"Введите новое значение:",
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_edit_text(update, context, state, edit_data):
    """Обрабатывает ввод нового значения для редактирования"""
    user_id = update.effective_user.id
    text = update.message.text
    
    # Проверяем согласие
    if not check_user_consent(user_id):
        await update.message.reply_text(
            "⚠️ Для использования бота необходимо дать согласие на обработку данных. "
            "Используйте команду /start."
        )
        return
    
    entry_id = edit_data['entry_id']
    field = edit_data['field']
    
    # Валидация в зависимости от поля
    validators = {
        'situation': validate_situation,
        'thought': validate_thought,
        'action': validate_action,
        'evidence_for': validate_evidence,
        'evidence_against': validate_evidence,
        'note': validate_note
    }
    
    validator = validators.get(field)
    if validator:
        is_valid, error_msg = validator(text)
        if not is_valid:
            detect_suspicious_activity(user_id, f'invalid_edit_{field}', error_msg)
            await update.message.reply_text(f"⚠️ {error_msg}")
            return
    
    if detect_suspicious_activity(user_id, f'edit_input_{field}', text):
        from handlers import process_suspicious_input_and_notify_admin
        names = {'situation': 'ситуация', 'thought': 'автоматическая мысль', 'action': 'действие',
                 'evidence_for': "доводы 'за'", 'evidence_against': "доводы 'против'", 'note': 'заметка'}
        await process_suspicious_input_and_notify_admin(
            update, context, user_id, f"Редактирование: {names.get(field, field)}", text
        )
        return
    
    # Обновляем запись в БД
    field_map = {
        'situation': 'situation',
        'thought': 'automatic_thought',
        'action': 'action',
        'evidence_for': 'evidence_for',
        'evidence_against': 'evidence_against',
        'note': 'note_to_future_self'
    }
    
    db_field = field_map.get(field)
    if not db_field:
        await update.message.reply_text("⚠️ Неизвестное поле для редактирования")
        return
    
    success = db.update_entry_field(entry_id, db_field, sanitize_text(text))
    if not success:
        await update.message.reply_text("⚠️ Не удалось обновить запись")
        return
    
    # Очищаем состояние
    db.clear_user_state(user_id)
    
    # Показываем обновленную запись
    entries = db.get_user_entries(user_id)
    entry = next((e for e in entries if e['id'] == entry_id), None)
    
    if entry:
        from utils import format_entry_summary
        summary = format_entry_summary(entry)
        
        keyboard = [
            [InlineKeyboardButton("✏️ Редактировать", callback_data=f'edit_entry_{entry_id}')],
            [InlineKeyboardButton("🔙 Назад к списку", callback_data='my_entries')],
            [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
        ]
        
        await update.message.reply_text(
            f"✅ *Поле обновлено!*\n\n{summary}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        logger.info(f"Пользователь {user_id} отредактировал поле {field} записи {entry_id}")
