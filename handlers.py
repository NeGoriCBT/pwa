from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from datetime import datetime, timedelta
import io
import os
import logging
from database import Database
from states import States
from security import (
    validate_situation, validate_thought, validate_action, validate_evidence,
    validate_note, validate_emotion, validate_intensity, check_rate_limit,
    check_user_consent, save_user_consent, sanitize_text, escape_markdown,
    validate_entry_access, detect_suspicious_activity, perform_security_check,
    has_user_password, save_user_password, check_user_password,
    is_password_verification_enabled, validate_password
)
from admin import is_admin, admin_command, handle_admin_callback, handle_admin_broadcast_message, check_and_notify_suspicious_activities, notify_admin
from utils import (
    get_main_menu_keyboard, get_emotions_keyboard, get_intensity_keyboard,
    get_yes_no_keyboard, get_period_keyboard, get_new_emotions_keyboard,
    get_back_to_menu_keyboard, format_entry_summary, check_success, create_calendar,
    get_consent_keyboard, get_cancel_entry_keyboard, get_cancel_entry_with_menu_keyboard
)
from excel_generator import generate_excel
from message_tracker import save_message_id

db = Database()
logger = logging.getLogger(__name__)

# Правила пароля для отображения пользователю (чтобы не нарушать валидацию)
PASSWORD_RULES = (
    "Правила пароля: минимум 4 символа, максимум 100. "
    "Используйте буквы и цифры. Избегайте спецсимволов (@#$ и т.п.) — они могут вызвать ошибки."
)
PASSWORD_VERIFY_TTL = 600  # 10 минут — сессия доступа после проверки пароля


def _get_password_verified_sections(user_id: int) -> set:
    """Возвращает множество проверенных разделов для пользователя"""
    from cache import get_cached
    data = get_cached(f'pw_verified_{user_id}', ttl=PASSWORD_VERIFY_TTL)
    return set(data) if data else set()


def _set_password_verified_section(user_id: int, section: str):
    """Добавляет раздел в проверенные для пользователя"""
    from cache import get_cached, set_cached
    sections = _get_password_verified_sections(user_id)
    sections.add(section)
    set_cached(f'pw_verified_{user_id}', list(sections), ttl=PASSWORD_VERIFY_TTL)


def _clear_password_verified_sections(user_id: int):
    """Очищает проверенные разделы при возврате в меню"""
    from cache import delete_key
    delete_key(f'pw_verified_{user_id}')

