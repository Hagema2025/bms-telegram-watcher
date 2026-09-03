from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import uuid

import requests

from collections import defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any, Dict, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import bms_api


import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            body = b"OK"

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Keep Render logs clean
        return


def start_health_server():
    port = int(os.environ.get("PORT", 10000))

    server = HTTPServer(("0.0.0.0", port), HealthHandler)

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    print(f"Health server started on port {port}")
# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN environment variable is not set."
    )

GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_WATCHES_PATH = os.getenv("GITHUB_WATCHES_PATH", "data/watches.json")
GITHUB_STATE_PATH = os.getenv("GITHUB_STATE_PATH", "data/watcher_state.json")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")


if not GITHUB_REPO or not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_REPO and GITHUB_TOKEN environment variables are required.")

MAX_MESSAGE_LENGTH = 3800


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    ),
)

log = logging.getLogger(
    "bms-telegram-bot"
)


# ============================================================
# CONVERSATION STATES
# ============================================================

URL = 1
COMBO = 2
VENUE = 3
DATE = 4


# ============================================================
# GLOBAL CACHE
# ============================================================

USER_CACHE: Dict[int, Dict[str, Any]] = {}


# ============================================================
# GITHUB JSON STORAGE
# ============================================================

GITHUB_API_BASE = "https://api.github.com"

def _github_headers():
    return {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "bms-telegram-bot"}

def _github_get_file(path):
    r=requests.get(f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{path}",headers=_github_headers(),timeout=20)
    if r.status_code==404: return None,None
    r.raise_for_status(); payload=r.json(); raw=base64.b64decode(payload["content"]).decode("utf-8"); return json.loads(raw),payload.get("sha")

def _github_put_file(path,data,message):
    url=f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{path}"; content=json.dumps(data,indent=2,ensure_ascii=False)+"\n"
    for attempt in range(3):
        _,sha=_github_get_file(path); body={"message":message,"content":base64.b64encode(content.encode()).decode(),"branch":GITHUB_BRANCH}
        if sha: body["sha"]=sha
        r=requests.put(url,headers=_github_headers(),json=body,timeout=20)
        if r.status_code in (200,201): return
        if r.status_code==409 and attempt<2: continue
        r.raise_for_status()
    raise RuntimeError(f"Could not update GitHub file: {path}")

def load_watches():
    data,_=_github_get_file(GITHUB_WATCHES_PATH); return (data or {}).get("watches",{}) if isinstance(data or {},dict) else {}

def save_watches(watches):
    _github_put_file(GITHUB_WATCHES_PATH,{"watches":watches},"Update BMS watches"); log.info("WATCHES SAVED | count=%d",len(watches))

def load_watcher_state():
    data,_=_github_get_file(GITHUB_STATE_PATH); return (data or {}).get("watches",{}) if isinstance(data or {},dict) else {}

# RENDER HEALTH SERVER
# ============================================================

class HealthHandler(
    BaseHTTPRequestHandler
):

    def do_GET(self):

        if self.path in (
            "/",
            "/health",
        ):

            body = b"OK"

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/plain",
            )

            self.send_header(
                "Content-Length",
                str(len(body)),
            )

            self.end_headers()

            self.wfile.write(body)

        else:

            self.send_response(404)
            self.end_headers()

    def log_message(
        self,
        format,
        *args,
    ):
        return


def start_health_server():
    """
    Render Web Services require the application to listen
    on the PORT supplied by Render.
    """

    port = int(
        os.getenv(
            "PORT",
            "10000",
        )
    )

    server = ThreadingHTTPServer(
        (
            "0.0.0.0",
            port,
        ),
        HealthHandler,
    )

    thread = Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    log.info(
        "Health server listening on 0.0.0.0:%s",
        port,
    )


# ============================================================
# TEXT HELPERS
# ============================================================

def chunk_text(
    text: str,
    max_length: int = MAX_MESSAGE_LENGTH,
) -> List[str]:

    if not text:
        return [""]

    chunks = []

    while len(text) > max_length:

        split_at = text.rfind(
            "\n",
            0,
            max_length,
        )

        if split_at <= 0:
            split_at = text.rfind(
                " ",
                0,
                max_length,
            )

        if split_at <= 0:
            split_at = max_length

        chunks.append(
            text[:split_at]
        )

        text = text[split_at:].lstrip()

    if text:
        chunks.append(text)

    return chunks


