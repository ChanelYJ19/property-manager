"""Two-way Telegram bot: sends deadline reminders with action buttons."""
import asyncio
import logging
from datetime import date, datetime

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from app import sheets
from app.optin import get_chat_id, set_chat_id
from config import settings

log = logging.getLogger(__name__)


def _keyboard(sheet_row: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Mark Done", callback_data=f"done:{sheet_row}"),
        InlineKeyboardButton("⏭️ Skip", callback_data=f"skip:{sheet_row}"),
    ]])


async def send_reminder(bot: Bot, chat_id: str, deadline: dict) -> None:
    name = deadline.get("Task", "Unknown task")
    due = deadline.get("Due Date", "unknown date")
    category = deadline.get("Category", "")
    days_until = (datetime.strptime(due, "%Y-%m-%d").date() - date.today()).days

    if days_until == 1:
        urgency = "due *tomorrow*"
    elif days_until == 0:
        urgency = "*due today*"
    else:
        urgency = f"due in {days_until} days ({due})"

    header = f"[{category}] " if category else ""
    text = f"{header}*{name}* is {urgency}."

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=_keyboard(deadline["sheet_row"]),
    )
    log.info("Sent Telegram reminder for '%s'", name)


async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    set_chat_id(chat_id)
    await update.message.reply_text(
        "You're all set! I'll send deadline reminders here.\n\n"
        "Tap *Mark Done* or *Skip* on any reminder to update the sheet instantly.\n"
        "Use /status to see what's coming up.",
        parse_mode="Markdown",
    )


async def _cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        deadlines = sheets.get_deadlines()
    except Exception:
        log.exception("Failed to fetch deadlines for /status")
        await update.message.reply_text("Couldn't reach the sheet right now — try again in a moment.")
        return

    today = date.today()
    upcoming = []
    for d in deadlines:
        status = d.get("Status", "").strip().upper()
        if status in ("DONE", "SKIPPED"):
            continue
        try:
            due = datetime.strptime(d["Due Date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        days_until = (due - today).days
        if 0 <= days_until <= 30:
            upcoming.append((days_until, d["Task"], d["Due Date"]))

    if not upcoming:
        await update.message.reply_text("Nothing due in the next 30 days.")
        return

    upcoming.sort()
    lines = []
    for days, task, due in upcoming:
        if days == 0:
            label = "today"
        elif days == 1:
            label = "tomorrow"
        else:
            label = f"in {days} days ({due})"
        lines.append(f"• *{task}* — {label}")

    await update.message.reply_text(
        "Upcoming deadlines:\n\n" + "\n".join(lines),
        parse_mode="Markdown",
    )


async def _handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    action, raw_row = query.data.split(":", 1)
    sheet_row = int(raw_row)
    status_map = {"done": "Done", "skip": "Skipped"}
    new_status = status_map.get(action)
    if not new_status:
        return

    try:
        sheets.update_status(sheet_row, new_status)
        icon = "✅" if action == "done" else "⏭️"
        original = query.message.text or ""
        await query.edit_message_text(
            text=f"{original}\n\n{icon} _Marked as {new_status}_",
            parse_mode="Markdown",
        )
        log.info("Row %s marked %s via Telegram", sheet_row, new_status)
    except Exception:
        log.exception("Failed to update row %s", sheet_row)
        await query.edit_message_text(
            text=(query.message.text or "") + "\n\n⚠️ _Update failed — check the sheet._",
            parse_mode="Markdown",
        )


def build_app() -> Application:
    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("status", _cmd_status))
    app.add_handler(CallbackQueryHandler(_handle_button))
    return app


def send_reminder_threadsafe(bot: Bot, loop: asyncio.AbstractEventLoop, deadline: dict) -> None:
    """Call send_reminder from a non-async thread (e.g. APScheduler callback)."""
    chat_id = get_chat_id()
    if not chat_id:
        log.warning("No Telegram chat_id registered — skipping reminder for '%s'", deadline.get("Task"))
        return
    future = asyncio.run_coroutine_threadsafe(send_reminder(bot, chat_id, deadline), loop)
    try:
        future.result(timeout=15)
    except Exception:
        log.exception("Telegram send failed for '%s'", deadline.get("Task"))
