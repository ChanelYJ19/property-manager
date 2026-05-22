"""Daily APScheduler job: check deadlines and send SMS reminders."""
import logging
from datetime import date, datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import sheets, sms
from app.optin import is_opted_in
from config import settings

log = logging.getLogger(__name__)

REMINDER_DAYS_AHEAD = [7, 3, 1]  # send reminders this many days before due date
def check_and_remind() -> None:
    """Scan the active year sheet and send SMS for upcoming tasks."""
    if not is_opted_in():
        log.info("Opt-in not confirmed — skipping reminders")
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
            message = sms.build_reminder(deadline)
            try:
                sid = sms.send_sms(message)
                log.info("Sent reminder SID=%s for task '%s'", sid, deadline.get("Task"))
            except Exception:
                log.exception("Failed to send SMS for task '%s'", deadline.get("Task"))


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        check_and_remind,
        trigger=CronTrigger(hour=9, minute=0),  # 9 AM daily
        id="daily_reminder",
        replace_existing=True,
    )
    scheduler.start()
    log.info("Scheduler started — daily reminders at 09:00")
    return scheduler