def date_label(
    value: str,
) -> str:

    try:
        dt = datetime.strptime(
            value,
            "%Y-%m-%d",
        )

        return dt.strftime(
            "%a, %d %b"
        )

    except Exception:
        return value


# ============================================================
# TELEGRAM SAFE HELPERS
# ============================================================

async def safe_callback_answer(
    query,
    text: str = "",
    show_alert: bool = False,
):

    try:
        await query.answer(
            text=text,
            show_alert=show_alert,
        )

    except Exception:
        log.exception(
            "Callback answer failed"
        )

async def safe_edit_message_text(
    target,
    text: str,
    reply_markup=None,
    parse_mode=ParseMode.HTML,
    retries: int = 3,
):
    for attempt in range(retries):
        try:
            if hasattr(target, "edit_message_text"):
                await target.edit_message_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            else:
                await target.edit_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            return True

        except BadRequest as exc:
            # "Message is not modified" is harmless.
            if "message is not modified" in str(exc).lower():
                return True

            log.exception("Telegram edit failed")

            if attempt == retries - 1:
                return False

        except (TimedOut, NetworkError):
            if attempt == retries - 1:
                log.exception("Telegram edit failed")
                return False

            await asyncio.sleep(1.5 * (attempt + 1))

        except Exception:
            log.exception("Telegram edit failed")
            return False

    return False
async def send_chunks(
    chat,
    text: str,
    parse_mode=ParseMode.HTML,
):
    for chunk in chunk_text(text):
        try:
            if hasattr(chat, "send_message"):
                await chat.send_message(
                    text=chunk,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )
            else:
                await chat.reply_text(
                    text=chunk,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )
        except (TimedOut, NetworkError):
            log.exception("Telegram send failed")
            raise

# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    USER_CACHE[user_id] = {
        "pending": {},
    }

    text = (
        "🎬 *BookMyShow Chennai Watcher*\n\n"
        "Send me the BookMyShow movie URL.\n\n"
        "Example:\n"
        "`https://in.bookmyshow.com/movies/"
        "chennai/movie-name/ET00447840`"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
    )

    return URL


# ============================================================
# RECEIVE URL
# ============================================================

