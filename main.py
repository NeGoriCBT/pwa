import logging
import asyncio
import re
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from config import BOT_TOKEN
from handlers import (
    start_command, button_handler, text_handler
)
from security import cleanup_old_data, perform_security_check
from admin import admin_command, check_and_notify_suspicious_activities
from backup import backup_database
from telegram.error import TelegramError


class RedactSecretsFilter(logging.Filter):
    """Маскирует секреты в логах (токен бота и bot-token URL сегменты)."""

    def __init__(self, token: str | None):
        super().__init__()
        self.token = token or ""
        # Telegram Bot API: .../bot<token>/<method>
        self.bot_url_re = re.compile(r"/bot\d+:[A-Za-z0-9_-]+")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            if self.token:
                msg = msg.replace(self.token, "***REDACTED_BOT_TOKEN***")
            msg = self.bot_url_re.sub("/bot***REDACTED_BOT_TOKEN***", msg)
            record.msg = msg
            record.args = ()
        except Exception:
            # Не ломаем logging pipeline из-за фильтра
            pass
        return True

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),  # Вывод в консоль
        logging.FileHandler('bot.log', encoding='utf-8')  # Вывод в файл
    ]
)

# Снижаем шум и риск утечки секретов из сетевых логов
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Глобальный фильтр маскировки для всех обработчиков
_redact_filter = RedactSecretsFilter(BOT_TOKEN)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(_redact_filter)

logger = logging.getLogger(__name__)