async def _ensure_sensitive_entry_confirmation(query, context, entry_type: str) -> bool:
    """
    Если пользователь ещё не подтверждал первую чувствительную запись — показывает предупреждение и кнопки.
    Возвращает True, если можно продолжать (уже подтверждал или только что нажал «Да»); False — показали экран подтверждения.
    """
    user_id = query.from_user.id
    if db.has_user_confirmed_sensitive_entry(user_id):
        return True
    confirm_callback = 'confirm_sensitive_entry_thoughts' if entry_type == 'thoughts' else 'confirm_sensitive_entry_exposure'
    keyboard = [
        [InlineKeyboardButton("✅ Да, понимаю", callback_data=confirm_callback)],
        [InlineKeyboardButton("❌ Отмена", callback_data='menu')],
    ]
    text = (
        "📋 *Подтверждение перед записью*\n\n"
        "Вы вносите данные о психологическом состоянии *добровольно*. "
        "Оператор сервиса не несёт ответственности за последствия использования бота.\n\n"
        "Продолжить создание записи?"
    )
    await safe_edit_message(
        query,
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return False


def add_cancel_button(keyboard: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """Добавляет кнопку отмены к клавиатуре"""
    if hasattr(keyboard, 'inline_keyboard'):
        # inline_keyboard может быть tuple, конвертируем в list
        keyboard_list = [list(row) for row in keyboard.inline_keyboard]
    else:
        keyboard_list = list(keyboard) if isinstance(keyboard, (list, tuple)) else []
    keyboard_list.append([InlineKeyboardButton("❌ Отменить создание записи", callback_data='cancel_entry')])
    return InlineKeyboardMarkup(keyboard_list)


async def process_suspicious_input_and_notify_admin(update, context, user_id: int, input_type_label: str, text: str) -> None:
    """
    Обрабатывает подозрительный ввод: проверка блокировки, уведомление админу, сброс в меню.
    Вызывать после detect_suspicious_activity, когда она вернула truthy результат.
    """
    from active_protection import get_user_protection_status, get_block_message, delete_user_messages
    from admin import notify_admin_with_buttons

    logger.warning(f"🚨 Подозрительная активность обнаружена у пользователя {user_id}: {input_type_label}")
    status = get_user_protection_status(user_id)

    if status['is_blocked']:
        try:
            deleted_count = await delete_user_messages(context.bot, user_id)
            if deleted_count > 0:
                logger.info(f"Удалено {deleted_count} сообщений заблокированного пользователя {user_id}")
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщения пользователя {user_id}: {e}")
        block_message = get_block_message(user_id)
        if block_message:
            await update.message.reply_text(block_message, parse_mode='Markdown')
        return

    db.clear_user_state(user_id)
    try:
        safe_text = escape_markdown(text[:200])
        from log_masking import mask_user_data_in_log
        log_message = f"📨 Уведомление о подозрительной активности от пользователя {user_id}\nТип: {input_type_label}\nТекст: {text[:200]}"
        logger.info(mask_user_data_in_log(log_message))
        rep_info = f"\n*Баллы репутации:* {status['violation_score']}"
        if status['protection_level'] > 0:
            rep_info += f"\n*Уровень защиты:* {status['protection_level']}"
        message = (
            f"⚠️ *Подозрительная активность*\n\n"
            f"*Тип:* {input_type_label}\n"
            f"*Пользователь ID:* {user_id}\n"
            f"*Текст:* {safe_text}{rep_info}"
        )
        activities = db.get_recent_suspicious_activities(limit=1)
        activity_id = activities[0]['id'] if activities else None
        keyboard = [
            [
                InlineKeyboardButton("✅ Игнорировать", callback_data=f'admin_ignore_activity_{activity_id}'),
                InlineKeyboardButton("🚫 Заблокировать", callback_data=f'admin_block_user_{user_id}_{activity_id}')
            ]
        ]
        await notify_admin_with_buttons(context.bot, message, InlineKeyboardMarkup(keyboard))
        logger.info("✅ Уведомление о подозрительной активности отправлено")
    except Exception as e:
        logger.error(f"❌ Не удалось отправить уведомление админу: {type(e).__name__}: {e}", exc_info=True)

    warning_msg = "⚠️ Обнаружена подозрительная активность. Вы возвращены в главное меню."
    if status['protection_level'] >= 1:
        warning_msg += f"\n\n⚠️ Ваш уровень защиты: {status['protection_level']}. Будьте осторожны."
    await update.message.reply_text(warning_msg, reply_markup=get_main_menu_keyboard())


async def safe_edit_message(query, text: str, reply_markup=None, parse_mode='Markdown'):
    """
    Безопасно редактирует сообщение, проверяя его тип (текст/фото/документ)
    Если редактирование невозможно, отправляет новое сообщение
    Автоматически сохраняет message_id новых сообщений
    """
    user_id = query.from_user.id
    chat_id = query.message.chat.id if query.message else None
    
    try:
        # Проверяем тип сообщения
        has_photo = query.message and query.message.photo and len(query.message.photo) > 0
        has_document = query.message and query.message.document
        
        if has_photo:
            # Если сообщение содержит фото, редактируем подпись
            await query.edit_message_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        elif has_document:
            # Если сообщение содержит документ, отправляем новое сообщение
            sent_message = await query.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            if sent_message:
                save_message_id(user_id, sent_message, chat_id)
        else:
            # Если текстовое сообщение, редактируем текст
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
    except Exception as e:
        # Если не удалось отредактировать, отправляем новое сообщение
        logger.warning(f"Не удалось отредактировать сообщение: {e}, отправляем новое")
        try:
            sent_message = await query.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            if sent_message:
                save_message_id(user_id, sent_message, chat_id)
        except Exception as e2:
            logger.error(f"Не удалось отправить новое сообщение: {e2}")

# Инфографика (путь к изображениям - нужно будет добавить)
INFOGRAPHICS = [
    
    {'image': 'images/1.jpg', 'text': '...'},
    {'text': '2. *Зачем?*\nЧтобы выявлять и оспаривать негативные автоматические мысли.'},
    {'text': '3. *Шаг 1: Ситуация*\nОпишите событие, вызвавшее реакцию.'},
    {'text': '4. *Шаг 2: Эмоции и Мысли*\nОпределите их и оцените интенсивность.'},
    {'text': '5. *Шаг 3: Анализ*\nНайдите доводы "за" и "против", придумайте альтернативу.'},
    {'text': '6. *Шаг 4: Итог*\nОцените изменение эмоций, закрепите новый взгляд.'}
]

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start и /menu"""
    user = update.effective_user
    user_id = user.id
    
    # Сохраняем chat_id админа, если это админ
    from admin import is_admin, save_admin_chat_id_from_update
    
    # Проверяем блокировку (админ не блокируется)
    if not is_admin(user) and db.is_user_blocked(user_id):
        from active_protection import get_block_message
        block_message = get_block_message(user_id)
        if block_message:
            sent_message = await update.message.reply_text(block_message, parse_mode='Markdown')
            if sent_message:
                save_message_id(user_id, sent_message, update.effective_chat.id)
        return
    
    if is_admin(user):
        save_admin_chat_id_from_update(update)
        # Админ: пропускаем согласие, пароль и rate limit — сразу показываем меню
        message_text = (
            "Привет! Я помогу вам вести дневник мыслей по методу "
            "когнитивно-поведенческой терапии. Выберите действие:"
        )
        await update.message.reply_text(
            message_text,
            reply_markup=get_main_menu_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    # Проверяем rate limiting
    allowed, error_msg = check_rate_limit(user_id, 'command')
    if not allowed:
        await update.message.reply_text(f"⚠️ {error_msg}")
        return
    
    # Проверяем согласие пользователя
    if not check_user_consent(user_id):
        # Сначала проверяем подтверждение возраста
        if not db.has_user_confirmed_age(user_id):
            keyboard = [
                [InlineKeyboardButton("Мне 18 лет или больше", callback_data='age_confirm_18')],
                [InlineKeyboardButton("Мне 14–17 лет, есть согласие законного представителя", callback_data='age_confirm_14_17')],
            ]
            await update.message.reply_text(
                "📋 *Подтверждение возраста*\n\n"
                "Сервис предназначен для пользователей от 18 лет. "
                "Лица 14–17 лет могут пользоваться ботом при наличии согласия законного представителя на обработку персональных данных.\n\n"
                "Подтвердите ваш возраст:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return
        # Важное уведомление (не замена профессиональной помощи)
        notice_text = (
            "⚠️ *Важное уведомление*\n\n"
            "Этот бот — инструмент для *самонаблюдения* и *не является заменой* "
            "профессиональной психологической или психиатрической помощи.\n\n"
            "Если вы испытываете острый кризис, суицидальные мысли или нуждаетесь в диагностике и лечении, "
            "немедленно обратитесь к специалисту.\n\n"
            "📞 *Телефон доверия (бесплатно по РФ):* 8-800-2000-122\n\n"
            "Используя бот, вы подтверждаете, что понимаете эти ограничения и используете сервис на свой страх и риск.\n\n"
        )
        # Показываем согласие на обработку данных
        consent_text = (
            "👋 *Добро пожаловать!*\n\n"
            "Продолжая пользоваться ботом, вы соглашаетесь с политикой хранения данных "
            "и даете свое согласие на обработку персональных данных.\n\n"
            "Документы о политике конфиденциальности и обработке данных можно скачать "
            "через кнопку '📋 Документы согласия' в меню.\n\n"
            "Пожалуйста, подтвердите ваше согласие:"
        )
        
        # Отправляем изображение при первом запуске
        base_dir = os.path.dirname(os.path.abspath(__file__))
        image_path = os.path.join(base_dir, 'images', '1.jpg')
        
        full_consent_text = notice_text + consent_text
        if os.path.exists(image_path):
            with open(image_path, 'rb') as photo:
                sent_message = await update.message.reply_photo(
                    photo=photo,
                    caption=full_consent_text,
                    reply_markup=get_consent_keyboard(),
                    parse_mode='Markdown'
                )
                if sent_message:
                    save_message_id(user_id, sent_message, update.effective_chat.id)
        else:
            sent_message = await update.message.reply_text(
                full_consent_text,
                reply_markup=get_consent_keyboard(),
                parse_mode='Markdown'
            )
            if sent_message:
                save_message_id(user_id, sent_message, update.effective_chat.id)
        return
    
    # Если согласие есть, но пароль не установлен — просим создать
    if not has_user_password(user_id):
        db.save_user_state(user_id, States.WAITING_PASSWORD_CREATE, {})
        await update.message.reply_text(
            "🔐 Для защиты ваших записей создайте пароль.\n\n"
            "В наше время аккаунты Telegram нередко оказываются скомпрометированы. "
            "Пароль защитит ваши записи — без него посторонний *не сможет просмотреть, скачать или удалить* ваши данные.\n\n"
            "Пароль будет запрашиваться при входе в «Мои записи», «Скачать», «Удалить» и «Поиск».\n\n"
            f"*{PASSWORD_RULES}*\n\nВведите пароль:",
            parse_mode='Markdown'
        )
        return
    
    # Очищаем состояние при возврате в меню (отмена ввода пароля и т.п.)
    db.clear_user_state(user_id)
    _clear_password_verified_sections(user_id)
    
    # Если согласие есть, проверяем, первый ли это запуск (нет записей)
    entries = db.get_user_entries(user_id)
    is_first_launch = len(entries) == 0
    
    message_text = (
        "Привет! Я помогу вам вести дневник мыслей по методу "
        "когнитивно-поведенческой терапии. Выберите действие:"
    )
    
    # При первом запуске отправляем изображение вместе с сообщением
    if is_first_launch:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        image_path = os.path.join(base_dir, 'images', '1.jpg')
        
        if os.path.exists(image_path):
            with open(image_path, 'rb') as photo:
                sent_message = await update.message.reply_photo(
                    photo=photo,
                    caption=message_text,
                    reply_markup=get_main_menu_keyboard(),
                    parse_mode='Markdown'
                )
                if sent_message:
                    save_message_id(user_id, sent_message, update.effective_chat.id)
        else:
            sent_message = await update.message.reply_text(
                message_text,
                reply_markup=get_main_menu_keyboard(),
                parse_mode='Markdown'
            )
            if sent_message:
                save_message_id(user_id, sent_message, update.effective_chat.id)
    else:
        sent_message = await update.message.reply_text(
            message_text,
            reply_markup=get_main_menu_keyboard(),
            parse_mode='Markdown'
        )
        if sent_message:
            save_message_id(user_id, sent_message, update.effective_chat.id)
    
    # Пытаемся закрепить сообщение
    try:
        await context.bot.pin_chat_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id
        )
    except Exception as e:
        logger.warning(f"Не удалось закрепить сообщение: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик всех callback кнопок"""
    query = update.callback_query
    
    if not query:
        logger.warning("Received callback query without query object")
        return
    
    user_id = query.from_user.id
    
    from admin import is_admin
    # Проверяем блокировку (админ не блокируется)
    if not is_admin(query.from_user) and db.is_user_blocked(user_id):
        from active_protection import get_block_message
        block_message = get_block_message(user_id)
        if block_message:
            try:
                await query.answer("Вы заблокированы", show_alert=True)
                await safe_edit_message(query, block_message, parse_mode='Markdown')
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение о блокировке пользователю {user_id}: {e}")
        else:
            try:
                await query.answer("Вы заблокированы", show_alert=True)
            except Exception as e:
                logger.warning(f"Не удалось ответить на callback query для заблокированного пользователя {user_id}: {e}")
        return
    
    # Сохраняем message_id для возможного удаления при блокировке
    if query.message:
        db.save_user_message(user_id, query.message.message_id, query.message.chat.id)
    
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Не удалось ответить на callback query: {e}")
    
    data = query.data
    
    if not data:
        logger.warning(f"Received callback query without data from user {user_id}")
        return
    
    if data == 'menu':
        _clear_password_verified_sections(query.from_user.id)
        await show_menu(query, context)
    
    elif data == 'info':
        await show_info(query, context)
    
    elif data == 'info_exposure':
        await show_info_exposure(query, context)
    
    elif data == 'new_entry':
        await start_new_entry(query, context)
    
    elif data == 'new_entry_thoughts':
        if not _ensure_sensitive_entry_confirmation(query, context, 'thoughts'):
            return
        await start_new_entry_thoughts(query, context)
    
    elif data == 'new_entry_exposure':
        if not _ensure_sensitive_entry_confirmation(query, context, 'exposure'):
            return
        from exposure_handlers import start_new_entry_exposure
        await start_new_entry_exposure(query, context)
    
    elif data == 'confirm_sensitive_entry_thoughts':
        user_id = query.from_user.id
        if not db.has_user_confirmed_sensitive_entry(user_id):
            db.save_confirmation_log(user_id, 'sensitive_entry')
            logger.info(f"User {user_id} confirmed sensitive entry (thoughts)")
        await start_new_entry_thoughts(query, context)
    
    elif data == 'confirm_sensitive_entry_exposure':
        user_id = query.from_user.id
        if not db.has_user_confirmed_sensitive_entry(user_id):
            db.save_confirmation_log(user_id, 'sensitive_entry')
            logger.info(f"User {user_id} confirmed sensitive entry (exposure)")
        from exposure_handlers import start_new_entry_exposure
        await start_new_entry_exposure(query, context)
    
    # Промежуточные меню для выбора типа дневника (с проверкой пароля)
    elif data == 'my_entries_menu':
        if await request_password_for_action(query, context, 'my_entries_menu', section='my_entries'):
            return
        from utils import get_diary_type_menu_keyboard
        await safe_edit_message(
            query,
            "📂 *Мои записи*\n\nВыберите тип дневника:",
            reply_markup=get_diary_type_menu_keyboard('my_entries'),
            parse_mode='Markdown'
        )
    
    elif data == 'my_entries_thoughts':
        await show_my_entries(query, context)
    
    elif data == 'my_entries_exposure':
        from exposure_handlers import show_my_exposures
        await show_my_exposures(query, context)
    
    elif data == 'statistics_menu':
        from utils import get_diary_type_menu_keyboard
        await safe_edit_message(
            query,
            "📊 *Статистика*\n\nВыберите тип дневника:",
            reply_markup=get_diary_type_menu_keyboard('statistics'),
            parse_mode='Markdown'
        )
    
    elif data == 'statistics_thoughts':
        from statistics import show_user_statistics
        await show_user_statistics(query, context)
    
    elif data == 'statistics_exposure':
        from exposure_handlers import show_user_statistics_exposure
        await show_user_statistics_exposure(query, context)
    
    elif data == 'search_menu_main':
        if await request_password_for_action(query, context, 'search_menu_main', section='search'):
            return
        from utils import get_diary_type_menu_keyboard
        await safe_edit_message(
            query,
            "🔍 *Поиск*\n\nВыберите тип дневника:",
            reply_markup=get_diary_type_menu_keyboard('search'),
            parse_mode='Markdown'
        )
    
    elif data == 'search_thoughts':
        from search import show_search_menu
        await show_search_menu(query, context)
    
    elif data == 'search_exposure':
        from exposure_handlers import show_search_menu_exposure
        await show_search_menu_exposure(query, context)
    
    elif data == 'download_menu':
        if await request_password_for_action(query, context, 'download_menu', section='download'):
            return
        from utils import get_diary_type_menu_keyboard
        await safe_edit_message(
            query,
            "📥 *Скачать*\n\nВыберите тип дневника:",
            reply_markup=get_diary_type_menu_keyboard('download'),
            parse_mode='Markdown'
        )
    
    elif data == 'download_thoughts':
        await show_download_period(query, context)
    
    elif data == 'download_exposure':
        from exposure_handlers import show_download_period_exposure
        await show_download_period_exposure(query, context)
    
    elif data == 'delete_menu':
        if await request_password_for_action(query, context, 'delete_menu', section='delete'):
            return
        from utils import get_diary_type_menu_keyboard
        await safe_edit_message(
            query,
            "🗑️ *Удалить*\n\nВыберите тип дневника:",
            reply_markup=get_diary_type_menu_keyboard('delete'),
            parse_mode='Markdown'
        )
    
    elif data == 'delete_thoughts':
        await show_delete_period(query, context)
    
    elif data == 'delete_exposure':
        from exposure_handlers import show_delete_period_exposure
        await show_delete_period_exposure(query, context)
    
    elif data == 'template_menu':
        from utils import get_diary_type_menu_keyboard
        await safe_edit_message(
            query,
            "📄 *Шаблон*\n\nВыберите тип дневника:",
            reply_markup=get_diary_type_menu_keyboard('template'),
            parse_mode='Markdown'
        )
    
    elif data == 'template_thoughts':
        await send_template(query, context)
    
    elif data == 'template_exposure':
        from exposure_handlers import send_template_exposure
        await send_template_exposure(query, context)
    
    elif data == 'questions':
        await show_questions(query, context)
    
    # Старые обработчики для обратной совместимости
    elif data == 'my_entries':
        await show_my_entries(query, context)
    
    elif data == 'my_exposures':
        from exposure_handlers import show_my_exposures
        await show_my_exposures(query, context)
    
    elif data == 'download':
        await show_download_period(query, context)
    
    elif data == 'download_exposure':
        from exposure_handlers import show_download_period_exposure
        await show_download_period_exposure(query, context)
    
    elif data == 'download_template':
        await send_template(query, context)
    
    elif data == 'download_template_exposure':
        from exposure_handlers import send_template_exposure
        await send_template_exposure(query, context)
    
    elif data == 'delete':
        await show_delete_period(query, context)
    
    elif data == 'delete_exposure':
        from exposure_handlers import show_delete_period_exposure
        await show_delete_period_exposure(query, context)
    
    elif data == 'statistics':
        from statistics import show_user_statistics
        await show_user_statistics(query, context)
    
    elif data == 'search':
        from search import show_search_menu
        await show_search_menu(query, context)
    
    elif data == 'search_text':
        from search import handle_search_text
        await handle_search_text(query, context)
    
    elif data == 'search_date':
        from search import handle_search_date
        await handle_search_date(query, context)
    
    elif data == 'search_emotions':
        from search import handle_search_emotions
        await handle_search_emotions(query, context)
    
    elif data == 'reminders':
        from reminders import show_reminders_menu
        await show_reminders_menu(query, context)
    
    elif data in ['reminder_enable', 'reminder_disable', 'reminder_set_time']:
        from reminders import (
            handle_reminder_enable,
            handle_reminder_disable,
            handle_reminder_set_time,
        )
        if data == 'reminder_enable':
            await handle_reminder_enable(query, context)
        elif data == 'reminder_disable':
            await handle_reminder_disable(query, context)
        elif data == 'reminder_set_time':
            await handle_reminder_set_time(query, context)
    
    elif data == 'reminder_timezone_menu':
        from reminders import show_timezone_menu
        await show_timezone_menu(query, context)
    
    elif data.startswith('rem_tz_'):
        from reminders import handle_timezone_choice
        try:
            idx = int(data.replace('rem_tz_', ''))
            await handle_timezone_choice(query, context, idx)
        except ValueError:
            await query.answer("Ошибка выбора", show_alert=True)
    
    elif data in ('age_confirm_18', 'age_confirm_14_17'):
        user_id = query.from_user.id
        if not db.has_user_confirmed_age(user_id):
            db.save_confirmation_log(user_id, 'age')
            logger.info(f"User {user_id} confirmed age (variant: {data})")
        notice_text = (
            "⚠️ *Важное уведомление*\n\n"
            "Этот бот — инструмент для *самонаблюдения* и *не является заменой* "
            "профессиональной психологической или психиатрической помощи.\n\n"
            "Если вы испытываете острый кризис, суицидальные мысли или нуждаетесь в диагностике и лечении, "
            "немедленно обратитесь к специалисту.\n\n"
            "📞 *Телефон доверия (бесплатно по РФ):* 8-800-2000-122\n\n"
            "Используя бот, вы подтверждаете, что понимаете эти ограничения и используете сервис на свой страх и риск.\n\n"
        )
        consent_text = (
            "👋 *Добро пожаловать!*\n\n"
            "Продолжая пользоваться ботом, вы соглашаетесь с политикой хранения данных "
            "и даете свое согласие на обработку персональных данных.\n\n"
            "Документы о политике конфиденциальности и обработке данных можно скачать "
            "через кнопку '📋 Документы согласия' в меню.\n\n"
            "Пожалуйста, подтвердите ваше согласие:"
        )
        await safe_edit_message(
            query,
            notice_text + consent_text,
            reply_markup=get_consent_keyboard(),
            parse_mode='Markdown'
        )
    
    elif data == 'consent_yes':
        await handle_consent_yes(query, context)
    
    elif data == 'consent_no':
        await handle_consent_no(query, context)
    
    elif data == 'download_consent_docs':
        await send_consent_documents(query, context)
    
    elif data == 'password_settings':
        await handle_password_settings(query, context)
    
    elif data == 'password_disable_confirm':
        await handle_password_disable_confirm(query, context)
    
    elif data == 'password_disable':
        await handle_password_disable(query, context)
    
    elif data == 'password_enable':
        await handle_password_enable(query, context)
    
    elif data == 'password_reset_request':
        await handle_password_reset_request(query, context)
    
    elif data == 'password_reset_confirm':
        await handle_password_reset_confirm(query, context)
    
    elif data == 'delete_account':
        await handle_delete_account(query, context)
    
    elif data == 'confirm_delete_account':
        await handle_confirm_delete_account(query, context)
    
    elif data == 'cancel_entry':
        await handle_cancel_entry(query, context)
    
    # Обработка действий с подозрительной активностью (проверяем ПЕРЕД общим admin_)
    elif data.startswith('admin_ignore_activity_'):
        await handle_ignore_activity(query, context, data)
    
    elif data.startswith('admin_block_user_'):
        await handle_block_user(query, context, data)
    
    elif data.startswith('admin_unblock_user_'):
        await handle_unblock_user(query, context, data)
    
    elif data.startswith('admin_remove_restrictions_'):
        await handle_remove_restrictions(query, context, data)
    
    elif data.startswith('admin_reset_approve_'):
        from admin import handle_admin_reset_approve
        await handle_admin_reset_approve(query, context, data)
    
    elif data.startswith('admin_reset_reject_'):
        from admin import handle_admin_reset_reject
        await handle_admin_reset_reject(query, context, data)
    
    # Обработка админских callback (общий обработчик в конце)
    elif data.startswith('admin_'):
        await handle_admin_callback(query, context, data)
    
    # Обработка поиска по эмоциям
    elif data.startswith('search_emotion_'):
        from search import handle_search_emotion_choice
        emotion = data.replace('search_emotion_', '')
        await handle_search_emotion_choice(query, context, emotion)
    
    # Обработка календаря для экспозиций (должно быть ПЕРЕД обработкой exposure_)
    elif data.startswith('exposure_date_') or data.startswith('exposure_time_') or data == 'exposure_back_date':
        await handle_calendar(query, context, data)
    
    # Обработка календаря
    elif data.startswith('cal_') or data.startswith('search_'):
        await handle_calendar(query, context, data)
    
    # Обработка создания записи
    # ВАЖНО: проверяем точные значения ПЕРЕД проверкой startswith
    elif data in ['emotion_custom', 'emotion_yes', 'emotion_no']:
        await handle_emotion_custom_flow(query, context, data)
    
    elif data.startswith('emotion_'):
        # Проверяем состояние для правильной маршрутизации
        state_info = db.get_user_state(query.from_user.id)
        if state_info:
            state = state_info.get('state')
            if state == States.WAITING_EXPOSURE_REALITY_EMOTION:
                from exposure_handlers import handle_exposure_reality_emotion_choice
                await handle_exposure_reality_emotion_choice(query, context, data)
            elif state == States.WAITING_EXPOSURE_EMOTION:
                from exposure_handlers import handle_exposure_emotion_choice
                await handle_exposure_emotion_choice(query, context, data)
            else:
                await handle_emotion_choice(query, context, data)
        else:
            await handle_emotion_choice(query, context, data)
    
    elif data.startswith('intensity_'):
        await handle_intensity_choice(query, context, data)
    
    # Обработка эмоций для экспозиции
    elif data in ['exposure_emotion_yes', 'exposure_emotion_no']:
        from exposure_handlers import handle_exposure_more_emotions
        await handle_exposure_more_emotions(query, context, data)
    
    # Обработка дополнительных ожиданий для экспозиции
    elif data in ['exposure_expectation_yes', 'exposure_expectation_no']:
        from exposure_handlers import handle_exposure_more_expectations
        await handle_exposure_more_expectations(query, context, data)
    
    # Обработка результатов ожиданий для экспозиции
    elif data.startswith('expectation_fulfilled_'):
        from exposure_handlers import handle_exposure_expectation_fulfilled
        await handle_exposure_expectation_fulfilled(query, context, data)
    
    # Обработка дополнительных эмоций в реальности для экспозиции
    elif data in ['exposure_reality_emotion_yes', 'exposure_reality_emotion_no']:
        from exposure_handlers import handle_exposure_reality_more_emotions
        await handle_exposure_reality_more_emotions(query, context, data)
    
    # ВАЖНО: проверяем обработку потоков новых эмоций ПЕРЕД выбором конкретной эмоции
    elif data in ['new_emotion_yes', 'new_emotion_no', 'new_emotion_none']:
        await handle_new_emotion_flow(query, context, data)
    
    elif data in ['new_emotion_custom']:
        await handle_new_emotion_custom(query, context)
    
    elif data.startswith('new_emotion_'):
        await handle_new_emotion_choice(query, context, data)
    
    elif data in ['alt_thought_yes', 'alt_thought_no']:
        await handle_alternative_thought_flow(query, context, data)
    
    # Обработка продолжительности для экспозиций (ВАЖНО: перед обработкой интенсивности)
    elif data.startswith('exposure_duration_'):
        from exposure_handlers import handle_exposure_duration_choice
        await handle_exposure_duration_choice(query, context, data)
        return
    
    # Обработка периодов для экспозиций
    elif data.startswith('download_exposure_') or data.startswith('delete_exposure_'):
        from exposure_handlers import handle_period_choice_exposure
        await handle_period_choice_exposure(query, context, data)
    
    # Обработка поиска экспозиций
    elif data == 'search_exposure_text':
        from exposure_handlers import handle_search_exposure_text
        await handle_search_exposure_text(query, context)
    
    elif data == 'search_exposure_date':
        from exposure_handlers import handle_search_exposure_date
        await handle_search_exposure_date(query, context)
    
    # Обработка периодов
    elif data.startswith('download_') or data.startswith('delete_'):
        await handle_period_choice(query, context, data)
    
    # Обработка записей
    elif data.startswith('entry_'):
        await show_entry_detail(query, context, data)
    
    # Обработка начала заполнения реальности для экспозиции
    elif data.startswith('exposure_fill_reality_'):
        exposure_id_str = data.replace('exposure_fill_reality_', '')
        if exposure_id_str.isdigit():
            exposure_id = int(exposure_id_str)
            from exposure_handlers import start_exposure_reality_fill
            await start_exposure_reality_fill(query, context, exposure_id)
    
    # Обработка экспозиций (только для просмотра деталей, не для календаря/времени)
    elif data.startswith('exposure_') and not data.startswith('exposure_date_') and not data.startswith('exposure_time_'):
        # Проверяем, что это действительно ID экспозиции (число после 'exposure_')
        exposure_id_str = data.replace('exposure_', '')
        if exposure_id_str.isdigit():
            from exposure_handlers import show_exposure_detail
            await show_exposure_detail(query, context, data)
    
    elif data.startswith('edit_entry_'):
        entry_id = int(data.replace('edit_entry_', ''))
        from entry_edit import show_edit_entry_menu
        await show_edit_entry_menu(query, context, entry_id)
    
    elif data.startswith('edit_'):
        from entry_edit import handle_edit_field
        await handle_edit_field(query, context, data)
    
    elif data.startswith('confirm_delete_'):
        if data.startswith('confirm_delete_exposure_'):
            from exposure_handlers import handle_confirm_delete_exposures
            await handle_confirm_delete_exposures(query, context, data)
        else:
            await handle_confirm_delete_entries(query, context, data)

async def show_menu(query, context):
    """Показывает главное меню"""
    user_id = query.from_user.id
    
    from admin import is_admin
    if not is_admin(query.from_user) and not check_user_consent(user_id):
        await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
        return
    
    message_text = (
        "Привет! Я помогу вам вести дневник мыслей по методу "
        "когнитивно-поведенческой терапии. Выберите действие:"
    )
    await safe_edit_message(
        query,
        message_text,
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown'
    )

async def show_info(query, context):
    """Показывает информацию о дневнике мыслей"""
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
    
    # Отправляем 5 картинок одним сообщением (media group) — 6.jpg не отправляем
    from telegram import InputMediaPhoto
    from io import BytesIO
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    images_dir = os.path.join(base_dir, 'images')
    media_group = []
    photo_data_list = []  # Храним данные в памяти до отправки
    
    # Читаем изображения 1–5 в память (6.jpg исключён)
    for i in range(1, 6):
        image_path = os.path.join(images_dir, f'{i}.jpg')
        if os.path.exists(image_path):
            try:
                # Читаем файл в память
                with open(image_path, 'rb') as f:
                    photo_data = f.read()
                # Сохраняем данные в списке, чтобы они оставались в памяти
                photo_data_list.append(photo_data)
                # Создаем BytesIO объект для каждого изображения
                media_group.append(InputMediaPhoto(media=BytesIO(photo_data)))
            except Exception as e:
                logger.error(f"Ошибка при чтении изображения {i}.jpg: {e}")
        else:
            logger.warning(f"⚠️ Изображение {i}.jpg не найдено в {images_dir}")
    
    if media_group:
        try:
            # Отправляем изображения одним media group
            sent_messages = await query.message.reply_media_group(media=media_group)
            # Сохраняем message_id для всех отправленных сообщений
            for sent_msg in sent_messages:
                if sent_msg:
                    save_message_id(user_id, sent_msg, query.message.chat.id)
            logger.info(f"Отправлено {len(sent_messages)} изображений пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка при отправке media group: {e}")
            # Fallback: отправляем по одной
            for i in range(1, 6):
                image_path = os.path.join(images_dir, f'{i}.jpg')
                if os.path.exists(image_path):
                    try:
                        with open(image_path, 'rb') as photo:
                            sent_message = await query.message.reply_photo(photo=photo)
                            if sent_message:
                                save_message_id(user_id, sent_message, query.message.chat.id)
                    except Exception as e2:
                        logger.error(f"Ошибка при отправке изображения {i}: {e2}")
    else:
        await query.answer("⚠️ Изображения не найдены", show_alert=True)
        return
    
    # Отправляем текст со ссылкой на подробную информацию
    info_text = (
        "📖 *Подробнее о дневнике мыслей:*\n"
        "[Читать на сайте](https://negoricbt.github.io/NeGORI/pages/dnev.html)"
    )
    
    sent_message = await query.message.reply_text(
        info_text,
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode='Markdown',
        disable_web_page_preview=False
    )
    if sent_message:
        save_message_id(user_id, sent_message, query.message.chat.id)

async def show_info_exposure(query, context):
    """Показывает информацию о дневнике экспозиций"""
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
    
    # Отправляем 6 картинок одним сообщением (media group)
    from telegram import InputMediaPhoto
    from io import BytesIO
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    images_dir = os.path.join(base_dir, 'images')
    media_group = []
    photo_data_list = []  # Храним данные в памяти до отправки
    
    # Читаем все 6 изображений в память (11.jpg, 22.jpg, 33.jpg, 44.jpg, 55.jpg, 66.jpg)
    image_names = ['11.jpg', '22.jpg', '33.jpg', '44.jpg', '55.jpg', '66.jpg']
    for image_name in image_names:
        image_path = os.path.join(images_dir, image_name)
        if os.path.exists(image_path):
            try:
                # Читаем файл в память
                with open(image_path, 'rb') as f:
                    photo_data = f.read()
                # Сохраняем данные в списке, чтобы они оставались в памяти
                photo_data_list.append(photo_data)
                # Создаем BytesIO объект для каждого изображения
                media_group.append(InputMediaPhoto(media=BytesIO(photo_data)))
            except Exception as e:
                logger.error(f"Ошибка при чтении изображения {image_name}: {e}")
        else:
            logger.warning(f"⚠️ Изображение {image_name} не найдено в {images_dir}")
    
    if media_group:
        try:
            # Отправляем изображения одним media group
            sent_messages = await query.message.reply_media_group(media=media_group)
            # Сохраняем message_id для всех отправленных сообщений
            for sent_msg in sent_messages:
                if sent_msg:
                    save_message_id(user_id, sent_msg, query.message.chat.id)
            logger.info(f"Отправлено {len(sent_messages)} изображений пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка при отправке media group: {e}")
            # Fallback: отправляем по одной
            for image_name in image_names:
                image_path = os.path.join(images_dir, image_name)
                if os.path.exists(image_path):
                    try:
                        with open(image_path, 'rb') as photo:
                            sent_message = await query.message.reply_photo(photo=photo)
                            if sent_message:
                                save_message_id(user_id, sent_message, query.message.chat.id)
                    except Exception as e2:
                        logger.error(f"Ошибка при отправке изображения {image_name}: {e2}")
    else:
        await query.answer("⚠️ Изображения не найдены", show_alert=True)
        return
    
    # Отправляем текст со ссылкой на подробную информацию
    info_text = (
        "📖 *Подробнее о дневнике экспозиций:*\n"
        "[Читать на сайте](https://negoricbt.github.io/NeGORI/pages/dnevexp.html)"
    )
    
    sent_message = await query.message.reply_text(
        info_text,
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode='Markdown',
        disable_web_page_preview=False
    )
    if sent_message:
        save_message_id(user_id, sent_message, query.message.chat.id)

async def start_new_entry(query, context):
    """Начинает процесс создания новой записи - выбор типа"""
    user_id = query.from_user.id
    
    from admin import is_admin
    if not is_admin(query.from_user) and db.is_user_blocked(user_id):
        from active_protection import get_block_message
        block_message = get_block_message(user_id)
        if block_message:
            await query.answer("Вы заблокированы", show_alert=True)
            await safe_edit_message(query, block_message, parse_mode='Markdown')
        return
    
    if not is_admin(query.from_user):
        from active_protection import check_user_restrictions
        allowed, restriction_msg = check_user_restrictions(user_id)
        if not allowed:
            await query.answer(restriction_msg, show_alert=True)
            await safe_edit_message(
                query,
                restriction_msg,
                reply_markup=get_back_to_menu_keyboard()
            )
            return
        
        if not check_user_consent(user_id):
            await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
            return
        
        allowed, error_msg = check_rate_limit(user_id, 'command')
        if not allowed:
            await query.answer(error_msg, show_alert=True)
            return
    
    # Предлагаем выбрать тип записи
    keyboard = [
        [InlineKeyboardButton("💭 Дневник мыслей", callback_data='new_entry_thoughts')],
        [InlineKeyboardButton("📅 Дневник экспозиций", callback_data='new_entry_exposure')],
        [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
    ]
    
    await safe_edit_message(
        query,
        "📝 *Новая запись*\n\n"
        "Выберите тип дневника:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def start_new_entry_thoughts(query, context):
    """Начинает процесс создания новой записи дневника мыслей"""
    user_id = query.from_user.id
    
    from admin import is_admin
    if not is_admin(query.from_user) and db.is_user_blocked(user_id):
        from active_protection import get_block_message
        block_message = get_block_message(user_id)
        if block_message:
            await query.answer("Вы заблокированы", show_alert=True)
            await safe_edit_message(query, block_message, parse_mode='Markdown')
        return
    
    if not is_admin(query.from_user):
        from active_protection import check_user_restrictions
        allowed, restriction_msg = check_user_restrictions(user_id)
        if not allowed:
            await query.answer(restriction_msg, show_alert=True)
            await safe_edit_message(
                query,
                restriction_msg,
                reply_markup=get_back_to_menu_keyboard()
            )
            return
        
        if not check_user_consent(user_id):
            await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
            return
        
        allowed, error_msg = check_rate_limit(user_id, 'entry_creation')
        if not allowed:
            await query.answer(error_msg, show_alert=True)
            return
    
    db.clear_user_state(user_id)
    
    entry_data = {
        'emotions_before': [],
        'alternative_thoughts': [],
        'emotions_after': [],
        'current_emotion_index': 0,
        'current_alt_thought_index': 0,
        'reassessing_emotion_index': 0
    }
    
    db.save_user_state(user_id, States.WAITING_SITUATION, entry_data)
    
    await safe_edit_message(
        query,
        "*Шаг 1: Ситуация*\n\n"
        "Опишите ситуацию, которая вызвала у вас эмоциональную реакцию "
        "(где, когда, что произошло?).",
        reply_markup=get_cancel_entry_keyboard(),
        parse_mode='Markdown'
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    
    # Сохраняем message_id для возможного удаления при блокировке
    if update.message:
        db.save_user_message(user_id, update.message.message_id, update.effective_chat.id)
    
    from admin import is_admin
    # Проверяем блокировку (админ не блокируется)
    if not is_admin(update.effective_user) and db.is_user_blocked(user_id):
        from active_protection import get_block_message
        block_message = get_block_message(user_id)
        if block_message:
            sent_message = await update.message.reply_text(block_message, parse_mode='Markdown')
            if sent_message:
                db.save_bot_message(user_id, sent_message.message_id, update.effective_chat.id)
        return
    
    text = update.message.text
    
    # Проверка для админа: рассылка или просмотр пользователя
    if is_admin(update.effective_user):
        state_info = db.get_user_state(user_id)
        if state_info and state_info.get('state') == States.ADMIN_BROADCAST_MESSAGE:
            await handle_admin_broadcast_message(update, context, text)
            return
        try:
            # Пытаемся распарсить как ID пользователя
            target_user_id = int(text.strip())
            if 100000000 <= target_user_id <= 9999999999:  # Примерный диапазон Telegram user_id
                # Показываем информацию о пользователе напрямую
                from admin import show_user_info
                await show_user_info(update, context, target_user_id)
                return
        except (ValueError, AttributeError):
            pass  # Не числовой ID, продолжаем обычную обработку
    
    # Проверяем согласие
    if not check_user_consent(user_id):
        await update.message.reply_text(
            "⚠️ Для использования бота необходимо дать согласие на обработку данных. "
            "Используйте команду /start."
        )
        return
    
    # Проверяем rate limiting
    allowed, error_msg = check_rate_limit(user_id, 'message')
    if not allowed:
        await update.message.reply_text(f"⚠️ {error_msg}")
        return
    
    state_info = db.get_user_state(user_id)
    
    if not state_info:
        await update.message.reply_text(
            "Используйте команду /menu для начала работы."
        )
        return
    
    state = state_info['state']
    entry_data = state_info['data']
    
    if state == States.WAITING_REMINDER_TIME:
        from reminders import handle_reminder_time_text
        await handle_reminder_time_text(update, context, text)
        return
    
    # Создание пароля после согласия
    if state == States.WAITING_PASSWORD_CREATE:
        is_valid, err = validate_password(text)
        if not is_valid:
            await update.message.reply_text(f"⚠️ {err}\n\n{PASSWORD_RULES}\n\nПопробуйте снова:")
            return
        save_user_password(user_id, text.strip())
        db.clear_user_state(user_id)
        await update.message.reply_text(
            "✅ Пароль успешно создан!\n\n"
            "Привет! Я помогу вам вести дневник мыслей по методу "
            "когнитивно-поведенческой терапии. Выберите действие:",
            reply_markup=get_main_menu_keyboard(),
            parse_mode='Markdown'
        )
        logger.info(f"User {user_id} created password")
        return
    
    # Проверка пароля для доступа к записям
    if state == States.WAITING_PASSWORD_VERIFY:
        if not check_user_password(user_id, text.strip()):
            db.clear_user_state(user_id)
            _clear_password_verified_sections(user_id)
            await update.message.reply_text(
                "❌ Пароль неверен. Вы возвращены в главное меню.",
                reply_markup=get_main_menu_keyboard(),
                parse_mode='Markdown'
            )
            return
        db.clear_user_state(user_id)
        section = entry_data.get('section')
        if section:
            _set_password_verified_section(user_id, section)
        action = entry_data.get('action', '')
        chat_id = entry_data.get('chat_id', update.effective_chat.id)
        message_id = entry_data.get('message_id')
        action_data = entry_data.get('action_data', {})
        await execute_action_after_password(context.bot, user_id, chat_id, message_id, action, action_data, update)
        return
    
    # Проверка пароля перед отключением
    if state == States.WAITING_PASSWORD_FOR_DISABLE:
        if not check_user_password(user_id, text.strip()):
            db.clear_user_state(user_id)
            await update.message.reply_text(
                "❌ Пароль неверен. Вы возвращены в главное меню.",
                reply_markup=get_main_menu_keyboard(),
                parse_mode='Markdown'
            )
            return
        db.clear_user_state(user_id)
        chat_id = entry_data.get('chat_id', update.effective_chat.id)
        message_id = entry_data.get('message_id')
        keyboard = [
            [InlineKeyboardButton("✅ Да, отключить", callback_data='password_disable_confirm')],
            [InlineKeyboardButton("❌ Отмена", callback_data='password_settings')]
        ]
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=PASSWORD_WARNING + "\n\nВы уверены, что хотите отключить проверку пароля?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception:
            await update.message.reply_text(
                PASSWORD_WARNING + "\n\nВы уверены, что хотите отключить проверку пароля?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        return
    
    # Новый пароль при включении проверки
    if state == States.WAITING_PASSWORD_NEW_FOR_ENABLE:
        is_valid, err = validate_password(text)
        if not is_valid:
            await update.message.reply_text(f"⚠️ {err}\n\n{PASSWORD_RULES}\n\nПопробуйте снова:")
            return
        save_user_password(user_id, text.strip())
        db.set_password_verification_enabled(user_id, True)
        db.clear_user_state(user_id)
        await update.message.reply_text(
            "✅ *Проверка пароля включена*\n\n"
            "Новый пароль установлен. Теперь при входе в «Мои записи», «Скачать», «Удалить» и «Поиск» потребуется ввод пароля.\n\n"
            "Это защищает ваши данные в случае компрометации аккаунта Telegram.",
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode='Markdown'
        )
        logger.info(f"Пользователь {user_id} включил проверку пароля с новым паролем")
        return
    
    # Обработка состояний экспозиций
    if state == States.WAITING_EXPOSURE_SITUATION:
        from exposure_handlers import handle_exposure_situation
        await handle_exposure_situation(update, context)
        return
    
    if state == States.WAITING_EXPOSURE_TIME:
        from exposure_handlers import handle_exposure_time_text
        await handle_exposure_time_text(update, context)
        return
    
    if state == States.WAITING_EXPOSURE_EXPECTATION:
        from exposure_handlers import handle_exposure_expectation
        await handle_exposure_expectation(update, context)
        return
    
    if state == States.WAITING_EXPOSURE_PROBABILITY:
        from exposure_handlers import handle_exposure_probability
        await handle_exposure_probability(update, context)
        return
    
    if state == States.WAITING_EXPOSURE_DURATION:
        from exposure_handlers import handle_exposure_duration
        await handle_exposure_duration(update, context)
        return
    
    if state == States.WAITING_EXPOSURE_REALITY_DESCRIPTION:
        from exposure_handlers import handle_exposure_reality_description
        await handle_exposure_reality_description(update, context)
        return
    
    if state == States.WAITING_EXPOSURE_WHAT_MATCHED:
        from exposure_handlers import handle_exposure_what_matched
        await handle_exposure_what_matched(update, context)
        return
    
    if state == States.WAITING_EXPOSURE_WHAT_DIFFERED:
        from exposure_handlers import handle_exposure_what_differed
        await handle_exposure_what_differed(update, context)
        return
    
    if state == States.WAITING_EXPOSURE_FINAL_SUMMARY:
        from exposure_handlers import handle_exposure_final_summary
        await handle_exposure_final_summary(update, context)
        return
    
    if state == States.WAITING_EXPOSURE_REALITY:
        from exposure_handlers import handle_exposure_reality
        await handle_exposure_reality(update, context)
        return
    
    # Обработка редактирования записей
    from entry_edit import EditStates, handle_edit_text
    if state in [EditStates.EDITING_SITUATION, EditStates.EDITING_AUTOMATIC_THOUGHT,
                 EditStates.EDITING_ACTION, EditStates.EDITING_EVIDENCE_FOR,
                 EditStates.EDITING_EVIDENCE_AGAINST, EditStates.EDITING_NOTE]:
        await handle_edit_text(update, context, state, entry_data)
        return
    
    # Обработка поиска
    if state == States.WAITING_SEARCH_QUERY:
        entry_type = entry_data.get('entry_type', 'thoughts')
        if entry_type == 'exposure':
            from exposure_handlers import handle_search_exposure_query
            await handle_search_exposure_query(update, context)
        else:
            from search import handle_search_query
            await handle_search_query(update, context)
        return
    
    # Шаг 1: Ситуация
    if state == States.WAITING_SITUATION:
        # Валидация
        is_valid, error_msg = validate_situation(text)
        if not is_valid:
            # Обнаружение подозрительной активности
            detect_suspicious_activity(user_id, 'invalid_situation', error_msg)
            keyboard = get_cancel_entry_keyboard()
            await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=keyboard)
            return
        
        # Проверка на подозрительную активность
        protection_result = detect_suspicious_activity(user_id, 'situation_input', text)
        if protection_result:
            await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод ситуации", text)
            return
        entry_data['situation'] = sanitize_text(text)
        db.save_user_state(user_id, States.WAITING_EMOTION, entry_data)
        keyboard = add_cancel_button(get_emotions_keyboard())
        await update.message.reply_text(
            "*Шаг 2: Эмоции*\n\n"
            "Какая эмоция возникла? Выберите из списка или напишите свою.",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    
    # Шаг 2.1: Кастомная эмоция
    elif state == States.WAITING_CUSTOM_EMOTION:
        # Проверяем, не является ли это кастомной эмоцией для экспозиции
        # Для этого нужно проверить, есть ли в entry_data поле, указывающее на экспозицию
        # Также проверяем, что состояние было установлено в контексте экспозиции
        is_exposure = (
            'situation_name' in entry_data or 
            'event_datetime' in entry_data or 
            'exposure_id' in entry_data or
            'expectations_data' in entry_data
        )
        
        # Дополнительная проверка: если есть emotions_before и это не обычный дневник мыслей
        # (в обычном дневнике мыслей emotions_before тоже есть, но там нет situation_name)
        if not is_exposure and 'emotions_before' in entry_data:
            # Проверяем, есть ли другие признаки экспозиции
            # В экспозициях emotions_before может быть пустым списком на начальном этапе
            is_exposure = 'situation_name' in entry_data or 'event_datetime' in entry_data
        
        if is_exposure:
            # Это экспозиция
            logger.info(f"Detected exposure custom emotion for user {user_id}, entry_data keys: {list(entry_data.keys())}")
            from exposure_handlers import handle_exposure_custom_emotion
            await handle_exposure_custom_emotion(update, context)
            return
        
        # Дополнительная проверка: если состояние было установлено в контексте экспозиции,
        # но поля еще не заполнены, проверяем предыдущее состояние
        # Это может произойти, если пользователь только начал процесс экспозиции
        logger.info(f"Processing custom emotion for user {user_id}, state: {state}, entry_data keys: {list(entry_data.keys())}")
        
        # Если entry_data пустой или содержит только базовые поля, это может быть экспозиция
        # Проверяем, не было ли предыдущее состояние связано с экспозицией
        if not entry_data or len(entry_data) == 0:
            logger.warning(f"Empty entry_data for user {user_id} in WAITING_CUSTOM_EMOTION - might be exposure")
        
        # Валидация для обычного дневника мыслей
        is_valid, error_msg = validate_emotion(text)
        if not is_valid:
            detect_suspicious_activity(user_id, 'invalid_emotion', error_msg)
            keyboard = get_cancel_entry_keyboard()
            await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=keyboard)
            return
        protection_result = detect_suspicious_activity(user_id, 'emotion_input', text)
        if protection_result:
            await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод своей эмоции", text)
            return
        entry_data['current_emotion'] = sanitize_text(text)
        db.save_user_state(user_id, States.WAITING_EMOTION_INTENSITY, entry_data)
        keyboard = add_cancel_button(get_intensity_keyboard())
        await update.message.reply_text(
            "Насколько сильна была эта эмоция? Оцените по шкале от 0 до 100.",
            reply_markup=keyboard
        )
    
    # Шаг 3: Автоматическая мысль
    elif state == States.WAITING_AUTOMATIC_THOUGHT:
        # Валидация
        is_valid, error_msg = validate_thought(text)
        if not is_valid:
            # Обнаружение подозрительной активности
            detect_suspicious_activity(user_id, 'invalid_thought', error_msg)
            keyboard = get_cancel_entry_keyboard()
            await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=keyboard)
            return
        
        # Проверка на подозрительную активность
        protection_result = detect_suspicious_activity(user_id, 'thought_input', text)
        if protection_result:
            await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод автоматической мысли", text)
            return
        entry_data['automatic_thought'] = sanitize_text(text)
        db.save_user_state(user_id, States.WAITING_AUTOMATIC_THOUGHT_CONFIDENCE, entry_data)
        keyboard = add_cancel_button(get_intensity_keyboard())
        await update.message.reply_text(
            "Насколько вы были уверены в этой мысли (0-100%)?",
            reply_markup=keyboard
        )
    
    # Шаг 4: Поведение
    elif state == States.WAITING_ACTION:
        is_valid, error_msg = validate_action(text)
        if not is_valid:
            detect_suspicious_activity(user_id, 'invalid_action', error_msg)
            keyboard = get_cancel_entry_keyboard()
            await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=keyboard)
            return
        protection_result = detect_suspicious_activity(user_id, 'action_input', text)
        if protection_result:
            await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод действия", text)
            return
        entry_data['action'] = sanitize_text(text)
        db.save_user_state(user_id, States.WAITING_EVIDENCE_FOR, entry_data)
        # Получаем автоматическую мысль из шага 3
        automatic_thought = entry_data.get('automatic_thought', '')
        # Экранируем для безопасного отображения
        safe_thought = escape_markdown(automatic_thought)
        keyboard = get_cancel_entry_keyboard()
        await update.message.reply_text(
            f"*Шаг 5: Анализ мысли*\n\n"
            f"*Ваша автоматическая мысль:* {safe_thought}\n\n"
            "Найдите доводы, которые подтверждают вашу автоматическую мысль. "
            "Что говорит в ее пользу?",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    
    # Шаг 5: Доводы за
    elif state == States.WAITING_EVIDENCE_FOR:
        is_valid, error_msg = validate_evidence(text)
        if not is_valid:
            detect_suspicious_activity(user_id, 'invalid_evidence', error_msg)
            keyboard = get_cancel_entry_keyboard()
            await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=keyboard)
            return
        protection_result = detect_suspicious_activity(user_id, 'evidence_input', text)
        if protection_result:
            await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод доводов за", text)
            return
        entry_data['evidence_for'] = sanitize_text(text)
        db.save_user_state(user_id, States.WAITING_EVIDENCE_AGAINST, entry_data)
        keyboard = get_cancel_entry_keyboard()
        await update.message.reply_text(
            "А теперь найдите доводы, которые опровергают ее. "
            "Что говорит против нее? Есть ли другие объяснения?",
            reply_markup=keyboard
        )
    
    # Шаг 5: Доводы против
    elif state == States.WAITING_EVIDENCE_AGAINST:
        is_valid, error_msg = validate_evidence(text)
        if not is_valid:
            detect_suspicious_activity(user_id, 'invalid_evidence', error_msg)
            keyboard = get_cancel_entry_keyboard()
            await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=keyboard)
            return
        protection_result = detect_suspicious_activity(user_id, 'evidence_against_input', text)
        if protection_result:
            await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод доводов против", text)
            return
        entry_data['evidence_against'] = sanitize_text(text)
        # Показываем контекст для альтернативной мысли
        situation = escape_markdown(entry_data.get('situation', ''))
        automatic_thought = escape_markdown(entry_data.get('automatic_thought', ''))
        evidence_for = escape_markdown(entry_data.get('evidence_for', ''))
        evidence_against = escape_markdown(entry_data.get('evidence_against', ''))
        
        context_text = (
            f"*Ситуация:* {situation}\n\n"
            f"*Автоматическая мысль:* {automatic_thought}\n\n"
            f"*Доводы за:* {evidence_for}\n\n"
            f"*Доводы против:* {evidence_against}\n\n"
            "Учитывая ситуацию и доводы 'за' и 'против', какую более уравновешенную "
            "или альтернативную мысль вы можете предложить?"
        )
        db.save_user_state(user_id, States.WAITING_ALTERNATIVE_THOUGHT, entry_data)
        keyboard = get_cancel_entry_keyboard()
        await update.message.reply_text(context_text, reply_markup=keyboard, parse_mode='Markdown')
    
    # Шаг 6: Альтернативная мысль
    elif state == States.WAITING_ALTERNATIVE_THOUGHT:
        is_valid, error_msg = validate_thought(text)
        if not is_valid:
            detect_suspicious_activity(user_id, 'invalid_alternative_thought', error_msg)
            keyboard = get_cancel_entry_keyboard()
            await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=keyboard)
            return
        protection_result = detect_suspicious_activity(user_id, 'alternative_thought_input', text)
        if protection_result:
            await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод альтернативной мысли", text)
            return
        entry_data['current_alternative_thought'] = sanitize_text(text)
        db.save_user_state(user_id, States.WAITING_ALTERNATIVE_THOUGHT_CONFIDENCE, entry_data)
        keyboard = add_cancel_button(get_intensity_keyboard())
        await update.message.reply_text(
            "Насколько вы сейчас уверены в этой альтернативной мысли (0-100%)?",
            reply_markup=keyboard
        )
    
    # Кастомная новая эмоция для экспозиции (в реальности)
    elif state == States.WAITING_CUSTOM_NEW_EMOTION:
        # Проверяем, не является ли это кастомной эмоцией для экспозиции в реальности
        if 'exposure_id' in entry_data or entry_data.get('is_exposure_reality'):
            from exposure_handlers import handle_exposure_custom_reality_emotion
            await handle_exposure_custom_reality_emotion(update, context)
            return
    
    # Шаг 7: Кастомная новая эмоция
    elif state == States.WAITING_CUSTOM_NEW_EMOTION:
        is_valid, error_msg = validate_emotion(text)
        if not is_valid:
            detect_suspicious_activity(user_id, 'invalid_new_emotion', error_msg)
            keyboard = get_cancel_entry_keyboard()
            await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=keyboard)
            return
        protection_result = detect_suspicious_activity(user_id, 'new_emotion_input', text)
        if protection_result:
            await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод новой эмоции", text)
            return
        entry_data['current_new_emotion'] = sanitize_text(text)
        db.save_user_state(user_id, States.WAITING_NEW_EMOTION_INTENSITY, entry_data)
        keyboard = add_cancel_button(get_intensity_keyboard())
        await update.message.reply_text(
            "Насколько сильна эта эмоция? Оцените по шкале от 0 до 100.",
            reply_markup=keyboard
        )
    
    # Шаг 8: Заметка будущему себе
    elif state == States.WAITING_NOTE_TO_FUTURE_SELF:
        is_valid, error_msg = validate_note(text)
        if not is_valid:
            detect_suspicious_activity(user_id, 'invalid_note', error_msg)
            keyboard = get_cancel_entry_keyboard()
            await update.message.reply_text(f"⚠️ {error_msg}", reply_markup=keyboard)
            return
        protection_result = detect_suspicious_activity(user_id, 'note_input', text)
        if protection_result:
            await process_suspicious_input_and_notify_admin(update, context, user_id, "Ввод заметки будущему себе", text)
            return
        entry_data['note_to_future_self'] = sanitize_text(text)
        
        # Проверяем rate limiting для создания записи
        allowed, error_msg = check_rate_limit(user_id, 'entry_creation')
        if not allowed:
            await update.message.reply_text(f"⚠️ {error_msg}")
            return
        
        # Сохраняем запись в БД
        try:
            entry_id = db.save_entry(user_id, entry_data)
            db.clear_user_state(user_id)
            
            await update.message.reply_text(
                "✅ Запись сохранена! Вы всегда можете найти её в разделе 'Мои записи'.",
                reply_markup=get_back_to_menu_keyboard()
            )
            logger.info(f"User {user_id} created entry {entry_id}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении записи для пользователя {user_id}: {e}")
            await update.message.reply_text(
                "⚠️ Произошла ошибка при сохранении записи. Попробуйте позже.",
                reply_markup=get_back_to_menu_keyboard()
            )
    
    # Удаление: подтверждение
    elif state == States.WAITING_DELETE_CONFIRMATION:
        # Проверяем rate limiting для удаления
        allowed, error_msg = check_rate_limit(user_id, 'delete')
        if not allowed:
            await update.message.reply_text(f"⚠️ {error_msg}")
            return
        
        if text.upper().strip() == 'УДАЛИТЬ':
            start_date = entry_data.get('delete_start_date')
            end_date = entry_data.get('delete_end_date')
            
            try:
                deleted_count = db.delete_entries(user_id, start_date, end_date)
                db.clear_user_state(user_id)
                
                await update.message.reply_text(
                    f"✅ Удалено записей: {deleted_count}",
                    reply_markup=get_back_to_menu_keyboard()
                )
                logger.info(f"User {user_id} deleted {deleted_count} entries")
            except Exception as e:
                logger.error(f"Ошибка при удалении записей для пользователя {user_id}: {e}")
                await update.message.reply_text(
                    "⚠️ Произошла ошибка при удалении. Попробуйте позже.",
                    reply_markup=get_back_to_menu_keyboard()
                )
        else:
            await update.message.reply_text(
                "Операция отменена.",
                reply_markup=get_back_to_menu_keyboard()
            )
            db.clear_user_state(user_id)