async def receive_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    url = (
        update.message.text or ""
    ).strip()

    try:
        parsed = bms_api.parse_bms_url(
            url
        )

    except Exception as exc:

        await update.message.reply_text(
            f"❌ Invalid BookMyShow URL.\n\n"
            f"`{exc}`",
            parse_mode=ParseMode.MARKDOWN,
        )

        return URL

    event_code = parsed[
        "event_code"
    ]

    region_slug = parsed[
        "region_slug"
    ]

    movie_slug = parsed.get(
        "movie_slug",
        "",
    )

    movie_name = (
        bms_api.movie_name_from_slug(
            movie_slug
        )
    )

    USER_CACHE[user_id] = {
        "pending": {
            "event_code": event_code,
            "region_slug": region_slug,
            "movie_slug": movie_slug,
            "movie_name": movie_name,
            "movie_url": url,
        }
    }

    status_message = await update.message.reply_text(
        "🔎 Checking BookMyShow...\n\n"
        "Please wait."
    )

    try:

        (
            region_code,
            sub_code,
            lat,
            lon,
            geohash,
        ) = bms_api.resolve_region(
            region_slug
        )

        data = await asyncio.to_thread(
            bms_api.fetch_bms,
            event_code,
            region_slug,
            datetime.now(),
            region_code,
            lat,
            lon,
            geohash,
            None,
            event_code,
        )

        variants = (
            bms_api.extract_event_variants(
                data
            )
        )

        if not variants:

            await safe_edit_message_text(
                status_message,
                "❌ No language / format variants "
                "were found for this movie.",
            )

            return URL

        keyboard = []

        for key, variant in variants.items():

            language = variant.get(
                "language",
                "",
            )

            movie_format = variant.get(
                "format",
                "",
            )

            disabled = bool(
                variant.get(
                    "disabled",
                    False,
                )
            )

            label = (
                f"{language} - "
                f"{movie_format}"
            )

            if disabled:
                label += " ⚠️"

            keyboard.append(
                [
                    InlineKeyboardButton(
                        label,
                        callback_data=(
                            f"combo|{key}"
                        ),
                    )
                ]
            )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "Any Language / Format",
                    callback_data="combo|ANY",
                )
            ]
        )

        await safe_edit_message_text(
            status_message,
            (
                f"🎬 *{movie_name}*\n\n"
                "Select language / format:"
            ),
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

        return COMBO

    except Exception as exc:

        log.exception(
            "URL processing failed"
        )

        await safe_edit_message_text(
            status_message,
            (
                "❌ Could not read BookMyShow.\n\n"
                f"`{exc}`"
            ),
        )

        return URL


# ============================================================
# COMBO CALLBACK
# ============================================================

async def combo_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await safe_callback_answer(
        query
    )

    user_id = query.from_user.id

    cache = USER_CACHE.get(
        user_id,
        {},
    )

    pending = cache.get(
        "pending",
        {},
    )

    if not pending:

        await safe_edit_message_text(
            query,
            "❌ Session expired. Please use /start.",
        )

        return ConversationHandler.END

    data = query.data or ""

    combo = data.split(
        "|",
        1,
    )[1]

    if combo.upper() == "ANY":
        combo = "Any"

    pending["combo"] = combo

    cache["pending"] = pending
    USER_CACHE[user_id] = cache

    keyboard = [
        [
            InlineKeyboardButton(
                "🎬 Any Cinema",
                callback_data="venue|any",
            )
        ],
        [
            InlineKeyboardButton(
                "🏢 Choose Cinemas",
                callback_data="venue|choose",
            )
        ],
    ]

    await safe_edit_message_text(
        query,
        (
            f"🎬 *{pending.get('movie_name', 'Movie')}*\n\n"
            f"Language / Format: *{combo}*\n\n"
            "Where should I watch?"
        ),
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )

    return VENUE


# ============================================================
# VENUE HELPERS
# ============================================================

def _venue_name_from_item(
    item: Any,
) -> str:

    if isinstance(
        item,
        str,
    ):
        return item

    if isinstance(
        item,
        dict,
    ):

        return str(
            item.get("name")
            or item.get("venue_name")
            or item.get("title")
            or ""
        ).strip()

    return ""


def _venue_code_from_item(
    item: Any,
) -> str:

    if isinstance(
        item,
        dict,
    ):

        return str(
            item.get("code")
            or item.get("venue_code")
            or item.get("id")
            or ""
        ).strip()

    return ""


def get_chennai_venues():
    from chennai_venues import CHENNAI_VENUES

    result = []

    for item in CHENNAI_VENUES:

        name = _venue_name_from_item(
            item
        )

        code = _venue_code_from_item(
            item
        )

        if name:
            result.append(
                {
                    "name": name,
                    "code": code,
                }
            )

    return result


def show_venue_list(
    query,
    page: int = 0,
):

    venues = get_chennai_venues()

    page_size = 8

    total_pages = max(
        1,
        (
            len(venues)
            + page_size
            - 1
        )
        // page_size,
    )

    page = max(
        0,
        min(
            page,
            total_pages - 1,
        ),
    )

    start_index = (
        page * page_size
    )

    page_items = venues[
        start_index:
        start_index + page_size
    ]

    keyboard = []

    for item in page_items:

        name = item["name"]

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"☐ {name}",
                    callback_data=(
                        f"vtoggle|{page}|{name}"
                    ),
                )
            ]
        )

    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅️ Previous",
                callback_data=(
                    f"vpage|{page - 1}"
                ),
            )
        )

    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                "Next ➡️",
                callback_data=(
                    f"vpage|{page + 1}"
                ),
            )
        )

    if nav:
        keyboard.append(nav)

    keyboard.append(
        [
            InlineKeyboardButton(
                "✅ Done",
                callback_data="venue|done",
            )
        ]
    )

    selected = USER_CACHE.get(
        query.from_user.id,
        {},
    ).get(
        "pending",
        {},
    ).get(
        "venues",
        [],
    )

    selected_text = (
        "\n".join(
            f"• {name}"
            for name in selected
        )
        if selected
        else "None selected"
    )

    text = (
        "🏢 *Choose cinemas*\n\n"
        f"Selected:\n{selected_text}\n\n"
        f"Page {page + 1}/{total_pages}"
    )

    return (
        text,
        InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# VENUE CALLBACK
# ============================================================

async def venue_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await safe_callback_answer(
        query
    )

    user_id = query.from_user.id

    cache = USER_CACHE.get(
        user_id,
        {},
    )

    pending = cache.get(
        "pending",
        {},
    )

    if not pending:

        await safe_edit_message_text(
            query,
            "❌ Session expired. Please use /start.",
        )

        return ConversationHandler.END

    data = query.data or ""

    # --------------------------------------------------------
    # Any Cinema
    # --------------------------------------------------------

    if data == "venue|any":

        pending["venue_mode"] = "any"
        pending["venues"] = []

        cache["pending"] = pending
        USER_CACHE[user_id] = cache

        return await show_dates(
            query,
            pending,
        )

    # --------------------------------------------------------
    # Choose cinemas
    # --------------------------------------------------------

    if data == "venue|choose":

        pending["venue_mode"] = "selected"

        if "venues" not in pending:
            pending["venues"] = []

        cache["pending"] = pending
        USER_CACHE[user_id] = cache

        text, markup = show_venue_list(
            query,
            0,
        )

        await safe_edit_message_text(
            query,
            text,
            reply_markup=markup,
        )

        return VENUE

    # --------------------------------------------------------
    # Venue page
    # --------------------------------------------------------

    if data.startswith(
        "vpage|"
    ):

        try:
            page = int(
                data.split(
                    "|",
                    1,
                )[1]
            )
        except Exception:
            page = 0

        text, markup = show_venue_list(
            query,
            page,
        )

        await safe_edit_message_text(
            query,
            text,
            reply_markup=markup,
        )

        return VENUE

    # --------------------------------------------------------
    # Venue toggle
    # --------------------------------------------------------

    if data.startswith(
        "vtoggle|"
    ):

        parts = data.split(
            "|",
            2,
        )

        if len(parts) < 3:
            return VENUE

        try:
            page = int(parts[1])
        except Exception:
            page = 0

        venue_name = parts[2]

        selected = pending.setdefault(
            "venues",
            [],
        )

        if venue_name in selected:
            selected.remove(
                venue_name
            )
        else:
            selected.append(
                venue_name
            )

        cache["pending"] = pending
        USER_CACHE[user_id] = cache

        text, markup = show_venue_list(
            query,
            page,
        )

        await safe_edit_message_text(
            query,
            text,
            reply_markup=markup,
        )

        return VENUE

    # --------------------------------------------------------
    # Done
    # --------------------------------------------------------

    if data == "venue|done":

        selected = pending.get(
            "venues",
            [],
        )

        if not selected:

            await safe_callback_answer(
                query,
                "Select at least one cinema.",
                show_alert=True,
            )

            return VENUE

        pending["venue_mode"] = "selected"

        cache["pending"] = pending
        USER_CACHE[user_id] = cache

        return await show_dates(
            query,
            pending,
        )

    return VENUE


# ============================================================
# DATE SELECTION
# ============================================================

async def show_dates(
    query,
    pending: Dict[str, Any],
):

    today = datetime.now().date()

    keyboard = []

    for offset in range(7):

        target = today + timedelta(
            days=offset
        )

        date_code = target.strftime(
            "%Y-%m-%d"
        )

        label = target.strftime(
            "%a, %d %b"
        )

        if offset == 0:
            label += " — Today"

        keyboard.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=(
                        f"date|{date_code}"
                    ),
                )
            ]
        )

    await safe_edit_message_text(
        query,
        (
            f"🎬 *{pending.get('movie_name', 'Movie')}*\n\n"
            f"Format: *{pending.get('combo', 'Any')}*\n"
            f"Cinema: *"
            f"{'Any Cinema' if pending.get('venue_mode') == 'any' else 'Selected Cinemas'}"
            f"*\n\n"
            "📅 Select date:"
        ),
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )

    return DATE


