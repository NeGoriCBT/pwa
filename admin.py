"""
Модуль админки для бота
"""
import io
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import ContextTypes
from config import ADMIN_USERNAME, BOT_TOKEN
from database import Database
from security import check_rate_limit

logger = logging.getLogger(__name__)
db = Database()

async def show_user_info_for_admin(query_or_update, context, user_id: int):
    """Показывает информацию о пользователе для админа"""
    # Получаем информацию о пользователе
    user_stats = db.get_user_stats(user_id)
    entries = db.get_user_entries(user_id)
    exposures = db.get_user_exposures(user_id) if hasattr(db, 'get_user_exposures') else []
    
    # Получаем статус защиты
    from active_protection import get_user_protection_status
    protection_status = get_user_protection_status(user_id)
    
    # Получаем подозрительные активности
    suspicious_activities = db.get_user_suspicious_activities(user_id, limit=10) if hasattr(db, 'get_user_suspicious_activities') else []
    
    # Проверяем, заблокирован ли пользователь
    is_blocked = db.is_user_blocked(user_id)
    blocked_info = None
    if is_blocked:
        blocked_users = db.get_blocked_users()
        user_block = next((u for u in blocked_users if u['user_id'] == user_id), None)
        if user_block:
            blocked_info = user_block
    
    # Формируем текст
    from datetime import datetime
    from security import escape_markdown
    
    text = f"👤 *Информация о пользователе*\n\n"
    text += f"*ID:* `{user_id}`\n\n"
    
    # Статус блокировки
    if is_blocked:
        text += "🚫 *Статус:* Заблокирован\n"
        if blocked_info:
            blocked_date = datetime.fromisoformat(blocked_info['blocked_at']).strftime('%d.%m.%Y %H:%M')
            text += f"*Заблокирован:* {blocked_date}\n"
            if blocked_info.get('blocked_reason'):
                reason = escape_markdown(str(blocked_info['blocked_reason'])[:100])
                text += f"*Причина:* {reason}\n"
            if blocked_info.get('auto_blocked', 0):
                if blocked_info.get('unblock_at'):
                    try:
                        unblock_time = datetime.fromisoformat(blocked_info['unblock_at'])
                        time_left = unblock_time - datetime.now()
                        if time_left.total_seconds() > 0:
                            hours = int(time_left.total_seconds() // 3600)
                            minutes = int((time_left.total_seconds() % 3600) // 60)
                            text += f"*Разблокировка через:* {hours}ч {minutes}м\n"
                        else:
                            text += "*Разблокировка:* Время истекло\n"
                    except:
                        text += "*Тип:* Автоблокировка\n"
                else:
                    text += "*Тип:* Постоянная блокировка\n"
            else:
                text += "*Тип:* Блокировка админом\n"
    else:
        text += "✅ *Статус:* Активен\n"
    
    text += "\n"
    
    # Репутация
    text += f"*Репутация:*\n"
    text += f"• Баллы: {protection_status['violation_score']}\n"
    text += f"• Уровень защиты: {protection_status['protection_level']}\n"
    text += f"• Уровень ограничений: {protection_status['restrictions_level']}\n"
    if protection_status.get('last_violation'):
        last_violation = escape_markdown(str(protection_status['last_violation']))
        text += f"• Последнее нарушение: {last_violation}\n"
    text += "\n"
    
    # Статистика
    text += f"*Статистика:*\n"
    text += f"• Записей дневника мыслей: {len(entries)}\n"
    if hasattr(db, 'get_user_exposures'):
        text += f"• Записей дневника экспозиций: {len(exposures)}\n"
    text += f"• Подозрительных активностей: {user_stats['suspicious_count']}\n"
    if user_stats.get('last_activity'):
        last_activity = datetime.fromisoformat(user_stats['last_activity']).strftime('%d.%m.%Y %H:%M')
        text += f"• Последняя активность: {last_activity}\n"
    text += "\n"
    
    # Последние подозрительные активности
    if suspicious_activities:
        text += f"*Последние подозрительные активности:*\n"
        for act in suspicious_activities[:5]:
            act_time = datetime.fromisoformat(act['timestamp']).strftime('%d.%m %H:%M')
            act_type = escape_markdown(str(act['activity_type'])[:30])
            text += f"• {act_time}: {act_type}\n"
        text += "\n"
    
    # Кнопки действий
    keyboard = []
    if is_blocked:
        keyboard.append([InlineKeyboardButton("🔓 Разблокировать", callback_data=f'admin_unblock_user_{user_id}')])
    else:
        keyboard.append([InlineKeyboardButton("🚫 Заблокировать", callback_data=f'admin_block_user_{user_id}_0')])
    
    # Кнопка снятия всех ограничений (показываем если есть блокировка, репутация или ограничения)
    if is_blocked or protection_status['violation_score'] > 0 or protection_status['restrictions_level'] > 0:
        keyboard.append([InlineKeyboardButton("✨ Снять все ограничения", callback_data=f'admin_remove_restrictions_{user_id}')])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_back')])
    
    # Определяем, это callback query или update
    if isinstance(query_or_update, CallbackQuery):
        await query_or_update.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # Это Update, отправляем новое сообщение
        await query_or_update.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def show_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Обертка для show_user_info_for_admin из handlers.py"""
    await show_user_info_for_admin(update, context, user_id)

def is_admin(user) -> bool:
    """Проверяет, является ли пользователь админом"""
    if not user:
        return False
    if not hasattr(user, 'username') or not user.username:
        return False
    admin_username_clean = ADMIN_USERNAME.replace('@', '').lower()
    user_username_clean = user.username.lower()
    return user_username_clean == admin_username_clean

# Кэш для chat_id админа
_admin_chat_id = None

def save_admin_chat_id_from_update(update_or_query):
    """Сохраняет chat_id админа из update или query (когда админ пишет боту)"""
    global _admin_chat_id
    from cache import clear_cache
    
    # Обрабатываем Update
    if isinstance(update_or_query, Update):
        if update_or_query.effective_user and is_admin(update_or_query.effective_user):
            chat_id = update_or_query.effective_chat.id
            username = update_or_query.effective_user.username
            db.save_admin_chat_id(chat_id)
            _admin_chat_id = chat_id
            # Очищаем кэш настроек админа при обновлении
            clear_cache('admin_chat_id')
            logger.info(f"✅ Chat_id админа сохранен из update: {chat_id} (username: @{username})")
    # Обрабатываем CallbackQuery
    elif hasattr(update_or_query, 'from_user') and hasattr(update_or_query, 'message'):
        if is_admin(update_or_query.from_user):
            chat_id = update_or_query.message.chat.id
            username = update_or_query.from_user.username
            db.save_admin_chat_id(chat_id)
            _admin_chat_id = chat_id
            # Очищаем кэш настроек админа при обновлении
            clear_cache('admin_chat_id')
            logger.info(f"✅ Chat_id админа сохранен из query: {chat_id} (username: @{username})")

async def notify_admin(bot, message: str):
    """Отправляет уведомление админу"""
    global _admin_chat_id
    from cache import get_cached, set_cached
    
    logger.info(f"🔔 Попытка отправить уведомление админу. Длина сообщения: {len(message)}")
    
    try:
        # Пробуем получить из кэша
        cached_chat_id = get_cached('admin_chat_id', ttl=3600)  # Кэш на 1 час
        if cached_chat_id:
            _admin_chat_id = cached_chat_id
            logger.debug(f"✅ Chat_id админа загружен из кэша: {_admin_chat_id}")
        
        # Если нет в кэше, пробуем получить из БД
        if _admin_chat_id is None:
            saved_chat_id = db.get_admin_chat_id()
            if saved_chat_id:
                _admin_chat_id = saved_chat_id
                set_cached('admin_chat_id', saved_chat_id, ttl=3600)
                logger.info(f"✅ Chat_id админа загружен из БД: {_admin_chat_id}")
            else:
                logger.warning(f"⚠️ Chat_id админа не найден в БД")
        
        # Если все еще нет, пробуем получить через get_chat
        if _admin_chat_id is None:
            try:
                # Пробуем с @ и без
                for username_variant in [ADMIN_USERNAME, ADMIN_USERNAME.replace('@', '')]:
                    try:
                        chat = await bot.get_chat(username_variant)
                        _admin_chat_id = chat.id
                        db.save_admin_chat_id(_admin_chat_id)
                        logger.info(f"✅ Получен chat_id админа через get_chat: {_admin_chat_id} (username: {username_variant})")
                        break
                    except:
                        continue
            except Exception as e:
                logger.error(f"❌ Не удалось получить chat админа по username {ADMIN_USERNAME}: {e}")
        
        # Если chat_id есть, отправляем
        if _admin_chat_id:
            logger.info(f"📤 Отправка уведомления на chat_id: {_admin_chat_id}")
            try:
                result = await bot.send_message(
                    chat_id=_admin_chat_id, 
                    text=message, 
                    parse_mode='Markdown'
                )
                logger.info(f"✅ Уведомление админу отправлено успешно на {_admin_chat_id}. Message ID: {result.message_id}")
                return
            except Exception as e:
                logger.warning(f"⚠️ Не удалось отправить с Markdown на {_admin_chat_id}, пробуем без форматирования. Ошибка: {type(e).__name__}: {e}")
                # Пробуем без parse_mode
                try:
                    plain_message = message.replace('*', '').replace('_', '').replace('`', '')
                    result = await bot.send_message(
                        chat_id=_admin_chat_id, 
                        text=plain_message
                    )
                    logger.info(f"✅ Уведомление админу отправлено без форматирования. Message ID: {result.message_id}")
                    return
                except Exception as e2:
                    logger.error(f"❌ Не удалось отправить уведомление на {_admin_chat_id}. Ошибка: {type(e2).__name__}: {e2}", exc_info=True)
                    # Сбрасываем кэш
                    _admin_chat_id = None
        else:
            logger.warning(f"⚠️ Chat_id админа не найден, пробуем username")
        
        # Последняя попытка - по username напрямую
        logger.warning(f"📤 Последняя попытка: отправка по username напрямую: {ADMIN_USERNAME}")
        try:
            result = await bot.send_message(chat_id=ADMIN_USERNAME, text=message, parse_mode='Markdown')
            logger.info(f"✅ Уведомление отправлено по username: {ADMIN_USERNAME}. Message ID: {result.message_id}")
            return
        except Exception as e:
            logger.error(f"❌ Не удалось отправить по username с Markdown. Username: {ADMIN_USERNAME}, Ошибка: {type(e).__name__}: {e}")
            # Пробуем без форматирования
            try:
                plain_message = message.replace('*', '').replace('_', '').replace('`', '')
                result = await bot.send_message(chat_id=ADMIN_USERNAME, text=plain_message)
                logger.info(f"✅ Уведомление отправлено по username без форматирования. Message ID: {result.message_id}")
                return
            except Exception as e2:
                logger.error(f"❌ Финальная попытка отправки также не удалась. Ошибка: {type(e2).__name__}: {e2}", exc_info=True)
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при отправке уведомления админу: {type(e).__name__}: {e}", exc_info=True)

async def execute_broadcast(query, context, message_text: str):
    """Выполняет рассылку сообщения всем пользователям"""
    from states import States
    from telegram.error import Forbidden, BadRequest
    user_ids = db.get_all_broadcast_user_ids()
    success_count = 0
    fail_count = 0
    await query.edit_message_text("📤 Рассылка началась...")
    for user_id in user_ids:
        try:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message_text,
                    parse_mode='Markdown'
                )
            except BadRequest:
                plain_text = message_text.replace('*', '').replace('_', '').replace('`', '')
                await context.bot.send_message(chat_id=user_id, text=plain_text)
            success_count += 1
        except Forbidden:
            fail_count += 1
            logger.debug(f"Пользователь {user_id} заблокировал бота")
        except BadRequest as e:
            fail_count += 1
            logger.debug(f"Не удалось отправить {user_id}: {e}")
        except Exception as e:
            fail_count += 1
            logger.warning(f"Ошибка при отправке пользователю {user_id}: {e}")
        await asyncio.sleep(0.05)
    db.clear_user_state(query.from_user.id)
    result_text = (
        f"✅ *Рассылка завершена*\n\n"
        f"*Доставлено:* {success_count}\n"
        f"*Не доставлено:* {fail_count}\n"
        f"*Всего получателей:* {len(user_ids)}"
    )
    keyboard = [[InlineKeyboardButton("🔙 В админ-панель", callback_data='admin_back')]]
    await query.edit_message_text(
        result_text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    logger.info(f"Рассылка админом: доставлено {success_count}, не доставлено {fail_count}")

async def handle_admin_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Обрабатывает ввод текста рассылки от админа"""
    from states import States
    if text.strip().lower() in ('/cancel', 'отмена', 'cancel'):
        db.clear_user_state(update.effective_user.id)
        await update.message.reply_text("Рассылка отменена. Используйте /admin для возврата в админ-панель.")
        return
    if not text.strip():
        await update.message.reply_text("⚠️ Текст сообщения не может быть пустым.")
        return
    db.save_user_state(update.effective_user.id, States.ADMIN_BROADCAST_MESSAGE, {'broadcast_text': text})
    preview = text[:200] + "..." if len(text) > 200 else text
    keyboard = [
        [
            InlineKeyboardButton("✅ Отправить", callback_data='admin_broadcast_confirm'),
            InlineKeyboardButton("❌ Отмена", callback_data='admin_broadcast_cancel')
        ]
    ]
    try:
        await update.message.reply_text(
            f"📋 *Предпросмотр рассылки*\n\n{preview}\n\n"
            f"Подтвердите отправку:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception:
        await update.message.reply_text(
            f"📋 Предпросмотр рассылки:\n\n{preview}\n\nПодтвердите отправку:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def check_and_notify_suspicious_activities(bot):
    """Проверяет и отправляет уведомления о подозрительной активности"""
    try:
        activities = db.get_unnotified_suspicious_activities()
        
        if not activities:
            logger.debug("Нет непроинформированных подозрительных активностей")
            return
        
        logger.info(f"Найдено {len(activities)} непроинформированных подозрительных активностей")
        
        for activity in activities:
            message = (
                f"⚠️ *Подозрительная активность*\n\n"
                f"*Тип:* {activity['activity_type']}\n"
                f"*Пользователь ID:* {activity['user_id']}\n"
                f"*Описание:* {activity['description']}\n"
                f"*Время:* {activity['timestamp']}"
            )
            
            # Создаем клавиатуру с кнопками
            keyboard = [
                [
                    InlineKeyboardButton("✅ Игнорировать", callback_data=f'admin_ignore_activity_{activity["id"]}'),
                    InlineKeyboardButton("🚫 Заблокировать", callback_data=f'admin_block_user_{activity["user_id"]}_{activity["id"]}')
                ]
            ]
            
            try:
                await notify_admin_with_buttons(bot, message, InlineKeyboardMarkup(keyboard))
                db.mark_activity_notified(activity['id'])
                logger.info(f"Уведомление о подозрительной активности {activity['id']} отправлено и отмечено")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления о подозрительной активности {activity['id']}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Критическая ошибка в check_and_notify_suspicious_activities: {e}", exc_info=True)

async def notify_admin_with_buttons(bot, message: str, reply_markup):
    """Отправляет уведомление админу с кнопками"""
    global _admin_chat_id
    
    logger.info(f"🔔 Попытка отправить уведомление админу с кнопками. Длина сообщения: {len(message)}")
    
    try:
        # Получаем chat_id админа
        if _admin_chat_id is None:
            saved_chat_id = db.get_admin_chat_id()
            if saved_chat_id:
                _admin_chat_id = saved_chat_id
                logger.info(f"✅ Chat_id админа загружен из БД: {_admin_chat_id}")
        
        if _admin_chat_id is None:
            try:
                for username_variant in [ADMIN_USERNAME, ADMIN_USERNAME.replace('@', '')]:
                    try:
                        chat = await bot.get_chat(username_variant)
                        _admin_chat_id = chat.id
                        db.save_admin_chat_id(_admin_chat_id)
                        logger.info(f"✅ Получен chat_id админа через get_chat: {_admin_chat_id}")
                        break
                    except:
                        continue
            except Exception as e:
                logger.error(f"❌ Не удалось получить chat админа: {e}")
        
        if _admin_chat_id:
            try:
                result = await bot.send_message(
                    chat_id=_admin_chat_id,
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
                logger.info(f"✅ Уведомление с кнопками отправлено на {_admin_chat_id}. Message ID: {result.message_id}")
                return
            except Exception as e:
                logger.warning(f"⚠️ Не удалось отправить с Markdown, пробуем без форматирования: {e}")
                try:
                    plain_message = message.replace('*', '').replace('_', '').replace('`', '')
                    result = await bot.send_message(
                        chat_id=_admin_chat_id,
                        text=plain_message,
                        reply_markup=reply_markup
                    )
                    logger.info(f"✅ Уведомление с кнопками отправлено без форматирования")
                    return
                except Exception as e2:
                    logger.error(f"❌ Не удалось отправить уведомление с кнопками: {e2}")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке уведомления с кнопками: {e}", exc_info=True)


async def handle_admin_reset_approve(query, context, data: str):
    """Одобряет заявку на сброс пароля"""
    if not is_admin(query.from_user):
        await query.answer("❌ Нет прав доступа.", show_alert=True)
        return
    try:
        req_id = int(data.replace('admin_reset_approve_', ''))
    except ValueError:
        await query.answer("Ошибка: неверный ID заявки.", show_alert=True)
        return
    user_id = db.approve_password_reset_request(req_id)
    if user_id is None:
        await query.answer("Заявка уже обработана или не найдена.", show_alert=True)
        return
    # Уведомляем пользователя и предлагаем создать новый пароль сразу
    from states import States
    from handlers import PASSWORD_RULES
    db.save_user_state(user_id, States.WAITING_PASSWORD_CREATE, {})
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ *Заявка на сброс пароля одобрена*\n\n"
                 "Ваш пароль сброшен. Создайте новый пароль:\n\n"
                 f"*{PASSWORD_RULES}*\n\nВведите новый пароль:",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить пользователя {user_id} об одобрении: {e}")
    await query.answer("Пароль сброшен. Пользователь уведомлён.", show_alert=True)
    # Возвращаем к списку заявок
    requests_list = db.get_pending_password_reset_requests()
    if not requests_list:
        text = "✅ Заявок на сброс пароля нет."
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]]
    else:
        text = "🔑 *Заявки на сброс пароля:*\n\n"
        for req in requests_list[:20]:
            from datetime import datetime
            req_date = datetime.fromisoformat(req['requested_at']).strftime('%d.%m.%Y %H:%M')
            text += f"• Заявка #{req['id']} — пользователь {req['user_id']} — {req_date}\n"
        if len(requests_list) > 20:
            text += f"\n... и ещё {len(requests_list) - 20}"
        keyboard = []
        for req in requests_list[:15]:
            keyboard.append([
                InlineKeyboardButton(f"✅ Одобрить #{req['id']}", callback_data=f'admin_reset_approve_{req["id"]}'),
                InlineKeyboardButton(f"❌ Отклонить #{req['id']}", callback_data=f'admin_reset_reject_{req["id"]}')
            ])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_back')])
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_admin_reset_reject(query, context, data: str):
    """Отклоняет заявку на сброс пароля"""
    if not is_admin(query.from_user):
        await query.answer("❌ Нет прав доступа.", show_alert=True)
        return
    try:
        req_id = int(data.replace('admin_reset_reject_', ''))
    except ValueError:
        await query.answer("Ошибка: неверный ID заявки.", show_alert=True)
        return
    user_id = db.reject_password_reset_request(req_id)
    if user_id is None:
        await query.answer("Заявка уже обработана или не найдена.", show_alert=True)
        return
    # Уведомляем пользователя
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ *Заявка на сброс пароля отклонена*\n\n"
                 "Ваша заявка была отклонена администратором. "
                 "Если вы считаете, что это ошибка, обратитесь к администратору.",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить пользователя {user_id} об отклонении: {e}")
    await query.answer("Заявка отклонена. Пользователь уведомлён.", show_alert=True)
    # Возвращаем к списку заявок
    requests_list = db.get_pending_password_reset_requests()
    if not requests_list:
        text = "✅ Заявок на сброс пароля нет."
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]]
    else:
        text = "🔑 *Заявки на сброс пароля:*\n\n"
        for req in requests_list[:20]:
            from datetime import datetime
            req_date = datetime.fromisoformat(req['requested_at']).strftime('%d.%m.%Y %H:%M')
            text += f"• Заявка #{req['id']} — пользователь {req['user_id']} — {req_date}\n"
        if len(requests_list) > 20:
            text += f"\n... и ещё {len(requests_list) - 20}"
        keyboard = []
        for req in requests_list[:15]:
            keyboard.append([
                InlineKeyboardButton(f"✅ Одобрить #{req['id']}", callback_data=f'admin_reset_approve_{req["id"]}'),
                InlineKeyboardButton(f"❌ Отклонить #{req['id']}", callback_data=f'admin_reset_reject_{req["id"]}')
            ])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_back')])
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик админских команд"""
    user = update.effective_user
    
    if not is_admin(user):
        await update.message.reply_text("❌ У вас нет прав доступа к админ-панели.")
        return
    
    # Сохраняем chat_id админа при первом обращении
    save_admin_chat_id_from_update(update)
    
    # Сохраняем chat_id админа
    save_admin_chat_id_from_update(update)
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика бота", callback_data='admin_stats')],
        [InlineKeyboardButton("🚫 Заблокированные", callback_data='admin_blocked_users')],
        [InlineKeyboardButton("⚠️ Ограниченные", callback_data='admin_restricted_users')],
        [InlineKeyboardButton("🔑 Заявки на сброс пароля", callback_data='admin_password_resets')],
        [InlineKeyboardButton("📢 Сообщение всем", callback_data='admin_broadcast')],
        [InlineKeyboardButton("📋 Экспорт логов подтверждений", callback_data='admin_export_confirmation_logs')],
        [InlineKeyboardButton("🗑️ Удалить всех пользователей", callback_data='admin_delete_all_users')],
        [InlineKeyboardButton("🔌 Выключить бота", callback_data='admin_shutdown')],
        [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
    ]
    
    admin_chat_id = db.get_admin_chat_id()
    admin_info = f"\n\n*Chat_id:* `{update.effective_chat.id}`"
    if admin_chat_id:
        admin_info += f"\n*Сохраненный chat_id:* `{admin_chat_id}`"
    admin_info += f"\n*Username:* {ADMIN_USERNAME}"
    
    await update.message.reply_text(
        f"🔐 *Админ-панель*{admin_info}\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    

async def handle_admin_callback(query, context, data):
    """Обрабатывает админские callback"""
    user = query.from_user
    
    if not is_admin(user):
        await query.answer("❌ У вас нет прав доступа.", show_alert=True)
        return
    
    if data == 'admin_stats':
        # Статистика бота (расширенная)
        stats = db.get_admin_stats()
        stats_text = (
            f"📊 *Статистика бота*\n\n"
            f"*👥 Пользователи:*\n"
            f"  Всего: {stats['total_users']}\n"
            f"  Новых за неделю: {stats['new_users_week']}\n"
            f"  Новых за месяц: {stats['new_users_month']}\n\n"
            f"*📝 Записи:*\n"
            f"  Всего: {stats['total_entries']}\n"
            f"  Дневник мыслей — за неделю: {stats['new_entries_thoughts_week']}, за месяц: {stats['new_entries_thoughts_month']}\n"
            f"  Дневник экспозиций — за неделю: {stats['new_entries_exposures_week']}, за месяц: {stats['new_entries_exposures_month']}\n\n"
            f"*⚠️ Подозрительная активность:*\n"
            f"  За сегодня: {stats['suspicious_today']}\n"
            f"  За неделю: {stats['suspicious_week']}\n"
            f"  За месяц: {stats['suspicious_month']}\n\n"
            f"*🚫 Заблокированных:* {stats['blocked_count']}\n"
            f"*⚠️ Ограниченных:* {stats['restricted_count']}"
        )
        await query.edit_message_text(
            stats_text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]
            ])
        )
    
    elif data == 'admin_password_resets':
        # Заявки на сброс пароля
        requests_list = db.get_pending_password_reset_requests()
        if not requests_list:
            text = "✅ Заявок на сброс пароля нет."
        else:
            text = "🔑 *Заявки на сброс пароля:*\n\n"
            for req in requests_list[:20]:
                from datetime import datetime
                req_date = datetime.fromisoformat(req['requested_at']).strftime('%d.%m.%Y %H:%M')
                text += f"• Заявка #{req['id']} — пользователь {req['user_id']} — {req_date}\n"
            if len(requests_list) > 20:
                text += f"\n... и ещё {len(requests_list) - 20}"
        keyboard = []
        for req in requests_list[:15]:
            keyboard.append([
                InlineKeyboardButton(
                    f"✅ Одобрить #{req['id']}",
                    callback_data=f'admin_reset_approve_{req["id"]}'
                ),
                InlineKeyboardButton(
                    f"❌ Отклонить #{req['id']}",
                    callback_data=f'admin_reset_reject_{req["id"]}'
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_back')])
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == 'admin_export_confirmation_logs':
        # Экспорт логов подтверждений (возраст, первая чувствительная запись) — для предоставления по запросу / в суд
        logs = db.get_confirmation_logs()
        type_ru = {'age': 'Подтверждение возраста', 'sensitive_entry': 'Подтверждение перед первой чувствительной записью'}
        # CSV с BOM для корректного открытия в Excel (UTF-8)
        lines = ['id;user_id;confirmation_type;confirmed_at;type_description']
        for row in logs:
            desc = type_ru.get(row['confirmation_type'], row['confirmation_type'])
            lines.append(f"{row['id']};{row['user_id']};{row['confirmation_type']};{row['confirmed_at']};{desc}")
        csv_content = '\n'.join(lines)
        buf = io.BytesIO(csv_content.encode('utf-8-sig'))
        buf.seek(0)
        filename = f"confirmation_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        try:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=buf,
                filename=filename,
                caption="📋 Логи подтверждений (возраст, первая чувствительная запись). Можно предоставить по запросу или в суд."
            )
            await query.answer("Файл отправлен в чат.")
        except Exception as e:
            logger.exception("Ошибка отправки экспорта логов подтверждений")
            await query.answer(f"Ошибка: {e}", show_alert=True)
        await query.edit_message_text(
            "📋 *Экспорт логов подтверждений*\n\nФайл CSV отправлен в чат. Содержит: id записи, user_id (Telegram ID), тип подтверждения, дата/время (ISO).",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]])
        )
    
    elif data == 'admin_restricted_users':
        # Ограниченные пользователи (с возможностью снятия ограничений)
        restricted = db.get_restricted_users()
        if not restricted:
            text = "✅ Ограниченных пользователей нет."
        else:
            text = "⚠️ *Ограниченные пользователи:*\n\n"
            for u in restricted[:20]:
                text += f"• ID: {u['user_id']} — баллы: {u['violation_score']}, уровень: {u['restrictions_level']}\n"
            if len(restricted) > 20:
                text += f"\n... и ещё {len(restricted) - 20}"
        keyboard = []
        for u in restricted[:15]:
            keyboard.append([
                InlineKeyboardButton(
                    f"✨ Снять ограничения {u['user_id']}",
                    callback_data=f'admin_remove_restrictions_{u["user_id"]}'
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_back')])
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == 'admin_delete_all_users':
        # Подтверждение удаления всех пользователей
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, удалить всех", callback_data='admin_delete_all_users_confirm'),
                InlineKeyboardButton("❌ Отмена", callback_data='admin_back')
            ]
        ]
        await query.edit_message_text(
            "⚠️ *Удаление всех пользователей*\n\n"
            "Вы уверены? Будут удалены:\n"
            "• Все записи дневников\n"
            "• Все данные пользователей (согласия, пароли, состояния)\n"
            "• Заблокированные, ограниченные, заявки на сброс пароля\n\n"
            "Это действие нельзя отменить.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == 'admin_delete_all_users_confirm':
        count = db.delete_all_users()
        logger.warning(f"Админ {user.id} удалил всех пользователей")
        await query.edit_message_text(
            f"✅ *Готово*\n\nУдалены все пользователи и их данные.\nОчищено таблиц: {count}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 В админ-панель", callback_data='admin_back')]
            ]),
            parse_mode='Markdown'
        )
    
    elif data == 'admin_shutdown':
        # Подтверждение выключения бота
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, выключить", callback_data='admin_shutdown_confirm'),
                InlineKeyboardButton("❌ Отмена", callback_data='admin_back')
            ]
        ]
        
        await query.edit_message_text(
            "⚠️ *Выключение бота*\n\n"
            "Вы уверены, что хотите выключить бота?\n\n"
            "Бот остановится и перестанет отвечать на запросы.\n"
            "Для повторного запуска нужно будет запустить скрипт вручную.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == 'admin_shutdown_confirm':
        # Выключаем бота
        await query.edit_message_text(
            "🛑 *Бот выключается...*\n\n"
            "Бот будет остановлен через несколько секунд.",
            parse_mode='Markdown'
        )
        
        logger.warning(f"Админ {user.id} выключил бота")
        
        # Останавливаем бота через несколько секунд
        async def shutdown_delayed():
            await asyncio.sleep(2)
            try:
                # Получаем application из context
                application = context.application
                if application:
                    await application.stop()
                    logger.info("✅ Бот остановлен админом через application.stop()")
                else:
                    # Альтернативный способ - через os
                    import os
                    import signal
                    logger.warning("Application не найдено в context, используем SIGTERM")
                    os.kill(os.getpid(), signal.SIGTERM)
            except Exception as e:
                logger.error(f"Ошибка при выключении бота: {e}")
                # Последняя попытка - через os
                try:
                    import os
                    import signal
                    os.kill(os.getpid(), signal.SIGTERM)
                except:
                    pass
        
        # Запускаем отложенное выключение
        asyncio.create_task(shutdown_delayed())
    
    elif data == 'admin_broadcast':
        # Рассылка всем пользователям
        from states import States
        user_ids = db.get_all_broadcast_user_ids()
        db.save_user_state(query.from_user.id, States.ADMIN_BROADCAST_MESSAGE, {})
        await query.edit_message_text(
            f"📢 *Рассылка*\n\n"
            f"Получателей: *{len(user_ids)}* пользователей (без заблокированных)\n\n"
            f"Введите текст сообщения для рассылки.\n"
            f"Поддерживается Markdown форматирование.\n\n"
            f"Для отмены отправьте /cancel",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data='admin_broadcast_cancel')]
            ])
        )
    
    elif data == 'admin_broadcast_confirm':
        # Подтверждение рассылки
        from states import States
        state_info = db.get_user_state(query.from_user.id)
        if not state_info or state_info.get('state') != States.ADMIN_BROADCAST_MESSAGE:
            await query.answer("Сессия истекла. Начните заново.", show_alert=True)
            return
        broadcast_text = state_info.get('data', {}).get('broadcast_text', '')
        if not broadcast_text:
            await query.answer("Текст сообщения не найден.", show_alert=True)
            return
        await execute_broadcast(query, context, broadcast_text)
    
    elif data == 'admin_broadcast_cancel':
        db.clear_user_state(query.from_user.id)
        keyboard = [
            [InlineKeyboardButton("📊 Статистика бота", callback_data='admin_stats')],
            [InlineKeyboardButton("🚫 Заблокированные", callback_data='admin_blocked_users')],
            [InlineKeyboardButton("⚠️ Ограниченные", callback_data='admin_restricted_users')],
            [InlineKeyboardButton("🔑 Заявки на сброс пароля", callback_data='admin_password_resets')],
            [InlineKeyboardButton("📢 Сообщение всем", callback_data='admin_broadcast')],
            [InlineKeyboardButton("🗑️ Удалить всех пользователей", callback_data='admin_delete_all_users')],
            [InlineKeyboardButton("🔌 Выключить бота", callback_data='admin_shutdown')],
            [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
        ]
        admin_chat_id = db.get_admin_chat_id()
        admin_info = f"\n\n*Ваш chat_id:* `{query.from_user.id}`"
        if admin_chat_id:
            admin_info += f"\n*Сохраненный chat_id:* `{admin_chat_id}`"
        admin_info += f"\n*Username:* {ADMIN_USERNAME}"
        await query.edit_message_text(
            f"🔐 *Админ-панель*{admin_info}\n\nРассылка отменена.\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == 'admin_blocked_users':
        # Список заблокированных пользователей (с возможностью разблокировки каждого)
        blocked_users = db.get_blocked_users()
        
        if not blocked_users:
            text = "✅ Заблокированных пользователей нет."
        else:
            text = "🚫 *Заблокированные пользователи:*\n\n"
            for u in blocked_users[:20]:
                from datetime import datetime
                blocked_date = datetime.fromisoformat(u['blocked_at']).strftime('%d.%m.%Y %H:%M')
                text += f"• ID: {u['user_id']} — {blocked_date}\n"
            if len(blocked_users) > 20:
                text += f"\n... и ещё {len(blocked_users) - 20}"
        
        keyboard = []
        for u in blocked_users[:15]:
            keyboard.append([
                InlineKeyboardButton(
                    f"🔓 Разблокировать {u['user_id']}",
                    callback_data=f'admin_unblock_user_{u["user_id"]}'
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_back')])
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == 'admin_back':
        keyboard = [
            [InlineKeyboardButton("📊 Статистика бота", callback_data='admin_stats')],
            [InlineKeyboardButton("🚫 Заблокированные", callback_data='admin_blocked_users')],
            [InlineKeyboardButton("⚠️ Ограниченные", callback_data='admin_restricted_users')],
            [InlineKeyboardButton("🔑 Заявки на сброс пароля", callback_data='admin_password_resets')],
            [InlineKeyboardButton("📢 Сообщение всем", callback_data='admin_broadcast')],
            [InlineKeyboardButton("🗑️ Удалить всех пользователей", callback_data='admin_delete_all_users')],
            [InlineKeyboardButton("🔌 Выключить бота", callback_data='admin_shutdown')],
            [InlineKeyboardButton("🔙 В меню", callback_data='menu')]
        ]
        
        # Показываем chat_id админа для отладки
        admin_chat_id = db.get_admin_chat_id()
        admin_info = f"\n\n*Ваш chat_id:* `{query.from_user.id}`"
        if admin_chat_id:
            admin_info += f"\n*Сохраненный chat_id:* `{admin_chat_id}`"
        admin_info += f"\n*Username:* {ADMIN_USERNAME}"
        
        await query.edit_message_text(
            f"🔐 *Админ-панель*{admin_info}\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
