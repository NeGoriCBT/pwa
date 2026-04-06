"""
Модуль для отслеживания и сохранения message_id всех сообщений бота
"""
from database import Database

db = Database()

def save_message_id(user_id: int, message, chat_id: int = None):
    """
    Универсальная функция для сохранения message_id сообщения
    Работает как с сообщениями пользователя, так и с сообщениями бота
    """
    if not message:
        return
    
    message_id = None
    if hasattr(message, 'message_id'):
        message_id = message.message_id
    elif isinstance(message, int):
        message_id = message
    
    if not message_id:
        return
    
    if not chat_id:
        # Пытаемся получить chat_id из сообщения
        if hasattr(message, 'chat') and hasattr(message.chat, 'id'):
            chat_id = message.chat.id
        elif hasattr(message, 'effective_chat') and hasattr(message.effective_chat, 'id'):
            chat_id = message.effective_chat.id
    
    if not chat_id:
        return
    
    # Сохраняем message_id
    db.save_bot_message(user_id, message_id, chat_id)
