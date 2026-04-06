import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
DEVELOPER_USERNAME = '@chiefmacd'
ADMIN_USERNAME = '@chiefmacd'  # Админ бота

# Ключ шифрования БД (должен быть в .env файле)
# Для включения шифрования данных (рекомендуется, работает на Windows):
#   pip install cryptography
# Для шифрования БД (требует C++ компилятор на Windows):
#   pip install pysqlcipher3
# И добавьте в .env: DB_ENCRYPTION_KEY=your_secret_key_here_min_32_chars
DB_ENCRYPTION_KEY = os.getenv('DB_ENCRYPTION_KEY', None)