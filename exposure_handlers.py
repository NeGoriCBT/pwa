"""
Модуль для обработки дневника экспозиций
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ContextTypes
import logging
from typing import Optional
from datetime import datetime, timedelta
from database import Database
from security import (
    check_user_consent, check_rate_limit, sanitize_text, escape_markdown,
    validate_exposure_situation, validate_exposure_expectation,
    validate_exposure_reality_description, validate_exposure_summary, validate_emotion,
    detect_suspicious_activity,
)
from utils import get_back_to_menu_keyboard, get_cancel_entry_keyboard, create_calendar, get_intensity_keyboard, get_emotions_keyboard, get_yes_no_keyboard
from states import States
from handlers import safe_edit_message, add_cancel_button, process_suspicious_input_and_notify_admin
from message_tracker import save_message_id

db = Database()
logger = logging.getLogger(__name__)

async def start_new_entry_exposure(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начинает процесс создания новой записи экспозиции"""
    user_id = query.from_user.id
    
    # Проверяем, не заблокирован ли пользователь (ПЕРВЫМ ДЕЛОМ!)
    if db.is_user_blocked(user_id):
        from active_protection import get_block_message
        block_message = get_block_message(user_id)
        if block_message:
            await query.answer("Вы заблокированы", show_alert=True)
            await safe_edit_message(query, block_message, parse_mode='Markdown')
        else:
            await query.answer("Вы заблокированы", show_alert=True)
        return
    
    # Проверяем согласие
    if not check_user_consent(user_id):
        await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
        return
    
    # Проверяем rate limiting
    allowed, error_msg = check_rate_limit(user_id, 'entry_creation')
    if not allowed:
        await query.answer(error_msg, show_alert=True)
        return
    
    db.clear_user_state(user_id)
    
    exposure_data = {}
    db.save_user_state(user_id, States.WAITING_EXPOSURE_SITUATION, exposure_data)
    
    await safe_edit_message(
        query,
        "📝 *Дневник экспозиций*\n\n"
        "*Шаг 1: Название ситуации*\n\n"
        "Как бы вы кратко назвали предстоящую ситуацию?\n"
        "(Например: 'Разговор с начальником о проекте', 'Поездка в метро в час пик')",
        reply_markup=get_cancel_entry_keyboard(),
        parse_mode='Markdown'
    )

async def handle_exposure_situation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ввод названия ситуации"""
    user_id = update.effective_user.id
    text = update.message.text
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_SITUATION:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    is_valid, error_msg = validate_exposure_situation(text)
    if not is_valid:
        detect_suspicious_activity(user_id, 'invalid_exposure_situation', error_msg)
        await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=get_cancel_entry_keyboard())
        return
    if detect_suspicious_activity(user_id, 'exposure_situation_input', text):
        await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод названия ситуации (экспозиция)", text)
        return
    
    exposure_data = state_info['data']
    exposure_data['situation_name'] = sanitize_text(text)
    
    db.save_user_state(user_id, States.WAITING_EXPOSURE_DATE, exposure_data)
    
    await update.message.reply_text(
        "✅ Принято. Теперь выберите **дату**, когда эта ситуация произойдет.",
        reply_markup=create_calendar(prefix='exposure_date'),
        parse_mode='Markdown'
    )

async def handle_exposure_date_choice(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, 
                                     year: int, month: int, day: int) -> None:
    """Обрабатывает выбор даты для экспозиции (новый процесс - текстовый ввод времени)"""
    user_id = query.from_user.id
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_DATE:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    exposure_data = state_info['data']
    exposure_data['selected_date'] = f"{year}-{month:02d}-{day:02d}"
    
    db.save_user_state(user_id, States.WAITING_EXPOSURE_TIME, exposure_data)
    
    await safe_edit_message(
        query,
        f"✅ Дата выбрана: {day}.{month}.{year}\n\n"
        "⏰ *Шаг 2: Время события*\n\n"
        "Укажите время, когда произойдет событие, в формате **hh:MM**\n"
        "(Например: 14:30, 09:15)",
        reply_markup=get_cancel_entry_keyboard(),
        parse_mode='Markdown'
    )

async def handle_exposure_time_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает текстовый ввод времени в формате hh:MM"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_TIME:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    # Валидация формата времени hh:MM
    import re
    time_pattern = r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$'
    if not re.match(time_pattern, text):
        await update.message.reply_text(
            "⚠️ Неверный формат времени. Укажите время в формате **hh:MM**\n"
            "(Например: 14:30, 09:15)",
            reply_markup=get_cancel_entry_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    exposure_data = state_info['data']
    selected_date = exposure_data.get('selected_date')
    event_datetime = f"{selected_date} {text}:00"
    exposure_data['event_datetime'] = event_datetime
    exposure_data['expectations_data'] = []  # Инициализируем список ожиданий
    exposure_data['emotions_before'] = []  # Инициализируем список эмоций
    
    db.save_user_state(user_id, States.WAITING_EXPOSURE_EXPECTATION, exposure_data)
    
    await update.message.reply_text(
        f"✅ Время выбрано: {text}\n\n"
        "💭 *Шаг 3: Ожидания*\n\n"
        "Что вы ожидаете от этой ситуации или чего боитесь?\n"
        "Опишите ваши ожидания или страхи.",
        reply_markup=get_cancel_entry_keyboard(),
        parse_mode='Markdown'
    )

async def handle_exposure_time_choice(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, time_str: str) -> None:
    """Обрабатывает выбор времени для экспозиции (старый формат - для обратной совместимости)"""
    user_id = query.from_user.id
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_TIME:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    exposure_data = state_info['data']
    selected_date = exposure_data.get('selected_date')
    
    # Если time_str уже в формате hh:MM, используем его, иначе парсим
    if ':' in time_str:
        event_datetime = f"{selected_date} {time_str}:00"
    else:
        # Старый формат - оставляем для обратной совместимости
        event_datetime = f"{selected_date} {time_str}:00"
    
    exposure_data['event_datetime'] = event_datetime
    exposure_data['expectations_data'] = []  # Инициализируем список ожиданий
    exposure_data['emotions_before'] = []  # Инициализируем список эмоций
    
    db.save_user_state(user_id, States.WAITING_EXPOSURE_EXPECTATION, exposure_data)
    
    await safe_edit_message(
        query,
        f"✅ Время выбрано: {time_str}\n\n"
        "💭 *Шаг 3: Ожидания*\n\n"
        "Что вы ожидаете от этой ситуации или чего боитесь?\n"
        "Опишите ваши ожидания или страхи.",
        reply_markup=get_cancel_entry_keyboard(),
        parse_mode='Markdown'
    )

async def handle_exposure_expectation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ввод ожидания/страха (новый процесс - шаг 3)"""
    user_id = update.effective_user.id
    text = update.message.text
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_EXPECTATION:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    is_valid, error_msg = validate_exposure_expectation(text)
    if not is_valid:
        detect_suspicious_activity(user_id, 'invalid_exposure_expectation', error_msg)
        await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=get_cancel_entry_keyboard())
        return
    if detect_suspicious_activity(user_id, 'exposure_expectation_input', text):
        await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод ожидания (экспозиция)", text)
        return
    
    exposure_data = state_info['data']
    if 'expectations_data' not in exposure_data:
        exposure_data['expectations_data'] = []
    
    exposure_data['current_expectation'] = sanitize_text(text)
    db.save_user_state(user_id, States.WAITING_EXPOSURE_PROBABILITY, exposure_data)
    
    await update.message.reply_text(
        "📊 *Вероятность*\n\n"
        "Насколько вероятно, что это произойдет? Оцените от 0 до 100%.",
        reply_markup=add_cancel_button(get_intensity_keyboard()),
        parse_mode='Markdown'
    )

