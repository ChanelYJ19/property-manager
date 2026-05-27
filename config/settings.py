import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_SHEETS_CREDS_JSON = os.environ["GOOGLE_SHEETS_CREDS_JSON"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

PUSHOVER_APP_TOKEN = os.getenv("PUSHOVER_APP_TOKEN", "")
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY", "")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

ACTIVE_YEAR = int(os.getenv("ACTIVE_YEAR", "2025"))
