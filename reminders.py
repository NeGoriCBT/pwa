"""
Модуль для напоминаний о ведении дневника
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import logging
import re
from typing import Optional
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo, available_timezones
from database import Database
from security import check_user_consent

db = Database()
logger = logging.getLogger(__name__)

# Подпись для UI и IANA-имя зоны (время напоминания считается в этой зоне)
REMINDER_TIMEZONE_CHOICES = [
    ("Москва, СПб", "Europe/Moscow"),
    ("Калининград", "Europe/Kaliningrad"),
    ("Самара", "Europe/Samara"),
    ("Екатеринбург", "Asia/Yekaterinburg"),
    ("Омск", "Asia/Omsk"),
    ("Новосибирск", "Asia/Novosibirsk"),
    ("Красноярск", "Asia/Krasnoyarsk"),
    ("Иркутск", "Asia/Irkutsk"),
    ("Якутск", "Asia/Yakutsk"),
    ("Владивосток", "Asia/Vladivostok"),
    ("Киев", "Europe/Kyiv"),
    ("UTC", "UTC"),
    ("Берлин", "Europe/Berlin"),
    ("Лондон", "Europe/London"),
    ("Нью-Йорк", "America/New_York"),
]


def normalize_timezone(tz_name: str) -> str:
    """Возвращает корректное IANA-имя или UTC при ошибке."""
    if not tz_name:
        return "UTC"
    name = tz_name.strip()
    if name in available_timezones():
        return name
    if name.upper() == "UTC":
        return "UTC"
    try:
        ZoneInfo(name)
        return name
    except Exception:
        logger.warning(f"Неизвестная таймзона '{tz_name}', используем UTC")
        return "UTC"


def now_in_user_tz(tz_name: str) -> datetime:
    """Текущие дата и время в зоне пользователя."""
    z = normalize_timezone(tz_name)
    try:
        return datetime.now(ZoneInfo(z))
    except Exception:
        return datetime.now(ZoneInfo("UTC"))


def _entry_local_date(ts_str: str, user_tz: str) -> Optional[date]:
    """Календарная дата записи в часовом поясе пользователя."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        # Naive ISO — как при save_entry (локальное время сервера бота)
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    try:
        u = ZoneInfo(normalize_timezone(user_tz))
    except Exception:
        u = ZoneInfo("UTC")
    return dt.astimezone(u).date()


def user_has_entry_today(user_id: int, tz_name: str) -> bool:
    """Есть ли запись за календарный «сегодня» у пользователя в его часовом поясе."""
    today_user = now_in_user_tz(tz_name).date()
    # Запас по строковому фильтру БД (граница суток между зонами)
    start_q = (today_user - timedelta(days=2)).isoformat()
    entries = db.get_user_entries(user_id, start_date=start_q)
    for e in entries:
        d = _entry_local_date(e["timestamp"], tz_name)
        if d == today_user:
            return True
    return False