# ============================================================
# VENUE FILTERING
# ============================================================

def filter_venues(
    shows,
    pending: Dict[str, Any],
):

    if pending.get(
        "venue_mode"
    ) == "any":
        return shows

    selected = [
        str(x).strip().lower()
        for x in pending.get(
            "venues",
            [],
        )
    ]

    if not selected:
        return []

    result = []

    for show in shows:

        actual = (
            str(
                show.venue_name
            )
            .strip()
            .lower()
        )

        matched = any(
            name in actual
            or actual in name
            for name in selected
        )

        if matched:
            result.append(
                show
            )

    return result


# ============================================================
# BUILD STATE
# ============================================================

STATUS_TEXT = {
    "0": "SOLD OUT",
    "1": "ALMOST FULL",
    "2": "FILLING FAST",
    "3": "AVAILABLE",
}


def is_available_status(
    status: Any,
) -> bool:

    value = str(
        status or ""
    ).strip().lower()

    return value in {
        "3",
        "available",
        "avail",
        "available_now",
        "bookable",
    }


def build_state(
    shows,
) -> Dict[str, Any]:

    state: Dict[str, Any] = {}

    for show in shows:

        for category in show.categories:

            key = (
                f"{show.venue_code}|"
                f"{show.time}|"
                f"{show.language_format_text}|"
                f"{category.name}"
            )

            state[key] = {
                "venue": show.venue_name,
                "venue_code": show.venue_code,
                "time": show.time,
                "screen": show.screen_attr,
                "language": show.language,
                "format": show.movie_format,
                "language_format": (
                    show.language_format_text
                ),
                "category": category.name,
                "price": category.price,
                "status": category.status,
                "available": is_available_status(
                    category.status
                ),
            }

    return state


