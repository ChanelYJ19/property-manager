"""Outbound push notifications via Pushover."""
import requests
from config import settings

_PUSHOVER_API = "https://api.pushover.net/1/messages.json"


def send_sms(body: str, title: str = "Property Manager") -> str:
    """Send a push notification via Pushover. Returns the request UUID."""
    resp = requests.post(_PUSHOVER_API, data={
        "token": settings.PUSHOVER_APP_TOKEN,
        "user": settings.PUSHOVER_USER_KEY,
        "message": body,
        "title": title,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json().get("request", "")


def build_reminder(deadline: dict) -> str:
    """Format a deadline dict into a push notification reminder."""
    name = deadline.get("Task", "Unknown task")
    due = deadline.get("Due Date", "unknown date")
    status = deadline.get("Status", "")
    msg = f"'{name}' is due {due}."
    if status:
        msg += f" Current status: {status}."
    return msg
