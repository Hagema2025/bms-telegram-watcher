from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

# ============================================================
# CONFIG
# ============================================================

API_URL = (
    "https://in.bookmyshow.com/api/movies-data/v4/"
    "showtimes-by-event/primary-dynamic"
)

BASE = "https://in.bookmyshow.com"

REGION_MAP = {
    "chennai": (
        "CHEN",
        "chennai",
        "13.056",
        "80.206",
        "tf3",
    ),
}


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class CatInfo:
    name: str
    price: str
    status: str


@dataclass
class ShowInfo:
    venue_name: str
    venue_code: str
    time: str
    screen_attr: str
    categories: List[CatInfo] = field(default_factory=list)
    language: str = ""
    movie_format: str = ""
    language_format_text: str = ""


@dataclass
class Venue:
    name: str
    showtimes: List[str] = field(default_factory=list)


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://in.bookmyshow.com/",
        "Origin": "https://in.bookmyshow.com",
        "Connection": "keep-alive",
    }
)


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def normalize_language(value: str) -> str:
    value = clean_text(value).lower()

    aliases = {
        "mal": "malayalam",
        "malayalam": "malayalam",
        "tam": "tamil",
        "tamil": "tamil",
        "tel": "telugu",
        "telugu": "telugu",
        "hin": "hindi",
        "hindi": "hindi",
        "eng": "english",
        "english": "english",
        "kan": "kannada",
        "kannada": "kannada",
        "bengali": "bengali",
        "marathi": "marathi",
        "punjabi": "punjabi",
        "gujarati": "gujarati",
    }

    return aliases.get(value, value)


def normalize_format(value: str) -> str:
    value = clean_text(value).lower()

    if "imax" in value:
        return "imax"

    if "4dx" in value:
        return "4dx"

    if "3d" in value:
        return "3d"

    if "2d" in value:
        return "2d"

    return value


def normalize_combo(combo: str) -> tuple[str, str]:
    combo = clean_text(combo)

    if " - " in combo:
        language, movie_format = combo.split(" - ", 1)
    elif "|" in combo:
        language, movie_format = combo.split("|", 1)
    else:
        language = combo
        movie_format = ""

    return (
        normalize_language(language),
        normalize_format(movie_format),
    )


def combo_display(language: str, movie_format: str) -> str:
    language = clean_text(language)
    movie_format = clean_text(movie_format)

    if not language and not movie_format:
        return ""

    if language and movie_format:
        return f"{language.title()} - {movie_format.upper()}"

    return language.title() if language else movie_format.upper()


# ============================================================
# DATE HELPERS
# ============================================================

def normalize_date_code(value: Any) -> str:
    if value is None:
        return datetime.now().strftime("%Y%m%d")

    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")

    if isinstance(value, date_type):
        return value.strftime("%Y%m%d")

    value = clean_text(value)

    if re.fullmatch(r"\d{8}", value):
        return value

    for fmt in (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(value, fmt).strftime("%Y%m%d")
        except ValueError:
            pass

    raise ValueError(f"Invalid date: {value}")


# ============================================================
# REGION
# ============================================================

def resolve_region(region: str):
    region = clean_text(region).lower()

    if region not in REGION_MAP:
        raise ValueError(
            f"Unsupported region '{region}'. "
            f"Available regions: {', '.join(REGION_MAP)}"
        )

    return REGION_MAP[region]


# ============================================================
# URL / MOVIE HELPERS
# ============================================================

def parse_movie_url(movie_url: str) -> Dict[str, str]:
    result = {
        "event_code": "",
        "region_slug": "",
        "movie_slug": "",
    }

    movie_url = clean_text(movie_url)

    if not movie_url:
        return result

    try:
        parsed = urlparse(movie_url)
        path = parsed.path.strip("/")

        parts = [p for p in path.split("/") if p]

        # Typical BMS URL:
        # /movies/.../movie-name/ETxxxxxx
        for part in parts:
            if re.fullmatch(r"ET\d+", part, re.I):
                result["event_code"] = part.upper()

        if parts:
            result["movie_slug"] = parts[-2] if len(parts) >= 2 else parts[-1]

    except Exception:
        log.exception("Failed to parse movie URL")

    print(result)

    return result


def movie_name_from_slug(slug: str) -> str:
    slug = clean_text(slug)

    if not slug:
        return ""

    slug = re.sub(r"-+", " ", slug)
    slug = re.sub(r"\s+", " ", slug)

    return slug.strip().title()


# ============================================================
# BMS HEADERS
# ============================================================

def _bms_headers(
    region_code: str,
    region_slug: str,
    geohash: str,
    lat: str,
    lon: str,
    event_code: str = "",
) -> Dict[str, str]:
    referer = "https://in.bookmyshow.com/"

    if event_code:
        referer = (
            f"https://in.bookmyshow.com/movies/"
            f"{region_slug}/movie/{event_code}"
        )

    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": session.headers["User-Agent"],
        "Referer": referer,
        "Origin": "https://in.bookmyshow.com",

        # Browser-like client headers
        "sec-ch-ua": (
            '"Chromium";v="145", '
            '"Google Chrome";v="145", '
            '"Not-A.Brand";v="99"'
        ),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',

        # BMS headers
        "x-app-code": "WEB",
        "x-geohash": geohash,
        "x-latitude": lat,
        "x-location-selection": "manual",
        "x-longitude": lon,
        "x-platform": "WEB",
        "x-platform-code": "WEB",
        "x-region-code": region_code,
        "x-region-slug": region_slug,
        "x-lsid": "",
    }


