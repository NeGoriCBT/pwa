import sqlite3
import json
import os
import base64
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

# Попытка импортировать SQLCipher для шифрования БД
try:
    from pysqlcipher3 import dbapi2 as sqlite3_cipher
    SQLCIPHER_AVAILABLE = True
except ImportError:
    SQLCIPHER_AVAILABLE = False
    sqlite3_cipher = None

# Попытка импортировать cryptography для шифрования данных
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    Fernet = None

class Database:
    def __init__(self, db_name: str = 'cognitive_diary.db', encryption_key: str = None):
        import logging
        self.logger = logging.getLogger(__name__)
        
        self.db_name = db_name
        # Используем ключ из config или из переменной окружения
        from config import DB_ENCRYPTION_KEY as config_key
        self.encryption_key = encryption_key or config_key or os.getenv('DB_ENCRYPTION_KEY')
        
        # КРИТИЧЕСКАЯ ПРОВЕРКА: Если cryptography доступен, ключ ОБЯЗАТЕЛЕН
        if CRYPTOGRAPHY_AVAILABLE and not self.encryption_key:
            error_msg = (
                "🚨 КРИТИЧЕСКАЯ ОШИБКА БЕЗОПАСНОСТИ: "
                "cryptography установлен, но ключ шифрования (DB_ENCRYPTION_KEY) не задан!\n"
                "Данные будут сохраняться НЕЗАШИФРОВАННЫМИ.\n"
                "Добавьте DB_ENCRYPTION_KEY в файл .env и перезапустите бота."
            )
            self.logger.error(error_msg)
            raise ValueError(error_msg)
        
        # Определяем тип шифрования
        self.use_db_encryption = SQLCIPHER_AVAILABLE and self.encryption_key
        self.use_data_encryption = CRYPTOGRAPHY_AVAILABLE and self.encryption_key
        
        # Инициализируем Fernet для шифрования данных
        self.fernet = None
        if self.use_data_encryption:
            self._init_fernet()
        
        # Логирование
        if self.use_db_encryption:
            self.logger.info("🔐 Используется шифрование БД (SQLCipher)")
        elif self.use_data_encryption:
            self.logger.info("🔐 Используется шифрование данных (cryptography)")
            if not self.encryption_key or len(self.encryption_key) < 32:
                self.logger.warning("⚠️ Рекомендуется использовать ключ длиной минимум 32 символа")
        elif SQLCIPHER_AVAILABLE and not self.encryption_key:
            self.logger.warning("⚠️ SQLCipher установлен, но ключ шифрования не задан. БД не зашифрована.")
        elif not SQLCIPHER_AVAILABLE and not CRYPTOGRAPHY_AVAILABLE:
            self.logger.warning("⚠️ Шифрование не доступно. Для шифрования данных: pip install cryptography")
            self.logger.warning("   Для шифрования БД (требует C++ компилятор): pip install pysqlcipher3")
        
        self.init_db()
    
    def _init_fernet(self):
        """Инициализирует Fernet для шифрования данных"""
        if not CRYPTOGRAPHY_AVAILABLE or not self.encryption_key:
            return
        
        # Генерируем ключ из пароля используя PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'cognitive_diary_salt',  # Фиксированная соль
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self.encryption_key.encode()))
        self.fernet = Fernet(key)
    
    def _encrypt_data(self, data: str) -> str:
        """Шифрует строку данных"""
        if not self.fernet or not data:
            return data
        try:
            return self.fernet.encrypt(data.encode()).decode()
        except Exception:
            return data
    
    def _decrypt_data(self, encrypted_data: str) -> str:
        """Расшифровывает строку данных с проверкой целостности"""
        if not self.fernet or not encrypted_data:
            return encrypted_data
        try:
            decrypted = self.fernet.decrypt(encrypted_data.encode()).decode()
            return decrypted
        except Exception as e:
            # Проверка целостности: если не удалось расшифровать, данные повреждены
            self.logger.error(f"❌ Ошибка дешифрования данных: {type(e).__name__}: {e}")
            self.logger.error(f"   Возможно, данные повреждены или использован неправильный ключ")
            # Возвращаем оригинальные данные, чтобы не сломать работу бота
            # Но логируем ошибку для администратора
            return encrypted_data
    
    def _parse_json_field(self, field_value: Any) -> List[Dict]:
        """Парсит JSON поле с обработкой ошибок"""
        if not field_value:
            return []
        if isinstance(field_value, (list, dict)):
            return field_value if isinstance(field_value, list) else [field_value]
        if isinstance(field_value, str):
            try:
                parsed = json.loads(field_value)
                return parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                self.logger.warning(f"Не удалось распарсить JSON поле: {field_value}")
                return []
        return []
    
    def get_connection(self):
        """Получает соединение с БД (с шифрованием или без)"""
        if self.use_db_encryption:
            conn = sqlite3_cipher.connect(self.db_name)
            conn.execute(f"PRAGMA key='{self.encryption_key}'")
            return conn
        else:
            return sqlite3.connect(self.db_name)
    
    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                situation TEXT,
                emotions_before TEXT,
                automatic_thought TEXT,
                automatic_thought_confidence INTEGER,
                action TEXT,
                evidence_for TEXT,
                evidence_against TEXT,
                alternative_thoughts TEXT,
                emotions_after TEXT,
                note_to_future_self TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_states (
                user_id INTEGER PRIMARY KEY,
                state TEXT,
                current_data TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_consents (
                user_id INTEGER PRIMARY KEY,
                consent_given INTEGER NOT NULL DEFAULT 0,
                consent_date TEXT,
                consent_ip TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_passwords (
                user_id INTEGER PRIMARY KEY,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                password_enabled INTEGER DEFAULT 1
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_rate_limits (
                user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                PRIMARY KEY (user_id, action_type, timestamp)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS suspicious_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                activity_type TEXT NOT NULL,
                description TEXT,
                timestamp TEXT NOT NULL,
                notified INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS security_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_type TEXT NOT NULL,
                check_date TEXT NOT NULL,
                result TEXT,
                details TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_id INTEGER PRIMARY KEY,
                blocked_at TEXT NOT NULL,
                blocked_reason TEXT,
                activity_id INTEGER
            )
        ''')
        
        # Миграция: добавляем новые колонки, если их нет
        # Проверяем наличие колонок через PRAGMA table_info
        cursor.execute("PRAGMA table_info(blocked_users)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        if 'auto_blocked' not in existing_columns:
            try:
                cursor.execute('ALTER TABLE blocked_users ADD COLUMN auto_blocked INTEGER DEFAULT 0')
                self.logger.info("Добавлена колонка auto_blocked в таблицу blocked_users")
            except sqlite3.OperationalError as e:
                self.logger.warning(f"Не удалось добавить колонку auto_blocked: {e}")
        
        if 'unblock_at' not in existing_columns:
            try:
                cursor.execute('ALTER TABLE blocked_users ADD COLUMN unblock_at TEXT')
                self.logger.info("Добавлена колонка unblock_at в таблицу blocked_users")
            except sqlite3.OperationalError as e:
                self.logger.warning(f"Не удалось добавить колонку unblock_at: {e}")
        
        # Миграция: password_enabled в user_passwords
        cursor.execute("PRAGMA table_info(user_passwords)")
        pw_columns = [row[1] for row in cursor.fetchall()]
        if 'password_enabled' not in pw_columns:
            try:
                cursor.execute('ALTER TABLE user_passwords ADD COLUMN password_enabled INTEGER DEFAULT 1')
                cursor.execute('UPDATE user_passwords SET password_enabled = 1 WHERE password_enabled IS NULL')
                self.logger.info("Добавлена колонка password_enabled в таблицу user_passwords")
            except sqlite3.OperationalError as e:
                self.logger.warning(f"Не удалось добавить колонку password_enabled: {e}")
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_reputation (
                user_id INTEGER PRIMARY KEY,
                violation_score INTEGER DEFAULT 0,
                last_violation TEXT,
                auto_blocked INTEGER DEFAULT 0,
                restrictions_level INTEGER DEFAULT 0,
                last_score_reduction TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_messages (
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                PRIMARY KEY (user_id, message_id, chat_id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_reminders (
                user_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                reminder_time TEXT
            )
        ''')
        
        cursor.execute("PRAGMA table_info(user_reminders)")
        reminder_columns = [row[1] for row in cursor.fetchall()]
        if 'timezone' not in reminder_columns:
            try:
                cursor.execute(
                    "ALTER TABLE user_reminders ADD COLUMN timezone TEXT DEFAULT 'Europe/Moscow'"
                )
                self.logger.info("Добавлена колонка timezone в таблицу user_reminders")
            except sqlite3.OperationalError as e:
                self.logger.warning(f"Не удалось добавить колонку timezone в user_reminders: {e}")
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS confirmation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                confirmation_type TEXT NOT NULL,
                confirmed_at TEXT NOT NULL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS password_reset_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                requested_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                processed_at TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS exposures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                situation_name TEXT,
                event_datetime TEXT NOT NULL,
                expectations TEXT,
                reality TEXT,
                reminder_sent INTEGER DEFAULT 0,
                reality_received INTEGER DEFAULT 0
            )
        ''')
        
        # Миграция: добавляем новые колонки для нового процесса экспозиций
        cursor.execute("PRAGMA table_info(exposures)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        # Добавляем новые колонки, если их нет
        new_columns = {
            'event_duration': 'INTEGER',
            'expectations_data': 'TEXT',
            'emotions_before': 'TEXT',
            'emotions_after': 'TEXT',
            'comparison': 'TEXT'
        }
        
        for column_name, column_type in new_columns.items():
            if column_name not in existing_columns:
                try:
                    cursor.execute(f'ALTER TABLE exposures ADD COLUMN {column_name} {column_type}')
                    self.logger.info(f"Добавлена колонка {column_name} в таблицу exposures")
                except sqlite3.OperationalError as e:
                    self.logger.warning(f"Не удалось добавить колонку {column_name}: {e}")
        
        # Создаем индексы для оптимизации запросов
        try:
            # Индекс на user_id в таблице entries (для быстрого поиска записей пользователя)
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_entries_user_id 
                ON entries(user_id)
            ''')
            
            # Индекс на timestamp в таблице entries (для быстрого поиска по дате)
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_entries_timestamp 
                ON entries(timestamp)
            ''')
            
            # Композитный индекс для поиска записей пользователя по дате
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_entries_user_timestamp 
                ON entries(user_id, timestamp)
            ''')
            
            # Индекс на user_id в suspicious_activity (для быстрого поиска активности)
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_suspicious_user_id 
                ON suspicious_activity(user_id)
            ''')
            
            # Индекс на timestamp в suspicious_activity
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_suspicious_timestamp 
                ON suspicious_activity(timestamp)
            ''')
            
            # Индекс на user_id в user_rate_limits
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_rate_limits_user_id 
                ON user_rate_limits(user_id)
            ''')
            
            # Индекс на timestamp в user_rate_limits
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_rate_limits_timestamp 
                ON user_rate_limits(timestamp)
            ''')
            
            # Индекс на user_id в user_messages
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_user_id 
                ON user_messages(user_id)
            ''')
            
            # Индекс на user_id в user_reminders
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_reminders_user_id 
                ON user_reminders(user_id)
            ''')
            
            # Индекс на enabled в user_reminders (для быстрого поиска пользователей с включенными напоминаниями)
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_reminders_enabled 
                ON user_reminders(enabled)
            ''')
            
            # Композитный индекс для поиска пользователей с включенными напоминаниями
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_reminders_enabled_user 
                ON user_reminders(enabled, user_id)
            ''')
            
            # Индекс на user_id в user_consents
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_consents_user_id 
                ON user_consents(user_id)
            ''')
            
            # Индекс на user_id в blocked_users
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_blocked_user_id 
                ON blocked_users(user_id)
            ''')
            
            # Индексы для exposures
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_exposures_user_id 
                ON exposures(user_id)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_exposures_event_datetime 
                ON exposures(event_datetime)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_exposures_user_datetime 
                ON exposures(user_id, event_datetime)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_exposures_reminder_sent 
                ON exposures(reminder_sent, event_datetime)
            ''')
            
            self.logger.info("✅ Индексы БД созданы успешно")
        except sqlite3.OperationalError as e:
            self.logger.warning(f"Не удалось создать некоторые индексы: {e}")
        
        conn.commit()
        conn.close()
    
    def save_entry(self, user_id: int, entry_data: Dict[str, Any]) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Шифруем чувствительные поля, если включено шифрование
        def encrypt_field(value):
            if value and self.use_data_encryption:
                return self._encrypt_data(str(value))
            return value
        
        cursor.execute('''
            INSERT INTO entries (
                user_id, timestamp, situation, emotions_before,
                automatic_thought, automatic_thought_confidence, action,
                evidence_for, evidence_against, alternative_thoughts,
                emotions_after, note_to_future_self
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            datetime.now().isoformat(),
            encrypt_field(entry_data.get('situation')),
            json.dumps(entry_data.get('emotions_before', []), ensure_ascii=False),  # JSON не шифруем отдельно
            encrypt_field(entry_data.get('automatic_thought')),
            entry_data.get('automatic_thought_confidence'),
            encrypt_field(entry_data.get('action')),
            encrypt_field(entry_data.get('evidence_for')),
            encrypt_field(entry_data.get('evidence_against')),
            json.dumps(entry_data.get('alternative_thoughts', []), ensure_ascii=False),
            json.dumps(entry_data.get('emotions_after', []), ensure_ascii=False),
            encrypt_field(entry_data.get('note_to_future_self'))
        ))
        
        entry_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return entry_id
    
    def get_user_entries(self, user_id: int, start_date: Optional[str] = None, 
                        end_date: Optional[str] = None) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = 'SELECT * FROM entries WHERE user_id = ?'
        params = [user_id]
        
        if start_date:
            query += ' AND timestamp >= ?'
            params.append(start_date)
        if end_date:
            query += ' AND timestamp <= ?'
            params.append(end_date)
        
        query += ' ORDER BY timestamp DESC'
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        # Расшифровываем поля, если они зашифрованы
        def decrypt_field(value):
            if value and self.use_data_encryption:
                return self._decrypt_data(str(value))
            return value
        
        entries = []
        for row in rows:
            entries.append({
                'id': row[0],
                'user_id': row[1],
                'timestamp': row[2],
                'situation': decrypt_field(row[3]),
                'emotions_before': self._parse_json_field(row[4]),
                'automatic_thought': decrypt_field(row[5]),
                'automatic_thought_confidence': row[6],
                'action': decrypt_field(row[7]),
                'evidence_for': decrypt_field(row[8]),
                'evidence_against': decrypt_field(row[9]),
                'alternative_thoughts': self._parse_json_field(row[10]),
                'emotions_after': self._parse_json_field(row[11]),
                'note_to_future_self': decrypt_field(row[12])
            })
        
        conn.close()
        return entries
    
    def delete_entries(self, user_id: int, start_date: Optional[str] = None,
                      end_date: Optional[str] = None) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = 'DELETE FROM entries WHERE user_id = ?'
        params = [user_id]
        
        if start_date:
            query += ' AND timestamp >= ?'
            params.append(start_date)
        if end_date:
            query += ' AND timestamp <= ?'
            params.append(end_date)
        
        cursor.execute(query, params)
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted_count
    
    def save_user_state(self, user_id: int, state: str, data: Dict):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        data_json = json.dumps(data, ensure_ascii=False)
        # Шифруем данные состояния, если включено шифрование
        if self.use_data_encryption:
            data_json = self._encrypt_data(data_json)
        
        cursor.execute('''
            INSERT OR REPLACE INTO user_states (user_id, state, current_data)
            VALUES (?, ?, ?)
        ''', (user_id, state, data_json))
        
        conn.commit()
        conn.close()
    
    def get_user_state(self, user_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT state, current_data FROM user_states WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            # Расшифровываем данные состояния, если они зашифрованы
            data_json = row[1]
            if data_json and self.use_data_encryption:
                data_json = self._decrypt_data(data_json)
            
            return {
                'state': row[0],
                'data': json.loads(data_json) if data_json else {}
            }
        return None
    
    def clear_user_state(self, user_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM user_states WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    
    def check_user_consent(self, user_id: int) -> bool:
        """Проверяет, дал ли пользователь согласие на обработку данных"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT consent_given FROM user_consents WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        return row is not None and row[0] == 1
    
    def save_user_consent(self, user_id: int, consent_given: bool, ip_address: Optional[str] = None):
        """Сохраняет согласие пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO user_consents (user_id, consent_given, consent_date, consent_ip)
            VALUES (?, ?, ?, ?)
        ''', (user_id, 1 if consent_given else 0, datetime.now().isoformat(), ip_address))
        
        conn.commit()
        conn.close()

    def has_user_confirmed_age(self, user_id: int) -> bool:
        """Проверяет, подтвердил ли пользователь возраст"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM confirmation_logs WHERE user_id = ? AND confirmation_type = ?',
            (user_id, 'age')
        )
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def has_user_confirmed_sensitive_entry(self, user_id: int) -> bool:
        """Проверяет, подтвердил ли пользователь внесение чувствительных данных (первая запись)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM confirmation_logs WHERE user_id = ? AND confirmation_type = ?',
            (user_id, 'sensitive_entry')
        )
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def save_confirmation_log(self, user_id: int, confirmation_type: str):
        """Сохраняет лог подтверждения (age или sensitive_entry)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO confirmation_logs (user_id, confirmation_type, confirmed_at)
            VALUES (?, ?, ?)
        ''', (user_id, confirmation_type, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        self.logger.info(f"Confirmation log: user_id={user_id}, type={confirmation_type}")

    def get_confirmation_logs(self, user_id: Optional[int] = None) -> List[Dict]:
        """
        Возвращает логи подтверждений (возраст, первая чувствительная запись) для экспорта.
        При необходимости можно предоставить в суд или по запросу уполномоченных органов.
        user_id: если задан — только записи этого пользователя; иначе — все.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        if user_id is not None:
            cursor.execute('''
                SELECT id, user_id, confirmation_type, confirmed_at
                FROM confirmation_logs WHERE user_id = ?
                ORDER BY confirmed_at DESC
            ''', (user_id,))
        else:
            cursor.execute('''
                SELECT id, user_id, confirmation_type, confirmed_at
                FROM confirmation_logs
                ORDER BY confirmed_at DESC
            ''')
        rows = cursor.fetchall()
        conn.close()
        return [
            {'id': r[0], 'user_id': r[1], 'confirmation_type': r[2], 'confirmed_at': r[3]}
            for r in rows
        ]

    def has_user_password(self, user_id: int) -> bool:
        """Проверяет, установлен ли пароль у пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM user_passwords WHERE user_id = ?', (user_id,))
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def is_password_verification_enabled(self, user_id: int) -> bool:
        """Проверяет, включена ли проверка пароля (пароль есть и не отключён)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT password_enabled FROM user_passwords WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        return row is not None and (row[0] is None or row[0] != 0)

    def set_password_verification_enabled(self, user_id: int, enabled: bool):
        """Включает или отключает проверку пароля"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE user_passwords SET password_enabled = ? WHERE user_id = ?',
            (1 if enabled else 0, user_id)
        )
        conn.commit()
        conn.close()

    def save_user_password_hash(self, user_id: int, password_hash: str):
        """Сохраняет хеш пароля пользователя (хеш должен быть создан снаружи)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO user_passwords (user_id, password_hash, created_at, password_enabled)
            VALUES (?, ?, ?, 1)
        ''', (user_id, password_hash, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def get_user_password_hash(self, user_id: int) -> Optional[str]:
        """Получает хеш пароля пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT password_hash FROM user_passwords WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def check_user_password(self, user_id: int, password: str) -> bool:
        """Проверяет пароль пользователя"""
        import hashlib
        stored_hash = self.get_user_password_hash(user_id)
        if not stored_hash:
            return False
        salt = str(user_id).encode()
        new_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000).hex()
        return new_hash == stored_hash

    def delete_user_password(self, user_id: int):
        """Удаляет пароль пользователя (для сброса)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_passwords WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

    def create_password_reset_request(self, user_id: int) -> Optional[int]:
        """Создаёт заявку на сброс пароля. Возвращает id заявки или None при ошибке."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO password_reset_requests (user_id, requested_at, status)
                VALUES (?, ?, 'pending')
            ''', (user_id, datetime.now().isoformat()))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            self.logger.warning(f"Ошибка создания заявки на сброс пароля: {e}")
            return None
        finally:
            conn.close()

    def get_pending_password_reset_requests(self) -> List[Dict]:
        """Возвращает список заявок на сброс пароля со статусом pending"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, user_id, requested_at FROM password_reset_requests
            WHERE status = 'pending'
            ORDER BY requested_at ASC
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [{'id': r[0], 'user_id': r[1], 'requested_at': r[2]} for r in rows]

    def get_password_reset_request_by_id(self, req_id: int) -> Optional[Dict]:
        """Возвращает заявку по id"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, user_id, requested_at, status FROM password_reset_requests
            WHERE id = ?
        ''', (req_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {'id': row[0], 'user_id': row[1], 'requested_at': row[2], 'status': row[3]}

    def has_user_pending_reset_request(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя активная заявка на сброс"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 1 FROM password_reset_requests WHERE user_id = ? AND status = 'pending'
        ''', (user_id,))
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def approve_password_reset_request(self, req_id: int) -> Optional[int]:
        """Одобряет заявку: удаляет пароль, обновляет статус. Возвращает user_id или None."""
        req = self.get_password_reset_request_by_id(req_id)
        if not req or req['status'] != 'pending':
            return None
        user_id = req['user_id']
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_passwords WHERE user_id = ?', (user_id,))
        cursor.execute('''
            UPDATE password_reset_requests SET status = 'approved', processed_at = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), req_id))
        conn.commit()
        conn.close()
        return user_id

    def reject_password_reset_request(self, req_id: int) -> Optional[int]:
        """Отклоняет заявку. Возвращает user_id или None."""
        req = self.get_password_reset_request_by_id(req_id)
        if not req or req['status'] != 'pending':
            return None
        user_id = req['user_id']
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE password_reset_requests SET status = 'rejected', processed_at = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), req_id))
        conn.commit()
        conn.close()
        return user_id
    
    def delete_user_data(self, user_id: int):
        """Удаляет все данные пользователя (GDPR/152-ФЗ compliance)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM entries WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM exposures WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM user_states WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM user_consents WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM user_passwords WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM password_reset_requests WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM user_rate_limits WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM confirmation_logs WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM user_reminders WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM user_messages WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM suspicious_activity WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM user_reputation WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM blocked_users WHERE user_id = ?', (user_id,))
        
        conn.commit()
        conn.close()

    def delete_all_users(self) -> int:
        """Удаляет всех пользователей и все их данные. Возвращает количество очищенных таблиц."""
        conn = self.get_connection()
        cursor = conn.cursor()
        tables = [
            'entries', 'user_states', 'user_consents', 'user_passwords',
            'password_reset_requests', 'user_rate_limits', 'suspicious_activity',
            'user_messages', 'user_reputation', 'blocked_users', 'user_reminders',
            'exposures', 'confirmation_logs'
        ]
        for table in tables:
            try:
                cursor.execute(f'DELETE FROM {table}')
            except Exception as e:
                self.logger.warning(f"Не удалось очистить {table}: {e}")
        conn.commit()
        conn.close()
        self.logger.info("Все пользователи и их данные удалены")
        return len(tables)
    
    def log_rate_limit(self, user_id: int, action_type: str):
        """Логирует действие для rate limiting"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO user_rate_limits (user_id, action_type, timestamp)
            VALUES (?, ?, ?)
        ''', (user_id, action_type, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def check_rate_limit(self, user_id: int, action_type: str, max_actions: int, time_window_seconds: int) -> bool:
        """Проверяет, не превышен ли лимит действий"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cutoff_time = (datetime.now() - timedelta(seconds=time_window_seconds)).isoformat()
        
        cursor.execute('''
            SELECT COUNT(*) FROM user_rate_limits
            WHERE user_id = ? AND action_type = ? AND timestamp > ?
        ''', (user_id, action_type, cutoff_time))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count < max_actions
    
    def cleanup_old_rate_limits(self, days: int = 1):
        """Очищает старые записи rate limiting"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cutoff_time = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute('DELETE FROM user_rate_limits WHERE timestamp < ?', (cutoff_time,))
        
        conn.commit()
        conn.close()
    
    def update_entry_field(self, entry_id: int, field: str, value: str):
        """
        Обновляет конкретное поле записи
        Автоматически шифрует значение, если включено шифрование
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Шифруем значение, если это чувствительное поле
        encrypted_value = value
        sensitive_fields = ['situation', 'automatic_thought', 'action', 
                          'evidence_for', 'evidence_against', 'note_to_future_self']
        
        if field in sensitive_fields and self.use_data_encryption:
            encrypted_value = self._encrypt_data(str(value))
        
        # Обновляем поле
        cursor.execute(f'UPDATE entries SET {field} = ? WHERE id = ?', 
                      (encrypted_value, entry_id))
        
        conn.commit()
        conn.close()
        
        self.logger.info(f"Обновлено поле {field} записи {entry_id}")
        return cursor.rowcount > 0

    def cleanup_old_messages(self, hours: int = 48):
        """
        Очищает старые сообщения из таблицы user_messages
        Telegram API позволяет удалять сообщения только до 48 часов
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cutoff_time = (datetime.now() - timedelta(hours=hours)).isoformat()
        cursor.execute('DELETE FROM user_messages WHERE timestamp < ?', (cutoff_time,))
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted_count > 0:
            self.logger.info(f"🧹 Очищено {deleted_count} старых сообщений (старше {hours} часов)")
        
        return deleted_count
    
    def log_suspicious_activity(self, user_id: int, activity_type: str, description: str):
        """Логирует подозрительную активность"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO suspicious_activity (user_id, activity_type, description, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (user_id, activity_type, description, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def get_unnotified_suspicious_activities(self) -> List[Dict]:
        """Получает непроинформированные подозрительные активности"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, user_id, activity_type, description, timestamp
            FROM suspicious_activity
            WHERE notified = 0
            ORDER BY timestamp DESC
            LIMIT 50
        ''')
        
        rows = cursor.fetchall()
        activities = []
        for row in rows:
            activities.append({
                'id': row[0],
                'user_id': row[1],
                'activity_type': row[2],
                'description': row[3],
                'timestamp': row[4]
            })
        
        conn.close()
        return activities
    
    def mark_activity_notified(self, activity_id: int):
        """Отмечает активность как проинформированную"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('UPDATE suspicious_activity SET notified = 1 WHERE id = ?', (activity_id,))
        
        conn.commit()
        conn.close()
    
    def save_security_check(self, check_type: str, result: str, details: str = None):
        """Сохраняет результат проверки безопасности"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO security_checks (check_type, check_date, result, details)
            VALUES (?, ?, ?, ?)
        ''', (check_type, datetime.now().isoformat(), result, details))
        
        conn.commit()
        conn.close()
    
    def get_user_stats(self, user_id: int) -> Dict:
        """Получает статистику пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Количество записей
        cursor.execute('SELECT COUNT(*) FROM entries WHERE user_id = ?', (user_id,))
        entries_count = cursor.fetchone()[0]
        
        # Последняя активность
        cursor.execute('SELECT MAX(timestamp) FROM entries WHERE user_id = ?', (user_id,))
        last_activity = cursor.fetchone()[0]
        
        # Количество подозрительных активностей
        cursor.execute('SELECT COUNT(*) FROM suspicious_activity WHERE user_id = ?', (user_id,))
        suspicious_count = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'entries_count': entries_count,
            'last_activity': last_activity,
            'suspicious_count': suspicious_count
        }
    
    def get_all_user_ids(self) -> List[tuple]:
        """Получает все ID пользователей"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT DISTINCT user_id FROM entries')
        user_ids = cursor.fetchall()
        
        conn.close()
        return user_ids

    def get_all_broadcast_user_ids(self) -> List[int]:
        """
        Получает все ID пользователей для рассылки.
        Объединяет user_states, entries, exposures, user_reminders.
        Исключает заблокированных пользователей.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT user_id FROM (
                SELECT user_id FROM user_states
                UNION SELECT user_id FROM entries
                UNION SELECT user_id FROM user_reminders
                UNION SELECT user_id FROM user_consents
                UNION SELECT user_id FROM exposures
            )
            WHERE user_id NOT IN (SELECT user_id FROM blocked_users)
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]
    
    def get_total_entries_count(self) -> int:
        """Получает общее количество записей"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM entries')
        count = cursor.fetchone()[0]
        
        conn.close()
        return count
    
    def get_total_suspicious_count(self) -> int:
        """Получает общее количество подозрительных активностей"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM suspicious_activity')
        count = cursor.fetchone()[0]
        
        conn.close()
        return count

    def get_admin_stats(self) -> Dict:
        """
        Получает полную статистику для админ-панели.
        Возвращает: total_users, new_users_week, new_users_month, total_entries,
        new_entries_thoughts_week, new_entries_thoughts_month, new_entries_exposures_week,
        new_entries_exposures_month, suspicious_today, suspicious_week, suspicious_month,
        blocked_count, restricted_count
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        week_ago = (now - timedelta(days=7)).isoformat()
        month_ago = (now - timedelta(days=30)).isoformat()

        # Всего пользователей (из всех источников)
        cursor.execute('''
            SELECT COUNT(DISTINCT user_id) FROM (
                SELECT user_id FROM user_states
                UNION SELECT user_id FROM entries
                UNION SELECT user_id FROM user_reminders
                UNION SELECT user_id FROM user_consents
                UNION SELECT user_id FROM exposures
            )
        ''')
        total_users = cursor.fetchone()[0]

        # Новые пользователи: первые активности (entries, exposures, consent) за период
        cursor.execute('''
            SELECT COUNT(*) FROM (
                SELECT user_id, MIN(first_seen) as first_seen FROM (
                    SELECT user_id, timestamp as first_seen FROM entries
                    UNION ALL
                    SELECT user_id, created_at as first_seen FROM exposures
                    UNION ALL
                    SELECT user_id, consent_date as first_seen FROM user_consents WHERE consent_date IS NOT NULL
                ) GROUP BY user_id
            ) WHERE first_seen >= ?
        ''', (week_ago,))
        new_users_week = cursor.fetchone()[0]

        cursor.execute('''
            SELECT COUNT(*) FROM (
                SELECT user_id, MIN(first_seen) as first_seen FROM (
                    SELECT user_id, timestamp as first_seen FROM entries
                    UNION ALL
                    SELECT user_id, created_at as first_seen FROM exposures
                    UNION ALL
                    SELECT user_id, consent_date as first_seen FROM user_consents WHERE consent_date IS NOT NULL
                ) GROUP BY user_id
            ) WHERE first_seen >= ?
        ''', (month_ago,))
        new_users_month = cursor.fetchone()[0]

        # Всего записей
        cursor.execute('SELECT COUNT(*) FROM entries')
        total_entries = cursor.fetchone()[0]

        # Новые записи дневника мыслей
        cursor.execute('SELECT COUNT(*) FROM entries WHERE timestamp >= ?', (week_ago,))
        new_entries_thoughts_week = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM entries WHERE timestamp >= ?', (month_ago,))
        new_entries_thoughts_month = cursor.fetchone()[0]

        # Новые записи дневника экспозиций
        cursor.execute('SELECT COUNT(*) FROM exposures WHERE created_at >= ?', (week_ago,))
        new_entries_exposures_week = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM exposures WHERE created_at >= ?', (month_ago,))
        new_entries_exposures_month = cursor.fetchone()[0]

        # Подозрительная активность по периодам
        cursor.execute('SELECT COUNT(*) FROM suspicious_activity WHERE timestamp >= ?', (today_start,))
        suspicious_today = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM suspicious_activity WHERE timestamp >= ?', (week_ago,))
        suspicious_week = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM suspicious_activity WHERE timestamp >= ?', (month_ago,))
        suspicious_month = cursor.fetchone()[0]

        # Заблокированные
        cursor.execute('SELECT COUNT(*) FROM blocked_users')
        blocked_count = cursor.fetchone()[0]

        # Ограниченные (violation_score > 0 или restrictions_level > 0, не заблокированы)
        cursor.execute('''
            SELECT COUNT(*) FROM user_reputation ur
            WHERE (ur.violation_score > 0 OR ur.restrictions_level > 0)
            AND ur.user_id NOT IN (SELECT user_id FROM blocked_users)
        ''')
        restricted_count = cursor.fetchone()[0]

        conn.close()
        return {
            'total_users': total_users,
            'new_users_week': new_users_week,
            'new_users_month': new_users_month,
            'total_entries': total_entries,
            'new_entries_thoughts_week': new_entries_thoughts_week,
            'new_entries_thoughts_month': new_entries_thoughts_month,
            'new_entries_exposures_week': new_entries_exposures_week,
            'new_entries_exposures_month': new_entries_exposures_month,
            'suspicious_today': suspicious_today,
            'suspicious_week': suspicious_week,
            'suspicious_month': suspicious_month,
            'blocked_count': blocked_count,
            'restricted_count': restricted_count,
        }

    def get_restricted_users(self) -> List[Dict]:
        """Получает ограниченных пользователей (violation_score > 0 или restrictions_level > 0, не заблокированы)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT ur.user_id, ur.violation_score, ur.restrictions_level, ur.last_violation
            FROM user_reputation ur
            WHERE (ur.violation_score > 0 OR ur.restrictions_level > 0)
            AND ur.user_id NOT IN (SELECT user_id FROM blocked_users)
            ORDER BY ur.violation_score DESC, ur.restrictions_level DESC
        ''')
        rows = cursor.fetchall()
        users = []
        for row in rows:
            users.append({
                'user_id': row[0],
                'violation_score': row[1],
                'restrictions_level': row[2],
                'last_violation': row[3],
            })
        conn.close()
        return users
    
    def get_recent_suspicious_activities(self, limit: int = 10) -> List[Dict]:
        """Получает последние подозрительные активности"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, user_id, activity_type, description, timestamp
            FROM suspicious_activity
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        activities = []
        for row in rows:
            activities.append({
                'id': row[0],
                'user_id': row[1],
                'activity_type': row[2],
                'description': row[3],
                'timestamp': row[4]
            })
        
        conn.close()
        return activities
    
    def get_user_suspicious_activities(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Получает подозрительные активности конкретного пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, user_id, activity_type, description, timestamp
            FROM suspicious_activity
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (user_id, limit))
        
        rows = cursor.fetchall()
        activities = []
        for row in rows:
            activities.append({
                'id': row[0],
                'user_id': row[1],
                'activity_type': row[2],
                'description': row[3],
                'timestamp': row[4]
            })
        
        conn.close()
        return activities
    
    def get_recent_security_checks(self, limit: int = 10) -> List[Dict]:
        """Получает последние проверки безопасности"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT check_type, check_date, result, details
            FROM security_checks
            ORDER BY check_date DESC
            LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        checks = []
        for row in rows:
            checks.append({
                'check_type': row[0],
                'check_date': row[1],
                'result': row[2],
                'details': row[3]
            })
        
        conn.close()
        return checks
    
    def save_admin_chat_id(self, chat_id: int) -> None:
        """Сохраняет chat_id админа (с очисткой кэша)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO admin_settings (key, value)
            VALUES (?, ?)
        ''', ('admin_chat_id', str(chat_id)))
        
        conn.commit()
        conn.close()
        
        # Очищаем кэш при сохранении
        try:
            from cache import clear_cache
            clear_cache('admin_chat_id')
        except ImportError:
            pass
    
    def get_admin_chat_id(self) -> Optional[int]:
        """Получает сохраненный chat_id админа (с кэшированием)"""
        # Пытаемся получить из кэша
        try:
            from cache import get_cached, set_cached
            cached_id = get_cached('admin_chat_id', ttl=3600)  # Кэш на 1 час
            if cached_id is not None:
                return cached_id
        except ImportError:
            pass
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('admin_chat_id',))
        row = cursor.fetchone()
        conn.close()
        
        result = None
        if row:
            try:
                result = int(row[0])
            except (ValueError, TypeError):
                result = None
        
        # Сохраняем в кэш
        if result is not None:
            try:
                from cache import set_cached
                set_cached('admin_chat_id', result, ttl=3600)
            except ImportError:
                pass
        
        return result
    
    def block_user(self, user_id: int, reason: str = None, activity_id: int = None):
        """Блокирует пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO blocked_users (user_id, blocked_at, blocked_reason, activity_id)
            VALUES (?, ?, ?, ?)
        ''', (user_id, datetime.now().isoformat(), reason, activity_id))
        
        conn.commit()
        conn.close()
    
    def unblock_user(self, user_id: int):
        """Разблокирует пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM blocked_users WHERE user_id = ?', (user_id,))
        
        conn.commit()
        conn.close()
    
    def is_user_blocked(self, user_id: int) -> bool:
        """Проверяет, заблокирован ли пользователь"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT user_id FROM blocked_users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        return row is not None
    
    def get_blocked_users(self) -> List[Dict]:
        """Получает список заблокированных пользователей"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Проверяем наличие колонок
        cursor.execute("PRAGMA table_info(blocked_users)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        # Формируем список колонок для SELECT
        base_columns = ['user_id', 'blocked_at', 'blocked_reason', 'activity_id']
        select_columns = base_columns.copy()
        
        if 'auto_blocked' in existing_columns:
            select_columns.append('auto_blocked')
        else:
            select_columns.append('NULL as auto_blocked')
        
        if 'unblock_at' in existing_columns:
            select_columns.append('unblock_at')
        else:
            select_columns.append('NULL as unblock_at')
        
        query = f'''
            SELECT {', '.join(select_columns)}
            FROM blocked_users
            ORDER BY blocked_at DESC
        '''
        
        cursor.execute(query)
        rows = cursor.fetchall()
        users = []
        for row in rows:
            user_dict = {
                'user_id': row[0],
                'blocked_at': row[1],
                'blocked_reason': row[2],
                'activity_id': row[3]
            }
            
            # Добавляем опциональные поля
            if len(row) > 4:
                user_dict['auto_blocked'] = row[4] if row[4] is not None else 0
            else:
                user_dict['auto_blocked'] = 0
            
            if len(row) > 5:
                user_dict['unblock_at'] = row[5]
            else:
                user_dict['unblock_at'] = None
            
            users.append(user_dict)
        
        conn.close()
        return users
    
    def get_user_reputation(self, user_id: int) -> Dict:
        """Получает репутацию пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT violation_score, last_violation, auto_blocked, restrictions_level, last_score_reduction
            FROM user_reputation
            WHERE user_id = ?
        ''', (user_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'violation_score': row[0],
                'last_violation': row[1],
                'auto_blocked': row[2],
                'restrictions_level': row[3],
                'last_score_reduction': row[4]
            }
        return {
            'violation_score': 0,
            'last_violation': None,
            'auto_blocked': 0,
            'restrictions_level': 0,
            'last_score_reduction': None
        }
    
    def update_user_reputation(self, user_id: int, score_delta: int, violation_type: str = None):
        """Обновляет репутацию пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Получаем текущую репутацию
        current = self.get_user_reputation(user_id)
        new_score = max(0, current['violation_score'] + score_delta)
        
        cursor.execute('''
            INSERT OR REPLACE INTO user_reputation 
            (user_id, violation_score, last_violation, last_score_reduction)
            VALUES (?, ?, ?, ?)
        ''', (
            user_id,
            new_score,
            datetime.now().isoformat() if violation_type else current['last_violation'],
            current['last_score_reduction']
        ))
        
        conn.commit()
        conn.close()
        return new_score
    
    def set_user_restrictions_level(self, user_id: int, level: int):
        """Устанавливает уровень ограничений для пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO user_reputation 
            (user_id, violation_score, restrictions_level)
            VALUES (?, COALESCE((SELECT violation_score FROM user_reputation WHERE user_id = ?), 0), ?)
        ''', (user_id, user_id, level))
        
        conn.commit()
        conn.close()
    
    def auto_block_user(self, user_id: int, reason: str, duration_hours: int = None):
        """Автоматически блокирует пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        unblock_at = None
        if duration_hours:
            unblock_at = (datetime.now() + timedelta(hours=duration_hours)).isoformat()
        
        cursor.execute('''
            INSERT OR REPLACE INTO blocked_users 
            (user_id, blocked_at, blocked_reason, auto_blocked, unblock_at)
            VALUES (?, ?, ?, 1, ?)
        ''', (user_id, datetime.now().isoformat(), reason, unblock_at))
        
        # Обновляем репутацию
        cursor.execute('''
            UPDATE user_reputation SET auto_blocked = 1 WHERE user_id = ?
        ''', (user_id,))
        
        conn.commit()
        conn.close()
    
    def reduce_reputation_scores(self, reduction_amount: int = 5):
        """Уменьшает баллы репутации для всех пользователей (ежедневная амнистия)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        today = datetime.now().date().isoformat()
        
        cursor.execute('''
            UPDATE user_reputation
            SET violation_score = MAX(0, violation_score - ?),
                last_score_reduction = ?
            WHERE violation_score > 0
            AND (last_score_reduction IS NULL OR last_score_reduction < ?)
        ''', (reduction_amount, today, today))
        
        conn.commit()
        conn.close()
    
    def auto_unblock_expired_users(self):
        """Автоматически разблокирует пользователей с истекшим временем блокировки"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Проверяем наличие колонок
        cursor.execute("PRAGMA table_info(blocked_users)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        now = datetime.now().isoformat()
        
        # Формируем запрос в зависимости от наличия колонок
        if 'auto_blocked' in existing_columns and 'unblock_at' in existing_columns:
            # Полная версия с проверкой auto_blocked и unblock_at
            cursor.execute('''
                SELECT user_id FROM blocked_users
                WHERE auto_blocked = 1
                AND unblock_at IS NOT NULL
                AND unblock_at <= ?
            ''', (now,))
        elif 'unblock_at' in existing_columns:
            # Только проверка unblock_at (если auto_blocked нет)
            cursor.execute('''
                SELECT user_id FROM blocked_users
                WHERE unblock_at IS NOT NULL
                AND unblock_at <= ?
            ''', (now,))
        else:
            # Если нет колонок для временной блокировки, ничего не делаем
            conn.close()
            return 0
        
        users_to_unblock = [row[0] for row in cursor.fetchall()]
        
        if users_to_unblock:
            placeholders = ','.join('?' * len(users_to_unblock))
            cursor.execute(f'''
                DELETE FROM blocked_users
                WHERE user_id IN ({placeholders})
            ''', users_to_unblock)
            
            # Обновляем репутацию (если таблица существует)
            try:
                cursor.execute(f'''
                    UPDATE user_reputation
                    SET auto_blocked = 0
                    WHERE user_id IN ({placeholders})
                ''', users_to_unblock + users_to_unblock)
            except sqlite3.OperationalError:
                # Если колонка auto_blocked не существует в user_reputation, пропускаем
                pass
            
            conn.commit()
        
        conn.close()
        return len(users_to_unblock)
    
    def get_recent_violations_count(self, user_id: int, minutes: int = 10) -> int:
        """Подсчитывает количество нарушений за последние N минут"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        since = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        
        cursor.execute('''
            SELECT COUNT(*) FROM suspicious_activity
            WHERE user_id = ? AND timestamp >= ?
        ''', (user_id, since))
        
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def save_user_message(self, user_id: int, message_id: int, chat_id: int):
        """Сохраняет ID сообщения пользователя для возможного удаления"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO user_messages (user_id, message_id, chat_id, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (user_id, message_id, chat_id, datetime.now().isoformat()))
            conn.commit()
        except Exception as e:
            self.logger.warning(f"Не удалось сохранить message_id: {e}")
        finally:
            conn.close()
    
    def save_bot_message(self, user_id: int, message_id: int, chat_id: int):
        """Сохраняет ID сообщения бота для возможного удаления"""
        # Используем ту же таблицу, но с отрицательным user_id для сообщений бота
        # Или можно использовать отдельное поле, но проще использовать ту же таблицу
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO user_messages (user_id, message_id, chat_id, timestamp)
                VALUES (?, ?, ?, ?)
            ''', (user_id, message_id, chat_id, datetime.now().isoformat()))
            conn.commit()
        except Exception as e:
            self.logger.warning(f"Не удалось сохранить message_id бота: {e}")
        finally:
            conn.close()
    
    def get_user_messages(self, user_id: int) -> List[Dict]:
        """Получает список всех сообщений пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT message_id, chat_id, timestamp
            FROM user_messages
            WHERE user_id = ?
            ORDER BY timestamp DESC
        ''', (user_id,))
        
        rows = cursor.fetchall()
        messages = []
        for row in rows:
            messages.append({
                'message_id': row[0],
                'chat_id': row[1],
                'timestamp': row[2]
            })
        
        conn.close()
        return messages
    
    def delete_user_messages(self, user_id: int):
        """Удаляет записи о сообщениях пользователя из БД"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM user_messages WHERE user_id = ?', (user_id,))
        
        conn.commit()
        conn.close()
    
    def get_user_reminder_settings(self, user_id: int) -> Dict:
        """Получает настройки напоминаний пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Создаем таблицу, если её нет
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_reminders (
                user_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                reminder_time TEXT DEFAULT '20:00',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute(
            'SELECT enabled, reminder_time, timezone FROM user_reminders WHERE user_id = ?',
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            tz = row[2] if row[2] else 'Europe/Moscow'
            return {'enabled': bool(row[0]), 'time': row[1], 'timezone': tz}
        return {'enabled': False, 'time': '20:00', 'timezone': 'Europe/Moscow'}
    
    def set_user_reminder_settings(
        self,
        user_id: int,
        enabled: bool = None,
        reminder_time: str = None,
        timezone: str = None,
    ):
        """Устанавливает настройки напоминаний пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Создаем таблицу, если её нет
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_reminders (
                user_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                reminder_time TEXT DEFAULT '20:00',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Получаем текущие настройки
        current = self.get_user_reminder_settings(user_id)
        
        if enabled is not None:
            current['enabled'] = enabled
        if reminder_time is not None:
            current['time'] = reminder_time
        if timezone is not None:
            current['timezone'] = timezone
        
        tz = current.get('timezone') or 'Europe/Moscow'
        cursor.execute('''
            INSERT OR REPLACE INTO user_reminders (user_id, enabled, reminder_time, timezone)
            VALUES (?, ?, ?, ?)
        ''', (user_id, 1 if current['enabled'] else 0, current['time'], tz))
        
        conn.commit()
        conn.close()
    
    def get_users_with_reminders(self) -> List[Dict]:
        """Получает список пользователей с включенными напоминаниями"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT user_id, reminder_time, timezone FROM user_reminders WHERE enabled = 1
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                'user_id': row[0],
                'time': row[1],
                'timezone': row[2] if row[2] else 'Europe/Moscow',
            }
            for row in rows
        ]
    
    # ========== Методы для работы с экспозициями ==========
    
    def save_exposure(self, user_id: int, exposure_data: Dict[str, Any]) -> int:
        """Сохраняет запись экспозиции"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Шифруем чувствительные поля, если включено шифрование
        def encrypt_field(value):
            if value and self.use_data_encryption:
                return self._encrypt_data(str(value))
            return value
        
        import json
        
        # Проверяем, какие колонки существуют в таблице
        cursor.execute("PRAGMA table_info(exposures)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        # Формируем список колонок и значений в зависимости от структуры таблицы
        columns = ['user_id', 'created_at', 'situation_name', 'event_datetime']
        values = [
            user_id,
            datetime.now().isoformat(),
            encrypt_field(exposure_data.get('situation_name')),
            exposure_data.get('event_datetime')
        ]
        
        # Добавляем новые колонки, если они существуют
        if 'event_duration' in existing_columns:
            columns.append('event_duration')
            values.append(exposure_data.get('event_duration'))
        
        if 'expectations_data' in existing_columns:
            columns.append('expectations_data')
            values.append(json.dumps(exposure_data.get('expectations_data', []), ensure_ascii=False))
        elif 'expectations' in existing_columns:
            # Для обратной совместимости со старым форматом
            columns.append('expectations')
            expectations_text = ''
            if exposure_data.get('expectations_data'):
                expectations_text = '; '.join([exp.get('text', '') for exp in exposure_data.get('expectations_data', [])])
            values.append(encrypt_field(expectations_text))
        
        if 'emotions_before' in existing_columns:
            columns.append('emotions_before')
            values.append(json.dumps(exposure_data.get('emotions_before', []), ensure_ascii=False))
        
        columns.extend(['reality', 'reminder_sent', 'reality_received'])
        values.extend([
            encrypt_field(exposure_data.get('reality')),
            exposure_data.get('reminder_sent', 0),
            exposure_data.get('reality_received', 0)
        ])
        
        if 'emotions_after' in existing_columns:
            columns.append('emotions_after')
            values.append(json.dumps(exposure_data.get('emotions_after', []), ensure_ascii=False))
        
        if 'comparison' in existing_columns:
            columns.append('comparison')
            values.append(encrypt_field(exposure_data.get('comparison')))
        
        # Формируем запрос
        placeholders = ', '.join(['?'] * len(values))
        columns_str = ', '.join(columns)
        
        cursor.execute(f'''
            INSERT INTO exposures ({columns_str})
            VALUES ({placeholders})
        ''', values)
        
        exposure_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return exposure_id
    
    def get_user_exposures(self, user_id: int, start_date: Optional[str] = None,
                          end_date: Optional[str] = None) -> List[Dict]:
        """Получает записи экспозиций пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = 'SELECT * FROM exposures WHERE user_id = ?'
        params = [user_id]
        
        if start_date:
            query += ' AND event_datetime >= ?'
            params.append(start_date)
        if end_date:
            query += ' AND event_datetime <= ?'
            params.append(end_date)
        
        query += ' ORDER BY event_datetime DESC'
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        # Получаем названия колонок
        column_names = [description[0] for description in cursor.description]
        
        exposures = []
        for row in rows:
            exposure = dict(zip(column_names, row))
            # Расшифровываем данные, если нужно
            if self.use_data_encryption:
                if exposure.get('situation_name'):
                    exposure['situation_name'] = self._decrypt_data(exposure['situation_name'])
                if exposure.get('reality'):
                    exposure['reality'] = self._decrypt_data(exposure['reality'])
                if exposure.get('comparison'):
                    exposure['comparison'] = self._decrypt_data(exposure['comparison'])
            # Парсим JSON поля
            import json
            if exposure.get('expectations_data'):
                exposure['expectations_data'] = self._parse_json_field(exposure['expectations_data'])
            if exposure.get('emotions_before'):
                exposure['emotions_before'] = self._parse_json_field(exposure['emotions_before'])
            if exposure.get('emotions_after'):
                exposure['emotions_after'] = self._parse_json_field(exposure['emotions_after'])
            # Для обратной совместимости
            if not exposure.get('expectations_data') and exposure.get('expectations'):
                exposure['expectations_data'] = [{'text': exposure.get('expectations'), 'probability': None}]
            exposures.append(exposure)
        
        conn.close()
        return exposures
    
    def get_exposure(self, exposure_id: int) -> Optional[Dict]:
        """Получает конкретную запись экспозиции"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM exposures WHERE id = ?', (exposure_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return None
        
        column_names = [description[0] for description in cursor.description]
        exposure = dict(zip(column_names, row))
        
        # Расшифровываем данные, если нужно
        if self.use_data_encryption:
            if exposure.get('situation_name'):
                exposure['situation_name'] = self._decrypt_data(exposure['situation_name'])
            if exposure.get('reality'):
                exposure['reality'] = self._decrypt_data(exposure['reality'])
            if exposure.get('comparison'):
                exposure['comparison'] = self._decrypt_data(exposure['comparison'])
        # Парсим JSON поля
        import json
        if exposure.get('expectations_data'):
            exposure['expectations_data'] = self._parse_json_field(exposure['expectations_data'])
        if exposure.get('emotions_before'):
            exposure['emotions_before'] = self._parse_json_field(exposure['emotions_before'])
        if exposure.get('emotions_after'):
            exposure['emotions_after'] = self._parse_json_field(exposure['emotions_after'])
        # Для обратной совместимости
        if not exposure.get('expectations_data') and exposure.get('expectations'):
            exposure['expectations_data'] = [{'text': exposure.get('expectations'), 'probability': None}]
        
        conn.close()
        return exposure
    
    def update_exposure_reality(self, exposure_id: int, reality: str, emotions_after: Optional[List[Dict]] = None, comparison: Optional[str] = None) -> bool:
        """Обновляет поля reality, emotions_after и comparison для экспозиции"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Проверяем, какие колонки существуют
        cursor.execute("PRAGMA table_info(exposures)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        # Шифруем, если нужно
        if self.use_data_encryption:
            reality_encrypted = self._encrypt_data(reality)
            if comparison:
                comparison_encrypted = self._encrypt_data(comparison)
        else:
            reality_encrypted = reality
            if comparison:
                comparison_encrypted = comparison
        
        # Формируем запрос в зависимости от существующих колонок
        import json
        updates = ['reality = ?', 'reality_received = 1']
        values = [reality_encrypted]
        
        if 'emotions_after' in existing_columns and emotions_after is not None:
            updates.append('emotions_after = ?')
            values.append(json.dumps(emotions_after, ensure_ascii=False))
        
        if 'comparison' in existing_columns and comparison:
            updates.append('comparison = ?')
            values.append(comparison_encrypted)
        
        values.append(exposure_id)
        
        query = f'''
            UPDATE exposures 
            SET {', '.join(updates)}
            WHERE id = ?
        '''
        
        cursor.execute(query, values)
        
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success
    
    def mark_exposure_reminder_sent(self, exposure_id: int) -> bool:
        """Отмечает, что напоминание отправлено"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE exposures 
            SET reminder_sent = 1
            WHERE id = ?
        ''', (exposure_id,))
        
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success
    
    def get_pending_exposures_for_reminder(self, current_datetime: str) -> List[Dict]:
        """Получает экспозиции, для которых нужно отправить напоминание"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Находим экспозиции, где:
        # 1. event_datetime <= current_datetime (событие уже началось)
        # 2. event_datetime + event_duration минут <= current_datetime (время напоминания наступило)
        # 3. reminder_sent = 0
        # 4. reality_received = 0
        # 5. event_duration IS NOT NULL (исключаем ручную проработку)
        cursor.execute('''
            SELECT * FROM exposures
            WHERE reminder_sent = 0
            AND reality_received = 0
            AND event_duration IS NOT NULL
            AND event_datetime <= ?
            AND datetime(event_datetime, '+' || COALESCE(event_duration, 30) || ' minutes') <= ?
        ''', (current_datetime, current_datetime))
        
        rows = cursor.fetchall()
        column_names = [description[0] for description in cursor.description]
        
        exposures = []
        for row in rows:
            exposure = dict(zip(column_names, row))
            # Расшифровываем данные, если нужно
            if self.use_data_encryption:
                if exposure.get('situation_name'):
                    exposure['situation_name'] = self._decrypt_data(exposure['situation_name'])
                if exposure.get('expectations'):
                    exposure['expectations'] = self._decrypt_data(exposure['expectations'])
            exposures.append(exposure)
        
        conn.close()
        return exposures
    
    def delete_exposure(self, exposure_id: int, user_id: int) -> bool:
        """Удаляет запись экспозиции"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM exposures WHERE id = ? AND user_id = ?', (exposure_id, user_id))
        
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success
    
    def get_total_exposures_count(self) -> int:
        """Получает общее количество записей экспозиций"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM exposures')
        count = cursor.fetchone()[0]
        conn.close()
        return count