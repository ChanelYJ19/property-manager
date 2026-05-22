import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_SHEETS_CREDS_JSON = os.environ["GOOGLE_SHEETS_CREDS_JSON"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

PUSHOVER_APP_TOKEN = os.environ["PUSHOVER_APP_TOKEN"]
PUSHOVER_USER_KEY = os.environ["PUSHOVER_USER_KEY"]

ACTIVE_YEAR = int(os.getenv("ACTIVE_YEAR", "2025"))
