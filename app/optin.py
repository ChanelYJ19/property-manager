"""Notification opt-in state management."""
import json
import logging
import os

log = logging.getLogger(__name__)

_STATE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "optin_state.json"))


def _load() -> dict:
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE) as f:
            return json.load(f)
    return {"opted_in": True}


def _save(state: dict) -> None:
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f)


def is_opted_in() -> bool:
    return _load().get("opted_in", True)


def set_opted_in() -> None:
    _save({"opted_in": True})
    log.info("Opt-in recorded")


def set_opted_out() -> None:
    _save({"opted_in": False})
    log.info("Opt-out recorded")


def get_chat_id() -> str | None:
    return _load().get("telegram_chat_id")


def set_chat_id(chat_id: str) -> None:
    state = _load()
    state["telegram_chat_id"] = chat_id
    _save(state)
    log.info("Registered Telegram chat_id=%s", chat_id)