async def periodic_cleanup(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая очистка старых данных"""
    try:
        from database import Database
        db = Database()
        
        # Очистка старых rate limit записей
        cleanup_old_data()
        
        # Очистка старых сообщений (старше 48 часов - лимит Telegram API)
        db.cleanup_old_messages(hours=48)
        
        logger.info("✅ Периодическая очистка данных выполнена")
    except Exception as e:
        logger.error(f"❌ Ошибка при периодической очистке: {e}", exc_info=True)

async def periodic_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая отправка напоминаний"""
    try:
        from database import Database
        from reminders import send_reminder, now_in_user_tz
        db = Database()
        
        # Получаем всех пользователей с включенными напоминаниями
        users = db.get_users_with_reminders()
        
        for user_info in users:
            user_id = user_info['user_id']
            reminder_time = user_info['time']
            tz_name = user_info.get('timezone') or 'Europe/Moscow'
            local_hhmm = now_in_user_tz(tz_name).strftime('%H:%M')
            
            # Время напоминания в локальном часовом поясе пользователя
            if local_hhmm == reminder_time:
                await send_reminder(context.bot, user_id)
        
        logger.info(f"Проверка напоминаний выполнена: {len(users)} пользователей с включенными напоминаниями")
    except Exception as e:
        logger.error(f"Ошибка при проверке напоминаний: {e}", exc_info=True)

async def periodic_exposure_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая проверка и отправка напоминаний для экспозиций"""
    try:
        from database import Database
        from exposure_handlers import send_exposure_reminder
        db = Database()
        
        # Используем формат без микросекунд для корректного сравнения в SQLite
        current_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        pending_exposures = db.get_pending_exposures_for_reminder(current_datetime)
        
        for exposure in pending_exposures:
            user_id = exposure['user_id']
            exposure_id = exposure['id']
            event_duration = exposure.get('event_duration')
            event_datetime = exposure.get('event_datetime')
            logger.info(f"🔄 Периодическая проверка: найдена экспозиция {exposure_id} (продолжительность: {event_duration} мин, событие: {event_datetime})")
            await send_exposure_reminder(context.bot, user_id, exposure_id)
        
        if pending_exposures:
            logger.info(f"✅ Периодическая проверка: отправлено напоминаний для экспозиций: {len(pending_exposures)}")
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке напоминаний для экспозиций: {e}", exc_info=True)

def schedule_exposure_reminder(application, user_id: int, exposure_id: int, reminder_datetime: datetime):
    """Планирует напоминание для экспозиции"""
    try:
        from exposure_handlers import send_exposure_reminder
        
        job_queue = application.job_queue
        if not job_queue:
            logger.warning(f"JobQueue не доступен для экспозиции {exposure_id}, напоминание будет отправлено через периодическую проверку")
            return
        
        # Вычисляем задержку до напоминания
        now = datetime.now()
        if reminder_datetime <= now:
            # Если время уже прошло, отправляем сразу через периодическую проверку
            logger.info(f"⏰ Время напоминания для экспозиции {exposure_id} уже прошло ({reminder_datetime}), будет отправлено при следующей периодической проверке")
        else:
            delay = (reminder_datetime - now).total_seconds()
            # Используем async функцию правильно
            async def send_reminder_wrapper(ctx):
                logger.info(f"🔔 JobQueue: отправка напоминания для экспозиции {exposure_id}")
                await send_exposure_reminder(ctx.bot, user_id, exposure_id)
            
            # Используем datetime объект для точного времени выполнения
            job_queue.run_once(send_reminder_wrapper, when=reminder_datetime)
            logger.info(f"✅ JobQueue: напоминание для экспозиции {exposure_id} запланировано на {reminder_datetime} (через {delay:.0f} секунд)")
    except Exception as e:
        logger.error(f"❌ Ошибка при планировании напоминания для экспозиции {exposure_id}: {e}", exc_info=True)

async def periodic_reputation_maintenance(context: ContextTypes.DEFAULT_TYPE):
    """Периодическое обслуживание системы репутации"""
    try:
        from database import Database
        db = Database()
        
        # Уменьшаем баллы репутации (ежедневная амнистия)
        db.reduce_reputation_scores(reduction_amount=5)
        logger.info("Ежедневное уменьшение баллов репутации выполнено")
        
        # Автоматически разблокируем пользователей с истекшим временем
        unblocked_count = db.auto_unblock_expired_users()
        if unblocked_count > 0:
            logger.info(f"Автоматически разблокировано пользователей: {unblocked_count}")
    except Exception as e:
        logger.error(f"Ошибка при обслуживании системы репутации: {e}", exc_info=True)

async def periodic_security_check(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая проверка безопасности"""
    try:
        results = perform_security_check()
        logger.info(f"Проверка безопасности выполнена: {results}")
        
        # Проверяем и отправляем уведомления о подозрительной активности
        try:
            await check_and_notify_suspicious_activities(context.bot)
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомлений о подозрительной активности: {e}")
    except Exception as e:
        logger.error(f"Ошибка при проверке безопасности: {e}")

async def periodic_backup(context: ContextTypes.DEFAULT_TYPE):
    """Периодическое создание бэкапа базы данных"""
    try:
        backup_path = backup_database()
        if backup_path:
            logger.info(f"Периодический бэкап БД создан: {backup_path}")
        else:
            logger.warning("Не удалось создать периодический бэкап БД")
    except Exception as e:
        logger.error(f"Ошибка при создании периодического бэкапа: {e}", exc_info=True)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик ошибок"""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
    
    # Пытаемся отправить сообщение об ошибке пользователю
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ Произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже или используйте команду /menu."
            )
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение об ошибке: {e}")

# Глобальная переменная для доступа к application из других модулей
_application_instance = None

def main():
    """Запуск бота"""
    global _application_instance
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    _application_instance = application
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", start_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    # Регистрируем глобальный обработчик ошибок (должен быть последним)
    application.add_error_handler(error_handler)
    
    # Настраиваем периодическую очистку данных и проверки безопасности
    # Проверяем, установлен ли JobQueue
    try:
        job_queue = application.job_queue
        if job_queue:
            # Очистка данных каждые 6 часов
            job_queue.run_repeating(periodic_cleanup, interval=21600, first=21600)  # 6 часов = 21600 секунд
            # Проверка безопасности каждые 12 часов
            job_queue.run_repeating(periodic_security_check, interval=43200, first=43200)  # 12 часов = 43200 секунд
            # Бэкап БД каждые 24 часа (86400 секунд)
            job_queue.run_repeating(periodic_backup, interval=86400, first=86400)
            # Обслуживание системы репутации каждые 24 часа (уменьшение баллов, разблокировка)
            job_queue.run_repeating(periodic_reputation_maintenance, interval=86400, first=86400)
            # Проверка напоминаний каждую минуту
            job_queue.run_repeating(periodic_reminders, interval=60, first=60)
            # Проверка напоминаний для экспозиций каждую минуту
            job_queue.run_repeating(periodic_exposure_reminders, interval=60, first=60)
            logger.info("JobQueue настроен для периодической очистки данных, проверок безопасности, бэкапов, обслуживания репутации и напоминаний")
        else:
            logger.warning("JobQueue не установлен. Установите: pip install 'python-telegram-bot[job-queue]'")
    except Exception as e:
        logger.warning(f"Не удалось настроить JobQueue: {e}")
    
    # Запускаем бота
    logger.info("Бот запущен")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()