# ============================================================
# CHANGE DETECTION
# ============================================================

def detect_changes(
    old_state: Dict[str, Any],
    new_state: Dict[str, Any],
) -> List[Dict[str, Any]]:

    changes = []

    # --------------------------------------------------------
    # New available shows/categories
    # --------------------------------------------------------

    for key, new_item in new_state.items():

        old_item = old_state.get(
            key
        )

        if old_item is None:

            if new_item.get(
                "available"
            ):

                changes.append(
                    {
                        "type": "NEW",
                        "key": key,
                        "before": None,
                        "after": new_item,
                    }
                )

            continue

        old_available = bool(
            old_item.get(
                "available"
            )
        )

        new_available = bool(
            new_item.get(
                "available"
            )
        )

        # ----------------------------------------------------
        # Sold out -> available
        # ----------------------------------------------------

        if (
            not old_available
            and new_available
        ):

            changes.append(
                {
                    "type": "AVAILABLE",
                    "key": key,
                    "before": old_item,
                    "after": new_item,
                }
            )

        # ----------------------------------------------------
        # Price changed while available
        # ----------------------------------------------------

        elif (
            old_available
            and new_available
            and str(
                old_item.get("price", "")
            )
            != str(
                new_item.get("price", "")
            )
        ):

            changes.append(
                {
                    "type": "PRICE",
                    "key": key,
                    "before": old_item,
                    "after": new_item,
                }
            )

    return changes


# ============================================================
# WATCH CREATED MESSAGE
# ============================================================

def build_watch_created_message(
    watch: Dict[str, Any],
) -> str:

    venue_text = (
        "Any Cinema"
        if watch.get(
            "venue_mode"
        ) == "any"
        else "\n".join(
            f"• {x}"
            for x in watch.get(
                "venues",
                [],
            )
        )
    )

    return (
        "✅ *Watch created!*\n\n"
        f"🎬 *{watch.get('movie_name', 'Movie')}*\n"
        f"🎞 Format: *{watch.get('combo', 'Any')}*\n"
        f"📅 Date: *{date_label(watch.get('date', ''))}*\n"
        f"🏢 Cinema:\n{venue_text}\n\n"
        f"🆔 Watch ID: `{watch.get('id')}`\n\n"
        "⏱ The GitHub checker will check BookMyShow every *~5 minutes*.\n\n"
        "You will receive an alert when tickets become "
        "available or a new matching show appears."
    )


# ============================================================
# DATE CALLBACK
# ============================================================

