"""Two-way Telegram bot: sends deadline reminders with action buttons."""
import asyncio
import html
import logging
from datetime import date, datetime, timedelta

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from rapidfuzz import fuzz, process

from app import sheets
from app.optin import get_chat_id, set_chat_id
from config import settings

log = logging.getLogger(__name__)


def _esc(text) -> str:
    return html.escape(str(text))


def _keyboard(sheet_row: int, due_col: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Mark Done", callback_data=f"done:{sheet_row}"),
        InlineKeyboardButton("⏭️ Skip", callback_data=f"skip:{sheet_row}"),
        InlineKeyboardButton("⏰ Snooze", callback_data=f"snooze:{sheet_row}:{due_col}"),
    ]])


def _snooze_keyboard(sheet_row: int, due_col: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1 day", callback_data=f"snz:1:{sheet_row}:{due_col}"),
            InlineKeyboardButton("3 days", callback_data=f"snz:3:{sheet_row}:{due_col}"),
            InlineKeyboardButton("7 days", callback_data=f"snz:7:{sheet_row}:{due_col}"),
        ],
        [InlineKeyboardButton("↩️ Cancel", callback_data=f"snz_cancel:{sheet_row}:{due_col}")],
    ])


async def send_overdue_alert(bot: Bot, chat_id: str, deadline: dict) -> None:
    name = deadline.get("Task", "Unknown task")
    due = deadline.get("Due Date", "unknown date")
    category = deadline.get("Category", "")
    notes = deadline.get("Notes", "").strip()
    days_overdue = (date.today() - datetime.strptime(due, "%Y-%m-%d").date()).days

    header = f"[{_esc(category)}] " if category else ""
    overdue_str = "1 day overdue" if days_overdue == 1 else f"{days_overdue} days overdue"
    notes_line = f"\n<i>{_esc(notes)}</i>" if notes else ""
    text = f"⚠️ {header}<b>{_esc(name)}</b> is {overdue_str} (was due {_esc(due)}).{notes_line}"

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=_keyboard(deadline["sheet_row"], deadline["due_date_col"]),
    )
    log.info("Sent overdue alert for '%s' (%s days)", name, days_overdue)


async def send_reminder(bot: Bot, chat_id: str, deadline: dict) -> None:
    name = deadline.get("Task", "Unknown task")
    due = deadline.get("Due Date", "unknown date")
    category = deadline.get("Category", "")
    notes = deadline.get("Notes", "").strip()
    days_until = (datetime.strptime(due, "%Y-%m-%d").date() - date.today()).days

    if days_until <= 0:
        urgency = "<b>due today</b>"
    elif days_until == 1:
        urgency = "due <b>tomorrow</b>"
    else:
        urgency = f"due in {days_until} days ({_esc(due)})"

    header = f"[{_esc(category)}] " if category else ""
    notes_line = f"\n<i>{_esc(notes)}</i>" if notes else ""
    text = f"{header}<b>{_esc(name)}</b> is {urgency}.{notes_line}"

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=_keyboard(deadline["sheet_row"], deadline["due_date_col"]),
    )
    log.info("Sent Telegram reminder for '%s'", name)


def _status_text(deadlines: list[dict]) -> str:
    today = date.today()
    overdue = []
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
        if days_until < 0:
            overdue.append((abs(days_until), d["Task"], d["Due Date"]))
        elif days_until <= 30:
            upcoming.append((days_until, d["Task"], d["Due Date"]))

    if not overdue and not upcoming:
        return "Nothing due or overdue in the next 30 days."

    lines = []
    if overdue:
        overdue.sort()
        lines.append("<b>Overdue:</b>")
        for days, task, due in overdue:
            lines.append(f"• ⚠️ <b>{_esc(task)}</b> — {days} day{'s' if days != 1 else ''} overdue (was due {_esc(due)})")
        lines.append("")
    if upcoming:
        upcoming.sort()
        lines.append("<b>Upcoming:</b>")
        for days, task, due in upcoming:
            if days == 0:
                label = "today"
            elif days == 1:
                label = "tomorrow"
            else:
                label = f"in {days} days ({_esc(due)})"
            lines.append(f"• <b>{_esc(task)}</b> — {label}")
    return "\n".join(lines)