# ========== Обработчики создания записи ==========

async def handle_emotion_choice(query, context, data):
    """Обрабатывает выбор эмоции из списка"""
    user_id = query.from_user.id
    emotion = data.replace('emotion_', '')
    state_info = db.get_user_state(user_id)
    
    if not state_info:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    entry_data = state_info['data']
    
    if emotion == 'custom':
        db.save_user_state(user_id, States.WAITING_CUSTOM_EMOTION, entry_data)
        keyboard = get_cancel_entry_keyboard()
        await query.edit_message_text("Напишите свою эмоцию:", reply_markup=keyboard)
        return
    
    entry_data['current_emotion'] = emotion
    db.save_user_state(user_id, States.WAITING_EMOTION_INTENSITY, entry_data)
    keyboard = add_cancel_button(get_intensity_keyboard())
    await query.edit_message_text(
        f"Насколько сильна была эмоция '{emotion}'? Оцените по шкале от 0 до 100.",
        reply_markup=keyboard
    )

async def handle_intensity_choice(query, context, data):
    """Обрабатывает выбор интенсивности"""
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
    
    try:
        intensity = int(data.replace('intensity_', ''))
    except ValueError:
        await query.answer("Неверное значение интенсивности.", show_alert=True)
        return
    
    # Валидация интенсивности
    is_valid, error_msg = validate_intensity(intensity)
    if not is_valid:
        await query.answer(error_msg, show_alert=True)
        return
    
    state_info = db.get_user_state(user_id)
    
    if not state_info:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    entry_data = state_info['data']
    state = state_info['state']
    
    # Сначала проверяем состояния для экспозиций (в порядке приоритета)
    if state == States.WAITING_EXPOSURE_REALITY_EMOTION_INTENSITY:
        # Обработка интенсивности реальной эмоции для экспозиции
        from exposure_handlers import handle_exposure_reality_emotion_intensity
        await handle_exposure_reality_emotion_intensity(query, context, data)
        return
    
    if state == States.WAITING_EXPOSURE_EMOTION_INTENSITY:
        # Обработка интенсивности эмоции для экспозиции
        from exposure_handlers import handle_exposure_emotion_intensity
        await handle_exposure_emotion_intensity(query, context, data)
        return
    
    if state == States.WAITING_EMOTION_INTENSITY:
        # Проверяем, не является ли это экспозицией (для экспозиций есть отдельный обработчик)
        # Это может произойти, если состояние было неправильно установлено
        is_exposure = (
            'exposure_id' in entry_data or 
            'situation_name' in entry_data or 
            'event_datetime' in entry_data or
            'expectations_data' in entry_data
        )
        
        if is_exposure:
            # Это экспозиция, но состояние неправильное - должно быть WAITING_EXPOSURE_EMOTION_INTENSITY
            # Обрабатываем через правильный обработчик
            logger.warning(f"User {user_id} has WAITING_EMOTION_INTENSITY but exposure data detected, redirecting to exposure handler")
            from exposure_handlers import handle_exposure_emotion_intensity
            await handle_exposure_emotion_intensity(query, context, data)
            return
        
        # Сохраняем эмоцию в список
        emotion_name = entry_data.get('current_emotion', '')
        if emotion_name:
            # Инициализируем emotions_before, если его нет
            if 'emotions_before' not in entry_data:
                entry_data['emotions_before'] = []
            entry_data['emotions_before'].append({
                'emotion': emotion_name,
                'intensity': intensity
            })
            # Очищаем текущую эмоцию
            entry_data.pop('current_emotion', None)
        
        db.save_user_state(user_id, States.WAITING_MORE_EMOTIONS, entry_data)
        keyboard = add_cancel_button(get_yes_no_keyboard('emotion_yes', 'emotion_no'))
        await query.edit_message_text(
            "Была еще эмоция?",
            reply_markup=keyboard
        )
    
    elif state == States.WAITING_AUTOMATIC_THOUGHT_CONFIDENCE:
        entry_data['automatic_thought_confidence'] = intensity
        db.save_user_state(user_id, States.WAITING_ACTION, entry_data)
        keyboard = get_cancel_entry_keyboard()
        await query.edit_message_text(
            "*Шаг 4: Поведение*\n\n"
            "Что вы сделали (или хотели сделать) в этой ситуации?",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    
    elif state == States.WAITING_ALTERNATIVE_THOUGHT_CONFIDENCE:
        # Сохраняем альтернативную мысль
        thought = entry_data.get('current_alternative_thought', '')
        if thought:
            entry_data['alternative_thoughts'].append({
                'thought': thought,
                'confidence': intensity
            })
            entry_data.pop('current_alternative_thought', None)
        
        db.save_user_state(user_id, States.WAITING_MORE_ALTERNATIVE_THOUGHTS, entry_data)
        keyboard = add_cancel_button(get_yes_no_keyboard('alt_thought_yes', 'alt_thought_no'))
        await query.edit_message_text(
            "Еще альтернативные мысли?",
            reply_markup=keyboard
        )
    
    elif state == States.WAITING_EXPOSURE_PROBABILITY:
        # Обработка вероятности для экспозиции
        from exposure_handlers import handle_exposure_probability
        await handle_exposure_probability(query, context, data)
        return
    
    elif state == States.WAITING_EXPOSURE_EMOTION_INTENSITY:
        # Обработка интенсивности эмоции для экспозиции
        from exposure_handlers import handle_exposure_emotion_intensity
        await handle_exposure_emotion_intensity(query, context, data)
        return
    
    elif state == States.WAITING_EXPOSURE_REALITY_EMOTION_INTENSITY:
        # Обработка интенсивности реальной эмоции для экспозиции
        # Это дублирующая проверка на случай, если первая не сработала
        from exposure_handlers import handle_exposure_reality_emotion_intensity
        await handle_exposure_reality_emotion_intensity(query, context, data)
        return
    
    elif state == States.WAITING_EMOTION_REASSESSMENT:
        # Обновляем интенсивность существующей эмоции
        reassess_index = entry_data.get('reassessing_emotion_index', 0)
        emotions_before = entry_data.get('emotions_before', [])
        
        if reassess_index < len(emotions_before):
            emotion_name = emotions_before[reassess_index]['emotion']
            # Находим или создаем запись в emotions_after
            emotions_after = entry_data.get('emotions_after', [])
            found = False
            for em in emotions_after:
                if em.get('emotion') == emotion_name:
                    em['intensity'] = intensity
                    found = True
                    break
            if not found:
                emotions_after.append({
                    'emotion': emotion_name,
                    'intensity': intensity
                })
            
            entry_data['emotions_after'] = emotions_after
            reassess_index += 1
            entry_data['reassessing_emotion_index'] = reassess_index
            
            # Проверяем, есть ли еще эмоции для переоценки
            if reassess_index < len(emotions_before):
                next_emotion = emotions_before[reassess_index]['emotion']
                alt_thoughts = entry_data.get('alternative_thoughts', [])
                first_alt = alt_thoughts[0].get('thought', '') if alt_thoughts else ''
                
                db.save_user_state(user_id, States.WAITING_EMOTION_REASSESSMENT, entry_data)
                keyboard = add_cancel_button(get_intensity_keyboard())
                await query.edit_message_text(
                    f"Теперь, когда вы рассмотрели альтернативную мысль '{first_alt}', "
                    f"как изменилась интенсивность эмоции '{next_emotion}'?",
                    reply_markup=keyboard
                )
            else:
                # Все эмоции переоценены, спрашиваем про новые
                db.save_user_state(user_id, States.WAITING_NEW_EMOTION, entry_data)
                await query.edit_message_text(
                    "*Шаг 7: Новые эмоции*\n\n"
                    "Появились ли другие, возможно, более приятные эмоции? "
                    "(Например, облегчение, спокойствие, надежда). Выберите или введите.",
                    reply_markup=get_new_emotions_keyboard(),
                    parse_mode='Markdown'
                )
        else:
            # Нет больше эмоций для переоценки
            db.save_user_state(user_id, States.WAITING_NEW_EMOTION, entry_data)
            await query.edit_message_text(
                "*Шаг 7: Новые эмоции*\n\n"
                "Появились ли другие, возможно, более приятные эмоции? "
                "(Например, облегчение, спокойствие, надежда). Выберите или введите.",
                reply_markup=get_new_emotions_keyboard(),
                parse_mode='Markdown'
            )
    
    elif state == States.WAITING_NEW_EMOTION_INTENSITY:
        # Сохраняем новую эмоцию
        emotion_name = entry_data.get('current_new_emotion', '')
        if emotion_name:
            entry_data['emotions_after'].append({
                'emotion': emotion_name,
                'intensity': intensity
            })
            entry_data.pop('current_new_emotion', None)
        
        db.save_user_state(user_id, States.WAITING_MORE_NEW_EMOTIONS, entry_data)
        keyboard = add_cancel_button(get_yes_no_keyboard('new_emotion_yes', 'new_emotion_no'))
        await query.edit_message_text(
            "Появились еще эмоции?",
            reply_markup=keyboard
        )

async def handle_emotion_custom_flow(query, context, data):
    """Обрабатывает поток кастомных эмоций и кнопки Да/Нет"""
    user_id = query.from_user.id
    state_info = db.get_user_state(user_id)
    
    if not state_info:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    entry_data = state_info['data']
    
    if data == 'emotion_custom':
        db.save_user_state(user_id, States.WAITING_CUSTOM_EMOTION, entry_data)
        await query.edit_message_text("Напишите свою эмоцию:")
    
    elif data == 'emotion_yes':
        # Возвращаемся к выбору эмоции
        db.save_user_state(user_id, States.WAITING_EMOTION, entry_data)
        keyboard = add_cancel_button(get_emotions_keyboard())
        await query.edit_message_text(
            "Какая еще эмоция возникла? Выберите из списка или напишите свою.",
            reply_markup=keyboard
        )
    
    elif data == 'emotion_no':
        # Переходим к автоматической мысли (Шаг 3)
        db.save_user_state(user_id, States.WAITING_AUTOMATIC_THOUGHT, entry_data)
        keyboard = get_cancel_entry_keyboard()
        await query.edit_message_text(
            "*Шаг 3: Автоматическая мысль*\n\n"
            "Какая мысль пришла вам в голову в тот момент? "
            "(Например, 'Я неудачник', 'Со мной так всегда').",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )

async def handle_alternative_thought_flow(query, context, data):
    """Обрабатывает поток альтернативных мыслей"""
    user_id = query.from_user.id
    state_info = db.get_user_state(user_id)
    
    if not state_info:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    entry_data = state_info['data']
    
    if data == 'alt_thought_yes':
        # Показываем контекст снова для новой альтернативной мысли
        situation = escape_markdown(entry_data.get('situation', ''))
        automatic_thought = escape_markdown(entry_data.get('automatic_thought', ''))
        evidence_for = escape_markdown(entry_data.get('evidence_for', ''))
        evidence_against = escape_markdown(entry_data.get('evidence_against', ''))
        
        context_text = (
            f"*Ситуация:* {situation}\n\n"
            f"*Автоматическая мысль:* {automatic_thought}\n\n"
            f"*Доводы за:* {evidence_for}\n\n"
            f"*Доводы против:* {evidence_against}\n\n"
            "Какую еще альтернативную мысль вы можете предложить?"
        )
        db.save_user_state(user_id, States.WAITING_ALTERNATIVE_THOUGHT, entry_data)
        await query.edit_message_text(context_text, parse_mode='Markdown')
    
    elif data == 'alt_thought_no':
        # Переходим к переоценке эмоций (Шаг 7)
        emotions_before = entry_data.get('emotions_before', [])
        if emotions_before:
            first_emotion = emotions_before[0]['emotion']
            alt_thoughts = entry_data.get('alternative_thoughts', [])
            first_alt = alt_thoughts[0].get('thought', '') if alt_thoughts else ''
            
            entry_data['reassessing_emotion_index'] = 0
            db.save_user_state(user_id, States.WAITING_EMOTION_REASSESSMENT, entry_data)
            keyboard = add_cancel_button(get_intensity_keyboard())
            await query.edit_message_text(
                f"*Шаг 7: Переоценка эмоций*\n\n"
                f"Теперь, когда вы рассмотрели альтернативную мысль '{first_alt}', "
                f"как изменилась интенсивность эмоции '{first_emotion}'?",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        else:
            # Если нет эмоций для переоценки, переходим к новым эмоциям
            db.save_user_state(user_id, States.WAITING_NEW_EMOTION, entry_data)
            keyboard = add_cancel_button(get_new_emotions_keyboard())
            await query.edit_message_text(
                "*Шаг 7: Новые эмоции*\n\n"
                "Появились ли другие, возможно, более приятные эмоции? "
                "(Например, облегчение, спокойствие, надежда). Выберите или введите.",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )

async def handle_new_emotion_choice(query, context, data):
    """Обрабатывает выбор новой эмоции"""
    user_id = query.from_user.id
    emotion = data.replace('new_emotion_', '')
    state_info = db.get_user_state(user_id)
    
    if not state_info:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    entry_data = state_info['data']
    
    if emotion == 'custom':
        db.save_user_state(user_id, States.WAITING_CUSTOM_NEW_EMOTION, entry_data)
        await query.edit_message_text("Напишите свою эмоцию:")
        return
    
    entry_data['current_new_emotion'] = emotion
    db.save_user_state(user_id, States.WAITING_NEW_EMOTION_INTENSITY, entry_data)
    keyboard = add_cancel_button(get_intensity_keyboard())
    await query.edit_message_text(
        f"Насколько сильна эмоция '{emotion}'? Оцените по шкале от 0 до 100.",
        reply_markup=keyboard
    )

async def handle_new_emotion_custom(query, context):
    """Обрабатывает кастомную новую эмоцию (через callback)"""
    user_id = query.from_user.id
    state_info = db.get_user_state(user_id)
    
    if not state_info:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    entry_data = state_info['data']
    db.save_user_state(user_id, States.WAITING_CUSTOM_NEW_EMOTION, entry_data)
    keyboard = get_cancel_entry_keyboard()
    await query.edit_message_text("Напишите свою эмоцию:", reply_markup=keyboard)

async def handle_new_emotion_flow(query, context, data):
    """Обрабатывает поток новых эмоций"""
    user_id = query.from_user.id
    state_info = db.get_user_state(user_id)
    
    if not state_info:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    entry_data = state_info['data']
    
    if data == 'new_emotion_yes':
        db.save_user_state(user_id, States.WAITING_NEW_EMOTION, entry_data)
        keyboard = add_cancel_button(get_new_emotions_keyboard())
        await query.edit_message_text(
            "Какая еще эмоция появилась? Выберите или введите.",
            reply_markup=keyboard
        )
    
    elif data in ['new_emotion_no', 'new_emotion_none']:
        # Формируем итоговую сводку (Шаг 8)
        summary = format_entry_summary(entry_data)
        is_success = check_success(entry_data)
        
        praise_text = ""
        if is_success:
            praise_text = (
                "Отлично! Вы проделали важную работу. "
                "Видите, как анализ мыслей может менять состояние?\n\n"
            )
        else:
            praise_text = (
                "Я вижу, что эмоции изменились незначительно или ухудшились. "
                "Это нормально! Самое главное — вы пробуете и не поддаетесь автоматическим мыслям. "
                "Обязательно получится. Если сложности сохраняются, вы можете скачать эту запись "
                "и обсудить с психотерапевтом.\n\n"
            )
        
        praise_text += "Помните, мы учимся, как в детстве учились ходить — шаг за шагом. Вы — молодец!"
        
        final_text = summary + "\n\n" + praise_text
        
        if is_success:
            # Запрашиваем заметку (Шаг 8)
            db.save_user_state(user_id, States.WAITING_NOTE_TO_FUTURE_SELF, entry_data)
            keyboard = get_cancel_entry_keyboard()
            await query.edit_message_text(
                final_text + "\n\n*Шаг 8: Заметка будущему себе*\n\n"
                "Чему вас научила эта ситуация? Что помогло? "
                "Напишите короткую заметку себе на будущее.",
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        else:
            # Сохраняем запись без заметки
            entry_id = db.save_entry(user_id, entry_data)
            db.clear_user_state(user_id)
            await query.edit_message_text(
                final_text,
                reply_markup=get_back_to_menu_keyboard(),
                parse_mode='Markdown'
            )

# ========== Обработчики календаря ==========

async def handle_calendar(query, context, data):
    """Обрабатывает события календаря"""
    user_id = query.from_user.id
    state_info = db.get_user_state(user_id)
    
    if not state_info:
        await query.answer("Сессия истекла. Начните заново.", show_alert=True)
        return
    
    state = state_info['state']
    entry_data = state_info['data']
    
    # Определяем префикс календаря
    prefix = 'cal'
    if data.startswith('search_'):
        prefix = 'search'
    
    # Игнорируем нажатия на пустые кнопки
    if data == 'cal_ignore' or data == 'search_ignore':
        await query.answer()
        return
    
    # Отмена выбора даты
    if data == 'cal_cancel' or data == 'search_cancel' or data == 'search_exposure_cancel' or \
       data == 'exposure_date_cancel' or data == 'download_exposure_cancel' or data == 'delete_exposure_cancel':
        action_type = entry_data.get('action_type', 'download')
        entry_type = entry_data.get('entry_type', 'thoughts')
        
        if entry_type == 'exposure' and state == States.WAITING_SEARCH_DATE:
            from exposure_handlers import show_search_menu_exposure
            await show_search_menu_exposure(query, context)
        elif entry_type == 'exposure' and action_type == 'download':
            from exposure_handlers import show_download_period_exposure
            await show_download_period_exposure(query, context)
        elif entry_type == 'exposure' and action_type == 'delete':
            from exposure_handlers import show_delete_period_exposure
            await show_delete_period_exposure(query, context)
        elif data == 'exposure_date_cancel':
            from exposure_handlers import start_new_entry_exposure
            await start_new_entry_exposure(query, context)
        elif action_type == 'download':
            await show_download_period(query, context)
        elif action_type == 'delete':
            await show_delete_period(query, context)
        elif state == States.WAITING_SEARCH_DATE:
            from search import show_search_menu
            await show_search_menu(query, context)
        return
    
    # Преобразуем search_ в cal_ для обработки (но не search_exposure_)
    if data.startswith('search_') and not data.startswith('search_exposure_'):
        data = data.replace('search_', 'cal_', 1)
    
    # Обработка календаря для поиска экспозиций
    if data.startswith('search_exposure_prev_month_'):
        parts = data.split('_')
        if len(parts) >= 6:
            year_str = parts[4]
            month_str = parts[5]
        else:
            _, _, _, _, year_str, month_str = data.split('_')
        year = int(year_str)
        month = int(month_str)
        
        if month == 1:
            month = 12
            year -= 1
        else:
            month -= 1
        
        await query.edit_message_text(
            "Выберите дату:",
            reply_markup=create_calendar(year, month, prefix='search_exposure')
        )
        return
    
    if data.startswith('search_exposure_next_month_'):
        parts = data.split('_')
        if len(parts) >= 6:
            year_str = parts[4]
            month_str = parts[5]
        else:
            _, _, _, _, year_str, month_str = data.split('_')
        year = int(year_str)
        month = int(month_str)
        
        if month == 12:
            month = 1
            year += 1
        else:
            month += 1
        
        await query.edit_message_text(
            "Выберите дату:",
            reply_markup=create_calendar(year, month, prefix='search_exposure')
        )
        return
    
    if data.startswith('search_exposure_day_'):
        _, _, _, _, year_str, month_str, day_str = data.split('_')
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)
        
        # Поиск экспозиций за выбранную дату
        start_date = datetime(year, month, day, 0, 0, 0).isoformat()
        end_date = datetime(year, month, day, 23, 59, 59).isoformat()
        
        exposures = db.get_user_exposures(user_id, start_date=start_date, end_date=end_date)
        db.clear_user_state(user_id)
        
        if not exposures:
            await query.edit_message_text(
                f"❌ Экспозиции за {day:02d}.{month:02d}.{year} не найдены.",
                reply_markup=get_back_to_menu_keyboard()
            )
            return
        
        # Показываем результаты (первые 20)
        keyboard = []
        for exposure in exposures[:20]:
            situation_name = exposure.get('situation_name', 'Без названия')
            event_datetime = exposure.get('event_datetime', '')
            if event_datetime:
                try:
                    dt = datetime.fromisoformat(event_datetime)
                    date_str = dt.strftime('%d.%m.%Y %H:%M')
                except:
                    date_str = event_datetime
            else:
                date_str = 'Дата не указана'
            preview = f"{date_str}: {situation_name[:30]}"
            if len(situation_name) > 30:
                preview += "..."
            keyboard.append([InlineKeyboardButton(preview, callback_data=f"exposure_{exposure['id']}")])
        
        keyboard.append([InlineKeyboardButton("🔙 В меню", callback_data='menu')])
        
        await query.edit_message_text(
            f"📅 *Найдено экспозиций за {day:02d}.{month:02d}.{year}: {len(exposures)}*\n\n"
            f"Выберите запись для просмотра:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        logger.info(f"Пользователь {user_id} выполнил поиск экспозиций по дате {day:02d}.{month:02d}.{year}: найдено {len(exposures)} записей")
        return
    
    # Навигация по календарю для download_exposure и delete_exposure
    if data.startswith('download_exposure_prev_month_') or data.startswith('delete_exposure_prev_month_'):
        parts = data.split('_')
        if len(parts) >= 6:
            year_str = parts[3] if 'download' in data else parts[3]
            month_str = parts[4] if 'download' in data else parts[4]
        else:
            _, _, _, year_str, month_str = data.split('_')[-2:]
        year = int(year_str)
        month = int(month_str)
        
        if month == 1:
            month = 12
            year -= 1
        else:
            month -= 1
        
        prefix = 'download_exposure' if 'download' in data else 'delete_exposure'
        await query.edit_message_text(
            "Выберите дату:",
            reply_markup=create_calendar(year, month, prefix=prefix)
        )
        return
    
    if data.startswith('download_exposure_next_month_') or data.startswith('delete_exposure_next_month_'):
        parts = data.split('_')
        if len(parts) >= 6:
            year_str = parts[3] if 'download' in data else parts[3]
            month_str = parts[4] if 'download' in data else parts[4]
        else:
            _, _, _, year_str, month_str = data.split('_')[-2:]
        year = int(year_str)
        month = int(month_str)
        
        if month == 12:
            month = 1
            year += 1
        else:
            month += 1
        
        prefix = 'download_exposure' if 'download' in data else 'delete_exposure'
        await query.edit_message_text(
            "Выберите дату:",
            reply_markup=create_calendar(year, month, prefix=prefix)
        )
        return
    
    # Обработка выбора даты для download_exposure и delete_exposure
    if data.startswith('download_exposure_day_') or data.startswith('delete_exposure_day_'):
        # Формат: download_exposure_day_YYYY_MM_DD или delete_exposure_day_YYYY_MM_DD
        # Убираем префикс и получаем day_YYYY_MM_DD
        if data.startswith('download_exposure_day_'):
            date_part = data.replace('download_exposure_day_', '')
        else:
            date_part = data.replace('delete_exposure_day_', '')
        
        # Разбираем day_YYYY_MM_DD
        date_parts = date_part.split('_')
        if len(date_parts) >= 4:
            # Формат: day_YYYY_MM_DD
            year_str = date_parts[1]
            month_str = date_parts[2]
            day_str = date_parts[3]
        else:
            # Fallback: последние 3 части
            year_str, month_str, day_str = date_parts[-3:]
        
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)
        
        selected_date = datetime(year, month, day)
        date_iso = selected_date.isoformat()
        
        state_info = db.get_user_state(user_id)
        if not state_info:
            await query.answer("Сессия истекла", show_alert=True)
            return
        
        state = state_info['state']
        entry_data = state_info['data']
        
        if 'download' in data:
            if state == States.WAITING_DOWNLOAD_START_DATE:
                entry_data['download_start_date'] = date_iso
                db.save_user_state(user_id, States.WAITING_DOWNLOAD_END_DATE, entry_data)
                await query.edit_message_text(
                    f"✅ Начальная дата: {day:02d}.{month:02d}.{year}\n\n"
                    "Выберите конечную дату:",
                    reply_markup=create_calendar(year, month, prefix='download_exposure')
                )
            elif state == States.WAITING_DOWNLOAD_END_DATE:
                entry_data['download_end_date'] = date_iso
                start_date_str = entry_data.get('download_start_date')
                if start_date_str:
                    start_date = datetime.fromisoformat(start_date_str)
                    if selected_date < start_date:
                        await query.answer("Конечная дата не может быть раньше начальной!", show_alert=True)
                        return
                
                start_date_iso = entry_data.get('download_start_date')
                end_date_iso = datetime(year, month, day, 23, 59, 59).isoformat()
                
                exposures = db.get_user_exposures(user_id, start_date=start_date_iso, end_date=end_date_iso)
                db.clear_user_state(user_id)
                
                if not exposures:
                    await query.edit_message_text(
                        "❌ Записи не найдены за выбранный период.",
                        reply_markup=get_back_to_menu_keyboard()
                    )
                    return
                
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
                    import os
                    if os.path.exists(excel_path):
                        os.remove(excel_path)
                except Exception as e:
                    logger.error(f"Ошибка при отправке Excel: {e}")
                    await query.answer("Ошибка при создании файла", show_alert=True)
        elif 'delete' in data:
            if state == States.WAITING_DELETE_START_DATE:
                entry_data['delete_start_date'] = date_iso
                db.save_user_state(user_id, States.WAITING_DELETE_END_DATE, entry_data)
                await query.edit_message_text(
                    f"✅ Начальная дата: {day:02d}.{month:02d}.{year}\n\n"
                    "Выберите конечную дату:",
                    reply_markup=create_calendar(year, month, prefix='delete_exposure')
                )
            elif state == States.WAITING_DELETE_END_DATE:
                entry_data['delete_end_date'] = date_iso
                start_date_str = entry_data.get('delete_start_date')
                if start_date_str:
                    start_date = datetime.fromisoformat(start_date_str)
                    if selected_date < start_date:
                        await query.answer("Конечная дата не может быть раньше начальной!", show_alert=True)
                        return
                
                start_date_iso = entry_data.get('delete_start_date')
                end_date_iso = datetime(year, month, day, 23, 59, 59).isoformat()
                
                exposures = db.get_user_exposures(user_id, start_date=start_date_iso, end_date=end_date_iso)
                count = len(exposures)
                
                if count == 0:
                    await query.edit_message_text(
                        "За выбранный период записей не найдено.",
                        reply_markup=get_back_to_menu_keyboard()
                    )
                    db.clear_user_state(user_id)
                    return
                
                state_data = {
                    'delete_start_date': start_date_iso,
                    'delete_end_date': end_date_iso,
                    'entry_type': 'exposure'
                }
                db.save_user_state(user_id, States.WAITING_DELETE_CONFIRMATION, state_data)
                
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Да, удалить", callback_data=f'confirm_delete_exposure_{count}_custom'),
                        InlineKeyboardButton("❌ Отмена", callback_data='menu')
                    ]
                ]
                
                await query.edit_message_text(
                    f"⚠️ *Подтверждение удаления*\n\n"
                    f"Период: {datetime.fromisoformat(start_date_iso).strftime('%d.%m.%Y')} - {day:02d}.{month:02d}.{year}\n"
                    f"Количество записей: *{count}*\n\n"
                    f"Вы уверены, что хотите удалить эти записи?\n\n"
                    f"Это действие нельзя отменить.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
        return
    
    # Навигация по календарю для экспозиций
    if data.startswith('exposure_date_prev_month_'):
        parts = data.split('_')
        if len(parts) >= 6:
            year_str = parts[4]
            month_str = parts[5]
        else:
            _, _, _, _, year_str, month_str = data.split('_')
        year = int(year_str)
        month = int(month_str)
        
        if month == 1:
            month = 12
            year -= 1
        else:
            month -= 1
        
        await query.edit_message_text(
            "Выберите дату:",
            reply_markup=create_calendar(year, month, prefix='exposure_date')
        )
        return
    
    if data.startswith('exposure_date_next_month_'):
        parts = data.split('_')
        if len(parts) >= 6:
            year_str = parts[4]
            month_str = parts[5]
        else:
            _, _, _, _, year_str, month_str = data.split('_')
        year = int(year_str)
        month = int(month_str)
        
        if month == 12:
            month = 1
            year += 1
        else:
            month += 1
        
        await query.edit_message_text(
            "Выберите дату:",
            reply_markup=create_calendar(year, month, prefix='exposure_date')
        )
        return
    
    # Переключение месяцев
    if data.startswith('cal_prev_month_'):
        parts = data.split('_')
        if len(parts) >= 5:
            year_str = parts[3]
            month_str = parts[4]
        else:
            _, _, _, year_str, month_str = data.split('_')
        year = int(year_str)
        month = int(month_str)
        
        if month == 1:
            month = 12
            year -= 1
        else:
            month -= 1
        
        await query.edit_message_text(
            "Выберите дату:",
            reply_markup=create_calendar(year, month, prefix=prefix)
        )
        return
    
    if data.startswith('cal_next_month_'):
        parts = data.split('_')
        if len(parts) >= 5:
            year_str = parts[3]
            month_str = parts[4]
        else:
            _, _, _, year_str, month_str = data.split('_')
        year = int(year_str)
        month = int(month_str)
        
        if month == 12:
            month = 1
            year += 1
        else:
            month += 1
        
        await query.edit_message_text(
            "Выберите дату:",
            reply_markup=create_calendar(year, month, prefix=prefix)
        )
        return
    
    # Выбор даты для экспозиций
    if data.startswith('exposure_date_day_'):
        from exposure_handlers import handle_exposure_date_choice
        # Формат: exposure_date_day_2026_1_24
        parts = data.split('_')
        if len(parts) >= 6:
            year_str = parts[3]
            month_str = parts[4]
            day_str = parts[5]
        else:
            # Fallback для старого формата (если есть)
            _, _, _, _, year_str, month_str, day_str = data.split('_')
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)
        await handle_exposure_date_choice(query, context, year, month, day)
        return
    
    # Выбор времени для экспозиций
    if data.startswith('exposure_time_'):
        from exposure_handlers import handle_exposure_time_choice
        time_str = data.replace('exposure_time_', '')
        await handle_exposure_time_choice(query, context, time_str)
        return
    
    # Назад к выбору даты для экспозиций
    if data == 'exposure_back_date':
        from exposure_handlers import start_new_entry_exposure
        state_info = db.get_user_state(user_id)
        if state_info:
            entry_data = state_info['data']
            if 'selected_date' in entry_data:
                del entry_data['selected_date']
            db.save_user_state(user_id, States.WAITING_EXPOSURE_DATE, entry_data)
        await query.edit_message_text(
            "📅 Выберите дату события:",
            reply_markup=create_calendar(prefix='exposure_date'),
            parse_mode='Markdown'
        )
        return
    
    # Выбор даты
    if data.startswith('cal_day_'):
        _, _, year_str, month_str, day_str = data.split('_')
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)
        
        selected_date = datetime(year, month, day)
        date_iso = selected_date.isoformat()
        
        # Проверяем, какую дату выбираем - начальную или конечную
        if state == States.WAITING_DOWNLOAD_START_DATE:
            entry_type = entry_data.get('entry_type', 'thoughts')
            entry_data['download_start_date'] = date_iso
            db.save_user_state(user_id, States.WAITING_DOWNLOAD_END_DATE, entry_data)
            prefix = 'download_exposure' if entry_type == 'exposure' else 'cal'
            await query.edit_message_text(
                f"✅ Начальная дата: {day:02d}.{month:02d}.{year}\n\n"
                "Выберите конечную дату:",
                reply_markup=create_calendar(year, month, prefix=prefix)
            )
        
        elif state == States.WAITING_DOWNLOAD_END_DATE:
            entry_type = entry_data.get('entry_type', 'thoughts')
            entry_data['download_end_date'] = date_iso
            # Проверяем, что конечная дата не раньше начальной
            start_date_str = entry_data.get('download_start_date')
            if start_date_str:
                start_date = datetime.fromisoformat(start_date_str)
                if selected_date < start_date:
                    await query.answer(
                        "Конечная дата не может быть раньше начальной!",
                        show_alert=True
                    )
                    return
            
            # Загружаем данные
            start_date_iso = entry_data.get('download_start_date')
            end_date_iso = datetime(year, month, day, 23, 59, 59).isoformat()
            
            if entry_type == 'exposure':
                from excel_generator import generate_excel
                exposures = db.get_user_exposures(user_id, start_date=start_date_iso, end_date=end_date_iso)
                db.clear_user_state(user_id)
                
                if not exposures:
                    await query.edit_message_text(
                        "❌ Записи не найдены за выбранный период.",
                        reply_markup=get_back_to_menu_keyboard()
                    )
                    return
                
                excel_path = generate_excel(exposures, user_id, entry_type='exposure')
                try:
                    with open(excel_path, 'rb') as excel_file:
                        await query.message.reply_document(
                            document=excel_file,
                            filename=f'Экспозиции_{user_id}.xlsx',
                            caption=f"📥 Экспортировано записей: {len(exposures)}"
                        )
                    await query.answer("Файл отправлен")
                    import os
                    if os.path.exists(excel_path):
                        os.remove(excel_path)
                except Exception as e:
                    logger.error(f"Ошибка при отправке Excel: {e}")
                    await query.answer("Ошибка при создании файла", show_alert=True)
                return
            
            entries = db.get_user_entries(user_id, start_date_iso, end_date_iso)
            if not entries:
                await query.edit_message_text(
                    "За выбранный период записей не найдено.",
                    reply_markup=get_back_to_menu_keyboard()
                )
                db.clear_user_state(user_id)
                return
            
            filepath = generate_excel(entries, user_id)
            await query.message.reply_document(
                document=open(filepath, 'rb'),
                filename=os.path.basename(filepath)
            )
            await query.message.reply_text(
                f"✅ Файл готов! Период: {datetime.fromisoformat(start_date_iso).strftime('%d.%m.%Y')} - {day:02d}.{month:02d}.{year}",
                reply_markup=get_back_to_menu_keyboard()
            )
            os.remove(filepath)
            db.clear_user_state(user_id)
        
        elif state == States.WAITING_DELETE_START_DATE:
            entry_type = entry_data.get('entry_type', 'thoughts')
            entry_data['delete_start_date'] = date_iso
            db.save_user_state(user_id, States.WAITING_DELETE_END_DATE, entry_data)
            prefix = 'delete_exposure' if entry_type == 'exposure' else 'cal'
            await query.edit_message_text(
                f"✅ Начальная дата: {day:02d}.{month:02d}.{year}\n\n"
                "Выберите конечную дату:",
                reply_markup=create_calendar(year, month, prefix=prefix)
            )
        
        elif state == States.WAITING_DELETE_END_DATE:
            entry_type = entry_data.get('entry_type', 'thoughts')
            entry_data['delete_end_date'] = date_iso
            # Проверяем, что конечная дата не раньше начальной
            start_date_str = entry_data.get('delete_start_date')
            if start_date_str:
                start_date = datetime.fromisoformat(start_date_str)
                if selected_date < start_date:
                    await query.answer(
                        "Конечная дата не может быть раньше начальной!",
                        show_alert=True
                    )
                    return
            
            # Подтверждаем удаление
            start_date_iso = entry_data.get('delete_start_date')
            end_date_iso = datetime(year, month, day, 23, 59, 59).isoformat()
            
            if entry_type == 'exposure':
                exposures = db.get_user_exposures(user_id, start_date=start_date_iso, end_date=end_date_iso)
                count = len(exposures)
                
                if count == 0:
                    await query.edit_message_text(
                        "За выбранный период записей не найдено.",
                        reply_markup=get_back_to_menu_keyboard()
                    )
                    db.clear_user_state(user_id)
                    return
                
                state_data = {
                    'delete_start_date': start_date_iso,
                    'delete_end_date': end_date_iso,
                    'entry_type': 'exposure'
                }
                db.save_user_state(user_id, States.WAITING_DELETE_CONFIRMATION, state_data)
                
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Да, удалить", callback_data=f'confirm_delete_exposure_{count}_custom'),
                        InlineKeyboardButton("❌ Отмена", callback_data='menu')
                    ]
                ]
                
                await query.edit_message_text(
                    f"⚠️ *Подтверждение удаления*\n\n"
                    f"Период: {datetime.fromisoformat(start_date_iso).strftime('%d.%m.%Y')} - {day:02d}.{month:02d}.{year}\n"
                    f"Количество записей: *{count}*\n\n"
                    f"Вы уверены, что хотите удалить эти записи?\n\n"
                    f"Это действие нельзя отменить.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                return
            
            entries = db.get_user_entries(user_id, start_date_iso, end_date_iso)
            count = len(entries)
            
            if count == 0:
                await query.edit_message_text(
                    "За выбранный период записей не найдено.",
                    reply_markup=get_back_to_menu_keyboard()
                )
                db.clear_user_state(user_id)
                return
            
            state_data = {
                'delete_start_date': start_date_iso,
                'delete_end_date': end_date_iso
            }
            db.save_user_state(user_id, States.WAITING_DELETE_CONFIRMATION, state_data)
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Да, удалить", callback_data=f'confirm_delete_{count}'),
                    InlineKeyboardButton("❌ Отмена", callback_data='menu')
                ]
            ]
            
            await query.edit_message_text(
                f"⚠️ *Подтверждение удаления*\n\n"
                f"Период: {datetime.fromisoformat(start_date_iso).strftime('%d.%m.%Y')} - {day:02d}.{month:02d}.{year}\n"
                f"Количество записей: *{count}*\n\n"
                f"Вы уверены, что хотите удалить эти записи?\n\n"
                f"Это действие нельзя отменить.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        
        elif state == States.WAITING_SEARCH_DATE:
            # Устанавливаем entry_type по умолчанию, если не установлен
            if 'entry_type' not in entry_data:
                entry_data['entry_type'] = 'thoughts'
            entry_type = entry_data.get('entry_type', 'thoughts')
            if entry_type == 'exposure':
                # Поиск экспозиций за выбранную дату
                start_date = datetime(year, month, day, 0, 0, 0).isoformat()
                end_date = datetime(year, month, day, 23, 59, 59).isoformat()
                
                exposures = db.get_user_exposures(user_id, start_date=start_date, end_date=end_date)
                db.clear_user_state(user_id)
                
                if not exposures:
                    await query.edit_message_text(
                        f"❌ Экспозиции за {day:02d}.{month:02d}.{year} не найдены.",
                        reply_markup=get_back_to_menu_keyboard()
                    )
                    return
                
                # Показываем результаты (первые 20)
                keyboard = []
                for exposure in exposures[:20]:
                    situation_name = exposure.get('situation_name', 'Без названия')
                    event_datetime = exposure.get('event_datetime', '')
                    if event_datetime:
                        try:
                            dt = datetime.fromisoformat(event_datetime)
                            date_str = dt.strftime('%d.%m.%Y %H:%M')
                        except:
                            date_str = event_datetime
                    else:
                        date_str = 'Дата не указана'
                    preview = f"{date_str}: {situation_name[:30]}"
                    if len(situation_name) > 30:
                        preview += "..."
                    keyboard.append([InlineKeyboardButton(preview, callback_data=f"exposure_{exposure['id']}")])
                
                keyboard.append([InlineKeyboardButton("🔙 В меню", callback_data='menu')])
                
                await query.edit_message_text(
                    f"📅 *Найдено экспозиций за {day:02d}.{month:02d}.{year}: {len(exposures)}*\n\n"
                    f"Выберите запись для просмотра:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                logger.info(f"Пользователь {user_id} выполнил поиск экспозиций по дате {day:02d}.{month:02d}.{year}: найдено {len(exposures)} записей")
            else:
                # Поиск записей за выбранную дату
                start_date = datetime(year, month, day, 0, 0, 0).isoformat()
                end_date = datetime(year, month, day, 23, 59, 59).isoformat()
                
                entries = db.get_user_entries(user_id, start_date, end_date)
                db.clear_user_state(user_id)
                
                if not entries:
                    await query.edit_message_text(
                        f"❌ Записи за {day:02d}.{month:02d}.{year} не найдены.",
                        reply_markup=get_back_to_menu_keyboard()
                    )
                    return
                
                # Показываем результаты (первые 20)
                keyboard = []
                for entry in entries[:20]:
                    date_str = datetime.fromisoformat(entry['timestamp']).strftime('%d.%m.%Y %H:%M')
                    situation_preview = entry['situation'][:30] + '...' if len(entry.get('situation', '')) > 30 else entry.get('situation', '')
                    text = f"{date_str}: {situation_preview}"
                    keyboard.append([InlineKeyboardButton(text, callback_data=f"entry_{entry['id']}")])
                
                keyboard.append([InlineKeyboardButton("🔙 В меню", callback_data='menu')])
                
                await query.edit_message_text(
                    f"📅 *Найдено записей за {day:02d}.{month:02d}.{year}: {len(entries)}*\n\n"
                    f"Выберите запись для просмотра:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
                logger.info(f"Пользователь {user_id} выполнил поиск по дате {day:02d}.{month:02d}.{year}: найдено {len(entries)} записей")

# ========== Пароль: запрос и выполнение действия ==========

async def request_password_for_action(query, context, action: str, action_data: dict = None, section: str = None):
    """
    Запрашивает пароль перед выполнением защищённого действия.
    section: раздел (my_entries, download, delete, search) — при успешной проверке даёт доступ ко всем действиям раздела.
    Возвращает True если вызывающему нужно прерваться (ждём ввода пароля).
    """
    user_id = query.from_user.id
    from admin import is_admin
    if is_admin(query.from_user):
        return False
    if not has_user_password(user_id):
        await query.answer("Сначала создайте пароль через /start", show_alert=True)
        return True
    if not is_password_verification_enabled(user_id):
        return False  # Проверка отключена — пропускаем
    # Проверяем, есть ли уже доступ к разделу (сессия)
    if section and section in _get_password_verified_sections(user_id):
        return False  # Уже проверено — пропускаем
    chat_id = query.message.chat.id
    message_id = query.message.message_id
    state_data = {
        'action': action,
        'chat_id': chat_id,
        'message_id': message_id,
        'action_data': action_data or {},
        'section': section
    }
    db.save_user_state(user_id, States.WAITING_PASSWORD_VERIFY, state_data)
    await safe_edit_message(
        query,
        f"🔐 *Введите пароль для доступа:*\n\n{PASSWORD_RULES}",
        parse_mode='Markdown'
    )
    return True

async def execute_action_after_password(bot, user_id: int, chat_id: int, message_id: int,
                                        action: str, action_data: dict, update: Update):
    """Выполняет действие после успешной проверки пароля"""
    from utils import get_diary_type_menu_keyboard
    try:
        if action == 'my_entries_menu':
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="📂 *Мои записи*\n\nВыберите тип дневника:",
                reply_markup=get_diary_type_menu_keyboard('my_entries'),
                parse_mode='Markdown'
            )
        elif action == 'download_menu':
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="📥 *Скачать*\n\nВыберите тип дневника:",
                reply_markup=get_diary_type_menu_keyboard('download'),
                parse_mode='Markdown'
            )
        elif action == 'delete_menu':
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="🗑️ *Удалить*\n\nВыберите тип дневника:",
                reply_markup=get_diary_type_menu_keyboard('delete'),
                parse_mode='Markdown'
            )
        elif action == 'search_menu_main':
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="🔍 *Поиск*\n\nВыберите тип дневника:",
                reply_markup=get_diary_type_menu_keyboard('search'),
                parse_mode='Markdown'
            )
        elif action == 'show_search_menu':
            keyboard = [
                [InlineKeyboardButton("🔍 Поиск по тексту", callback_data='search_text')],
                [InlineKeyboardButton("📅 Поиск по дате", callback_data='search_date')],
                [InlineKeyboardButton("😊 Фильтр по эмоциям", callback_data='search_emotions')],
                [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
            ]
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="🔍 *Поиск и фильтрация записей*\n\nВыберите способ поиска:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        elif action == 'show_search_menu_exposure':
            keyboard = [
                [InlineKeyboardButton("🔍 Поиск по тексту", callback_data='search_exposure_text')],
                [InlineKeyboardButton("📅 Поиск по дате", callback_data='search_exposure_date')],
                [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
            ]
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="🔍 *Поиск экспозиций*\n\nВыберите способ поиска:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        elif action == 'show_my_entries':
            entries = db.get_user_entries(user_id)
            if not entries:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id,
                    text="У вас пока нет записей. Создайте новую запись!",
                    reply_markup=get_back_to_menu_keyboard()
                )
                return
            keyboard = []
            for entry in entries[:20]:
                date_str = datetime.fromisoformat(entry['timestamp']).strftime('%d.%m.%Y %H:%M')
                situation_preview = entry['situation'][:30] + '...' if len(entry.get('situation', '')) > 30 else entry.get('situation', '')
                keyboard.append([InlineKeyboardButton(f"{date_str}: {situation_preview}", callback_data=f"entry_{entry['id']}")])
            keyboard.append([InlineKeyboardButton("🔙 В меню", callback_data='menu')])
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="📂 *Мои записи*\n\nВыберите запись для просмотра:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        elif action == 'show_my_exposures':
            from exposure_handlers import show_my_exposures_after_password
            await show_my_exposures_after_password(bot, user_id, chat_id, message_id)
        elif action == 'show_download_period':
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="📥 *Скачать записи*\n\nВыберите период:",
                reply_markup=get_period_keyboard('download'),
                parse_mode='Markdown'
            )
        elif action == 'show_download_period_exposure':
            from exposure_handlers import show_download_period_exposure_after_password
            await show_download_period_exposure_after_password(bot, user_id, chat_id, message_id)
        elif action == 'show_delete_period':
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="🗑️ *Удалить записи*\n\nВыберите период:",
                reply_markup=get_period_keyboard('delete'),
                parse_mode='Markdown'
            )
        elif action == 'show_delete_period_exposure':
            from exposure_handlers import show_delete_period_exposure_after_password
            await show_delete_period_exposure_after_password(bot, user_id, chat_id, message_id)
        elif action == 'show_entry_detail':
            entry_id = action_data.get('entry_id')
            if entry_id and validate_entry_access(user_id, entry_id):
                entries = db.get_user_entries(user_id)
                entry = next((e for e in entries if e['id'] == entry_id), None)
                if entry:
                    summary = format_entry_summary(entry)
                    keyboard = [
                        [InlineKeyboardButton("✏️ Редактировать запись", callback_data=f'edit_entry_{entry_id}')],
                        [InlineKeyboardButton("🔙 Назад к списку", callback_data='my_entries')],
                        [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
                    ]
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=summary,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
        elif action == 'show_exposure_detail':
            from exposure_handlers import show_exposure_detail_after_password
            await show_exposure_detail_after_password(bot, user_id, chat_id, message_id, action_data)
    except Exception as e:
        logger.error(f"Ошибка при выполнении действия после пароля: {e}", exc_info=True)
        await bot.send_message(chat_id=chat_id, text="⚠️ Произошла ошибка. Используйте /menu.")

# ========== Обработчики записей ==========

async def show_my_entries(query, context):
    """Показывает список записей пользователя"""
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
    
    if await request_password_for_action(query, context, 'show_my_entries', section='my_entries'):
        return
    
    entries = db.get_user_entries(user_id)
    
    if not entries:
        await safe_edit_message(
            query,
            "У вас пока нет записей. Создайте новую запись!",
            reply_markup=get_back_to_menu_keyboard()
        )
        return
    
    keyboard = []
    for entry in entries[:20]:  # Ограничиваем 20 записями
        date_str = datetime.fromisoformat(entry['timestamp']).strftime('%d.%m.%Y %H:%M')
        situation_preview = entry['situation'][:30] + '...' if len(entry.get('situation', '')) > 30 else entry.get('situation', '')
        text = f"{date_str}: {situation_preview}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"entry_{entry['id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 В меню", callback_data='menu')])
    
    await safe_edit_message(
        query,
        "📂 *Мои записи*\n\nВыберите запись для просмотра:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def show_entry_detail(query, context, data):
    """Показывает детали записи"""
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
    
    try:
        entry_id = int(data.replace('entry_', ''))
    except ValueError:
        await query.answer("Неверный идентификатор записи.", show_alert=True)
        return
    
    if await request_password_for_action(query, context, 'show_entry_detail', {'entry_id': entry_id}, section='my_entries'):
        return
    
    # Проверяем доступ к записи
    if not validate_entry_access(user_id, entry_id):
        await query.answer("Доступ запрещен", show_alert=True)
        logger.warning(f"User {user_id} attempted to access entry {entry_id} without permission")
        return
    
    entries = db.get_user_entries(user_id)
    entry = next((e for e in entries if e['id'] == entry_id), None)
    
    if not entry:
        await query.answer("Запись не найдена", show_alert=True)
        return
    
    summary = format_entry_summary(entry)
    
    keyboard = [
        [InlineKeyboardButton("✏️ Редактировать запись", callback_data=f'edit_entry_{entry_id}')],
        [InlineKeyboardButton("🔙 Назад к списку", callback_data='my_entries')],
        [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
    ]
    
    await safe_edit_message(
        query,
        summary,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ========== Обработчики скачивания и удаления ==========

async def show_download_period(query, context):
    """Показывает выбор периода для скачивания"""
    user_id = query.from_user.id
    from admin import is_admin
    if not is_admin(query.from_user) and not check_user_consent(user_id):
        await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
        return
    if await request_password_for_action(query, context, 'show_download_period', section='download'):
        return
    await safe_edit_message(
        query,
        "📥 *Скачать записи*\n\nВыберите период:",
        reply_markup=get_period_keyboard('download'),
        parse_mode='Markdown'
    )

async def show_delete_period(query, context):
    """Показывает выбор периода для удаления"""
    user_id = query.from_user.id
    from admin import is_admin
    if not is_admin(query.from_user) and not check_user_consent(user_id):
        await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
        return
    if await request_password_for_action(query, context, 'show_delete_period', section='delete'):
        return
    await safe_edit_message(
        query,
        "🗑️ *Удалить записи*\n\nВыберите период:",
        reply_markup=get_period_keyboard('delete'),
        parse_mode='Markdown'
    )

async def handle_period_choice(query, context, data):
    """Обрабатывает выбор периода"""
    user_id = query.from_user.id
    
    # Проверяем согласие
    if not check_user_consent(user_id):
        await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
        return
    
    action_type = 'download' if data.startswith('download_') else 'delete'
    
    # Проверяем rate limiting
    allowed, error_msg = check_rate_limit(user_id, action_type)
    if not allowed:
        await query.answer(error_msg, show_alert=True)
        return
    
    period = data.replace(f'{action_type}_', '')
    
    now = datetime.now()
    start_date = None
    end_date = now.isoformat()
    
    if period == '7':
        start_date = (now - timedelta(days=7)).isoformat()
    elif period == '30':
        start_date = (now - timedelta(days=30)).isoformat()
    elif period == 'all':
        start_date = None
    elif period == 'custom':
        # Запрашиваем произвольный период через календарь
        entry_data = {'action_type': action_type}
        if action_type == 'download':
            db.save_user_state(user_id, States.WAITING_DOWNLOAD_START_DATE, entry_data)
            await query.edit_message_text(
                "📅 *Произвольный период*\n\n"
                "Выберите начальную дату:",
                reply_markup=create_calendar(),
                parse_mode='Markdown'
            )
        else:
            db.save_user_state(user_id, States.WAITING_DELETE_START_DATE, entry_data)
            await query.edit_message_text(
                "📅 *Произвольный период*\n\n"
                "Выберите начальную дату:",
                reply_markup=create_calendar(),
                parse_mode='Markdown'
            )
        return
    
    if action_type == 'download':
        entries = db.get_user_entries(user_id, start_date, end_date)
        if not entries:
            await query.edit_message_text(
                "За выбранный период записей не найдено.",
                reply_markup=get_back_to_menu_keyboard()
            )
            return
        
        try:
            filepath = generate_excel(entries, user_id)
            with open(filepath, 'rb') as file:
                await query.message.reply_document(
                    document=file,
                    filename=os.path.basename(filepath)
                )
            await query.message.reply_text(
                "✅ Файл готов!",
                reply_markup=get_back_to_menu_keyboard()
            )
            os.remove(filepath)  # Удаляем временный файл
            logger.info(f"User {user_id} downloaded entries")
        except Exception as e:
            logger.error(f"Ошибка при генерации Excel для пользователя {user_id}: {e}")
            await query.message.reply_text(
                "⚠️ Произошла ошибка при создании файла. Попробуйте позже.",
                reply_markup=get_back_to_menu_keyboard()
            )
    
    elif action_type == 'delete':
        entries = db.get_user_entries(user_id, start_date, end_date)
        count = len(entries)
        
        if count == 0:
            await query.edit_message_text(
                "За выбранный период записей не найдено.",
                reply_markup=get_back_to_menu_keyboard()
            )
            return
        
        state_data = {
            'delete_start_date': start_date,
            'delete_end_date': end_date
        }
        db.save_user_state(user_id, States.WAITING_DELETE_CONFIRMATION, state_data)
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f'confirm_delete_{count}'),
                InlineKeyboardButton("❌ Отмена", callback_data='menu')
            ]
        ]
        
        await query.edit_message_text(
            f"⚠️ *Подтверждение удаления*\n\n"
            f"Вы уверены, что хотите удалить *{count}* записей?\n\n"
            f"Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def send_template(query, context):
    """Отправляет шаблон документа дневника мыслей"""
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
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(base_dir, 'docs', 'Шаблон_дневника_мыслей.docx')
    
    if not os.path.exists(template_path):
        await query.answer("Шаблон временно недоступен.", show_alert=True)
        await safe_edit_message(
            query,
            "⚠️ Шаблон временно недоступен.",
            reply_markup=get_back_to_menu_keyboard()
        )
        return
    
    try:
        with open(template_path, 'rb') as doc:
            await query.message.reply_document(
                document=doc,
                filename='Шаблон_дневника_мыслей.docx',
                caption="📄 Шаблон дневника мыслей"
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

async def show_questions(query, context):
    """Показывает информацию о вопросах"""
    from config import DEVELOPER_USERNAME
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
    
    await query.edit_message_text(
        f"По всем вопросам о работе бота, предложениям или сотрудничеству "
        f"вы можете написать разработчику: {DEVELOPER_USERNAME}",
        reply_markup=get_back_to_menu_keyboard()
    )

PASSWORD_WARNING = (
    "⚠️ *Важно о защите данных*\n\n"
    "В наше время аккаунты Telegram нередко оказываются скомпрометированы. "
    "Проверка пароля нужна для того, чтобы при краже аккаунта посторонний человек "
    "*не смог просмотреть, скачать или удалить* ваши личные записи в дневнике.\n\n"
    "Отключая проверку пароля, вы делаете данные доступными любому, кто получит доступ к вашему Telegram."
)


async def handle_password_settings(query, context):
    """Настройки пароля: включить/отключить проверку"""
    user_id = query.from_user.id
    
    if not has_user_password(user_id):
        await safe_edit_message(
            query,
            "🔐 *Настройки пароля*\n\n"
            "У вас пока нет пароля. Пароль создаётся при первом входе после согласия на обработку данных.\n\n"
            "Пароль защищает ваши записи от просмотра, скачивания и удаления в случае компрометации аккаунта Telegram.",
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    if is_password_verification_enabled(user_id):
        text = (
            "🔐 *Настройки пароля*\n\n"
            "Проверка пароля *включена* — при доступе к записям, скачиванию и удалению требуется пароль.\n\n"
            "Вы можете отключить проверку (не рекомендуется):"
        )
        keyboard = [
            [InlineKeyboardButton("⚠️ Отключить проверку пароля", callback_data='password_disable')],
            [InlineKeyboardButton("🔙 Назад", callback_data='menu')]
        ]
    else:
        text = (
            "🔐 *Настройки пароля*\n\n"
            "Проверка пароля *отключена* — доступ к записям без ввода пароля.\n\n"
            "Рекомендуем включить проверку для защиты данных:"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Включить проверку пароля", callback_data='password_enable')],
            [InlineKeyboardButton("🔙 Назад", callback_data='menu')]
        ]
    
    await safe_edit_message(
        query,
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def handle_password_disable(query, context):
    """Запрашивает пароль для проверки перед отключением"""
    user_id = query.from_user.id
    if not has_user_password(user_id) or not is_password_verification_enabled(user_id):
        await query.answer("Проверка пароля уже отключена.", show_alert=True)
        return
    
    chat_id = query.message.chat.id
    message_id = query.message.message_id
    db.save_user_state(user_id, States.WAITING_PASSWORD_FOR_DISABLE, {
        'chat_id': chat_id, 'message_id': message_id
    })
    await safe_edit_message(
        query,
        f"🔐 *Отключение проверки пароля*\n\n{PASSWORD_WARNING}\n\n"
        f"Для отключения введите текущий пароль:\n\n{PASSWORD_RULES}",
        parse_mode='Markdown'
    )


async def handle_password_disable_confirm(query, context):
    """Отключает проверку пароля"""
    user_id = query.from_user.id
    if not has_user_password(user_id):
        await query.answer("У вас нет пароля.", show_alert=True)
        return
    
    db.set_password_verification_enabled(user_id, False)
    await safe_edit_message(
        query,
        "✅ *Проверка пароля отключена*\n\n"
        "Теперь доступ к записям, скачиванию и удалению не требует ввода пароля.\n\n"
        "Вы можете включить проверку снова в настройках пароля.",
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode='Markdown'
    )
    logger.info(f"Пользователь {user_id} отключил проверку пароля")


async def handle_password_enable(query, context):
    """Запрашивает новый пароль при включении проверки"""
    user_id = query.from_user.id
    if not has_user_password(user_id):
        await query.answer("У вас нет пароля. Создайте его через /start.", show_alert=True)
        return
    
    chat_id = query.message.chat.id
    message_id = query.message.message_id
    db.save_user_state(user_id, States.WAITING_PASSWORD_NEW_FOR_ENABLE, {
        'chat_id': chat_id, 'message_id': message_id
    })
    await safe_edit_message(
        query,
        f"🔐 *Включение проверки пароля*\n\n"
        f"При включении требуется задать новый пароль.\n\n{PASSWORD_RULES}\n\nВведите новый пароль:",
        parse_mode='Markdown'
    )


async def handle_password_reset_request(query, context):
    """Обрабатывает заявку на сброс пароля"""
    user_id = query.from_user.id
    
    if not has_user_password(user_id):
        await query.answer("У вас нет пароля для сброса.", show_alert=True)
        return
    
    if db.has_user_pending_reset_request(user_id):
        await query.answer("Заявка уже отправлена. Ожидайте рассмотрения администратором.", show_alert=True)
        return
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Подтвердить заявку", callback_data='password_reset_confirm'),
            InlineKeyboardButton("❌ Отмена", callback_data='menu')
        ]
    ]
    
    await safe_edit_message(
        query,
        "🔑 *Заявка на сброс пароля*\n\n"
        "Вы хотите отправить заявку на сброс пароля?\n\n"
        "Администратор проверит заявку и при одобрении ваш пароль будет сброшен. "
        "После этого при следующем входе в раздел «Мои записи» или «Скачать» вам нужно будет создать новый пароль.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def handle_password_reset_confirm(query, context):
    """Подтверждает и отправляет заявку на сброс пароля"""
    user_id = query.from_user.id
    
    if not has_user_password(user_id):
        await query.answer("У вас нет пароля для сброса.", show_alert=True)
        return
    
    if db.has_user_pending_reset_request(user_id):
        await query.answer("Заявка уже отправлена. Ожидайте рассмотрения.", show_alert=True)
        return
    
    req_id = db.create_password_reset_request(user_id)
    if not req_id:
        await query.answer("Ошибка при создании заявки. Попробуйте позже.", show_alert=True)
        return
    
    # Уведомляем админа о новой заявке
    from admin import notify_admin_with_buttons
    from datetime import datetime
    req = db.get_password_reset_request_by_id(req_id)
    requested_at = datetime.fromisoformat(req['requested_at']).strftime('%d.%m.%Y %H:%M')
    admin_msg = (
        f"🔑 *Новая заявка на сброс пароля*\n\n"
        f"*ID заявки:* {req_id}\n"
        f"*Пользователь ID:* {user_id}\n"
        f"*Дата:* {requested_at}"
    )
    admin_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Одобрить", callback_data=f'admin_reset_approve_{req_id}'),
            InlineKeyboardButton("❌ Отклонить", callback_data=f'admin_reset_reject_{req_id}')
        ]
    ])
    try:
        await notify_admin_with_buttons(context.bot, admin_msg, admin_keyboard)
    except Exception as e:
        logger.warning(f"Не удалось уведомить админа о заявке на сброс: {e}")
    
    await safe_edit_message(
        query,
        "✅ *Заявка отправлена*\n\n"
        "Ваша заявка на сброс пароля отправлена администратору.\n\n"
        "Ожидайте рассмотрения. Вы получите уведомление о результате.",
        reply_markup=get_back_to_menu_keyboard(),
        parse_mode='Markdown'
    )


async def handle_delete_account(query, context):
    """Обрабатывает удаление аккаунта пользователя"""
    user_id = query.from_user.id
    
    # Проверяем согласие
    if not check_user_consent(user_id):
        await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
        return
    
    # Проверяем rate limiting
    allowed, error_msg = check_rate_limit(user_id, 'delete')
    if not allowed:
        await query.answer(error_msg, show_alert=True)
        return
    
    # Показываем подтверждение
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить все данные", callback_data='confirm_delete_account'),
            InlineKeyboardButton("❌ Отмена", callback_data='menu')
        ]
    ]
    
    await query.edit_message_text(
        "⚠️ *Удаление аккаунта*\n\n"
        "Вы уверены, что хотите удалить все свои данные?\n\n"
        "Это действие нельзя отменить. Будут удалены:\n"
        "• Все ваши записи\n"
        "• Все настройки\n"
        "• История активности\n\n"
        "После удаления вы сможете начать заново командой /start.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_cancel_entry(query, context):
    """Обрабатывает отмену создания записи"""
    user_id = query.from_user.id
    
    # Очищаем состояние пользователя
    db.clear_user_state(user_id)
    
    await safe_edit_message(
        query,
        "❌ *Создание записи отменено*\n\n"
        "Вы вернулись в главное меню.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode='Markdown'
    )
    logger.info(f"Пользователь {user_id} отменил создание записи")

async def handle_confirm_delete_entries(query, context, data):
    """Подтверждает и выполняет удаление записей"""
    user_id = query.from_user.id
    
    try:
        # Парсим количество из callback_data: confirm_delete_5
        count = int(data.replace('confirm_delete_', ''))
        
        # Получаем сохраненные даты из состояния
        state_info = db.get_user_state(user_id)
        if not state_info or state_info['state'] != States.WAITING_DELETE_CONFIRMATION:
            await query.answer("Сессия истекла. Начните заново.", show_alert=True)
            return
        
        state_data = state_info['data']
        start_date = state_data.get('delete_start_date')
        end_date = state_data.get('delete_end_date')
        
        # Удаляем записи
        deleted_count = db.delete_entries(user_id, start_date, end_date)
        db.clear_user_state(user_id)
        
        await safe_edit_message(
            query,
            f"✅ *Удаление выполнено*\n\n"
            f"Удалено записей: *{deleted_count}*",
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode='Markdown'
        )
        logger.info(f"Пользователь {user_id} удалил {deleted_count} записей")
    except Exception as e:
        logger.error(f"Ошибка при удалении записей: {e}", exc_info=True)
        await query.answer("Ошибка при удалении", show_alert=True)

async def handle_confirm_delete_account(query, context):
    """Подтверждает и выполняет удаление аккаунта"""
    user_id = query.from_user.id
    
    try:
        # Удаляем все данные пользователя
        db.delete_user_data(user_id)
        
        # Уведомляем админа
        try:
            await notify_admin(
                context.bot,
                f"⚠️ Пользователь {user_id} удалил свой аккаунт и все данные."
            )
        except:
            pass
        
        await query.edit_message_text(
            "✅ *Аккаунт удален*\n\n"
            "Все ваши данные были успешно удалены.\n\n"
            "Если вы передумаете, вы можете начать заново командой /start.",
            parse_mode='Markdown'
        )
        
        logger.info(f"User {user_id} deleted their account")
    except Exception as e:
        logger.error(f"Ошибка при удалении аккаунта пользователя {user_id}: {e}")
        await query.edit_message_text(
            "⚠️ Произошла ошибка при удалении аккаунта. Попробуйте позже.",
            reply_markup=get_back_to_menu_keyboard()
        )

async def handle_ignore_activity(query, context, data):
    """Обрабатывает игнорирование подозрительной активности"""
    from admin import is_admin
    
    if not is_admin(query.from_user):
        await query.answer("❌ У вас нет прав доступа.", show_alert=True)
        return
    
    try:
        activity_id = int(data.replace('admin_ignore_activity_', ''))
        db.mark_activity_notified(activity_id)
        
        await query.answer("✅ Активность проигнорирована", show_alert=False)
        
        # Пытаемся отредактировать сообщение с уведомлением
        message_edited = False
        try:
            # Проверяем, есть ли фото в сообщении
            has_photo = query.message and query.message.photo and len(query.message.photo) > 0
            
            if has_photo:
                await query.edit_message_caption(
                    caption="✅ Активность проигнорирована. Пользователь возвращен в меню.",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    "✅ Активность проигнорирована. Пользователь возвращен в меню.",
                    parse_mode='Markdown'
                )
            message_edited = True
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
        
        # Отправляем новое сообщение только если не удалось отредактировать
        if not message_edited:
            try:
                await query.message.reply_text(
                    "✅ Активность проигнорирована. Пользователь возвращен в меню."
                )
            except Exception as e2:
                logger.error(f"Не удалось отправить сообщение: {e2}")
        
        logger.info(f"Админ {query.from_user.id} проигнорировал активность {activity_id}")
    except Exception as e:
        logger.error(f"Ошибка при игнорировании активности: {e}")
        await query.answer("Ошибка при обработке", show_alert=True)

async def handle_block_user(query, context, data):
    """Обрабатывает блокировку пользователя"""
    from admin import is_admin
    from config import ADMIN_USERNAME
    
    if not is_admin(query.from_user):
        await query.answer("❌ У вас нет прав доступа.", show_alert=True)
        return
    
    try:
        # Парсим данные: admin_block_user_{user_id}_{activity_id}
        parts = data.replace('admin_block_user_', '').split('_')
        blocked_user_id = int(parts[0])
        activity_id = int(parts[1]) if len(parts) > 1 else None
        
        # Блокируем пользователя
        reason = f"Подозрительная активность (ID активности: {activity_id})"
        db.block_user(blocked_user_id, reason, activity_id)
        
        # Отмечаем активность как обработанную
        if activity_id:
            db.mark_activity_notified(activity_id)
        
        # Удаляем все сообщения пользователя
        try:
            from active_protection import delete_user_messages
            deleted_count = await delete_user_messages(context.bot, blocked_user_id)
            logger.info(f"Удалено {deleted_count} сообщений заблокированного пользователя {blocked_user_id}")
        except Exception as e:
            logger.warning(f"Не удалось удалить сообщения пользователя {blocked_user_id}: {e}")
        
        # Отправляем сообщение заблокированному пользователю
        try:
            await context.bot.send_message(
                chat_id=blocked_user_id,
                text=(
                    f"🚫 *Вы заблокированы*\n\n"
                    f"Ваш аккаунт был заблокирован из-за подозрительной активности.\n\n"
                    f"Для разблокировки свяжитесь с администратором: {ADMIN_USERNAME}"
                ),
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение заблокированному пользователю {blocked_user_id}: {e}")
        
        await query.answer("✅ Пользователь заблокирован", show_alert=False)
        
        # Пытаемся отредактировать сообщение с уведомлением
        message_edited = False
        try:
            # Проверяем, есть ли фото в сообщении
            has_photo = query.message and query.message.photo and len(query.message.photo) > 0
            
            if has_photo:
                # Если сообщение содержит фото, редактируем подпись
                await query.edit_message_caption(
                    caption=(
                        f"✅ *Пользователь заблокирован*\n\n"
                        f"Пользователь {blocked_user_id} был заблокирован.\n"
                        f"Сообщение о блокировке отправлено пользователю."
                    ),
                    parse_mode='Markdown'
                )
            else:
                # Если текстовое сообщение, редактируем текст
                await query.edit_message_text(
                    f"✅ *Пользователь заблокирован*\n\n"
                    f"Пользователь {blocked_user_id} был заблокирован.\n"
                    f"Сообщение о блокировке отправлено пользователю.",
                    parse_mode='Markdown'
                )
            message_edited = True
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
        
        # Отправляем новое сообщение только если не удалось отредактировать
        if not message_edited:
            try:
                await query.message.reply_text(
                    f"✅ Пользователь {blocked_user_id} заблокирован.\n"
                    f"Сообщение о блокировке отправлено пользователю."
                )
            except Exception as e2:
                logger.error(f"Не удалось отправить сообщение: {e2}")
        
        logger.info(f"Админ {query.from_user.id} заблокировал пользователя {blocked_user_id}")
    except Exception as e:
        logger.error(f"Ошибка при блокировке пользователя: {e}", exc_info=True)
        await query.answer("Ошибка при блокировке", show_alert=True)

async def handle_unblock_user(query, context, data):
    """Обрабатывает разблокировку пользователя (с обнулением рейтинга опасности)"""
    from admin import is_admin
    from active_protection import remove_all_restrictions
    
    if not is_admin(query.from_user):
        await query.answer("❌ У вас нет прав доступа.", show_alert=True)
        return
    
    try:
        user_id = int(data.replace('admin_unblock_user_', ''))
        remove_all_restrictions(user_id)
        
        # Отправляем сообщение разблокированному пользователю
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ *Вы разблокированы*\n\nВаш аккаунт был разблокирован администратором.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение разблокированному пользователю {user_id}: {e}")
        
        await query.answer("✅ Пользователь разблокирован", show_alert=False)
        
        # Пытаемся отредактировать сообщение
        message_edited = False
        try:
            has_photo = query.message and query.message.photo and len(query.message.photo) > 0
            
            if has_photo:
                await query.edit_message_caption(
                    caption=f"✅ Пользователь {user_id} разблокирован.",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    f"✅ Пользователь {user_id} разблокирован.",
                    parse_mode='Markdown'
                )
            message_edited = True
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
        
        # Отправляем новое сообщение только если не удалось отредактировать
        if not message_edited:
            try:
                await query.message.reply_text(
                    f"✅ Пользователь {user_id} разблокирован."
                )
            except Exception as e2:
                logger.error(f"Не удалось отправить сообщение: {e2}")
        
        logger.info(f"Админ {query.from_user.id} разблокировал пользователя {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при разблокировке пользователя: {e}", exc_info=True)
        await query.answer("Ошибка при разблокировке", show_alert=True)

async def handle_remove_restrictions(query, context, data):
    """Обрабатывает снятие всех ограничений с пользователя"""
    from admin import is_admin
    
    if not is_admin(query.from_user):
        await query.answer("❌ У вас нет прав доступа.", show_alert=True)
        return
    
    try:
        user_id = int(data.replace('admin_remove_restrictions_', ''))
        
        # Снимаем все ограничения
        from active_protection import remove_all_restrictions
        result = remove_all_restrictions(user_id)
        
        # Формируем сообщение о выполненных действиях
        actions = []
        if result['was_blocked']:
            actions.append("разблокирован")
        if result['had_reputation']:
            actions.append(f"репутация сброшена с {result['reputation_before']} до 0")
        if result['had_restrictions']:
            actions.append(f"ограничения сняты (было: {result['restrictions_before']})")
        
        if not actions:
            actions.append("ограничений не было")
        
        action_text = ", ".join(actions)
        
        # Отправляем сообщение пользователю
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ *Все ограничения сняты*\n\n"
                    "Администратор снял с вас все ограничения:\n"
                    f"• Разблокировка\n"
                    f"• Сброс репутации\n"
                    f"• Снятие ограничений\n\n"
                    "Вы можете продолжать пользоваться ботом без ограничений."
                ),
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
        
        await query.answer("✅ Все ограничения сняты", show_alert=False)
        
        # Показываем обновленную информацию о пользователе
        try:
            from admin import show_user_info_for_admin
            await show_user_info_for_admin(query, context, user_id)
        except Exception as e:
            logger.warning(f"Не удалось показать обновленную информацию о пользователе: {e}")
            # Если не удалось, показываем простое сообщение
            try:
                has_photo = query.message and query.message.photo and len(query.message.photo) > 0
                if has_photo:
                    await query.edit_message_caption(
                        caption=f"✅ Все ограничения сняты с пользователя {user_id}.\n\n{action_text}",
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text(
                        f"✅ *Все ограничения сняты*\n\n"
                        f"Пользователь {user_id}:\n"
                        f"• {action_text}",
                        parse_mode='Markdown'
                    )
            except Exception as e2:
                logger.error(f"Не удалось отредактировать сообщение: {e2}")
        
        logger.info(f"Админ {query.from_user.id} снял все ограничения с пользователя {user_id}: {action_text}")
    except Exception as e:
        logger.error(f"Ошибка при снятии ограничений: {e}", exc_info=True)
        await query.answer("Ошибка при снятии ограничений", show_alert=True)

async def handle_consent_yes(query, context):
    """Обрабатывает согласие пользователя"""
    user_id = query.from_user.id
    
    # Получаем IP адрес (если доступен)
    ip_address = None
    try:
        if query.message and query.message.chat:
            pass
    except:
        pass
    
    # Сохраняем согласие
    save_user_consent(user_id, True, ip_address)
    
    # Если пароль не установлен — просим создать
    if not has_user_password(user_id):
        db.save_user_state(user_id, States.WAITING_PASSWORD_CREATE, {})
        message_text = (
            "✅ *Спасибо за согласие!*\n\n"
            "🔐 Для защиты ваших записей создайте пароль.\n\n"
            "В наше время аккаунты Telegram нередко оказываются скомпрометированы. "
            "Пароль защитит ваши записи — без него посторонний *не сможет просмотреть, скачать или удалить* ваши данные.\n\n"
            f"*{PASSWORD_RULES}*\n\nВведите пароль:"
        )
        reply_markup = None
    else:
        message_text = (
            "✅ *Спасибо за согласие!*\n\n"
            "Привет! Я помогу вам вести дневник мыслей по методу "
            "когнитивно-поведенческой терапии. Выберите действие:"
        )
        reply_markup = get_main_menu_keyboard()
    
    # Проверяем, есть ли фото в сообщении
    try:
        has_photo = query.message and query.message.photo and len(query.message.photo) > 0
        
        if has_photo:
            await query.edit_message_caption(
                caption=message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.warning(f"Не удалось отредактировать сообщение, отправляем новое: {e}")
        try:
            await query.message.reply_text(
                message_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except Exception as e2:
            logger.error(f"Не удалось отправить новое сообщение: {e2}")
    
    logger.info(f"User {user_id} gave consent")

async def handle_consent_no(query, context):
    """Обрабатывает отказ от согласия"""
    user_id = query.from_user.id
    
    # Удаляем все данные пользователя
    db.delete_user_data(user_id)
    
    message_text = (
        "❌ *Согласие не получено*\n\n"
        "Для использования бота необходимо дать согласие на обработку персональных данных.\n\n"
        "Если вы передумаете, просто запустите бота командой /start снова."
    )
    
    # Проверяем, есть ли фото в сообщении
    try:
        # Проверяем наличие фото в сообщении
        has_photo = query.message and query.message.photo and len(query.message.photo) > 0
        
        if has_photo:
            # Если сообщение содержит фото, редактируем подпись
            await query.edit_message_caption(
                caption=message_text,
                parse_mode='Markdown'
            )
        else:
            # Если текстовое сообщение, редактируем текст
            await query.edit_message_text(
                message_text,
                parse_mode='Markdown'
            )
    except Exception as e:
        # Если не удалось отредактировать, отправляем новое сообщение
        logger.warning(f"Не удалось отредактировать сообщение, отправляем новое: {e}")
        try:
            await query.message.reply_text(
                message_text,
                parse_mode='Markdown'
            )
        except Exception as e2:
            logger.error(f"Не удалось отправить новое сообщение: {e2}")
    
    logger.info(f"User {user_id} declined consent")

async def send_consent_documents(query, context):
    """Отправляет документы согласия (Согласие на ПДн, Политика конфиденциальности, Пользовательское соглашение)."""
    user_id = query.from_user.id
    
    # Проверяем rate limiting (callback уже ответили в button_handler, не вызываем query.answer повторно)
    allowed, error_msg = check_rate_limit(user_id, 'download')
    if not allowed:
        try:
            await query.message.reply_text(f"⚠️ {error_msg}")
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение о лимите: {e}")
        return
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    docs_dir = os.path.join(base_dir, 'docs')
    
    documents = [
        'Согласие_на_обработку_персональных_данных.md',
        'Политика_конфиденциальности.md',
        'Пользовательское_соглашение.md',
    ]
    sent_count = 0
    
    for doc_name in documents:
        doc_path = os.path.join(docs_dir, doc_name)
        doc_path = os.path.normpath(os.path.abspath(doc_path))
        if os.path.isfile(doc_path):
            try:
                # Читаем файл в память и отправляем — надёжно при async
                with open(doc_path, 'rb') as f:
                    file_bytes = f.read()
                await query.message.reply_document(
                    document=io.BytesIO(file_bytes),
                    filename=doc_name
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Ошибка при отправке документа {doc_name}: {e}", exc_info=True)
        else:
            logger.warning(f"Документ не найден: {doc_path}")
    
    if sent_count > 0:
        # Клавиатура: если пользователь ещё не дал согласие — показываем снова кнопки согласия
        if not check_user_consent(user_id):
            reply_markup = get_consent_keyboard()
        else:
            reply_markup = get_back_to_menu_keyboard()
        await query.message.reply_text(
            f"✅ Отправлено документов: {sent_count}",
            reply_markup=reply_markup
        )
    else:
        try:
            has_photo = query.message and query.message.photo and len(query.message.photo) > 0
            if has_photo:
                await query.edit_message_caption(
                    caption="⚠️ Документы временно недоступны. Проверьте наличие файлов в папке docs.",
                    reply_markup=get_consent_keyboard() if not check_user_consent(user_id) else get_back_to_menu_keyboard()
                )
            else:
                await query.edit_message_text(
                    "⚠️ Документы временно недоступны. Проверьте наличие файлов в папке docs.",
                    reply_markup=get_consent_keyboard() if not check_user_consent(user_id) else get_back_to_menu_keyboard()
                )
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
            try:
                await query.message.reply_text(
                    "⚠️ Документы временно недоступны. Проверьте наличие файлов в папке docs.",
                    reply_markup=get_consent_keyboard() if not check_user_consent(user_id) else get_back_to_menu_keyboard()
                )
            except Exception as e2:
                logger.error(f"Не удалось отправить сообщение: {e2}")