# ============================================================
# FETCH BMS
# ============================================================

def fetch_bms(
    event_code: str,
    region: str = "chennai",
    date_code: str = "",
    language: str = "",
    ref_event_code: str = "",
) -> Dict[str, Any]:
    date_code = normalize_date_code(date_code)

    (
        region_code,
        region_slug,
        lat,
        lon,
        geohash,
    ) = resolve_region(region)

    event_code = clean_text(event_code)
    language = clean_text(language)
    ref_event_code = clean_text(ref_event_code)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": (
            f"https://in.bookmyshow.com/movies/"
            f"{region_slug}/buytickets/{event_code}/"
        ),
        "sec-ch-ua": (
            '"Chromium";v="145", '
            '"Not:A-Brand";v="99"'
        ),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "x-app-code": "WEB",
        "x-region-code": region_code,
        "x-region-slug": region_slug,
        "x-geohash": geohash,
        "x-latitude": lat,
        "x-longitude": lon,
        "x-location-selection": "manual",
        "x-lsid": "",
    }

    params = {
        "eventCode": event_code,
        "dateCode": date_code or "",
        "isDesktop": "true",
        "regionCode": region_code,
        "xLocationShared": "false",
        "memberId": "",
        "lsId": "",
        "subCode": "",
        "lat": lat,
        "lon": lon,
    }

    log.info(
        "BMS FETCH | event=%s | region=%s | date=%s | "
        "language=%s | ref=%s",
        event_code,
        region_slug,
        date_code,
        language,
        ref_event_code,
    )

    log.info("BMS PARAMS | %s", params)

    try:
        response = session.get(
            API_URL,
            params=params,
            headers=headers,
            timeout=30,
        )

        log.info(
            "BMS RESPONSE | status=%s | url=%s",
            response.status_code,
            response.url,
        )

        if response.status_code != 200:
            body = response.text[:2000]

            log.error(
                "BMS ERROR | status=%s | body=%s",
                response.status_code,
                body,
            )

            raise RuntimeError(
                f"BMS returned HTTP {response.status_code}: {body}"
            )

        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(
                f"BMS returned invalid JSON: "
                f"{response.text[:1000]}"
            ) from exc

        return data

    except requests.RequestException as exc:
        log.exception("BMS REQUEST FAILED")
        raise RuntimeError(
            f"BMS request failed: {exc}"
        ) from exc
# ============================================================
# VARIANT HELPERS
# ============================================================

