"""Daily APScheduler job: check deadlines and send Telegram reminders."""
import asyncio
import logging
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot

from app import sheets
from app.optin import get_chat_id, is_opted_in
from app.telegram_bot import send_reminder_threadsafe

log = logging.getLogger(__name__)

REMINDER_DAYS_AHEAD = [7, 3, 1]


def check_and_remind(bot: Bot, loop: asyncio.AbstractEventLoop) -> None:
    if not is_opted_in():
        log.info("Opt-in not confirmed — skipping reminders")
        return

    if not get_chat_id():
        log.info("No Telegram chat registered — skipping reminders")
        return

    try:
        deadlines = sheets.get_deadlines()
    except Exception:
        log.exception("Failed to fetch deadlines from Google Sheets")
        return

    today = date.today()
    for deadline in deadlines:
        raw_due = str(deadline.get("Due Date", "")).strip()
        status = str(deadline.get("Status", "")).strip().upper()

        if status in ("DONE", "SKIPPED"):
            continue

        try:
            due = datetime.strptime(raw_due, "%Y-%m-%d").date()
        except ValueError:
            log.warning("Skipping row with unparseable date: %s", raw_due)
            continue

        days_until = (due - today).days
        if days_until in REMINDER_DAYS_AHEAD:
            send_reminder_threadsafe(bot, loop, deadline)


def start_scheduler(bot: Bot, loop: asyncio.AbstractEventLoop) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        check_and_remind,
        trigger=CronTrigger(hour=9, minute=0),
        id="daily_reminder",
        replace_existing=True,
        kwargs={"bot": bot, "loop": loop},
    )
    scheduler.start()
    log.info("Scheduler started — daily reminders at 09:00")
    return scheduler
