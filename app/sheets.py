"""Google Sheets read/write via gspread."""
import json
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from config import settings

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Row 8 is the real header row; data starts at row 9
HEADER_ROW = 8
DATA_START_ROW = 9

# Column indices (1-based) matching the header row layout:
# '', Category, Property/Name, Notes, URL, Status, Jan, Feb, Mar, Apr, May,
# Jun, Jul, Aug, Sep, Oct, Nov, Dec, Payment Amounts
COL_CATEGORY = 2
COL_TASK = 3
COL_STATUS = 6
COL_MONTH_START = 7   # January
COL_MONTH_END = 18    # December

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _client() -> gspread.Client:
    creds_data = json.loads(settings.GOOGLE_SHEETS_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_data, scopes=_SCOPES)
    return gspread.authorize(creds)


def get_sheet(tab_name: str) -> gspread.Worksheet:
    client = _client()
    spreadsheet = client.open_by_key(settings.SPREADSHEET_ID)
    return spreadsheet.worksheet(tab_name)


def parse_date(raw: str) -> str | None:
    """Try to parse a date string and return YYYY-MM-DD, or None on failure."""
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# Keep private alias for internal callers
_parse_date = parse_date


def get_deadlines(tab_name: str = str(settings.ACTIVE_YEAR)) -> list[dict]:
    """
    Parse the year tab and return one dict per (task, due-date) pair.

    Each dict contains: Task, Due Date (YYYY-MM-DD), Status, Category,
    Notes, sheet_row (1-based), status_col (1-based, always COL_STATUS).
    """
    sheet = get_sheet(tab_name)
    all_rows = sheet.get_all_values()  # list of lists, 0-based index

    deadlines = []
    current_category = ""

    for row_idx, row in enumerate(all_rows, start=1):
        if row_idx < DATA_START_ROW:
            continue

        # Pad row to avoid index errors on short rows
        row = row + [""] * (COL_MONTH_END)

        category_val = row[COL_CATEGORY - 1].strip()
        task_val = row[COL_TASK - 1].strip()
        status_val = row[COL_STATUS - 1].strip()

        # Section header rows: have a category value but no task name
        if category_val and not task_val:
            current_category = category_val
            continue

        if not task_val:
            continue

        # Rows added via /add carry their own category in col B alongside the task
        # name in col C. Use it directly; otherwise fall back to the section header.
        effective_category = category_val if category_val else current_category

        # Collect all due dates from month columns
        for month_offset in range(12):
            col_idx = COL_MONTH_START + month_offset  # 1-based
            raw_date = row[col_idx - 1].strip()
            due_date = _parse_date(raw_date)
            if due_date:
                deadlines.append({
                    "Task": task_val,
                    "Due Date": due_date,
                    "Status": status_val,
                    "Category": effective_category,
                    "Notes": row[3].strip(),  # col D
                    "sheet_row": row_idx,
                    "status_col": COL_STATUS,
                    "due_date_col": col_idx,
                })

    return deadlines


def update_status(sheet_row: int, value: str, tab_name: str = str(settings.ACTIVE_YEAR)) -> None:
    """Write a new status into the Status column for a given row."""
    sheet = get_sheet(tab_name)
    sheet.update_cell(sheet_row, COL_STATUS, value)


def update_due_date(sheet_row: int, due_date_col: int, new_date: str, tab_name: str = str(settings.ACTIVE_YEAR)) -> None:
    """Write a new due date into the month column for a given row."""
    sheet = get_sheet(tab_name)
    sheet.update_cell(sheet_row, due_date_col, new_date)


def add_task(task: str, category: str, due_date_str: str, tab_name: str = str(settings.ACTIVE_YEAR)) -> None:
    """Append a new task row with the due date in the correct month column."""
    sheet = get_sheet(tab_name)
    due = datetime.strptime(due_date_str, "%Y-%m-%d").date()
    month_col = COL_MONTH_START + (due.month - 1)

    row = [""] * COL_MONTH_END
    row[COL_CATEGORY - 1] = category
    row[COL_TASK - 1] = task
    row[month_col - 1] = due.strftime("%m/%d/%Y")

    sheet.append_row(row)


def get_raw_last_rows(n: int = 5, tab_name: str = str(settings.ACTIVE_YEAR)) -> list[tuple[int, list[str]]]:
    """Return the last n non-empty rows as (1-based row_idx, values) tuples."""
    sheet = get_sheet(tab_name)
    all_rows = sheet.get_all_values()
    result = []
    for row_idx, row in enumerate(all_rows, start=1):
        if any(v.strip() for v in row):
            result.append((row_idx, row))
    return result[-n:]


def find_and_update(
    tab_name: str,
    lookup_col: str,
    lookup_value: str,
    update_col: str,
    update_value: str,
) -> bool:
    """
    Scan deadlines for a task name match and update its Status column.
    lookup_col / update_col are accepted for API compatibility but only
    'Task' -> 'Status' is supported by the custom sheet layout.
    """
    deadlines = get_deadlines(tab_name)
    for entry in deadlines:
        if entry.get(lookup_col, "").strip().lower() == lookup_value.strip().lower():
            update_status(entry["sheet_row"], update_value, tab_name)
            return True
    return False