def _extract_variants(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    variants: List[Dict[str, Any]] = []

    def walk(obj: Any):
        if isinstance(obj, dict):
            # Common variant/event object
            if (
                "eventCode" in obj
                or "event_code" in obj
                or "etCode" in obj
            ):
                event_code = first_non_empty(
                    obj.get("eventCode"),
                    obj.get("event_code"),
                    obj.get("etCode"),
                )

                language = first_non_empty(
                    obj.get("language"),
                    obj.get("languageName"),
                    obj.get("lang"),
                )

                movie_format = first_non_empty(
                    obj.get("format"),
                    obj.get("formatName"),
                    obj.get("movieFormat"),
                    obj.get("eventFormat"),
                )

                disabled = obj.get("disabled")

                variants.append(
                    {
                        "event_code": event_code,
                        "language": language,
                        "format": movie_format,
                        "disabled": disabled,
                    }
                )

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    # Remove duplicates
    unique = []
    seen = set()

    for item in variants:
        key = (
            item.get("event_code", ""),
            normalize_language(item.get("language", "")),
            normalize_format(item.get("format", "")),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(item)

    return unique


def resolve_variant(
    event_code: str,
    combo: str,
    region: str = "chennai",
    date_code: str = "",
) -> Dict[str, str]:
    target_language, target_format = normalize_combo(combo)

    date_code = normalize_date_code(date_code)

    log.info(
        "RESOLVE VARIANT | event=%s | combo=%s | date=%s",
        event_code,
        combo,
        date_code,
    )

    data = fetch_bms(
        event_code=event_code,
        region=region,
        date_code=date_code,
    )

    variants = _extract_variants(data)

    log.info(
        "EVENT VARIANTS | %s",
        variants,
    )

    # Exact language + format
    for variant in variants:
        language = normalize_language(
            variant.get("language", "")
        )
        movie_format = normalize_format(
            variant.get("format", "")
        )

        if (
            language == target_language
            and movie_format == target_format
        ):
            selected = first_non_empty(
                variant.get("event_code"),
                event_code,
            )

            log.info(
                "VARIANT RESOLVED | combo=%s | event=%s | "
                "language=%s | ref=%s | disabled=%s | date=%s",
                combo,
                selected,
                language,
                selected,
                variant.get("disabled"),
                date_code,
            )

            return {
                "event_code": selected,
                "language": language,
                "ref_event_code": event_code,
            }

    # Language match if exact format wasn't found
    for variant in variants:
        language = normalize_language(
            variant.get("language", "")
        )

        if language == target_language:
            selected = first_non_empty(
                variant.get("event_code"),
                event_code,
            )

            log.info(
                "VARIANT LANGUAGE FALLBACK | combo=%s | event=%s",
                combo,
                selected,
            )

            return {
                "event_code": selected,
                "language": language,
                "ref_event_code": event_code,
            }

    # Original event fallback
    log.warning(
        "VARIANT NOT FOUND | combo=%s | using original event=%s",
        combo,
        event_code,
    )

    return {
        "event_code": event_code,
        "language": target_language,
        "ref_event_code": "",
    }


# ============================================================
# SHOW EXTRACTION HELPERS
# ============================================================

def _find_value(
    obj: Dict[str, Any],
    *keys: str,
) -> Any:
    for key in keys:
        if key in obj:
            return obj[key]

    lower_map = {
        str(k).lower(): v
        for k, v in obj.items()
    }

    for key in keys:
        if key.lower() in lower_map:
            return lower_map[key.lower()]

    return None


def _extract_categories(
    show: Dict[str, Any],
) -> List[CatInfo]:
    raw_categories = _find_value(
        show,
        "categories",
        "Categories",
        "categoriesList",
    )

    if not isinstance(raw_categories, list):
        return []

    categories: List[CatInfo] = []

    for category in raw_categories:
        if not isinstance(category, dict):
            continue

        name = first_non_empty(
            _find_value(
                category,
                "name",
                "areaName",
                "categoryName",
                "label",
            )
        )

        price = first_non_empty(
            _find_value(
                category,
                "price",
                "priceStr",
                "displayPrice",
                "amount",
            )
        )

        status = first_non_empty(
            _find_value(
                category,
                "status",
                "availability",
                "availabilityStatus",
                "bookingStatus",
            )
        )

        # Sometimes price is nested.
        if not price:
            price_obj = _find_value(
                category,
                "price",
                "ticketPrice",
            )

            if isinstance(price_obj, dict):
                price = first_non_empty(
                    price_obj.get("display"),
                    price_obj.get("amount"),
                    price_obj.get("value"),
                )

        categories.append(
            CatInfo(
                name=name,
                price=price,
                status=status,
            )
        )

    return categories


def _walk_possible_show_objects(
    obj: Any,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    if isinstance(obj, dict):
        # A show object generally contains time information.
        has_time = any(
            key in obj
            for key in (
                "showTime",
                "showtime",
                "showTimeStr",
                "startTime",
                "start_time",
                "showDateTime",
            )
        )

        has_venue = any(
            key in obj
            for key in (
                "venue",
                "venueName",
                "venue_name",
                "cinema",
                "cinemaName",
            )
        )

        if has_time and has_venue:
            results.append(obj)

        for value in obj.values():
            results.extend(
                _walk_possible_show_objects(value)
            )

    elif isinstance(obj, list):
        for item in obj:
            results.extend(
                _walk_possible_show_objects(item)
            )

    return results


def _parse_show(
    show: Dict[str, Any],
    default_language: str = "",
    default_format: str = "",
) -> Optional[ShowInfo]:
    venue_obj = _find_value(
        show,
        "venue",
        "cinema",
        "theatre",
    )

    venue_name = ""

    if isinstance(venue_obj, dict):
        venue_name = first_non_empty(
            _find_value(
                venue_obj,
                "name",
                "venueName",
                "cinemaName",
                "theatreName",
            )
        )

    if not venue_name:
        venue_name = first_non_empty(
            _find_value(
                show,
                "venueName",
                "cinemaName",
                "theatreName",
                "venue_name",
            )
        )

    venue_code = ""

    if isinstance(venue_obj, dict):
        venue_code = first_non_empty(
            _find_value(
                venue_obj,
                "code",
                "venueCode",
                "cinemaCode",
                "id",
            )
        )

    if not venue_code:
        venue_code = first_non_empty(
            _find_value(
                show,
                "venueCode",
                "cinemaCode",
                "theatreCode",
                "venue_code",
            )
        )

    time = first_non_empty(
        _find_value(
            show,
            "showTime",
            "showtime",
            "showTimeStr",
            "startTime",
            "start_time",
            "showDateTime",
        )
    )

    if not venue_name or not time:
        return None

    screen_attr = first_non_empty(
        _find_value(
            show,
            "screenAttr",
            "screen",
            "screenName",
            "screenAttribute",
            "attributes",
        )
    )

    language = first_non_empty(
        _find_value(
            show,
            "language",
            "languageName",
        ),
        default_language,
    )

    movie_format = first_non_empty(
        _find_value(
            show,
            "format",
            "formatName",
            "movieFormat",
        ),
        default_format,
    )

    language_format_text = combo_display(
        language,
        movie_format,
    )

    categories = _extract_categories(show)

    return ShowInfo(
        venue_name=venue_name,
        venue_code=venue_code,
        time=time,
        screen_attr=screen_attr,
        categories=categories,
        language=language,
        movie_format=movie_format,
        language_format_text=language_format_text,
    )


# ============================================================
# PARSE SHOWS
# ============================================================

def parse_show_infos(
    data: Dict[str, Any],
    language: str = "",
    movie_format: str = "",
) -> List[ShowInfo]:
    raw_shows = _walk_possible_show_objects(data)

    results: List[ShowInfo] = []

    seen = set()

    for raw_show in raw_shows:
        show = _parse_show(
            raw_show,
            default_language=language,
            default_format=movie_format,
        )

        if show is None:
            continue

        key = (
            show.venue_code,
            show.venue_name.lower(),
            show.time,
            show.screen_attr,
        )

        if key in seen:
            continue

        seen.add(key)
        results.append(show)

    results.sort(
        key=lambda item: (
            item.venue_name.lower(),
            item.time,
        )
    )

    log.info(
        "PARSER RESULT | shows=%s | combo=%s",
        len(results),
        combo_display(language, movie_format),
    )

    return results


# ============================================================
# GET SHOW INFOS FOR DATE
# ============================================================

def get_show_infos_for_date(
    event_code: str,
    region: str,
    date_code: str,
    combo: str,
) -> List[ShowInfo]:
    date_code = normalize_date_code(date_code)

    target_language, target_format = normalize_combo(combo)

    resolved = resolve_variant(
        event_code=event_code,
        combo=combo,
        region=region,
        date_code=date_code,
    )

    resolved_event = resolved.get(
        "event_code",
        event_code,
    )

    resolved_language = resolved.get(
        "language",
        target_language,
    )

    ref_event_code = resolved.get(
        "ref_event_code",
        "",
    )

    # --------------------------------------------------------
    # Primary request
    # --------------------------------------------------------

    try:
        data = fetch_bms(
            event_code=resolved_event,
            region=region,
            date_code=date_code,
            language=resolved_language,
            ref_event_code=ref_event_code,
        )

        shows = parse_show_infos(
            data,
            language=resolved_language,
            movie_format=target_format,
        )

        if shows:
            return shows

    except Exception:
        log.exception(
            "PRIMARY SHOW FETCH FAILED | event=%s",
            resolved_event,
        )

    # --------------------------------------------------------
    # Fallback without language
    # --------------------------------------------------------

    if resolved_language:
        try:
            log.info(
                "SHOW FETCH FALLBACK | removing language"
            )

            data = fetch_bms(
                event_code=resolved_event,
                region=region,
                date_code=date_code,
                language="",
                ref_event_code=ref_event_code,
            )

            shows = parse_show_infos(
                data,
                language=resolved_language,
                movie_format=target_format,
            )

            if shows:
                return shows

        except Exception:
            log.exception(
                "LANGUAGE FALLBACK FAILED | event=%s",
                resolved_event,
            )

    # --------------------------------------------------------
    # Original event fallback
    # --------------------------------------------------------

    if resolved_event != event_code:
        try:
            log.info(
                "SHOW FETCH FALLBACK | original event=%s",
                event_code,
            )

            data = fetch_bms(
                event_code=event_code,
                region=region,
                date_code=date_code,
                language="",
                ref_event_code="",
            )

            shows = parse_show_infos(
                data,
                language=target_language,
                movie_format=target_format,
            )

            if shows:
                return shows

        except Exception:
            log.exception(
                "ORIGINAL EVENT FALLBACK FAILED | event=%s",
                event_code,
            )

    return []


# ============================================================
# VENUE GROUPING
# ============================================================

def shows_to_venues(
    shows: List[ShowInfo],
) -> List[Venue]:
    grouped: Dict[str, Venue] = {}

    for show in shows:
        key = show.venue_name.strip().lower()

        if key not in grouped:
            grouped[key] = Venue(
                name=show.venue_name,
                showtimes=[],
            )

        if show.time not in grouped[key].showtimes:
            grouped[key].showtimes.append(show.time)

    venues = list(grouped.values())

    for venue in venues:
        venue.showtimes.sort()

    venues.sort(
        key=lambda item: item.name.lower()
    )

    return venues


# ============================================================
# DEBUG HELPERS
# ============================================================

def debug_event(
    event_code: str,
    region: str = "chennai",
    date_code: str = "",
    combo: str = "",
):
    date_code = normalize_date_code(date_code)

    log.info(
        "DEBUG EVENT | event=%s | region=%s | date=%s | combo=%s",
        event_code,
        region,
        date_code,
        combo,
    )

    shows = get_show_infos_for_date(
        event_code=event_code,
        region=region,
        date_code=date_code,
        combo=combo,
    )

    log.info(
        "DEBUG RESULT | shows=%s",
        len(shows),
    )

    for show in shows:
        log.info(
            "SHOW | venue=%s | code=%s | time=%s | "
            "screen=%s | language=%s | format=%s",
            show.venue_name,
            show.venue_code,
            show.time,
            show.screen_attr,
            show.language,
            show.movie_format,
        )

        for category in show.categories:
            log.info(
                "CATEGORY | name=%s | price=%s | status=%s",
                category.name,
                category.price,
                category.status,
            )

    return shows


# ============================================================
# MAIN DEBUG
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    EVENT = "ET00473215"
    REGION = "chennai"
    DATE = "20260904"
    COMBO = "Malayalam - 2D"

    debug_event(
        event_code=EVENT,
        region=REGION,
        date_code=DATE,
        combo=COMBO,
    )