async def _cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    set_chat_id(chat_id)
    await update.message.reply_text(
        "You're all set! I'll send deadline reminders here.\n\n"
        "Tap <b>Mark Done</b>, <b>Skip</b>, or <b>Snooze</b> on any reminder to update the sheet.\n"
        "Or type /done <i>task name</i> anytime — I'll figure out which task you mean.\n"
        "Use /status to check what's coming up, or /help to see all commands.",
        parse_mode="HTML",
    )
    try:
        deadlines = sheets.get_deadlines()
        await update.message.reply_text(_status_text(deadlines), parse_mode="HTML")
    except Exception:
        log.exception("Failed to fetch deadlines for /start confirmation")
        await update.message.reply_text("Couldn't load deadlines right now — try /status in a moment.")


async def _cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Available commands</b>\n\n"
        "/status — show overdue + upcoming tasks (next 30 days)\n\n"
        "/add — add a new task to the sheet\n"
        "<i>e.g. /add or /add Insurance Renewal</i>\n\n"
        "/done <i>task name</i> — mark a task as done (no need to type it exactly)\n"
        "<i>e.g. /done insurance or /done water bill</i>\n\n"
        "/test — send a test reminder with live buttons\n"
        "/help — show this message\n\n"
        "On any reminder you can also tap <b>Mark Done</b>, <b>Skip</b>, or <b>Snooze</b> directly.",
        parse_mode="HTML",
    )


async def _cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        deadlines = sheets.get_deadlines()
    except Exception:
        log.exception("Failed to fetch deadlines for /status")
        await update.message.reply_text("Couldn't reach the sheet right now — try again in a moment.")
        return
    await update.message.reply_text(_status_text(deadlines), parse_mode="HTML")


async def _handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    action = parts[0]
    # query.message.text is plain text — escape it before embedding in HTML
    original = _esc(query.message.text or "")

    if action in ("done", "skip"):
        sheet_row = int(parts[1])
        status_map = {"done": "Done", "skip": "Skipped"}
        new_status = status_map[action]
        try:
            sheets.update_status(sheet_row, new_status)
            icon = "✅" if action == "done" else "⏭️"
            await query.edit_message_text(
                text=f"{original}\n\n{icon} <i>Marked as {new_status}</i>",
                parse_mode="HTML",
            )
            log.info("Row %s marked %s via Telegram", sheet_row, new_status)
        except Exception as e:
            log.exception("Failed to update row %s", sheet_row)
            await query.edit_message_text(
                text=original + f"\n\n⚠️ <i>Update failed: {_esc(str(e))}</i>",
                parse_mode="HTML",
            )

    elif action == "snooze":
        sheet_row, due_col = int(parts[1]), int(parts[2])
        await query.edit_message_text(
            text=original + "\n\nSnooze for how long?",
            parse_mode="HTML",
            reply_markup=_snooze_keyboard(sheet_row, due_col),
        )

    elif action == "snz":
        days, sheet_row, due_col = int(parts[1]), int(parts[2]), int(parts[3])
        new_due = date.today() + timedelta(days=days)
        new_due_str = new_due.strftime("%m/%d/%Y")
        try:
            sheets.update_due_date(sheet_row, due_col, new_due_str)
            label = "1 day" if days == 1 else f"{days} days"
            await query.edit_message_text(
                text=original + f"\n\n⏰ <i>Snoozed {label} — new due date: {_esc(new_due_str)}</i>",
                parse_mode="HTML",
            )
            log.info("Row %s snoozed %s days, new due %s", sheet_row, days, new_due_str)
        except Exception:
            log.exception("Failed to snooze row %s", sheet_row)
            await query.edit_message_text(
                text=original + "\n\n⚠️ <i>Snooze failed — check the sheet.</i>",
                parse_mode="HTML",
            )

    elif action == "snz_cancel":
        sheet_row, due_col = int(parts[1]), int(parts[2])
        await query.edit_message_text(
            text=original,
            parse_mode="HTML",
            reply_markup=_keyboard(sheet_row, due_col),
        )