async def show_reminders_menu(query, context):
    """Показывает меню настроек напоминаний"""
    user_id = query.from_user.id
    
    # Проверяем согласие
    if not check_user_consent(user_id):
        await query.answer("Сначала необходимо дать согласие на обработку данных.", show_alert=True)
        return
    
    settings = db.get_user_reminder_settings(user_id)
    reminders_enabled = settings.get('enabled', False)
    reminder_time = settings.get('time', '20:00')
    tz = settings.get('timezone', 'Europe/Moscow')
    tz_label = next((lbl for lbl, z in REMINDER_TIMEZONE_CHOICES if z == tz), tz)
    
    status_text = "✅ Включены" if reminders_enabled else "❌ Выключены"
    
    keyboard = [
        [InlineKeyboardButton("🔔 Включить напоминания", callback_data='reminder_enable')],
        [InlineKeyboardButton("🔕 Выключить напоминания", callback_data='reminder_disable')],
        [InlineKeyboardButton("⏰ Изменить время", callback_data='reminder_set_time')],
        [InlineKeyboardButton("🌍 Часовой пояс", callback_data='reminder_timezone_menu')],
        [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
    ]
    
    from handlers import safe_edit_message
    await safe_edit_message(
        query,
        f"🔔 *Напоминания*\n\n"
        f"*Статус:* {status_text}\n"
        f"*Время (ваше локальное):* {reminder_time}\n"
        f"*Часовой пояс:* {tz_label}\n\n"
        f"Напоминания помогут вам регулярно вести дневник мыслей.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def handle_reminder_enable(query, context):
    """Включает напоминания"""
    user_id = query.from_user.id
    db.set_user_reminder_settings(user_id, enabled=True)
    
    await query.answer("✅ Напоминания включены", show_alert=True)
    await show_reminders_menu(query, context)


async def handle_reminder_disable(query, context):
    """Выключает напоминания"""
    user_id = query.from_user.id
    db.set_user_reminder_settings(user_id, enabled=False)
    
    await query.answer("❌ Напоминания выключены", show_alert=True)
    await show_reminders_menu(query, context)


async def handle_reminder_set_time(query, context):
    """Запрашивает ввод времени напоминания (локальное время пользователя)."""
    user_id = query.from_user.id
    if not check_user_consent(user_id):
        await query.answer("Сначала необходимо дать согласие.", show_alert=True)
        return

    from states import States
    db.save_user_state(user_id, States.WAITING_REMINDER_TIME, {})
    await query.answer()
    from handlers import safe_edit_message
    await safe_edit_message(
        query,
        "⏰ *Время напоминания*\n\n"
        "Отправьте время в *вашем локальном часовом поясе* в формате `ЧЧ:ММ` "
        "(например, `20:30`).\n\n"
        "Часовой пояс можно сменить кнопкой «🌍 Часовой пояс» в меню напоминаний.",
        parse_mode='Markdown',
    )


async def show_timezone_menu(query, context):
    """Меню выбора часового пояса."""
    user_id = query.from_user.id
    if not check_user_consent(user_id):
        await query.answer("Сначала необходимо дать согласие.", show_alert=True)
        return

    rows = []
    for i, (label, _) in enumerate(REMINDER_TIMEZONE_CHOICES):
        rows.append([InlineKeyboardButton(label, callback_data=f'rem_tz_{i}')])
    rows.append([InlineKeyboardButton("🔙 К напоминаниям", callback_data='reminders')])

    from handlers import safe_edit_message
    await safe_edit_message(
        query,
        "🌍 *Часовой пояс*\n\n"
        "Выберите город — напоминания будут приходить в выбранном поясе в заданное вами время.",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode='Markdown',
    )


async def handle_timezone_choice(query, context, index: int):
    """Сохраняет выбранный часовой пояс."""
    if index < 0 or index >= len(REMINDER_TIMEZONE_CHOICES):
        await query.answer("Неверный выбор", show_alert=True)
        return
    _, iana = REMINDER_TIMEZONE_CHOICES[index]
    user_id = query.from_user.id
    db.set_user_reminder_settings(user_id, timezone=iana)
    await query.answer(f"Сохранено: {iana}", show_alert=False)
    await show_reminders_menu(query, context)


_TIME_RE = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$")


async def handle_reminder_time_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Обрабатывает ввод времени напоминания."""
    from states import States
    user_id = update.effective_user.id
    m = _TIME_RE.match(text.strip())
    if not m:
        await update.message.reply_text(
            "⚠️ Неверный формат. Укажите время как `ЧЧ:ММ`, например `09:30` или `20:00`.",
            parse_mode='Markdown',
        )
        return
    hh, mm = m.group(1), m.group(2)
    reminder_time = f"{int(hh):02d}:{mm}"
    db.set_user_reminder_settings(user_id, reminder_time=reminder_time)
    db.clear_user_state(user_id)
    await update.message.reply_text(
        f"✅ Время напоминания сохранено: *{reminder_time}* (по вашему часовому поясу).\n\n"
        "Откройте напоминания в меню, чтобы проверить настройки.",
        parse_mode='Markdown',
    )


async def send_reminder(bot, user_id: int):
    """Отправляет напоминание пользователю"""
    try:
        settings = db.get_user_reminder_settings(user_id)
        tz_name = settings.get('timezone', 'Europe/Moscow')
        if user_has_entry_today(user_id, tz_name):
            return
        
        # Отправляем напоминание
        keyboard = [
            [InlineKeyboardButton("📝 Создать запись", callback_data='new_entry')],
            [InlineKeyboardButton("🔕 Отключить напоминания", callback_data='reminder_disable')]
        ]
        
        await bot.send_message(
            chat_id=user_id,
            text="🔔 *Напоминание*\n\n"
                 "Не забудьте вести дневник мыслей сегодня! "
                 "Это поможет вам лучше понимать свои эмоции и реакции.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        logger.info(f"Отправлено напоминание пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминания пользователю {user_id}: {e}")
