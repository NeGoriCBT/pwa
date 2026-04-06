"""
Модуль для автоматического бэкапа базы данных
"""
import os
import shutil
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

def _get_encryption_key():
    """Получает ключ шифрования для бэкапов"""
    try:
        from config import DB_ENCRYPTION_KEY
        return DB_ENCRYPTION_KEY or os.getenv('DB_ENCRYPTION_KEY')
    except:
        return os.getenv('DB_ENCRYPTION_KEY')

def _encrypt_backup(file_path: str, encryption_key: str) -> bool:
    """Шифрует файл бэкапа"""
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        import base64
        
        # Генерируем ключ из пароля (тот же алгоритм, что в database.py)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'cognitive_diary_salt',
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(encryption_key.encode()))
        fernet = Fernet(key)
        
        # Читаем файл
        with open(file_path, 'rb') as f:
            data = f.read()
        
        # Шифруем
        encrypted_data = fernet.encrypt(data)
        
        # Сохраняем зашифрованный файл
        encrypted_path = file_path + '.encrypted'
        with open(encrypted_path, 'wb') as f:
            f.write(encrypted_data)
        
        # Удаляем незашифрованный файл
        os.remove(file_path)
        
        # Переименовываем зашифрованный файл
        os.rename(encrypted_path, file_path)
        
        logger.info(f"🔐 Бэкап зашифрован: {file_path}")
        return True
    except ImportError:
        logger.warning("⚠️ cryptography не установлен, бэкап не зашифрован")
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка при шифровании бэкапа: {e}", exc_info=True)
        return False

def backup_database(db_path: str = 'cognitive_diary.db', backup_dir: str = 'backups'):
    """
    Создает резервную копию базы данных
    
    Args:
        db_path: Путь к файлу базы данных
        backup_dir: Директория для хранения бэкапов
    """
    try:
        # Создаем директорию для бэкапов, если её нет
        backup_path = Path(backup_dir)
        backup_path.mkdir(exist_ok=True)
        
        # Проверяем существование БД
        if not os.path.exists(db_path):
            logger.warning(f"База данных {db_path} не найдена, пропускаем бэкап")
            return None
        
        # Генерируем имя файла бэкапа с датой и временем
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'cognitive_diary_backup_{timestamp}.db'
        backup_filepath = backup_path / backup_filename
        
        # Копируем файл БД
        shutil.copy2(db_path, backup_filepath)
        
        # Шифруем бэкап, если есть ключ
        encryption_key = _get_encryption_key()
        if encryption_key:
            if _encrypt_backup(str(backup_filepath), encryption_key):
                logger.info(f"✅ Зашифрованный бэкап создан: {backup_filepath}")
            else:
                logger.warning(f"⚠️ Бэкап создан, но не зашифрован: {backup_filepath}")
        else:
            logger.warning(f"⚠️ Бэкап создан без шифрования (ключ не найден): {backup_filepath}")
            logger.info(f"✅ Бэкап создан: {backup_filepath}")
        
        # Удаляем старые бэкапы (оставляем последние 10)
        cleanup_old_backups(backup_path, keep_count=10)
        
        return str(backup_filepath)
    except Exception as e:
        logger.error(f"❌ Ошибка при создании бэкапа: {e}", exc_info=True)
        return None

def cleanup_old_backups(backup_dir: Path, keep_count: int = 10):
    """
    Удаляет старые бэкапы, оставляя только последние keep_count
    
    Args:
        backup_dir: Директория с бэкапами
        keep_count: Количество бэкапов для сохранения
    """
    try:
        # Получаем все файлы бэкапов
        backup_files = list(backup_dir.glob('cognitive_diary_backup_*.db'))
        
        # Сортируем по времени модификации (новые первыми)
        backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        # Удаляем старые бэкапы
        if len(backup_files) > keep_count:
            for old_backup in backup_files[keep_count:]:
                try:
                    old_backup.unlink()
                    logger.info(f"🗑️ Удален старый бэкап: {old_backup.name}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить старый бэкап {old_backup.name}: {e}")
    except Exception as e:
        logger.error(f"Ошибка при очистке старых бэкапов: {e}", exc_info=True)
