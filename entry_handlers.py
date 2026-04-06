"""
Модуль для обработки создания и редактирования записей
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import logging
from database import Database
from states import States
from security import (
    validate_situation, validate_thought, validate_action, validate_evidence,
    validate_note, validate_emotion, sanitize_text, escape_markdown,
    check_rate_limit, check_user_consent, detect_suspicious_activity
)
from utils import (
    get_emotions_keyboard, get_intensity_keyboard, get_yes_no_keyboard,
    get_new_emotions_keyboard, get_cancel_entry_keyboard, get_main_menu_keyboard,
    format_entry_summary, check_success
)
from message_tracker import save_message_id

db = Database()
logger = logging.getLogger(__name__)

async def handle_cancel_entry(query, context):
    """Обрабатывает отмену создания записи"""
    user_id = query.from_user.id
    
    # Очищаем состояние пользователя
    db.clear_user_state(user_id)
    
    from handlers import safe_edit_message
    await safe_edit_message(
        query,
        "❌ *Создание записи отменено*\n\n"
        "Вы вернулись в главное меню.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown'
    )
    logger.info(f"Пользователь {user_id} отменил создание записи")