async def date_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await safe_callback_answer(
        query
    )

    user_id = query.from_user.id

    cache = USER_CACHE.get(
        user_id,
        {},
    )

    pending = cache.get(
        "pending",
        {},
    )

    if not pending:

        await safe_edit_message_text(
            query,
            "❌ Session expired. Please use /start.",
        )

        return ConversationHandler.END

    data = query.data or ""

    try:
        target_date = data.split(
            "|",
            1,
        )[1]
    except Exception:

        await safe_edit_message_text(
            query,
            "❌ Invalid date."
        )

        return DATE

    try:
        datetime.strptime(
            target_date,
            "%Y-%m-%d",
        )

    except ValueError:

        await safe_edit_message_text(
            query,
            "❌ Invalid date."
        )

        return DATE

    checking_text = (
        "📝 Creating watch...\n\n"
        f"Date: *{date_label(target_date)}*\n"
        "The GitHub checker will perform the first BookMyShow check."
    )

    await safe_edit_message_text(query, checking_text)

    try:
        # Render only manages the bot. BMS polling happens in GitHub Actions.
        state = {}
        watch_id = uuid.uuid4().hex[:8]

        now = datetime.now().isoformat()

        watch = {
            "id": watch_id,
            "user_id": user_id,
            "chat_id": query.message.chat_id,

            "event_code": pending[
                "event_code"
            ],

            "region_slug": pending[
                "region_slug"
            ],

            "movie_name": pending.get(
                "movie_name",
                "Movie",
            ),

            "movie_url": pending.get(
                "movie_url",
                "",
            ),

            "combo": pending.get(
                "combo",
                "Any",
            ),

            "date": target_date,

            "venue_mode": pending.get(
                "venue_mode",
                "any",
            ),

            "venues": pending.get(
                "venues",
                [],
            ),

            "last_state": state,

            "previous_state": state,

            "current_state": state,

            "last_changes": [],

            "initialized": False,

            "created_at": now,

            "poll_count": 0,

            "last_polled_at": None,
        }

        watches[watch_id] = watch

        save_watches(
            watches
        )

        await safe_edit_message_text(
            query,
            build_watch_created_message(
                watch
            ),
        )

        USER_CACHE.pop(
            user_id,
            None,
        )

        return ConversationHandler.END

    except Exception as exc:

        log.exception(
            "Failed to create watch"
        )

        await safe_edit_message_text(
            query,
            (
                "❌ Could not create watch.\n\n"
                f"`{exc}`"
            ),
        )

        return DATE


# ============================================================
# ALERT
# ============================================================

def build_alert(
    watch: Dict[str, Any],
    changes: List[Dict[str, Any]],
) -> str:

    lines = [
        "🚨 *BOOKMYSHOW ALERT*",
        "",
        f"🎬 *{watch.get('movie_name', 'Movie')}*",
        f"🎞 *{watch.get('combo', 'Any')}*",
        f"📅 *{date_label(watch.get('date', ''))}*",
        "",
    ]

    for change in changes:

        change_type = change.get(
            "type"
        )

        after = change.get(
            "after",
            {},
        )

        before = change.get(
            "before",
            {},
        )

        venue = after.get(
            "venue",
            "Unknown Cinema",
        )

        time = after.get(
            "time",
            "",
        )

        category = after.get(
            "category",
            "",
        )

        price = after.get(
            "price",
            "",
        )

        screen = after.get(
            "screen",
            "",
        )

        if change_type == "NEW":

            lines.append(
                "🆕 *NEW SHOW AVAILABLE*"
            )

        elif change_type == "AVAILABLE":

            lines.append(
                "🎟 *TICKETS NOW AVAILABLE*"
            )

        elif change_type == "PRICE":

            lines.append(
                "💰 *PRICE CHANGED*"
            )

            lines.append(
                f"Price: "
                f"{before.get('price', '')}"
                f" → {price}"
            )

        lines.append(
            f"🏢 {venue}"
        )

        lines.append(
            f"🕐 {time}"
        )

        if screen:
            lines.append(
                f"🎥 {screen}"
            )

        if category:
            lines.append(
                f"💺 {category}"
            )

        if price:
            lines.append(
                f"💵 {price}"
            )

        lines.append("")

    if watch.get(
        "movie_url"
    ):
        lines.append(
            f"🎫 {watch['movie_url']}"
        )

    return "\n".join(
        lines
    )


# ============================================================
# /WATCHES
# ============================================================

