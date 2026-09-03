from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

import requests

import bms_api

log = logging.getLogger("bms-github-checker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

WATCHES_FILE = os.getenv("WATCHES_FILE", "data/watches.json")
STATE_FILE = os.getenv("STATE_FILE", "data/watcher_state.json")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is required")


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def filter_venues(shows: list, watch: Dict[str, Any]) -> list:
    if watch.get("venue_mode") == "any":
        return shows
    selected = [str(x).strip().lower() for x in watch.get("venues", [])]
    if not selected:
        return []
    return [
        show for show in shows
        if any(name in str(show.venue_name).strip().lower()
               or str(show.venue_name).strip().lower() in name
               for name in selected)
    ]


def is_available_status(status: Any) -> bool:
    return str(status or "").strip().lower() in {
        "3", "available", "avail", "available_now", "bookable"
    }


def build_state(shows: list) -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    for show in shows:
        for category in show.categories:
            key = f"{show.venue_code}|{show.time}|{show.language_format_text}|{category.name}"
            state[key] = {
                "venue": show.venue_name,
                "venue_code": show.venue_code,
                "time": show.time,
                "screen": show.screen_attr,
                "language": show.language,
                "format": show.movie_format,
                "language_format": show.language_format_text,
                "category": category.name,
                "price": category.price,
                "status": category.status,
                "available": is_available_status(category.status),
            }
    return state


def detect_changes(old_state: Dict[str, Any], new_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    changes = []
    for key, new_item in new_state.items():
        old_item = old_state.get(key)
        if old_item is None:
            if new_item.get("available"):
                changes.append({"type": "NEW", "key": key, "before": None, "after": new_item})
            continue
        old_available = bool(old_item.get("available"))
        new_available = bool(new_item.get("available"))
        if not old_available and new_available:
            changes.append({"type": "AVAILABLE", "key": key, "before": old_item, "after": new_item})
        elif old_available and new_available and str(old_item.get("price", "")) != str(new_item.get("price", "")):
            changes.append({"type": "PRICE", "key": key, "before": old_item, "after": new_item})
    return changes


def date_label(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return value


def build_alert(watch: Dict[str, Any], changes: List[Dict[str, Any]]) -> str:
    lines = [
        "🚨 *BOOKMYSHOW ALERT*", "",
        f"🎬 *{watch.get('movie_name', 'Movie')}*",
        f"🎞 *{watch.get('combo', 'Any')}*",
        f"📅 *{date_label(watch.get('date', ''))}*", "",
    ]
    for change in changes:
        typ = change.get("type")
        after = change.get("after", {})
        before = change.get("before", {}) or {}
        if typ == "NEW": lines.append("🆕 *NEW SHOW AVAILABLE*")
        elif typ == "AVAILABLE": lines.append("🎟 *TICKETS NOW AVAILABLE*")
        elif typ == "PRICE":
            lines.append("💰 *PRICE CHANGED*")
            lines.append(f"Price: {before.get('price', '')} → {after.get('price', '')}")
        lines.append(f"🏢 {after.get('venue', 'Unknown Cinema')}")
        lines.append(f"🕐 {after.get('time', '')}")
        if after.get("screen"): lines.append(f"🎥 {after['screen']}")
        if after.get("category"): lines.append(f"💺 {after['category']}")
        if after.get("price"): lines.append(f"💵 {after['price']}")
        lines.append("")
    if watch.get("movie_url"):
        lines.append(f"🎫 {watch['movie_url']}")
    return "\n".join(lines)


def send_telegram(chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }, timeout=20)
    if not r.ok:
        log.error("Telegram response: %s", r.text[:1000])
    r.raise_for_status()


def main() -> None:
    watches_doc = load_json(WATCHES_FILE, {"watches": {}})
    watches = watches_doc.get("watches", {}) if isinstance(watches_doc, dict) else {}
    state_doc = load_json(STATE_FILE, {"watches": {}})
    states = state_doc.get("watches", {}) if isinstance(state_doc, dict) else {}

    if not watches:
        log.info("No active watches")
        return

    changed = False
    for watch_id, watch in list(watches.items()):
        if not watch.get("enabled", True):
            continue
        try:
            target_date = watch["date"]
            shows = bms_api.get_show_infos_for_date(
                watch["event_code"], watch["region_slug"], target_date, watch.get("combo")
            )
            shows = filter_venues(shows, watch)
            new_state = build_state(shows)

            previous = states.get(watch_id, {})
            old_state = previous.get("current_state", {})
            initialized = bool(previous.get("initialized", watch.get("initialized", False)))
            changes = [] if not initialized else detect_changes(old_state, new_state)

            if not initialized:
                log.info("INITIALIZED | watch=%s | state=%d", watch_id, len(new_state))
            elif changes:
                log.info("CHANGES | watch=%s | count=%d", watch_id, len(changes))
                send_telegram(int(watch["chat_id"]), build_alert(watch, changes))

            states[watch_id] = {
                "initialized": True,
                "current_state": new_state,
                "previous_state": old_state,
                "last_changes": changes,
                "poll_count": int(previous.get("poll_count", 0)) + 1,
                "last_polled_at": datetime.now().isoformat(),
            }
            changed = True
        except Exception as exc:
            log.exception("POLL FAILED | watch=%s", watch_id)
            previous = states.get(watch_id, {})
            states[watch_id] = {
                **previous,
                "last_changes": [{"type": "ERROR", "message": str(exc)}],
                "poll_count": int(previous.get("poll_count", 0)),
                "last_polled_at": datetime.now().isoformat(),
            }
            changed = True

    if changed:
        # Remove state for watches that have been stopped.
        states = {watch_id: value for watch_id, value in states.items() if watch_id in watches}
        save_json(STATE_FILE, {"watches": states})


if __name__ == "__main__":
    main()