async def _cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query_text = " ".join(context.args).strip()
    if not query_text:
        await update.message.reply_text(
            "Tell me which task to mark done — e.g. <code>/done insurance renewal</code>",
            parse_mode="HTML",
        )
        return

    try:
        deadlines = sheets.get_deadlines()
    except Exception:
        log.exception("Failed to fetch deadlines for /done")
        await update.message.reply_text("Couldn't reach the sheet — try again in a moment.")
        return

    pending = [d for d in deadlines if d.get("Status", "").strip().upper() not in ("DONE", "SKIPPED")]
    if not pending:
        await update.message.reply_text("No pending tasks found.")
        return

    task_names = [d["Task"] for d in pending]
    matches = process.extract(query_text, task_names, scorer=fuzz.WRatio, limit=3, score_cutoff=50)

    if not matches:
        known = "\n".join(f"• {_esc(n)}" for n in sorted(set(task_names))[:10])
        await update.message.reply_text(
            f"Couldn't find a task matching <i>{_esc(query_text)}</i>.\n\n"
            f"<b>Pending tasks I know about:</b>\n{known}",
            parse_mode="HTML",
        )
        return

    best_name, best_score, best_idx = matches[0]
    best_deadline = pending[best_idx]

    if best_score >= 85:
        try:
            sheets.update_status(best_deadline["sheet_row"], "Done")
            await update.message.reply_text(
                f"✅ Marked <b>{_esc(best_name)}</b> as Done.",
                parse_mode="HTML",
            )
        except Exception as e:
            log.exception("Failed to update status for '%s'", best_name)
            await update.message.reply_text(
                f"⚠️ Couldn't update the sheet for <b>{_esc(best_name)}</b>: <code>{_esc(str(e))}</code>",
                parse_mode="HTML",
            )
    else:
        buttons = [
            [InlineKeyboardButton(name, callback_data=f"done:{pending[idx]['sheet_row']}")]
            for name, _score, idx in matches
        ]
        await update.message.reply_text(
            f"Which task did you mean?\n<i>(searched for: {_esc(query_text)})</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )


async def _cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        deadlines = sheets.get_deadlines()
    except Exception:
        log.exception("Failed to fetch deadlines for /test")
        await update.message.reply_text("Couldn't reach the sheet — try again in a moment.")
        return

    pending = [d for d in deadlines if d.get("Status", "").strip().upper() not in ("DONE", "SKIPPED")]
    if not pending:
        await update.message.reply_text("No pending tasks in the sheet to test with.")
        return

    deadline = pending[0]
    due_date = deadline.get("Due Date", "")
    try:
        days_until = (datetime.strptime(due_date, "%Y-%m-%d").date() - date.today()).days
    except ValueError:
        days_until = 0

    await update.message.reply_text(
        "🧪 <b>Test reminder</b> — using your first pending task.\n"
        "<i>Buttons are live and will update the sheet if tapped.</i>",
        parse_mode="HTML",
    )
    if days_until < 0:
        await send_overdue_alert(context.bot, str(update.effective_chat.id), deadline)
    else:
        await send_reminder(context.bot, str(update.effective_chat.id), deadline)


async def _cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show raw sheet info to diagnose column layout and tab name."""
    from config import settings as cfg
    lines = [f"<b>Tab:</b> {_esc(str(cfg.ACTIVE_YEAR))}"]

    try:
        rows = sheets.get_raw_last_rows(5)
    except Exception as e:
        await update.message.reply_text(
            f"Tab: {_esc(str(cfg.ACTIVE_YEAR))}\nCouldn't read sheet: <code>{_esc(str(e))}</code>",
            parse_mode="HTML",
        )
        return

    if not rows:
        lines.append("No non-empty rows found in this tab.")
    else:
        lines.append(f"<b>Last {len(rows)} non-empty rows:</b>")
        for row_idx, vals in rows:
            cols = {i + 1: v for i, v in enumerate(vals) if v.strip()}
            col_str = ", ".join(f"col{c}={_esc(v)}" for c, v in cols.items())
            lines.append(f"Row {row_idx}: {col_str or '(all empty)'}")

    try:
        deadlines = sheets.get_deadlines()
        pending = [d for d in deadlines if d.get("Status", "").strip().upper() not in ("DONE", "SKIPPED")]
        lines.append(f"\n<b>Pending tasks parsed:</b> {len(pending)}")
        for d in pending[-5:]:
            lines.append(f"• {_esc(d['Task'])} [{_esc(d['Category'])}] due {_esc(d['Due Date'])}")
    except Exception as e:
        lines.append(f"get_deadlines error: <code>{_esc(str(e))}</code>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled exception for update %s", update, exc_info=context.error)


# /add conversation states
_ADD_NAME, _ADD_CATEGORY, _ADD_DUE = range(3)


def _category_keyboard(categories: list[str]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(cat, callback_data=f"addcat:{cat}")] for cat in categories[:8]]
    buttons.append([InlineKeyboardButton("✏️ Other", callback_data="addcat:__other__")])
    return InlineKeyboardMarkup(buttons)


async def _cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = " ".join(context.args).strip() if context.args else ""
    if name:
        context.user_data["add_task"] = name
        return await _add_ask_category(update, context)
    await update.message.reply_text("What's the task name?")
    return _ADD_NAME


async def _add_got_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["add_task"] = update.message.text.strip()
    return await _add_ask_category(update, context)


async def _add_ask_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        deadlines = sheets.get_deadlines()
        categories = sorted({d["Category"] for d in deadlines if d.get("Category")})
    except Exception:
        categories = []

    msg = update.message or update.callback_query.message
    if categories:
        await msg.reply_text("What category?", reply_markup=_category_keyboard(categories))
    else:
        await msg.reply_text("What category?")
    return _ADD_CATEGORY


async def _add_got_category_btn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    cat = query.data.split(":", 1)[1]
    if cat == "__other__":
        await query.edit_message_text("Type the category name:")
        return _ADD_CATEGORY
    context.user_data["add_category"] = cat
    await query.edit_message_text(
        f"Category: <b>{_esc(cat)}</b>\n\nWhat's the due date? (e.g. 06/15/2025)",
        parse_mode="HTML",
    )
    return _ADD_DUE


async def _add_got_category_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["add_category"] = update.message.text.strip()
    await update.message.reply_text("What's the due date? (e.g. 06/15/2025)")
    return _ADD_DUE


async def _add_got_due(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    due_date = sheets.parse_date(raw)
    if not due_date:
        await update.message.reply_text(
            "Couldn't read that date. Try MM/DD/YYYY (e.g. 06/15/2025):"
        )
        return _ADD_DUE

    task = context.user_data["add_task"]
    category = context.user_data["add_category"]
    try:
        sheets.add_task(task, category, due_date)
        await update.message.reply_text(
            f"✅ Added <b>{_esc(task)}</b> [{_esc(category)}] due {_esc(raw)}.",
            parse_mode="HTML",
        )
    except Exception:
        log.exception("Failed to add task '%s'", task)
        await update.message.reply_text("Couldn't save to the sheet — try again in a moment.")

    context.user_data.clear()
    return ConversationHandler.END


async def _add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


def build_app() -> Application:
    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("add", _cmd_add)],
        states={
            _ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, _add_got_name)],
            _ADD_CATEGORY: [
                CallbackQueryHandler(_add_got_category_btn, pattern="^addcat:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, _add_got_category_text),
            ],
            _ADD_DUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, _add_got_due)],
        },
        fallbacks=[CommandHandler("cancel", _add_cancel)],
    ))
    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("help", _cmd_help))
    app.add_handler(CommandHandler("status", _cmd_status))
    app.add_handler(CommandHandler("done", _cmd_done))
    app.add_handler(CommandHandler("test", _cmd_test))
    app.add_handler(CommandHandler("debug", _cmd_debug))
    app.add_handler(CallbackQueryHandler(_handle_button))
    app.add_error_handler(_error_handler)
    return app


def _threadsafe(coro, loop: asyncio.AbstractEventLoop, task_name: str) -> bool:
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        future.result(timeout=15)
        return True
    except Exception:
        log.exception("Telegram send failed for '%s'", task_name)
        return False


def send_reminder_threadsafe(bot: Bot, loop: asyncio.AbstractEventLoop, deadline: dict) -> bool:
    chat_id = get_chat_id()
    if not chat_id:
        log.warning("No Telegram chat_id registered — skipping reminder for '%s'", deadline.get("Task"))
        return False
    return _threadsafe(send_reminder(bot, chat_id, deadline), loop, deadline.get("Task", ""))


def send_overdue_alert_threadsafe(bot: Bot, loop: asyncio.AbstractEventLoop, deadline: dict) -> bool:
    chat_id = get_chat_id()
    if not chat_id:
        log.warning("No Telegram chat_id registered — skipping overdue alert for '%s'", deadline.get("Task"))
        return False
    return _threadsafe(send_overdue_alert(bot, chat_id, deadline), loop, deadline.get("Task", ""))


async def send_monthly_summary(bot: Bot, chat_id: str) -> None:
    try:
        deadlines = sheets.get_deadlines()
    except Exception:
        log.exception("Failed to fetch deadlines for monthly summary")
        return

    today = date.today()
    month_tasks = []
    for d in deadlines:
        try:
            due = datetime.strptime(d["Due Date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if due.month == today.month and due.year == today.year:
            month_tasks.append((due, d))

    month_label = today.strftime("%B %Y")

    if not month_tasks:
        await bot.send_message(chat_id=chat_id, text=f"📅 No tasks due in {month_label}.")
        return

    month_tasks.sort(key=lambda t: t[0])

    by_category: dict[str, list[tuple]] = {}
    for due, d in month_tasks:
        cat = d.get("Category", "Other") or "Other"
        by_category.setdefault(cat, []).append((due, d))

    pending = sum(1 for _, d in month_tasks if d.get("Status", "").strip().upper() not in ("DONE", "SKIPPED"))
    lines = [f"📅 <b>{_esc(month_label)}</b> — {len(month_tasks)} task{'s' if len(month_tasks) != 1 else ''} ({pending} pending)\n"]

    for cat, tasks in by_category.items():
        lines.append(f"<b>{_esc(cat)}</b>")
        for due, d in tasks:
            status = d.get("Status", "").strip().upper()
            icon = "✅" if status == "DONE" else "⏭️" if status == "SKIPPED" else "•"
            lines.append(f"{icon} {_esc(d['Task'])} — {due.strftime('%b')} {due.day}")
        lines.append("")

    await bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines).rstrip(),
        parse_mode="HTML",
    )
    log.info("Sent monthly summary for %s", month_label)


def send_monthly_summary_threadsafe(bot: Bot, loop: asyncio.AbstractEventLoop) -> None:
    chat_id = get_chat_id()
    if not chat_id:
        log.warning("No Telegram chat_id registered — skipping monthly summary")
        return
    _threadsafe(send_monthly_summary(bot, chat_id), loop, "monthly summary")