async def watches_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    global watches
    watches = load_watches()
    states = load_watcher_state()

    if not watches:

        await update.message.reply_text(
            (
                "📭 *No active watches.*\n\n"
                "Use /start to create one."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        return

    lines = [
        "👀 *ACTIVE WATCHES*",
        "",
        f"Total: *{len(watches)}*",
        "⏱ Checker interval: *~5 minutes*",
        "",
    ]

    for watch_id, watch in watches.items():

        venue_text = (
            "Any Cinema"
            if watch.get(
                "venue_mode"
            ) == "any"
            else ", ".join(
                watch.get(
                    "venues",
                    [],
                )
            )
        )

        lines.extend(
            [
                f"🆔 `{watch_id}`",
                f"🎬 {watch.get('movie_name', 'Movie')}",
                f"🎞 {watch.get('combo', 'Any')}",
                f"📅 {date_label(watch.get('date', ''))}",
                f"🏢 {venue_text}",
                f"🔄 Checks: {states.get(watch_id, {}).get('poll_count', 0)}",
                (
                    f"🕐 Last check: "
                    f"{states.get(watch_id, {}).get('last_polled_at') or 'Not yet'}"
                ),
                "",
            ]
        )

    lines.extend(
        [
            "Use:",
            "`/stop WATCH_ID`",
            "",
            "Watches stay active after alerts. Use "
            "`/stop WATCH_ID` when you no longer need one.",
        ]
    )

    await send_chunks(
        update.message,
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================
# /STOP
# ============================================================

async def stop_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not context.args:

        await update.message.reply_text(
            (
                "Usage:\n"
                "`/stop WATCH_ID`"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        return

    watch_id = (
        context.args[0]
        .strip()
    )

    watch = watches.get(
        watch_id
    )

    if not watch:

        await update.message.reply_text(
            f"❌ Watch `{watch_id}` not found.",
            parse_mode=ParseMode.MARKDOWN,
        )

        return

    # Only allow the owner to stop their watch.
    if int(
        watch.get("user_id", 0)
    ) != int(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "❌ You cannot stop another user's watch."
        )

        return

    watches.pop(
        watch_id,
        None,
    )

    save_watches(
        watches
    )

    await update.message.reply_text(
        (
            f"🛑 Watch `{watch_id}` stopped.\n\n"
            f"🎬 {watch.get('movie_name', 'Movie')}"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================
# /CANCEL
# ============================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    USER_CACHE.pop(
        update.effective_user.id,
        None,
    )

    await update.message.reply_text(
        "❌ Cancelled."
    )

    return ConversationHandler.END


# ============================================================
# NOOP
# ============================================================

async def noop(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await safe_callback_answer(
        query
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    log.exception(
        "Unhandled Telegram error",
        exc_info=context.error,
    )


# ============================================================
# GLOBAL WATCH STORAGE
# ============================================================

watches: Dict[
    str,
    Dict[str, Any],
] = {}


# ============================================================
# MAIN
# ============================================================

def main():

    global watches

    # --------------------------------------------------------
    # Start Render health endpoint first.
    # --------------------------------------------------------

    start_health_server()

    # --------------------------------------------------------
    # Initialize/load Supabase.
    # --------------------------------------------------------

    watches = load_watches()

    # --------------------------------------------------------
    # Telegram application.
    # --------------------------------------------------------

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # Conversation.
    # --------------------------------------------------------

    conversation_handler = (
        ConversationHandler(
            entry_points=[
                CommandHandler(
                    "start",
                    start,
                )
            ],

            states={
                URL: [
                    MessageHandler(
                        filters.TEXT
                        & ~filters.COMMAND,
                        receive_url,
                    )
                ],

                COMBO: [
                    CallbackQueryHandler(
                        combo_callback,
                        pattern=r"^combo\|",
                    )
                ],

                VENUE: [
                    CallbackQueryHandler(
                        venue_callback,
                        pattern=r"^(venue|vtoggle|vpage)\|",
                    )
                ],

                DATE: [
                    CallbackQueryHandler(
                        date_callback,
                        pattern=r"^date\|",
                    )
                ],
            },

            fallbacks=[
                CommandHandler(
                    "cancel",
                    cancel,
                )
            ],

            per_message=False,
        )
    )

    application.add_handler(
        conversation_handler
    )

    # --------------------------------------------------------
    # Other commands.
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "watches",
            watches_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "stop",
            stop_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            noop,
            pattern=r"^noop$",
        )
    )

    application.add_error_handler(
        error_handler
    )

    # BMS polling is handled by GitHub Actions every ~5 minutes.

    # --------------------------------------------------------
    # Telegram long polling.
    # --------------------------------------------------------

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    start_health_server()

    main()