async def handle_exposure_probability(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Обрабатывает выбор вероятности (0-100) для ожидания"""
    user_id = query.from_user.id
    
    try:
        probability = int(data.replace('intensity_', ''))
    except ValueError:
        await query.answer("Неверное значение вероятности.", show_alert=True)
        return
    
    if probability < 0 or probability > 100:
        await query.answer("Вероятность должна быть от 0 до 100.", show_alert=True)
        return
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_PROBABILITY:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    exposure_data = state_info['data']
    current_expectation = exposure_data.get('current_expectation', '')
    
    # Сохраняем ожидание с вероятностью
    if 'expectations_data' not in exposure_data:
        exposure_data['expectations_data'] = []
    
    exposure_data['expectations_data'].append({
        'text': current_expectation,
        'probability': probability
    })
    
    # Переходим к выбору эмоций
    if 'emotions_before' not in exposure_data:
        exposure_data['emotions_before'] = []
    db.save_user_state(user_id, States.WAITING_EXPOSURE_EMOTION, exposure_data)
    
    await safe_edit_message(
        query,
        f"✅ Вероятность сохранена: {probability}%\n\n"
        "😊 *Эмоции*\n\n"
        "Какие эмоции вы ожидаете испытать?",
        reply_markup=add_cancel_button(get_emotions_keyboard()),
        parse_mode='Markdown'
    )

async def handle_exposure_emotion_choice(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Обрабатывает выбор эмоции для экспозиции"""
    user_id = query.from_user.id
    emotion = data.replace('emotion_', '')
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_EMOTION:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    exposure_data = state_info['data']
    
    if emotion == 'custom':
        # Убеждаемся, что в exposure_data есть маркер, что это экспозиция
        # Это поможет правильно определить тип записи при вводе кастомной эмоции
        if 'situation_name' not in exposure_data:
            logger.warning(f"Exposure emotion choice: situation_name not found in exposure_data for user {user_id}")
        db.save_user_state(user_id, States.WAITING_CUSTOM_EMOTION, exposure_data)
        await safe_edit_message(
            query,
            "Напишите свою эмоцию:",
            reply_markup=get_cancel_entry_keyboard()
        )
        return
    
    # Сохраняем текущую эмоцию
    exposure_data['current_emotion'] = emotion
    db.save_user_state(user_id, States.WAITING_EXPOSURE_EMOTION_INTENSITY, exposure_data)
    
    await safe_edit_message(
        query,
        f"✅ Эмоция выбрана: {emotion}\n\n"
        "📊 *Выраженность эмоции*\n\n"
        "Насколько выражена эта эмоция? Оцените от 0 до 100%.",
        reply_markup=add_cancel_button(get_intensity_keyboard()),
        parse_mode='Markdown'
    )

async def handle_exposure_emotion_intensity(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Обрабатывает выбор интенсивности эмоции для экспозиции"""
    user_id = query.from_user.id
    
    try:
        intensity = int(data.replace('intensity_', ''))
    except ValueError:
        await query.answer("Неверное значение интенсивности.", show_alert=True)
        return
    
    if intensity < 0 or intensity > 100:
        await query.answer("Интенсивность должна быть от 0 до 100.", show_alert=True)
        return
    
    state_info = db.get_user_state(user_id)
    if not state_info:
        logger.warning(f"State info not found for user {user_id}")
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    current_state = state_info['state']
    if current_state != States.WAITING_EXPOSURE_EMOTION_INTENSITY:
        logger.warning(f"Unexpected state for user {user_id}: expected WAITING_EXPOSURE_EMOTION_INTENSITY, got {current_state}")
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    exposure_data = state_info['data']
    emotion_name = exposure_data.get('current_emotion', '')
    
    if not emotion_name:
        logger.warning(f"No current_emotion in exposure_data for user {user_id}")
        await query.answer("Ошибка: эмоция не найдена. Начните заново.", show_alert=True)
        return
    
    # Убеждаемся, что emotions_before инициализирован
    if 'emotions_before' not in exposure_data:
        exposure_data['emotions_before'] = []
    
    exposure_data['emotions_before'].append({
        'emotion': emotion_name,
        'intensity': intensity
    })
    exposure_data.pop('current_emotion', None)
    
    db.save_user_state(user_id, States.WAITING_EXPOSURE_MORE_EMOTIONS, exposure_data)
    
    await safe_edit_message(
        query,
        f"✅ Выраженность сохранена: {intensity}%\n\n"
        "Будут еще эмоции?",
        reply_markup=add_cancel_button(get_yes_no_keyboard('exposure_emotion_yes', 'exposure_emotion_no')),
        parse_mode='Markdown'
    )

async def handle_exposure_custom_emotion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ввод кастомной эмоции для экспозиции"""
    user_id = update.effective_user.id
    text = update.message.text
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_CUSTOM_EMOTION:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    exposure_data = state_info['data']
    is_valid, error_msg = validate_emotion(text)
    if not is_valid:
        detect_suspicious_activity(user_id, 'invalid_exposure_emotion', error_msg)
        await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=get_cancel_entry_keyboard())
        return
    if detect_suspicious_activity(user_id, 'exposure_emotion_input', text):
        await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод эмоции (экспозиция)", text)
        return
    
    exposure_data['current_emotion'] = sanitize_text(text)
    # Убеждаемся, что emotions_before инициализирован
    if 'emotions_before' not in exposure_data:
        exposure_data['emotions_before'] = []
    db.save_user_state(user_id, States.WAITING_EXPOSURE_EMOTION_INTENSITY, exposure_data)
    
    # Отправляем сообщение с клавиатурой интенсивности
    sent_message = await update.message.reply_text(
        "📊 *Выраженность эмоции*\n\n"
        "Насколько выражена эта эмоция? Оцените от 0 до 100%.",
        reply_markup=add_cancel_button(get_intensity_keyboard()),
        parse_mode='Markdown'
    )
    
    # Сохраняем message_id для возможного удаления
    if sent_message:
        from message_tracker import save_message_id
        save_message_id(user_id, sent_message, update.message.chat.id)

async def handle_exposure_more_emotions(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Обрабатывает вопрос о дополнительных эмоциях для экспозиции"""
    user_id = query.from_user.id
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_MORE_EMOTIONS:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    exposure_data = state_info['data']
    
    if data == 'exposure_emotion_yes':
        # Возвращаемся к выбору эмоции
        db.save_user_state(user_id, States.WAITING_EXPOSURE_EMOTION, exposure_data)
        await safe_edit_message(
            query,
            "😊 *Эмоции*\n\n"
            "Какие еще эмоции вы ожидаете испытать?",
            reply_markup=add_cancel_button(get_emotions_keyboard()),
            parse_mode='Markdown'
        )
    elif data == 'exposure_emotion_no':
        # Переходим к вопросу о дополнительных ожиданиях
        db.save_user_state(user_id, States.WAITING_EXPOSURE_MORE_EXPECTATIONS, exposure_data)
        await safe_edit_message(
            query,
            "💭 *Дополнительные ожидания*\n\n"
            "Ожидаете ли вы что-то еще от этой ситуации?",
            reply_markup=add_cancel_button(get_yes_no_keyboard('exposure_expectation_yes', 'exposure_expectation_no')),
            parse_mode='Markdown'
        )

async def handle_exposure_more_expectations(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Обрабатывает вопрос о дополнительных ожиданиях для экспозиции"""
    user_id = query.from_user.id
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_MORE_EXPECTATIONS:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    exposure_data = state_info['data']
    
    if data == 'exposure_expectation_yes':
        # Возвращаемся к вводу ожидания
        db.save_user_state(user_id, States.WAITING_EXPOSURE_EXPECTATION, exposure_data)
        await safe_edit_message(
            query,
            "💭 *Ожидания*\n\n"
            "Что еще вы ожидаете от этой ситуации или чего боитесь?\n"
            "Опишите ваши ожидания или страхи.",
            reply_markup=get_cancel_entry_keyboard(),
            parse_mode='Markdown'
        )
    elif data == 'exposure_expectation_no':
        # Переходим к продолжительности события
        db.save_user_state(user_id, States.WAITING_EXPOSURE_DURATION, exposure_data)
        from utils import get_duration_keyboard
        await safe_edit_message(
            query,
            "⏱️ *Продолжительность события*\n\n"
            "Как долго будет длиться это событие? Выберите продолжительность в минутах:",
            reply_markup=add_cancel_button(get_duration_keyboard()),
            parse_mode='Markdown'
        )

async def handle_exposure_duration_choice(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Обрабатывает выбор продолжительности события через инлайн клавиатуру"""
    user_id = query.from_user.id
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_DURATION:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    exposure_data = state_info['data']
    
    if data == 'exposure_duration_manual':
        # Пользователь выбрал "я сам проработаю в удобное для себя время"
        exposure_data['event_duration'] = None  # Помечаем, что продолжительность не указана
        exposure_data['manual_processing'] = True  # Флаг для ручной проработки
        
        # Сохраняем запись в БД
        exposure_id = db.save_exposure(user_id, exposure_data)
        
        # Очищаем состояние
        db.clear_user_state(user_id)
        
        situation_name = escape_markdown(exposure_data.get('situation_name', 'Ситуация'))
        try:
            event_datetime_str = exposure_data['event_datetime']
            event_datetime_obj = datetime.fromisoformat(event_datetime_str)
            event_datetime_display = event_datetime_obj.strftime('%d.%m.%Y %H:%M')
        except:
            event_datetime_display = exposure_data.get('event_datetime', '')
        
        await safe_edit_message(
            query,
            f"✅ *Запись создана!*\n\n"
            f"*Событие:* «{situation_name}»\n"
            f"*Время:* {event_datetime_display}\n\n"
            f"Хорошо, вы можете проработать событие после в любое удобное для себя время в пункте 'Мои записи'.",
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    # Извлекаем количество минут из callback_data
    try:
        duration_minutes = int(data.replace('exposure_duration_', ''))
    except ValueError:
        await query.answer("Неверное значение продолжительности.", show_alert=True)
        return
    
    if duration_minutes <= 0:
        await query.answer("Продолжительность должна быть положительным числом.", show_alert=True)
        return
    
    exposure_data['event_duration'] = duration_minutes
    exposure_data['manual_processing'] = False
    
    # Сохраняем запись в БД
    exposure_id = db.save_exposure(user_id, exposure_data)
    
    # Планируем напоминание через указанное время после начала события
    try:
        from main import schedule_exposure_reminder
        event_datetime_str = exposure_data['event_datetime']
        event_datetime_obj = datetime.fromisoformat(event_datetime_str)
        reminder_datetime = event_datetime_obj + timedelta(minutes=duration_minutes)
        
        if hasattr(context, 'application') and context.application:
            schedule_exposure_reminder(context.application, user_id, exposure_id, reminder_datetime)
        else:
            logger.warning(f"Не удалось запланировать напоминание: application не доступен")
    except Exception as e:
        logger.error(f"Ошибка при планировании напоминания: {e}", exc_info=True)
    
    # Очищаем состояние
    db.clear_user_state(user_id)
    
    situation_name = escape_markdown(exposure_data.get('situation_name', 'Ситуация'))
    try:
        event_date = event_datetime_obj.strftime('%d.%m.%Y')
        event_time = event_datetime_obj.strftime('%H:%M')
        reminder_datetime_obj = event_datetime_obj + timedelta(minutes=duration_minutes)
        reminder_datetime_display = reminder_datetime_obj.strftime('%d.%m.%Y, %H:%M')
    except:
        event_date = exposure_data.get('event_datetime', '')
        event_time = ''
        reminder_datetime_display = ''
    
    duration_text = f"{duration_minutes} минут" if duration_minutes < 60 else f"{duration_minutes // 60} час(ов)"
    
    await safe_edit_message(
        query,
        f"✅ *Запись создана!*\n\n"
        f"*Событие:* «{situation_name}»\n"
        f"*Дата:* {event_date}\n"
        f"*Время:* {event_time}\n"
        f"*Продолжительность:* {duration_text}\n\n"
        f"Вы молодец! Я вернусь {reminder_datetime_display}, "
        f"чтобы узнать, как все прошло на самом деле. Если вам будет неудобно, "
        f"вы сможете самостоятельно проанализировать ситуацию в любое удобное для вас время в разделе *Мои записи*.",
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode='Markdown'
    )

async def handle_exposure_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ввод продолжительности события"""
    user_id = update.effective_user.id
    text = update.message.text.strip().lower()
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_DURATION:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    if detect_suspicious_activity(user_id, 'exposure_duration_input', text):
        await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод продолжительности (экспозиция)", text)
        return
    
    # Парсим продолжительность (например: "30 минут", "2 часа", "1.5 часа")
    import re
    duration_minutes = None
    
    # Ищем число и единицу измерения
    match = re.search(r'(\d+\.?\d*)\s*(минут|минуты|минуту|час|часа|часов|ч|м|мин)', text)
    if match:
        value = float(match.group(1))
        unit = match.group(2).lower()
        
        if unit in ['час', 'часа', 'часов', 'ч']:
            duration_minutes = int(value * 60)
        elif unit in ['минут', 'минуты', 'минуту', 'м', 'мин']:
            duration_minutes = int(value)
    else:
        # Пробуем просто число - считаем минутами
        try:
            duration_minutes = int(float(text))
        except ValueError:
            await update.message.reply_text(
                "⚠️ Неверный формат. Укажите продолжительность в минутах или часах.\n"
                "Например: '30 минут', '2 часа', '1.5 часа'",
                reply_markup=get_cancel_entry_keyboard()
            )
            return
    
    if duration_minutes is None or duration_minutes <= 0:
        await update.message.reply_text(
            "⚠️ Продолжительность должна быть положительным числом.",
            reply_markup=get_cancel_entry_keyboard()
        )
        return
    
    exposure_data = state_info['data']
    exposure_data['event_duration'] = duration_minutes
    
    # Сохраняем запись в БД
    exposure_id = db.save_exposure(user_id, exposure_data)
    
    # Парсим дату и время события для дальнейшего использования
    event_datetime_str = exposure_data['event_datetime']
    try:
        event_datetime_obj = datetime.fromisoformat(event_datetime_str)
    except:
        event_datetime_obj = None
    
    # Планируем напоминание через указанное время после начала события
    if event_datetime_obj:
        try:
            from main import schedule_exposure_reminder
            reminder_datetime = event_datetime_obj + timedelta(minutes=duration_minutes)
            
            if hasattr(context, 'application') and context.application:
                schedule_exposure_reminder(context.application, user_id, exposure_id, reminder_datetime)
            else:
                logger.warning(f"Не удалось запланировать напоминание: application не доступен")
        except Exception as e:
            logger.error(f"Ошибка при планировании напоминания: {e}", exc_info=True)
    
    # Очищаем состояние
    db.clear_user_state(user_id)
    
    situation_name = escape_markdown(exposure_data.get('situation_name', 'Ситуация'))
    if event_datetime_obj:
        try:
            event_date = event_datetime_obj.strftime('%d.%m.%Y')
            event_time = event_datetime_obj.strftime('%H:%M')
            reminder_datetime_obj = event_datetime_obj + timedelta(minutes=duration_minutes)
            reminder_datetime_display = reminder_datetime_obj.strftime('%d.%m.%Y, %H:%M')
        except:
            event_date = exposure_data.get('event_datetime', '')
            event_time = ''
            reminder_datetime_display = ''
    else:
        event_date = exposure_data.get('event_datetime', '')
        event_time = ''
        reminder_datetime_display = ''
    
    duration_text = f"{duration_minutes} минут" if duration_minutes < 60 else f"{duration_minutes // 60} час(ов)"
    
    await update.message.reply_text(
        f"✅ *Запись создана!*\n\n"
        f"*Событие:* «{situation_name}»\n"
        f"*Дата:* {event_date}\n"
        f"*Время:* {event_time}\n"
        f"*Продолжительность:* {duration_text}\n\n"
        f"Вы молодец! Я вернусь {reminder_datetime_display}, "
        f"чтобы узнать, как все прошло на самом деле. Если вам будет неудобно, "
        f"вы сможете самостоятельно проанализировать ситуацию в любое удобное для вас время в разделе *Мои записи*.",
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode='Markdown'
    )
    
    logger.info(f"Пользователь {user_id} создал экспозицию {exposure_id} с продолжительностью {duration_minutes} минут")

async def handle_exposure_expectations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ввод ожиданий (старый формат - для обратной совместимости)"""
    user_id = update.effective_user.id
    text = update.message.text
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_EXPECTATIONS:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    is_valid, error_msg = validate_exposure_expectation(text)
    if not is_valid:
        detect_suspicious_activity(user_id, 'invalid_exposure_expectations', error_msg)
        await update.message.reply_text(f"⚠️ {error_msg}")
        return
    if detect_suspicious_activity(user_id, 'exposure_expectations_input', text):
        await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод ожиданий (экспозиция, старый формат)", text)
        return
    
    exposure_data = state_info['data']
    exposure_data['expectations'] = sanitize_text(text)
    
    # Сохраняем запись в БД
    exposure_id = db.save_exposure(user_id, exposure_data)
    
    # Очищаем состояние
    db.clear_user_state(user_id)
    
    # Планируем напоминание через APScheduler
    # Импортируем функцию планирования
    try:
        from main import schedule_exposure_reminder
        event_datetime_str = exposure_data['event_datetime']
        event_datetime_obj = datetime.fromisoformat(event_datetime_str)
        reminder_datetime = event_datetime_obj + timedelta(minutes=30)
        # Получаем application из context
        if hasattr(context, 'application') and context.application:
            schedule_exposure_reminder(context.application, user_id, exposure_id, reminder_datetime)
        else:
            logger.warning(f"Не удалось запланировать напоминание: application не доступен")
    except Exception as e:
        logger.error(f"Ошибка при планировании напоминания: {e}", exc_info=True)
    
    situation_name = escape_markdown(exposure_data.get('situation_name', 'Ситуация'))
    try:
        event_datetime_display = event_datetime_obj.strftime('%d.%m.%Y %H:%M')
    except:
        event_datetime_display = event_datetime_str
    
    await update.message.reply_text(
        f"📅 *Запись создана!*\n\n"
        f"*Событие:* «{situation_name}»\n"
        f"*Время:* {event_datetime_display}\n"
        f"Ваши ожидания сохранены.\n\n"
        f"Я напомню вам через 30 минут после указанного времени, "
        f"чтобы узнать, как все прошло на самом деле.",
        parse_mode='Markdown'
    )

async def start_exposure_reality_fill(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, exposure_id: int) -> None:
    """Начинает процесс заполнения реальности для существующей экспозиции"""
    user_id = query.from_user.id
    
    exposure = db.get_exposure(exposure_id)
    if not exposure or exposure['user_id'] != user_id:
        await query.answer("Запись не найдена", show_alert=True)
        return
    
    if exposure.get('reality_received', 0):
        await query.answer("Эта экспозиция уже завершена", show_alert=True)
        return
    
    situation_name = escape_markdown(exposure.get('situation_name', 'Ситуация'))
    expectations_data = exposure.get('expectations_data', [])
    emotions_before = exposure.get('emotions_before', [])
    
    expectations_text = ""
    if expectations_data:
        expectations_text = "\n\n*Ваши ожидания:*\n"
        for i, exp in enumerate(expectations_data, 1):
            exp_text = escape_markdown(exp.get('text', ''))
            probability = exp.get('probability')
            prob_text = f" (вероятность: {probability}%)" if probability is not None else ""
            expectations_text += f"{i}. {exp_text}{prob_text}\n"
    
    emotions_text = ""
    if emotions_before:
        emotions_text = "\n\n*Эмоции, которые вы ожидали:*\n"
        for em in emotions_before:
            em_name = escape_markdown(em.get('emotion', ''))
            intensity = em.get('intensity', 0)
            emotions_text += f"• {em_name}: {intensity}%\n"
    
    # Инициализируем данные для процесса
    reality_data = {
        'exposure_id': exposure_id,
        'current_expectation_index': 0,
        'expectation_results': [],
        'emotions_after': []
    }
    
    # Если есть ожидания, начинаем с первого
    if expectations_data:
        first_exp = expectations_data[0]
        exp_text = escape_markdown(first_exp.get('text', ''))
        probability = first_exp.get('probability')
        prob_text = f" (вероятность: {probability}%)" if probability is not None else ""
        
        keyboard = [
            [InlineKeyboardButton("✅ Да", callback_data='expectation_fulfilled_yes')],
            [InlineKeyboardButton("❌ Нет", callback_data='expectation_fulfilled_no')],
            [InlineKeyboardButton("⚠️ Не совсем", callback_data='expectation_fulfilled_partially')],
            [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
        ]
        
        await safe_edit_message(
            query,
            f"⏰ *Время подвести итоги*\n\n"
            f"По ситуации «{situation_name}»{expectations_text}{emotions_text}\n\n"
            f"*Свершилось ли ваше ожидание?*\n"
            f"«{exp_text}»{prob_text}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
        db.save_user_state(user_id, States.WAITING_EXPOSURE_EXPECTATION_FULFILLED, reality_data)
    else:
        # Если нет ожиданий, сразу переходим к описанию реальности
        await safe_edit_message(
            query,
            f"⏰ *Время подвести итоги*\n\n"
            f"По ситуации «{situation_name}»{emotions_text}\n\n"
            f"*Как все прошло на самом деле?*",
            parse_mode='Markdown'
        )
        
        db.save_user_state(user_id, States.WAITING_EXPOSURE_REALITY_DESCRIPTION, reality_data)
    
    logger.info(f"Пользователь {user_id} начал заполнение реальности для экспозиции {exposure_id}")

async def send_exposure_reminder(bot, user_id: int, exposure_id: int) -> None:
    """Отправляет напоминание о необходимости заполнить реальность (новый процесс)"""
    try:
        exposure = db.get_exposure(exposure_id)
        if not exposure or exposure['user_id'] != user_id:
            logger.warning(f"Экспозиция {exposure_id} не найдена или принадлежит другому пользователю")
            return
        
        if exposure.get('reality_received', 0):
            logger.info(f"Реальность для экспозиции {exposure_id} уже получена")
            return
        
        # Отмечаем, что напоминание отправлено
        db.mark_exposure_reminder_sent(exposure_id)
        
        situation_name = escape_markdown(exposure.get('situation_name', 'Ситуация'))
        expectations_data = exposure.get('expectations_data', [])
        emotions_before = exposure.get('emotions_before', [])
        
        expectations_text = ""
        if expectations_data:
            expectations_text = "\n\n*Ваши ожидания:*\n"
            for i, exp in enumerate(expectations_data, 1):
                exp_text = escape_markdown(exp.get('text', ''))
                probability = exp.get('probability')
                prob_text = f" (вероятность: {probability}%)" if probability is not None else ""
                expectations_text += f"{i}. {exp_text}{prob_text}\n"
        
        emotions_text = ""
        if emotions_before:
            emotions_text = "\n\n*Эмоции, которые вы ожидали:*\n"
            for em in emotions_before:
                em_name = escape_markdown(em.get('emotion', ''))
                intensity = em.get('intensity', 0)
                emotions_text += f"• {em_name}: {intensity}%\n"
        
        # Инициализируем данные для процесса
        reality_data = {
            'exposure_id': exposure_id,
            'current_expectation_index': 0,
            'expectation_results': [],
            'emotions_after': []
        }
        
        # Если есть ожидания, начинаем с первого
        if expectations_data:
            first_exp = expectations_data[0]
            exp_text = escape_markdown(first_exp.get('text', ''))
            probability = first_exp.get('probability')
            prob_text = f" (вероятность: {probability}%)" if probability is not None else ""
            
            keyboard = [
                [InlineKeyboardButton("✅ Да", callback_data='expectation_fulfilled_yes')],
                [InlineKeyboardButton("❌ Нет", callback_data='expectation_fulfilled_no')],
                [InlineKeyboardButton("⚠️ Не совсем", callback_data='expectation_fulfilled_partially')],
                [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
            ]
            
            await bot.send_message(
                chat_id=user_id,
                text=f"⏰ *Время подвести итоги*\n\n"
                     f"По ситуации «{situation_name}»{expectations_text}{emotions_text}\n\n"
                     f"*Свершилось ли ваше ожидание?*\n"
                     f"«{exp_text}»{prob_text}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
            db.save_user_state(user_id, States.WAITING_EXPOSURE_EXPECTATION_FULFILLED, reality_data)
        else:
            # Если нет ожиданий, сразу переходим к описанию реальности
            await bot.send_message(
                chat_id=user_id,
                text=f"⏰ *Время подвести итоги*\n\n"
                     f"По ситуации «{situation_name}»{emotions_text}\n\n"
                     f"*Как все прошло на самом деле?*",
                parse_mode='Markdown'
            )
            
            db.save_user_state(user_id, States.WAITING_EXPOSURE_REALITY_DESCRIPTION, reality_data)
        
        logger.info(f"Отправлено напоминание о реальности для экспозиции {exposure_id} пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминания о реальности: {e}", exc_info=True)

async def handle_exposure_expectation_fulfilled(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Обрабатывает ответ на вопрос 'Свершилось ли ваше ожидание?'"""
    user_id = query.from_user.id
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_EXPECTATION_FULFILLED:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    reality_data = state_info['data']
    exposure_id = reality_data.get('exposure_id')
    exposure = db.get_exposure(exposure_id)
    
    if not exposure:
        await query.answer("Ошибка: запись не найдена.", show_alert=True)
        return
    
    expectations_data = exposure.get('expectations_data', [])
    current_index = reality_data.get('current_expectation_index', 0)
    
    # Сохраняем результат для текущего ожидания
    fulfilled_status = 'yes' if 'yes' in data else ('no' if 'no' in data else 'partially')
    reality_data['expectation_results'].append({
        'expectation': expectations_data[current_index],
        'fulfilled': fulfilled_status
    })
    
    # Переходим к следующему ожиданию или к описанию реальности
    current_index += 1
    reality_data['current_expectation_index'] = current_index
    
    if current_index < len(expectations_data):
        # Есть еще ожидания
        next_exp = expectations_data[current_index]
        exp_text = next_exp.get('text', '')
        probability = next_exp.get('probability')
        prob_text = f" (вероятность: {probability}%)" if probability is not None else ""
        
        keyboard = [
            [InlineKeyboardButton("✅ Да", callback_data='expectation_fulfilled_yes')],
            [InlineKeyboardButton("❌ Нет", callback_data='expectation_fulfilled_no')],
            [InlineKeyboardButton("⚠️ Не совсем", callback_data='expectation_fulfilled_partially')],
            [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
        ]
        
        await safe_edit_message(
            query,
            f"✅ Ответ сохранен\n\n"
            f"*Свершилось ли ваше ожидание?*\n"
            f"«{exp_text}»{prob_text}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
        db.save_user_state(user_id, States.WAITING_EXPOSURE_EXPECTATION_FULFILLED, reality_data)
    else:
        # Все ожидания обработаны, переходим к описанию реальности
        db.save_user_state(user_id, States.WAITING_EXPOSURE_REALITY_DESCRIPTION, reality_data)
        
        await safe_edit_message(
            query,
            "✅ Все ожидания обработаны\n\n"
            "*Как все прошло на самом деле?*\n\n"
            "Опишите, что происходило на самом деле, ваши чувства и ощущения.",
            reply_markup=get_cancel_entry_keyboard(),
            parse_mode='Markdown'
        )

async def handle_exposure_reality_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает описание реальности"""
    user_id = update.effective_user.id
    text = update.message.text
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_REALITY_DESCRIPTION:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    is_valid, error_msg = validate_exposure_reality_description(text)
    if not is_valid:
        detect_suspicious_activity(user_id, 'invalid_reality_description', error_msg)
        await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=get_cancel_entry_keyboard())
        return
    if detect_suspicious_activity(user_id, 'reality_description_input', text):
        await process_suspicious_input_and_notify_admin(update, context, user_id, "Описание реальности (экспозиция)", text)
        return
    
    reality_data = state_info['data']
    reality_data['reality_description'] = sanitize_text(text)
    
    db.save_user_state(user_id, States.WAITING_EXPOSURE_WHAT_MATCHED, reality_data)
    
    await update.message.reply_text(
        "✅ Описание сохранено\n\n"
        "*Что было именно так, как вы ожидали?*\n\n"
        "Опишите, что совпало с вашими ожиданиями.",
        reply_markup=get_cancel_entry_keyboard(),
        parse_mode='Markdown'
    )

async def handle_exposure_what_matched(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ответ 'Что было именно так, как вы ожидали?'"""
    user_id = update.effective_user.id
    text = update.message.text
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_WHAT_MATCHED:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    is_valid, error_msg = validate_exposure_reality_description(text)
    if not is_valid:
        detect_suspicious_activity(user_id, 'invalid_what_matched', error_msg)
        await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=get_cancel_entry_keyboard())
        return
    if detect_suspicious_activity(user_id, 'what_matched_input', text):
        await process_suspicious_input_and_notify_admin(update, context, user_id, "Что совпало (экспозиция)", text)
        return
    
    reality_data = state_info['data']
    reality_data['what_matched'] = sanitize_text(text)
    
    db.save_user_state(user_id, States.WAITING_EXPOSURE_WHAT_DIFFERED, reality_data)
    
    await update.message.reply_text(
        "✅ Ответ сохранен\n\n"
        "*Что было иначе?*\n\n"
        "Опишите, что отличалось от ваших ожиданий.",
        reply_markup=get_cancel_entry_keyboard(),
        parse_mode='Markdown'
    )

async def handle_exposure_what_differed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ответ 'Что было иначе?'"""
    user_id = update.effective_user.id
    text = update.message.text
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_WHAT_DIFFERED:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    is_valid, error_msg = validate_exposure_reality_description(text)
    if not is_valid:
        detect_suspicious_activity(user_id, 'invalid_what_differed', error_msg)
        await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=get_cancel_entry_keyboard())
        return
    if detect_suspicious_activity(user_id, 'what_differed_input', text):
        await process_suspicious_input_and_notify_admin(update, context, user_id, "Что было иначе (экспозиция)", text)
        return
    
    reality_data = state_info['data']
    reality_data['what_differed'] = sanitize_text(text)
    
    # Получаем экспозицию для показа эмоций
    exposure_id = reality_data.get('exposure_id')
    exposure = db.get_exposure(exposure_id)
    emotions_before = exposure.get('emotions_before', [])
    
    if emotions_before:
        # Сохраняем первую эмоцию для оценки
        reality_data['current_emotion_index'] = 0
        reality_data['current_emotion'] = emotions_before[0].get('emotion', '')
        reality_data['expected_intensity'] = emotions_before[0].get('intensity', 0)
        
        db.save_user_state(user_id, States.WAITING_EXPOSURE_REALITY_EMOTION_INTENSITY, reality_data)
        
        safe_emotion = escape_markdown(reality_data['current_emotion'])
        await update.message.reply_text(
            f"✅ Ответ сохранен\n\n"
            f"*Оценка эмоций*\n\n"
            f"Вы ожидали эмоцию '{safe_emotion}' с выраженностью {reality_data['expected_intensity']}%.\n\n"
            f"Какой была выраженность этой эмоции на самом деле? Оцените от 0 до 100%.",
            reply_markup=add_cancel_button(get_intensity_keyboard()),
            parse_mode='Markdown'
        )
    else:
        # Нет эмоций, переходим к вопросу о дополнительных эмоциях
        db.save_user_state(user_id, States.WAITING_EXPOSURE_REALITY_MORE_EMOTIONS, reality_data)
        
        await update.message.reply_text(
            "✅ Ответ сохранен\n\n"
            "*Дополнительные эмоции*\n\n"
            "Были ли еще эмоции, которые вы не ожидали?",
            reply_markup=add_cancel_button(get_yes_no_keyboard('exposure_reality_emotion_yes', 'exposure_reality_emotion_no')),
            parse_mode='Markdown'
        )

async def handle_exposure_reality_emotion_intensity(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Обрабатывает выбор интенсивности реальной эмоции"""
    user_id = query.from_user.id
    
    try:
        intensity = int(data.replace('intensity_', ''))
    except ValueError:
        await query.answer("Неверное значение интенсивности.", show_alert=True)
        return
    
    if intensity < 0 or intensity > 100:
        await query.answer("Интенсивность должна быть от 0 до 100.", show_alert=True)
        return
    
    state_info = db.get_user_state(user_id)
    if not state_info:
        logger.warning(f"State info not found for user {user_id} in handle_exposure_reality_emotion_intensity")
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    current_state = state_info['state']
    if current_state != States.WAITING_EXPOSURE_REALITY_EMOTION_INTENSITY:
        logger.warning(f"Unexpected state for user {user_id} in handle_exposure_reality_emotion_intensity: expected WAITING_EXPOSURE_REALITY_EMOTION_INTENSITY, got {current_state}")
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    reality_data = state_info['data']
    emotion_name = reality_data.get('current_emotion', '')
    expected_intensity = reality_data.get('expected_intensity')
    
    # Сохраняем реальную эмоцию
    if 'emotions_after' not in reality_data:
        reality_data['emotions_after'] = []
    
    # Если это дополнительная эмоция (не было expected_intensity), сохраняем только actual
    if expected_intensity is not None:
        reality_data['emotions_after'].append({
            'emotion': emotion_name,
            'intensity_expected': expected_intensity,
            'intensity_actual': intensity
        })
    else:
        # Дополнительная эмоция, которой не было в ожиданиях
        reality_data['emotions_after'].append({
            'emotion': emotion_name,
            'intensity_actual': intensity
        })
    
    # Проверяем, есть ли еще эмоции для оценки (только если это была ожидаемая эмоция)
    if expected_intensity is not None:
        exposure_id = reality_data.get('exposure_id')
        exposure = db.get_exposure(exposure_id)
        emotions_before = exposure.get('emotions_before', [])
        current_index = reality_data.get('current_emotion_index', 0) + 1
        
        if current_index < len(emotions_before):
            # Есть еще ожидаемые эмоции
            reality_data['current_emotion_index'] = current_index
            next_emotion = emotions_before[current_index]
            reality_data['current_emotion'] = next_emotion.get('emotion', '')
            reality_data['expected_intensity'] = next_emotion.get('intensity', 0)
            
            db.save_user_state(user_id, States.WAITING_EXPOSURE_REALITY_EMOTION_INTENSITY, reality_data)
            
            await safe_edit_message(
                query,
                f"✅ Выраженность сохранена: {intensity}%\n\n"
                f"*Оценка эмоций*\n\n"
                f"Вы ожидали эмоцию '{reality_data['current_emotion']}' с выраженностью {reality_data['expected_intensity']}%.\n\n"
                f"Какой была выраженность этой эмоции на самом деле? Оцените от 0 до 100%.",
                reply_markup=add_cancel_button(get_intensity_keyboard()),
                parse_mode='Markdown'
            )
            return
    
    # Все эмоции оценены, переходим к вопросу о дополнительных
    db.save_user_state(user_id, States.WAITING_EXPOSURE_REALITY_MORE_EMOTIONS, reality_data)
    
    await safe_edit_message(
        query,
        f"✅ Выраженность сохранена: {intensity}%\n\n"
        "*Дополнительные эмоции*\n\n"
        "Были ли еще эмоции, которые вы не ожидали?",
        reply_markup=add_cancel_button(get_yes_no_keyboard('exposure_reality_emotion_yes', 'exposure_reality_emotion_no')),
        parse_mode='Markdown'
    )

async def handle_exposure_reality_more_emotions(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Обрабатывает вопрос о дополнительных эмоциях в реальности"""
    user_id = query.from_user.id
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_REALITY_MORE_EMOTIONS:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    reality_data = state_info['data']
    
    if data == 'exposure_reality_emotion_yes':
        # Переходим к выбору эмоции
        db.save_user_state(user_id, States.WAITING_EXPOSURE_REALITY_EMOTION, reality_data)
        await safe_edit_message(
            query,
            "😊 *Дополнительные эмоции*\n\n"
            "Какие еще эмоции вы испытали?",
            reply_markup=add_cancel_button(get_emotions_keyboard()),
            parse_mode='Markdown'
        )
    elif data == 'exposure_reality_emotion_no':
        # Переходим к итоговому резюме
        logger.info(f"User {user_id} answered 'no' to additional emotions, showing final summary. Current state: {state_info['state']}")
        # Убеждаемся, что мы действительно в правильном состоянии
        if state_info['state'] != States.WAITING_EXPOSURE_REALITY_MORE_EMOTIONS:
            logger.warning(f"Unexpected state when showing final summary: {state_info['state']}, expected WAITING_EXPOSURE_REALITY_MORE_EMOTIONS")
        # Переходим к итоговому резюме
        await show_exposure_final_summary(query, context, reality_data)
        return  # Важно: возвращаемся, чтобы не продолжать выполнение

async def handle_exposure_reality_emotion_choice(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Обрабатывает выбор дополнительной эмоции в реальности"""
    user_id = query.from_user.id
    emotion = data.replace('emotion_', '')
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_REALITY_EMOTION:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    reality_data = state_info['data']
    
    if emotion == 'custom':
        reality_data['is_exposure_reality'] = True  # Маркер для обработки в text_handler
        db.save_user_state(user_id, States.WAITING_CUSTOM_NEW_EMOTION, reality_data)
        await safe_edit_message(
            query,
            "Напишите свою эмоцию:",
            reply_markup=get_cancel_entry_keyboard()
        )
        return
    
    reality_data['current_emotion'] = emotion
    db.save_user_state(user_id, States.WAITING_EXPOSURE_REALITY_EMOTION_INTENSITY, reality_data)
    
    await safe_edit_message(
        query,
        f"✅ Эмоция выбрана: {emotion}\n\n"
        "📊 *Выраженность эмоции*\n\n"
        "Насколько выражена была эта эмоция? Оцените от 0 до 100%.",
        reply_markup=add_cancel_button(get_intensity_keyboard()),
        parse_mode='Markdown'
    )

async def handle_exposure_custom_reality_emotion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ввод кастомной эмоции в реальности для экспозиции"""
    user_id = update.effective_user.id
    text = update.message.text
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_CUSTOM_NEW_EMOTION:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    reality_data = state_info['data']
    if not reality_data.get('is_exposure_reality'):
        return
    
    is_valid, error_msg = validate_emotion(text)
    if not is_valid:
        detect_suspicious_activity(user_id, 'invalid_exposure_reality_emotion', error_msg)
        await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=get_cancel_entry_keyboard())
        return
    if detect_suspicious_activity(user_id, 'exposure_reality_emotion_input', text):
        await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод эмоции в реальности (экспозиция)", text)
        return
    
    reality_data['current_emotion'] = sanitize_text(text)
    reality_data.pop('is_exposure_reality', None)
    # Убеждаемся, что expected_intensity не установлен для дополнительных эмоций
    reality_data.pop('expected_intensity', None)
    db.save_user_state(user_id, States.WAITING_EXPOSURE_REALITY_EMOTION_INTENSITY, reality_data)
    
    # Отправляем сообщение с клавиатурой интенсивности
    sent_message = await update.message.reply_text(
        "📊 *Выраженность эмоции*\n\n"
        "Насколько выражена была эта эмоция? Оцените от 0 до 100%.",
        reply_markup=add_cancel_button(get_intensity_keyboard()),
        parse_mode='Markdown'
    )
    
    # Сохраняем message_id для возможного удаления
    if sent_message:
        save_message_id(user_id, sent_message, update.message.chat.id)

async def show_exposure_final_summary(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, reality_data: dict) -> None:
    """Показывает итоговое резюме и просит написать итог"""
    user_id = query.from_user.id
    exposure_id = reality_data.get('exposure_id')
    
    logger.info(f"Showing final summary for user {user_id}, exposure_id: {exposure_id}")
    
    exposure = db.get_exposure(exposure_id)
    
    if not exposure:
        logger.error(f"Exposure not found for user {user_id}, exposure_id: {exposure_id}")
        await query.answer("Ошибка: запись не найдена.", show_alert=True)
        return
    
    situation_name = escape_markdown(exposure.get('situation_name', 'Ситуация'))
    expectations_data = exposure.get('expectations_data', [])
    emotions_before = exposure.get('emotions_before', [])
    expectation_results = reality_data.get('expectation_results', [])
    emotions_after = reality_data.get('emotions_after', [])
    reality_description = escape_markdown(reality_data.get('reality_description', ''))
    what_matched = escape_markdown(reality_data.get('what_matched', ''))
    what_differed = escape_markdown(reality_data.get('what_differed', ''))
    
    summary_text = f"📊 *Итоговое резюме*\n\n"
    summary_text += f"*Событие:* «{situation_name}»\n\n"
    
    if expectations_data:
        summary_text += "*Ваши ожидания:*\n"
        for i, exp in enumerate(expectations_data, 1):
            exp_text = escape_markdown(exp.get('text', ''))
            probability = exp.get('probability')
            prob_text = f" (вероятность: {probability}%)" if probability is not None else ""
            result = "❓ Не оценено"
            if i <= len(expectation_results):
                fulfilled = expectation_results[i-1].get('fulfilled', '')
                if fulfilled == 'yes':
                    result = "✅ Да"
                elif fulfilled == 'no':
                    result = "❌ Нет"
                elif fulfilled == 'partially':
                    result = "⚠️ Не совсем"
            summary_text += f"{i}. {exp_text}{prob_text} - {result}\n"
        summary_text += "\n"
    
    if emotions_before:
        summary_text += "*Эмоции, которые вы ожидали:*\n"
        for em in emotions_before:
            em_name = escape_markdown(em.get('emotion', ''))
            intensity = em.get('intensity', 0)
            summary_text += f"• {em_name}: {intensity}%\n"
        summary_text += "\n"
    
    if reality_description:
        summary_text += f"*Как все прошло на самом деле:*\n{reality_description}\n\n"
    
    if what_matched:
        summary_text += f"*Что было именно так, как вы ожидали:*\n{what_matched}\n\n"
    
    if what_differed:
        summary_text += f"*Что было иначе:*\n{what_differed}\n\n"
    
    if emotions_after:
        summary_text += "*Эмоции в реальности:*\n"
        for em in emotions_after:
            em_name = escape_markdown(em.get('emotion', ''))
            intensity_expected = em.get('intensity_expected')
            intensity_actual = em.get('intensity_actual', 0)
            if intensity_expected is not None:
                summary_text += f"• {em_name}: ожидали {intensity_expected}%, было {intensity_actual}%\n"
            else:
                summary_text += f"• {em_name}: {intensity_actual}%\n"
        summary_text += "\n"
    
    summary_text += "——————————\n\n"
    summary_text += "*Напишите итог:*\n\n"
    summary_text += "Подведите итог: что вы узнали из этой ситуации? Что было важным?"
    
    db.save_user_state(user_id, States.WAITING_EXPOSURE_FINAL_SUMMARY, reality_data)
    
    await safe_edit_message(
        query,
        summary_text,
        reply_markup=get_cancel_entry_keyboard(),
        parse_mode='Markdown'
    )

async def handle_exposure_final_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает итоговое резюме"""
    user_id = update.effective_user.id
    text = update.message.text
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_FINAL_SUMMARY:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    is_valid, error_msg = validate_exposure_summary(text)
    if not is_valid:
        detect_suspicious_activity(user_id, 'invalid_final_summary', error_msg)
        await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=get_cancel_entry_keyboard())
        return
    if detect_suspicious_activity(user_id, 'final_summary_input', text):
        await process_suspicious_input_and_notify_admin(update, context, user_id, "Итоговое резюме (экспозиция)", text)
        return
    
    reality_data = state_info['data']
    exposure_id = reality_data.get('exposure_id')
    
    # Формируем полное резюме для сохранения
    exposure = db.get_exposure(exposure_id)
    if not exposure:
        await update.message.reply_text("Ошибка: запись не найдена.")
        return
    
    # Формируем итоговый текст для сохранения
    import json
    final_summary = {
        'reality_description': reality_data.get('reality_description', ''),
        'what_matched': reality_data.get('what_matched', ''),
        'what_differed': reality_data.get('what_differed', ''),
        'expectation_results': reality_data.get('expectation_results', []),
        'emotions_after': reality_data.get('emotions_after', []),
        'final_summary': sanitize_text(text)
    }
    
    # Обновляем запись в БД
    reality_text = json.dumps(final_summary, ensure_ascii=False, indent=2)
    emotions_after = reality_data.get('emotions_after', [])
    final_summary_text = final_summary.get('final_summary', '')
    
    success = db.update_exposure_reality(
        exposure_id, 
        reality_text,
        emotions_after=emotions_after,
        comparison=final_summary_text
    )
    
    if not success:
        await update.message.reply_text("Ошибка при сохранении данных.")
        return
    
    # Очищаем состояние
    db.clear_user_state(user_id)
    
    await update.message.reply_text(
        "✅ *Итог сохранен!*\n\n"
        "Спасибо! Эта запись сохранена в вашем дневнике. "
        "Регулярное сравнение ожиданий и реальности помогает мозгу учиться на опыте и снижать тревогу.",
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode='Markdown'
    )
    
    logger.info(f"Пользователь {user_id} завершил заполнение реальности для экспозиции {exposure_id}")

async def handle_exposure_reality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ввод реальности (старый формат - для обратной совместимости)"""
    user_id = update.effective_user.id
    text = update.message.text
    
    state_info = db.get_user_state(user_id)
    if not state_info or state_info['state'] != States.WAITING_EXPOSURE_REALITY:
        await update.message.reply_text("Используйте команду /menu для начала работы.")
        return
    
    is_valid, error_msg = validate_exposure_reality_description(text)
    if not is_valid:
        detect_suspicious_activity(user_id, 'invalid_exposure_reality', error_msg)
        await update.message.reply_text(f"⚠️ {error_msg}")
        return
    if detect_suspicious_activity(user_id, 'exposure_reality_input', text):
        await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод реальности (экспозиция, старый формат)", text)
        return
    
    exposure_id = state_info['data'].get('exposure_id')
    if not exposure_id:
        await update.message.reply_text("Ошибка: не найден ID экспозиции.")
        return
    
    success = db.update_exposure_reality(exposure_id, sanitize_text(text))
    
    if not success:
        await update.message.reply_text("Ошибка при сохранении данных.")
        return
    
    # Получаем полную запись для сравнения
    exposure = db.get_exposure(exposure_id)
    if not exposure:
        await update.message.reply_text("Ошибка: запись не найдена.")
        return
    
    # Очищаем состояние
    db.clear_user_state(user_id)
    
    # Формируем сравнение
    expectations = exposure.get('expectations', '')
    reality = exposure.get('reality', '')
    
    comparison_text = (
        f"📊 *Сравнение:*\n"
        f"——————————\n"
        f"**Тогда вы ожидали:**\n{expectations}\n"
        f"——————————\n"
        f"**Сейчас вы сообщили:**\n{reality}\n"
        f"——————————\n\n"
        f"Спасибо! Эта запись сохранена в вашем дневнике. "
        f"Регулярное сравнение ожиданий и реальности помогает мозгу учиться на опыте и снижать тревогу."
    )
    
    await update.message.reply_text(
        comparison_text,
        parse_mode='Markdown',
        reply_markup=get_back_to_menu_keyboard()
    )
    
    logger.info(f"Пользователь {user_id} заполнил реальность для экспозиции {exposure_id}")

def _format_exposure_detail(exposure: dict) -> tuple:
    """Формирует текст и клавиатуру для отображения деталей экспозиции"""
    import json
    exposure_id = exposure['id']
    situation_name = escape_markdown(exposure.get('situation_name', 'Без названия'))
    event_datetime = exposure.get('event_datetime', '')
    expectations_data = exposure.get('expectations_data', [])
    emotions_before = exposure.get('emotions_before', [])
    reality = exposure.get('reality', '')
    emotions_after = exposure.get('emotions_after', [])
    comparison = exposure.get('comparison', '')
    event_duration = exposure.get('event_duration')
    
    if event_datetime:
        try:
            dt = datetime.fromisoformat(event_datetime)
            date_str = dt.strftime('%d.%m.%Y %H:%M')
        except:
            date_str = event_datetime
    else:
        date_str = 'Дата не указана'
    
    status = "✅ Завершено" if exposure.get('reality_received', 0) else "⏳ Ожидает заполнения"
    
    detail_text = f"📅 *Экспозиция*\n\n"
    detail_text += f"*Название:* {situation_name}\n"
    detail_text += f"*Дата и время события:* {date_str}\n"
    if event_duration:
        duration_text = f"{event_duration} минут" if event_duration < 60 else f"{event_duration // 60} час(ов)"
        detail_text += f"*Продолжительность:* {duration_text}\n"
    detail_text += f"*Статус:* {status}\n\n"
    
    if expectations_data:
        detail_text += "*Ожидания:*\n"
        for i, exp in enumerate(expectations_data, 1):
            exp_text = escape_markdown(exp.get('text', ''))
            probability = exp.get('probability')
            if probability is not None:
                detail_text += f"{i}. {exp_text} (вероятность: {probability}%)\n"
            else:
                detail_text += f"{i}. {exp_text}\n"
        detail_text += "\n"
    elif exposure.get('expectations'):
        detail_text += f"*Ожидания:*\n{escape_markdown(exposure.get('expectations', ''))}\n\n"
    
    if emotions_before:
        detail_text += "*Эмоции, которые вы ожидали:*\n"
        for em in emotions_before:
            em_name = escape_markdown(em.get('emotion', ''))
            intensity = em.get('intensity', 0)
            detail_text += f"• {em_name}: {intensity}%\n"
        detail_text += "\n"
    
    if reality:
        try:
            if isinstance(reality, str):
                try:
                    reality_data = json.loads(reality)
                except (json.JSONDecodeError, ValueError):
                    detail_text += f"*Реальность:*\n{escape_markdown(str(reality))}\n"
                    reality_data = None
            else:
                reality_data = reality
            
            if reality_data and isinstance(reality_data, dict):
                reality_description = reality_data.get('realitydescription', '') or reality_data.get('reality_description', '')
                what_matched = reality_data.get('whatmatched', '') or reality_data.get('what_matched', '')
                what_differed = reality_data.get('whatdiffered', '') or reality_data.get('what_differed', '')
                expectation_results = reality_data.get('expectationresults', []) or reality_data.get('expectation_results', [])
                emotions_after_data = reality_data.get('emotionsafter', []) or reality_data.get('emotions_after', [])
                final_summary = reality_data.get('finalsummary', '') or reality_data.get('final_summary', '')
                
                detail_text += "*Реальность:*\n\n"
                if reality_description:
                    detail_text += f"*Как все прошло на самом деле:*\n{escape_markdown(reality_description)}\n\n"
                if expectation_results:
                    detail_text += "*Результаты ожиданий:*\n"
                    for i, result in enumerate(expectation_results, 1):
                        exp_data = result.get('expectation', {})
                        exp_text = escape_markdown(exp_data.get('text', ''))
                        fulfilled = result.get('fulfilled', '')
                        fulfilled_text = "✅ Да" if fulfilled == 'yes' else ("❌ Нет" if fulfilled == 'no' else ("⚠️ Не совсем" if fulfilled == 'partially' else "❓ Не оценено"))
                        detail_text += f"{i}. {exp_text} - {fulfilled_text}\n"
                    detail_text += "\n"
                if what_matched:
                    detail_text += f"*Что было именно так, как вы ожидали:*\n{escape_markdown(what_matched)}\n\n"
                if what_differed:
                    detail_text += f"*Что было иначе:*\n{escape_markdown(what_differed)}\n\n"
                if emotions_after_data:
                    detail_text += "*Эмоции в реальности:*\n"
                    for em in emotions_after_data:
                        em_name = escape_markdown(em.get('emotion', ''))
                        intensity_expected = em.get('intensityexpected') or em.get('intensity_expected')
                        intensity_actual = em.get('intensityactual') or em.get('intensity_actual', 0)
                        if intensity_expected is not None:
                            detail_text += f"• {em_name}: ожидали {intensity_expected}%, было {intensity_actual}%\n"
                        else:
                            detail_text += f"• {em_name}: {intensity_actual}%\n"
                    detail_text += "\n"
                if final_summary:
                    detail_text += f"*Итоговое резюме:*\n{escape_markdown(final_summary)}\n"
            else:
                detail_text += f"*Реальность:*\n{escape_markdown(str(reality))}\n"
        except (json.JSONDecodeError, TypeError):
            detail_text += f"*Реальность:*\n{escape_markdown(str(reality))}\n"
    else:
        detail_text += "*Реальность:*\nЕще не заполнено\n"
    
    if emotions_after:
        emotions_already_shown = False
        if reality:
            try:
                reality_data_check = json.loads(reality) if isinstance(reality, str) else reality
                if isinstance(reality_data_check, dict):
                    emotions_after_in_reality = reality_data_check.get('emotionsafter', []) or reality_data_check.get('emotions_after', [])
                    if emotions_after_in_reality:
                        emotions_already_shown = True
            except (json.JSONDecodeError, TypeError):
                pass
        if not emotions_already_shown:
            detail_text += "\n*Эмоции в реальности:*\n"
            for em in emotions_after:
                em_name = em.get('emotion', '')
                intensity_expected = em.get('intensity_expected')
                intensity_actual = em.get('intensity_actual', 0)
                if intensity_expected is not None:
                    detail_text += f"• {em_name}: ожидали {intensity_expected}%, было {intensity_actual}%\n"
                else:
                    detail_text += f"• {em_name}: {intensity_actual}%\n"
    
    if comparison:
        detail_text += f"\n*Сравнение:*\n{escape_markdown(str(comparison))}\n"
    
    keyboard = []
    if not exposure.get('reality_received', 0):
        keyboard.append([InlineKeyboardButton("✏️ Доработать", callback_data=f'exposure_fill_reality_{exposure_id}')])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='my_exposures')])
    
    return detail_text, keyboard

async def show_exposure_detail(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Показывает детали конкретной экспозиции"""
    user_id = query.from_user.id
    
    try:
        exposure_id = int(data.replace('exposure_', ''))
    except ValueError:
        await query.answer("Неверный идентификатор записи.", show_alert=True)
        return
    
    from handlers import request_password_for_action
    if await request_password_for_action(query, context, 'show_exposure_detail', {'exposure_id': exposure_id}, section='my_entries'):
        return
    
    exposure = db.get_exposure(exposure_id)
    if not exposure or exposure['user_id'] != user_id:
        await query.answer("Запись не найдена", show_alert=True)
        return
    
    detail_text, keyboard = _format_exposure_detail(exposure)
    
    await safe_edit_message(
        query,
        detail_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ========== Функции после проверки пароля ==========

async def show_my_exposures_after_password(bot, user_id: int, chat_id: int, message_id: int) -> None:
    """Показывает список экспозиций после проверки пароля"""
    exposures = db.get_user_exposures(user_id)
    if not exposures:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="📂 *Мои записи экспозиций*\n\nУ вас пока нет записей. Создайте новую запись.",
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode='Markdown'
        )
        return
    keyboard = []
    for exposure in exposures[:20]:
        situation_name = exposure.get('situation_name', 'Без названия')
        event_datetime = exposure.get('event_datetime', '')
        reality_received = exposure.get('reality_received', 0)
        if event_datetime:
            try:
                dt = datetime.fromisoformat(event_datetime)
                date_str = dt.strftime('%d.%m.%Y %H:%M')
            except:
                date_str = event_datetime
        else:
            date_str = 'Дата не указана'
        warning_emoji = "⚠️ " if not reality_received else ""
        preview = f"{warning_emoji}{date_str}: {situation_name[:30]}{'...' if len(situation_name) > 30 else ''}"
        keyboard.append([InlineKeyboardButton(preview, callback_data=f"exposure_{exposure['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 В меню", callback_data='menu')])
    incomplete_count = sum(1 for e in exposures if not e.get('reality_received', 0))
    incomplete_text = f"\n⚠️ Недоработанных: {incomplete_count}" if incomplete_count > 0 else ""
    await bot.edit_message_text(
        chat_id=chat_id, message_id=message_id,
        text=f"📂 *Мои записи экспозиций*\n\nВсего записей: {len(exposures)}{incomplete_text}\n\nВыберите запись для просмотра:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def show_download_period_exposure_after_password(bot, user_id: int, chat_id: int, message_id: int) -> None:
    """Показывает меню скачивания экспозиций после проверки пароля"""
    from utils import get_period_keyboard
    await bot.edit_message_text(
        chat_id=chat_id, message_id=message_id,
        text="📥 *Скачать записи экспозиций*\n\nВыберите период для скачивания:",
        reply_markup=get_period_keyboard(action_prefix='download_exposure'),
        parse_mode='Markdown'
    )

async def show_delete_period_exposure_after_password(bot, user_id: int, chat_id: int, message_id: int) -> None:
    """Показывает меню удаления экспозиций после проверки пароля"""
    from utils import get_period_keyboard
    await bot.edit_message_text(
        chat_id=chat_id, message_id=message_id,
        text="🗑️ *Удалить записи экспозиций*\n\n⚠️ Внимание! Это действие необратимо.\n\nВыберите период для удаления:",
        reply_markup=get_period_keyboard(action_prefix='delete_exposure'),
        parse_mode='Markdown'
    )

async def show_exposure_detail_after_password(bot, user_id: int, chat_id: int, message_id: int, action_data: dict) -> None:
    """Показывает детали экспозиции после проверки пароля"""
    exposure_id = action_data.get('exposure_id')
    if not exposure_id:
        return
    exposure = db.get_exposure(exposure_id)
    if not exposure or exposure['user_id'] != user_id:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="Запись не найдена")
        return
    detail_text, keyboard = _format_exposure_detail(exposure)
    await bot.edit_message_text(
        chat_id=chat_id, message_id=message_id,
        text=detail_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ========== Функции для меню ==========

async def show_my_exposures(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает список записей экспозиций пользователя"""
    user_id = query.from_user.id
    
    from admin import is_admin
    if not is_admin(query.from_user):
        if not check_user_consent(user_id):
            await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
            return
        allowed, error_msg = check_rate_limit(user_id, 'command')
        if not allowed:
            await query.answer(error_msg, show_alert=True)
            return
    
    from handlers import request_password_for_action
    if await request_password_for_action(query, context, 'show_my_exposures', section='my_entries'):
        return
    
    exposures = db.get_user_exposures(user_id)
    
    if not exposures:
        await safe_edit_message(
            query,
            "📂 *Мои записи экспозиций*\n\n"
            "У вас пока нет записей. Создайте новую запись, чтобы начать вести дневник экспозиций.",
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    # Показываем последние 20 записей
    keyboard = []
    for exposure in exposures[:20]:
        situation_name = exposure.get('situation_name', 'Без названия')
        event_datetime = exposure.get('event_datetime', '')
        reality_received = exposure.get('reality_received', 0)
        
        if event_datetime:
            try:
                dt = datetime.fromisoformat(event_datetime)
                date_str = dt.strftime('%d.%m.%Y %H:%M')
            except:
                date_str = event_datetime
        else:
            date_str = 'Дата не указана'
        
        # Добавляем эмодзи ⚠️ для недоработанных записей
        warning_emoji = "⚠️ " if not reality_received else ""
        
        preview = f"{warning_emoji}{date_str}: {situation_name[:30]}"
        if len(situation_name) > 30:
            preview += "..."
        
        keyboard.append([InlineKeyboardButton(preview, callback_data=f"exposure_{exposure['id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 В меню", callback_data='menu')])
    
    # Подсчитываем недоработанные записи
    incomplete_count = sum(1 for e in exposures if not e.get('reality_received', 0))
    incomplete_text = f"\n⚠️ Недоработанных: {incomplete_count}" if incomplete_count > 0 else ""
    
    await safe_edit_message(
        query,
        f"📂 *Мои записи экспозиций*\n\n"
        f"Всего записей: {len(exposures)}{incomplete_text}\n\n"
        f"Выберите запись для просмотра:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def show_download_period_exposure(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает меню выбора периода для скачивания экспозиций"""
    user_id = query.from_user.id
    
    from admin import is_admin
    if not is_admin(query.from_user):
        if not check_user_consent(user_id):
            await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
            return
        allowed, error_msg = check_rate_limit(user_id, 'command')
        if not allowed:
            await query.answer(error_msg, show_alert=True)
            return
    
    from handlers import request_password_for_action
    if await request_password_for_action(query, context, 'show_download_period_exposure', section='download'):
        return
    
    from utils import get_period_keyboard
    await safe_edit_message(
        query,
        "📥 *Скачать записи экспозиций*\n\n"
        "Выберите период для скачивания:",
        reply_markup=get_period_keyboard(action_prefix='download_exposure'),
        parse_mode='Markdown'
    )

async def send_template_exposure(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет шаблон дневника экспозиций"""
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
    
    import os
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, 'docs', 'Шаблон_дневника_экспозиций.docx')
    
    if os.path.exists(template_path):
        try:
            with open(template_path, 'rb') as doc:
                await query.message.reply_document(
                    document=doc,
                    filename='Шаблон_дневника_экспозиций.docx',
                    caption="📄 Шаблон дневника экспозиций"
                )
            await query.answer("Шаблон отправлен")
            await safe_edit_message(
                query,
                "✅ Шаблон отправлен!",
                reply_markup=get_back_to_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке шаблона: {e}")
            await query.answer("Ошибка при отправке шаблона", show_alert=True)
    else:
        await query.answer("Шаблон не найден", show_alert=True)
        await safe_edit_message(
            query,
            "⚠️ Шаблон временно недоступен.",
            reply_markup=get_back_to_menu_keyboard()
        )

async def show_delete_period_exposure(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает меню выбора периода для удаления экспозиций"""
    user_id = query.from_user.id
    
    from admin import is_admin
    if not is_admin(query.from_user):
        if not check_user_consent(user_id):
            await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
            return
        allowed, error_msg = check_rate_limit(user_id, 'command')
        if not allowed:
            await query.answer(error_msg, show_alert=True)
            return
    
    from handlers import request_password_for_action
    if await request_password_for_action(query, context, 'show_delete_period_exposure', section='delete'):
        return
    
    from utils import get_period_keyboard
    await safe_edit_message(
        query,
        "🗑️ *Удалить записи экспозиций*\n\n"
        "⚠️ Внимание! Это действие необратимо.\n\n"
        "Выберите период для удаления:",
        reply_markup=get_period_keyboard(action_prefix='delete_exposure'),
        parse_mode='Markdown'
    )

async def show_user_statistics_exposure(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает статистику по экспозициям"""
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
    
    exposures = db.get_user_exposures(user_id)
    
    total = len(exposures)
    completed = sum(1 for e in exposures if e.get('reality_received', 0))
    pending = total - completed
    
    stats_text = (
        f"📊 *Статистика экспозиций*\n\n"
        f"*Всего записей:* {total}\n"
        f"*Завершено:* {completed}\n"
        f"*Ожидают заполнения:* {pending}"
    )
    
    await safe_edit_message(
        query,
        stats_text,
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode='Markdown'
    )

async def show_search_menu_exposure(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает меню поиска экспозиций"""
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
    if await request_password_for_action(query, context, 'show_search_menu_exposure', section='search'):
        return
    
    keyboard = [
        [InlineKeyboardButton("🔍 Поиск по тексту", callback_data='search_exposure_text')],
        [InlineKeyboardButton("📅 Поиск по дате", callback_data='search_exposure_date')],
        [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
    ]
    
    await safe_edit_message(
        query,
        "🔍 *Поиск экспозиций*\n\n"
        "Выберите способ поиска:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_period_choice_exposure(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Обрабатывает выбор периода для экспозиций"""
    user_id = query.from_user.id
    
    if data.startswith('download_exposure_'):
        period = data.replace('download_exposure_', '')
        from datetime import timedelta
        now = datetime.now()
        
        if period == '7':
            start_date = (now - timedelta(days=7)).isoformat()
        elif period == '30':
            start_date = (now - timedelta(days=30)).isoformat()
        elif period == 'all':
            start_date = None
        elif period == 'custom':
            # Сохраняем состояние для выбора даты
            db.save_user_state(user_id, States.WAITING_DOWNLOAD_START_DATE, {'action_type': 'download', 'entry_type': 'exposure'})
            await safe_edit_message(
                query,
                "📅 Выберите начальную дату:",
                reply_markup=create_calendar(prefix='download_exposure'),
                parse_mode='Markdown'
            )
            return
        else:
            await query.answer("Выберите период из списка", show_alert=True)
            return
        
        exposures = db.get_user_exposures(user_id, start_date=start_date)
        
        if not exposures:
            await safe_edit_message(
                query,
                "❌ Записи не найдены за выбранный период.",
                reply_markup=get_back_to_menu_keyboard(),
                parse_mode='Markdown'
            )
            return
        
        # Генерируем Excel
        from excel_generator import generate_excel
        excel_path = generate_excel(exposures, user_id, entry_type='exposure')
        
        try:
            with open(excel_path, 'rb') as excel_file:
                await query.message.reply_document(
                    document=excel_file,
                    filename=f'Экспозиции_{user_id}.xlsx',
                    caption=f"📥 Экспортировано записей: {len(exposures)}"
                )
            await query.answer("Файл отправлен")
            # Удаляем временный файл
            import os
            if os.path.exists(excel_path):
                os.remove(excel_path)
        except Exception as e:
            logger.error(f"Ошибка при отправке Excel: {e}")
            await query.answer("Ошибка при создании файла", show_alert=True)
    
    elif data.startswith('delete_exposure_'):
        period = data.replace('delete_exposure_', '')
        from datetime import timedelta
        now = datetime.now()
        
        if period == '7':
            start_date = (now - timedelta(days=7)).isoformat()
        elif period == '30':
            start_date = (now - timedelta(days=30)).isoformat()
        elif period == 'all':
            start_date = None
        elif period == 'custom':
            # Сохраняем состояние для выбора даты
            db.save_user_state(user_id, States.WAITING_DELETE_START_DATE, {'action_type': 'delete', 'entry_type': 'exposure'})
            await safe_edit_message(
                query,
                "📅 Выберите начальную дату:",
                reply_markup=create_calendar(prefix='delete_exposure'),
                parse_mode='Markdown'
            )
            return
        else:
            await query.answer("Выберите период из списка", show_alert=True)
            return
        
        exposures = db.get_user_exposures(user_id, start_date=start_date)
        count = len(exposures)
        
        if count == 0:
            await safe_edit_message(
                query,
                "За выбранный период записей не найдено.",
                reply_markup=get_back_to_menu_keyboard(),
                parse_mode='Markdown'
            )
            return
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f'confirm_delete_exposure_{count}_{period}'),
                InlineKeyboardButton("❌ Отмена", callback_data='menu')
            ]
        ]
        
        await safe_edit_message(
            query,
            f"⚠️ *Подтверждение удаления*\n\n"
            f"Количество записей: *{count}*\n\n"
            f"Вы уверены, что хотите удалить эти записи?\n\n"
            f"Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def handle_confirm_delete_exposures(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    """Подтверждает и выполняет удаление экспозиций"""
    user_id = query.from_user.id
    parts = data.replace('confirm_delete_exposure_', '').split('_')
    count = int(parts[0])
    period = parts[1] if len(parts) > 1 else 'all'
    
    from datetime import timedelta
    now = datetime.now()
    
    # Проверяем, есть ли сохраненные даты в состоянии (для custom периода)
    state_info = db.get_user_state(user_id)
    if state_info and state_info.get('state') == States.WAITING_DELETE_CONFIRMATION:
        entry_data = state_info['data']
        if entry_data.get('entry_type') == 'exposure' and entry_data.get('delete_start_date'):
            start_date = entry_data.get('delete_start_date')
            end_date = entry_data.get('delete_end_date')
            exposures = db.get_user_exposures(user_id, start_date=start_date, end_date=end_date)
        else:
            exposures = []
    else:
        if period == '7':
            start_date = (now - timedelta(days=7)).isoformat()
        elif period == '30':
            start_date = (now - timedelta(days=30)).isoformat()
        elif period == 'all':
            start_date = None
        else:
            await query.answer("Ошибка: неверный период", show_alert=True)
            return
        
        exposures = db.get_user_exposures(user_id, start_date=start_date)
    
    deleted_count = 0
    
    for exposure in exposures:
        if db.delete_exposure(exposure['id'], user_id):
            deleted_count += 1
    
    db.clear_user_state(user_id)
    
    await safe_edit_message(
        query,
        f"✅ Удалено записей: {deleted_count}",
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode='Markdown'
    )
    logger.info(f"Пользователь {user_id} удалил {deleted_count} экспозиций")
