from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import List, Dict, Any, Optional
from calendar import monthrange
from datetime import datetime

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает главное меню с кнопками, адаптированными под размер текста"""
    keyboard = [
        [InlineKeyboardButton("ℹ️ Что такое дневник мыслей?", callback_data='info')],
        [InlineKeyboardButton("ℹ️ Что такое дневник экспозиций?", callback_data='info_exposure')],
        [InlineKeyboardButton("📝 Новая запись", callback_data='new_entry')],
        [InlineKeyboardButton("📂 Мои записи", callback_data='my_entries_menu')],
        [InlineKeyboardButton("📊 Статистика", callback_data='statistics_menu')],
        [InlineKeyboardButton("🔍 Поиск", callback_data='search_menu_main')],
        [InlineKeyboardButton("📥 Скачать", callback_data='download_menu')],
        [InlineKeyboardButton("🗑️ Удалить", callback_data='delete_menu')],
        [InlineKeyboardButton("📄 Шаблон", callback_data='template_menu')],
        [InlineKeyboardButton("📋 Документы согласия", callback_data='download_consent_docs')],
        [InlineKeyboardButton("🔐 Настройки пароля", callback_data='password_settings')],
        [InlineKeyboardButton("🔑 Заявка на сброс пароля", callback_data='password_reset_request')],
        [InlineKeyboardButton("🗑️ Удалить аккаунт", callback_data='delete_account')],
        [InlineKeyboardButton("❓ Вопросы по боту", callback_data='questions')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_diary_type_menu_keyboard(action: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора типа дневника"""
    keyboard = [
        [InlineKeyboardButton("💭 Дневник мыслей", callback_data=f'{action}_thoughts')],
        [InlineKeyboardButton("📅 Дневник экспозиций", callback_data=f'{action}_exposure')],
        [InlineKeyboardButton("🔙 Назад", callback_data='menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_duration_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора продолжительности события в минутах"""
    keyboard = [
        [
            InlineKeyboardButton("1", callback_data='exposure_duration_1'),
            InlineKeyboardButton("5", callback_data='exposure_duration_5'),
            InlineKeyboardButton("10", callback_data='exposure_duration_10'),
            InlineKeyboardButton("15", callback_data='exposure_duration_15')
        ],
        [
            InlineKeyboardButton("20", callback_data='exposure_duration_20'),
            InlineKeyboardButton("25", callback_data='exposure_duration_25'),
            InlineKeyboardButton("30", callback_data='exposure_duration_30'),
            InlineKeyboardButton("35", callback_data='exposure_duration_35')
        ],
        [
            InlineKeyboardButton("40", callback_data='exposure_duration_40'),
            InlineKeyboardButton("45", callback_data='exposure_duration_45'),
            InlineKeyboardButton("50", callback_data='exposure_duration_50'),
            InlineKeyboardButton("55", callback_data='exposure_duration_55')
        ],
        [
            InlineKeyboardButton("60", callback_data='exposure_duration_60'),
            InlineKeyboardButton("65", callback_data='exposure_duration_65'),
            InlineKeyboardButton("70", callback_data='exposure_duration_70'),
            InlineKeyboardButton("75", callback_data='exposure_duration_75')
        ],
        [
            InlineKeyboardButton("85", callback_data='exposure_duration_85'),
            InlineKeyboardButton("90", callback_data='exposure_duration_90'),
            InlineKeyboardButton("95", callback_data='exposure_duration_95'),
            InlineKeyboardButton("100", callback_data='exposure_duration_100')
        ],
        [
            InlineKeyboardButton("105", callback_data='exposure_duration_105'),
            InlineKeyboardButton("110", callback_data='exposure_duration_110'),
            InlineKeyboardButton("115", callback_data='exposure_duration_115'),
            InlineKeyboardButton("120", callback_data='exposure_duration_120')
        ],
        [
            InlineKeyboardButton("Я сам проработаю в удобное для себя время", callback_data='exposure_duration_manual')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_consent_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для согласия на обработку данных"""
    keyboard = [
        [InlineKeyboardButton("📋 Документы согласия", callback_data='download_consent_docs')],
        [
            InlineKeyboardButton("✅ Согласен", callback_data='consent_yes'),
            InlineKeyboardButton("❌ Не согласен", callback_data='consent_no')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_emotions_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("Тревога 😟", callback_data='emotion_тревога'),
            InlineKeyboardButton("Грусть 😔", callback_data='emotion_грусть')
        ],
        [
            InlineKeyboardButton("Тоска 🫤", callback_data='emotion_тоска'),
            InlineKeyboardButton("Гнев 😠", callback_data='emotion_гнев')
        ],
        [
            InlineKeyboardButton("Обида 😕", callback_data='emotion_обида'),
            InlineKeyboardButton("Вина 😣", callback_data='emotion_вина')
        ],
        [
            InlineKeyboardButton("Злость 👿", callback_data='emotion_злость'),
            InlineKeyboardButton("✏️ Ввести свою", callback_data='emotion_custom')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_intensity_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for i in range(0, 101, 10):
        if len(row) == 5:
            keyboard.append(row)
            row = []
        row.append(InlineKeyboardButton(str(i), callback_data=f'intensity_{i}'))
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

def get_yes_no_keyboard(yes_data: str = 'yes', no_data: str = 'no') -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("➕ Да", callback_data=yes_data),
            InlineKeyboardButton("❌ Нет", callback_data=no_data)
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_period_keyboard(action_prefix: str = 'download') -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📅 Последние 7 дней", callback_data=f'{action_prefix}_7')],
        [InlineKeyboardButton("📅 Последние 30 дней", callback_data=f'{action_prefix}_30')],
        [InlineKeyboardButton("📅 За все время", callback_data=f'{action_prefix}_all')],
        [InlineKeyboardButton("📅 Произвольный период", callback_data=f'{action_prefix}_custom')],
        [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_new_emotions_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("Радость 😊", callback_data='new_emotion_радость'),
            InlineKeyboardButton("Спокойствие 😌", callback_data='new_emotion_спокойствие')
        ],
        [
            InlineKeyboardButton("Облегчение 😮‍💨", callback_data='new_emotion_облегчение'),
            InlineKeyboardButton("Надежда 🤲", callback_data='new_emotion_надежда')
        ],
        [
            InlineKeyboardButton("Гордость 😌", callback_data='new_emotion_гордость'),
            InlineKeyboardButton("Благодарность 🙏", callback_data='new_emotion_благодарность')
        ],
        [InlineKeyboardButton("✏️ Ввести свою", callback_data='new_emotion_custom')],
        [InlineKeyboardButton("❌ Нет, эмоций больше не было", callback_data='new_emotion_none')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton("🔙 В меню", callback_data='menu')]]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_entry_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой отмены создания записи"""
    keyboard = [[InlineKeyboardButton("❌ Отменить создание записи", callback_data='cancel_entry')]]
    return InlineKeyboardMarkup(keyboard)

def get_cancel_entry_with_menu_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопками отмены и возврата в меню"""
    keyboard = [
        [InlineKeyboardButton("❌ Отменить создание записи", callback_data='cancel_entry')],
        [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_calendar(year: Optional[int] = None, month: Optional[int] = None, prefix: str = 'cal') -> InlineKeyboardMarkup:
    """Создает инлайн календарь для выбора даты"""
    if year is None:
        year = datetime.now().year
    if month is None:
        month = datetime.now().month
    
    # Заголовок календаря
    months = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
              'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
    
    keyboard = []
    
    # Кнопки навигации по году и месяцу
    keyboard.append([
        InlineKeyboardButton("◀️", callback_data=f"{prefix}_prev_month_{year}_{month}"),
        InlineKeyboardButton(f"{months[month-1]} {year}", callback_data=f"{prefix}_ignore"),
        InlineKeyboardButton("▶️", callback_data=f"{prefix}_next_month_{year}_{month}")
    ])
    
    # Дни недели
    weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    keyboard.append([InlineKeyboardButton(day, callback_data=f"{prefix}_ignore") for day in weekdays])
    
    # Дни месяца
    first_day, days_in_month = monthrange(year, month)
    # first_day - день недели первого дня (0 = понедельник, 6 = воскресенье)
    # Переводим в наш формат (0 = понедельник)
    first_day = (first_day) % 7
    
    row = []
    # Пустые ячейки для дней до первого дня месяца
    for _ in range(first_day):
        row.append(InlineKeyboardButton(" ", callback_data=f"{prefix}_ignore"))
    
    # Дни месяца
    for day in range(1, days_in_month + 1):
        row.append(InlineKeyboardButton(str(day), callback_data=f"{prefix}_day_{year}_{month}_{day}"))
        if len(row) == 7:
            keyboard.append(row)
            row = []
    
    # Заполняем оставшиеся ячейки пустыми кнопками
    while len(row) < 7:
        row.append(InlineKeyboardButton(" ", callback_data=f"{prefix}_ignore"))
    if row:
        keyboard.append(row)
    
    # Кнопка отмены
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"{prefix}_cancel")])
    
    return InlineKeyboardMarkup(keyboard)

def format_entry_summary(entry_data: dict) -> str:
    """Форматирует итоговую сводку записи"""
    from security import escape_markdown
    
    result = "📋 *Итоговая сводка*\n\n"
    
    # Экранируем пользовательские данные для безопасного отображения в Markdown
    situation = escape_markdown(str(entry_data.get('situation', '')))
    automatic_thought = escape_markdown(str(entry_data.get('automatic_thought', '')))
    action = escape_markdown(str(entry_data.get('action', '')))
    evidence_for = escape_markdown(str(entry_data.get('evidence_for', '')))
    evidence_against = escape_markdown(str(entry_data.get('evidence_against', '')))
    note = escape_markdown(str(entry_data.get('note_to_future_self', '')))
    
    result += f"*Ситуация:* {situation}\n\n"
    
    result += f"*Автоматическая мысль:* {automatic_thought}\n"
    result += f"\\(уверенность {entry_data.get('automatic_thought_confidence', 0)}%\\)\n\n"
    
    alt_thoughts = entry_data.get('alternative_thoughts', [])
    if alt_thoughts:
        result += "*Альтернативные мысли:*\n"
        for alt in alt_thoughts:
            thought = escape_markdown(str(alt.get('thought', '')))
            result += f"• {thought} \\(уверенность {alt.get('confidence', 0)}%\\)\n"
        result += "\n"
    
    emotions_before = entry_data.get('emotions_before', [])
    emotions_after = entry_data.get('emotions_after', [])
    
    result += "*Эмоции до:*\n"
    for em in emotions_before:
        emotion_name = escape_markdown(str(em.get('emotion', '')))
        old_intensity = em.get('intensity', 0)
        # Найти новую интенсивность для этой эмоции
        new_intensity = old_intensity
        for em_after in emotions_after:
            if em_after.get('emotion') == em.get('emotion'):
                new_intensity = em_after.get('intensity', old_intensity)
                break
        result += f"• {emotion_name}: {old_intensity}% → {new_intensity}%\n"
    result += "\n"
    
    # Новые эмоции
    new_emotions = [em for em in emotions_after 
                   if not any(em.get('emotion') == e.get('emotion') 
                            for e in emotions_before)]
    if new_emotions:
        result += "*Новые эмоции:*\n"
        for em in new_emotions:
            emotion_name = escape_markdown(str(em.get('emotion', '')))
            result += f"• {emotion_name}: {em.get('intensity', 0)}%\n"
        result += "\n"
    
    if entry_data.get('action'):
        result += f"*Действие:* {action}\n\n"
    
    if entry_data.get('evidence_for'):
        result += f"*Доводы за:* {evidence_for}\n\n"
    
    if entry_data.get('evidence_against'):
        result += f"*Доводы против:* {evidence_against}\n\n"
    
    if entry_data.get('note_to_future_self'):
        result += f"*Заметка будущему себе:*\n{note}\n"
    
    return result

def check_success(entry_data: dict) -> bool:
    """Проверяет, была ли запись успешной (снижение негативных эмоций или появление позитивных)"""
    emotions_before = entry_data.get('emotions_before', [])
    emotions_after = entry_data.get('emotions_after', [])
    
    # Проверяем снижение негативных эмоций
    for em_before in emotions_before:
        old_intensity = em_before.get('intensity', 0)
        emotion_name = em_before.get('emotion', '')
        
        # Ищем эту эмоцию в после
        for em_after in emotions_after:
            if em_after.get('emotion') == emotion_name:
                new_intensity = em_after.get('intensity', old_intensity)
                if old_intensity - new_intensity >= 20:
                    return True
                break
    
    # Проверяем появление позитивных эмоций
    positive_emotions = ['радость', 'спокойствие', 'облегчение', 'надежда', 'гордость', 'благодарность']
    for em_after in emotions_after:
        if any(pos in em_after.get('emotion', '').lower() for pos in positive_emotions):
            if em_after.get('intensity', 0) > 0:
                return True
    
    return False