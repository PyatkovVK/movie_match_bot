import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ADMIN_NAME = os.getenv('ADMIN_NAME')

# Настройки бота
ADMIN_IDS = [f"{ADMIN_NAME}"]

# Настройки Gemini
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TEMPERATURE = 0.7
GEMINI_MAX_TOKENS = 2000

# Проверка обязательных переменных
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле")

if not GEMINI_API_KEY:
    print("⚠️  ВНИМАНИЕ: GEMINI_API_KEY не найден. Будут использоваться резервные рекомендации.")