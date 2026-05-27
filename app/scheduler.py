"""Daily APScheduler job: check deadlines and send Telegram reminders."""
import asyncio
import logging
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot

from app import rate_limit, sheets
from app.optin import get_chat_id, is_opted_in
from app.telegram_bot import send_monthly_summary_threadsafe, send_overdue_alert_threadsafe, send_reminder_threadsafe

log = logging.getLogger(__name__)

REMINDER_DAYS_AHEAD = [7, 3, 1]
OVERDUE_ALERT_DAYS = [1, 3, 7, 14]


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
            if not rate_limit.already_sent(deadline["sheet_row"], raw_due, days_until):
                if send_reminder_threadsafe(bot, loop, deadline):
                    rate_limit.mark_sent(deadline["sheet_row"], raw_due, days_until)
        elif days_until < 0 and abs(days_until) in OVERDUE_ALERT_DAYS:
            interval = days_until  # negative, e.g. -1, -3, -7
            if not rate_limit.already_sent(deadline["sheet_row"], raw_due, interval):
                if send_overdue_alert_threadsafe(bot, loop, deadline):
                    rate_limit.mark_sent(deadline["sheet_row"], raw_due, interval)


def monthly_summary_job(bot: Bot, loop: asyncio.AbstractEventLoop) -> None:
    if not is_opted_in():
        return
    send_monthly_summary_threadsafe(bot, loop)


def start_scheduler(bot: Bot, loop: asyncio.AbstractEventLoop) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        check_and_remind,
        trigger=CronTrigger(hour=9, minute=0),
        id="daily_reminder",
        replace_existing=True,
        kwargs={"bot": bot, "loop": loop},
    )
    scheduler.add_job(
        monthly_summary_job,
        trigger=CronTrigger(day=1, hour=9, minute=0),
        id="monthly_summary",
        replace_existing=True,
        kwargs={"bot": bot, "loop": loop},
    )
    scheduler.start()
    log.info("Scheduler started — daily reminders at 09:00, monthly summary on the 1st")
    return scheduler
