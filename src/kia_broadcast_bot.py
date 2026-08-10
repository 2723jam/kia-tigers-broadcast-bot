from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter


KST = ZoneInfo("Asia/Seoul")
KBO_DAILY_SCHEDULE_URL = "https://eng.koreabaseball.com/Schedule/DailySchedule.aspx"
KBO_KOREAN_SCHEDULE_URL = "https://www.koreabaseball.com/Schedule/Schedule.aspx"
KBO_GAME_LIST_URL = "https://www.koreabaseball.com/ws/Main.asmx/GetKboGameList"
KT_CHANNEL_GUIDE_URL = "https://tv.kt.com/"
TELEGRAM_API_BASE_URL = "https://api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 15
USER_AGENT = "kia-broadcast-bot/1.0"
FIRST_CHECK_TIME = time(10, 0)
ROOT_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = Path(
    os.environ.get(
        "BOT_STATE_DIR",
        (
            "/tmp/kia_broadcast_bot_state"
            if os.environ.get("VERCEL")
            else str(ROOT_DIR / ".bot_state")
        ),
    )
)
COMMAND_STATE_PATH = STATE_DIR / "telegram_updates.json"
KBO_GAME_LIST_SERIES_IDS = "0,1,3,4,5,6,7,8,9"

CHANNEL_MAP = {
    "S-T": "SBS",
    "K-2T": "KBS2",
    "K-1T": "KBS1",
    "M-T": "MBC",
    "JTBC-T": "JTBC",
    "JTBC": "JTBC",
    "SPO-T": "SPOTV",
    "SPO-2T": "SPOTV2",
    "SS-T": "SBS SPORTS",
    "KN-T": "KBS N SPORTS",
    "MS-T": "MBC SPORTS+",
    "SBS": "SBS",
    "KBS2": "KBS2",
    "KBS 2TV": "KBS2",
    "KBS1": "KBS1",
    "KBS 1TV": "KBS1",
    "MBC": "MBC",
    "MBC TV": "MBC",
    "SPOTV": "SPOTV",
    "SPOTV2": "SPOTV2",
    "SBS SPORTS": "SBS SPORTS",
    "KBS N SPORTS": "KBS N SPORTS",
    "KBS N PSORTS": "KBS N SPORTS",
    "MBC SPORTS+": "MBC SPORTS+",
    "KBS LIFE": "KBS LIFE",
}

OLLEH_CHANNEL_MAP = {
    "SBS": ("SBS", "5"),
    "KBS2": ("KBS2", "7"),
    "KBS1": ("KBS1", "9"),
    "MBC": ("MBC", "11"),
    "JTBC": ("JTBC", "15"),
    "SPOTV": ("SPOTV", "51"),
    "SPOTV2": ("SPOTV2", "52"),
    "SBS SPORTS": ("SBS SPORTS", "58"),
    "KBS N SPORTS": ("KBS N SPORTS", "59"),
    "MBC SPORTS+": ("MBC SPORTS+", "60"),
    "KBS LIFE": ("KBS LIFE", "158"),
}

TEAM_ALIASES = {
    "KIA": ["KIA TIGERS", "KIA 타이거즈", "기아타이거즈", "KIA", "기아"],
    "KIWOOM": ["KIWOOM HEROES", "키움히어로즈", "KIWOOM", "키움"],
    "LG": ["LG TWINS", "LG트윈스", "LG", "엘지"],
    "DOOSAN": ["DOOSAN BEARS", "두산베어스", "DOOSAN", "두산"],
    "SAMSUNG": ["SAMSUNG LIONS", "삼성라이온즈", "SAMSUNG", "삼성"],
    "SSG": ["SSG LANDERS", "SSG랜더스", "SSG", "에스에스지"],
    "NC": ["NC DINOS", "NC다이노스", "NC", "엔씨"],
    "LOTTE": ["LOTTE GIANTS", "롯데자이언츠", "LOTTE", "롯데"],
    "HANWHA": ["HANWHA EAGLES", "한화이글스", "HANWHA", "한화"],
    "KT": ["KT WIZ", "KT위즈", "KT", "케이티"],
}

TEAM_DISPLAY_NAMES = {
    "KIA": "KIA",
    "KIWOOM": "키움",
    "LG": "LG",
    "DOOSAN": "두산",
    "SAMSUNG": "삼성",
    "SSG": "SSG",
    "NC": "NC",
    "LOTTE": "롯데",
    "HANWHA": "한화",
    "KT": "KT",
}

KBO_TEAM_ID_MAP = {
    "HT": "KIA",
    "WO": "KIWOOM",
    "LG": "LG",
    "OB": "DOOSAN",
    "SS": "SAMSUNG",
    "SK": "SSG",
    "NC": "NC",
    "LT": "LOTTE",
    "HH": "HANWHA",
    "KT": "KT",
}

LOCATION_MAP = {
    "JAMSIL": "잠실",
    "DAEGU": "대구",
    "MUNHAK": "문학",
    "GWANGJU": "광주",
    "GOCHEOKSKY": "고척",
    "GOCHEOK": "고척",
    "SAJIK": "사직",
    "CHANGWON": "창원",
    "DAEJEON": "대전",
    "SUWON": "수원",
    "POHANG": "포항",
    "ULSAN": "울산",
}

VALID_SEASON_TYPES = {"정규시즌", "WC", "준PO", "PO", "KS"}
STATUS_KEYWORDS = (
    "POSTPONED",
    "CANCELLED",
    "CANCELED",
    "DELAYED",
    "RAIN",
    "DUST",
    "WEATHER",
    "취소",
    "연기",
    "지연",
    "우천",
    "미세먼지",
    "기상",
)

TEAM_PATTERN = re.compile(
    r"(?<![A-Za-z0-9가-힣])("
    + "|".join(
        re.escape(alias)
        for aliases in TEAM_ALIASES.values()
        for alias in sorted(aliases, key=len, reverse=True)
    )
    + r")(?![A-Za-z0-9가-힣])",
    re.IGNORECASE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
HTTP_SESSION = requests.Session()
HTTP_SESSION.mount("https://", HTTPAdapter(pool_connections=8, pool_maxsize=8))
HTTP_SESSION.mount("http://", HTTPAdapter(pool_connections=8, pool_maxsize=8))


def get_now_kst() -> datetime:
    return datetime.now(tz=KST)


def get_today_kst() -> date:
    return get_now_kst().date()


def fetch_kbo_daily_schedule() -> str:
    headers = {"User-Agent": USER_AGENT}
    try:
        response = HTTP_SESSION.get(
            KBO_DAILY_SCHEDULE_URL,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        if response.apparent_encoding:
            response.encoding = response.apparent_encoding
        return response.text
    except requests.RequestException as exc:
        raise RuntimeError(f"KBO daily schedule fetch failed: {exc}") from exc


def fetch_kbo_game_list(target_date: date | str) -> list[dict[str, Any]]:
    game_date = _coerce_date(target_date)
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": KBO_KOREAN_SCHEDULE_URL,
        "X-Requested-With": "XMLHttpRequest",
    }
    data = {
        "leId": "1",
        "srId": KBO_GAME_LIST_SERIES_IDS,
        "date": game_date.strftime("%Y%m%d"),
    }

    try:
        response = HTTP_SESSION.post(
            KBO_GAME_LIST_URL,
            data=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"KBO game list fetch failed: {exc}") from exc

    return payload.get("game") or []


@lru_cache(maxsize=1)
def fetch_olleh_channel_guide() -> dict[str, tuple[str, str]]:
    headers = {"User-Agent": USER_AGENT}
    try:
        response = HTTP_SESSION.get(
            KT_CHANNEL_GUIDE_URL,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        if response.apparent_encoding:
            response.encoding = response.apparent_encoding
    except requests.RequestException as exc:
        raise RuntimeError(f"KT channel guide fetch failed: {exc}") from exc

    return _parse_olleh_channel_guide(response.text)


def parse_kbo_schedule(html_text: str, target_date: date | str) -> list[dict[str, Any]]:
    parsed_target_date = _coerce_date(target_date)
    soup = BeautifulSoup(html_text or "", "html.parser")

    games = _parse_table_schedule(soup, parsed_target_date)
    if not games:
        games = _parse_text_schedule(soup.get_text("\n"), parsed_target_date)
    return games


def filter_valid_season_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [game for game in games if game.get("season_type") in VALID_SEASON_TYPES]


def find_kia_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kia_games = []
    for game in games:
        teams = game.get("teams") or []
        game_text = game.get("game_text", "")
        if any(_is_kia_team(team) for team in teams) or _contains_kia(game_text):
            kia_games.append(dict(game))
    return kia_games


def sort_games_by_time(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_games = sorted(
        (dict(game) for game in games),
        key=lambda game: (_time_sort_value(game.get("time")), game.get("source_order", 0)),
    )

    is_doubleheader = len(sorted_games) >= 2
    for index, game in enumerate(sorted_games, start=1):
        existing_label = _clean_line(game.get("game_label"))
        game["game_order"] = index
        if is_doubleheader:
            game["game_label"] = f"DH {index}차"
            game["dh_label"] = game["game_label"]
        elif existing_label.startswith("DH "):
            game["game_label"] = existing_label
            game["dh_label"] = existing_label
        else:
            game["game_label"] = "단일경기"
            game["dh_label"] = ""
        game["game_key"] = _build_game_key(game)
    return sorted_games


def get_kia_games_from_kbo_game_list(
    kbo_game_list: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    games = _games_from_kbo_game_list(kbo_game_list)
    games = filter_valid_season_games(games)
    return sort_games_by_time(find_kia_games(games))


def enrich_games_with_starting_pitchers(
    games: list[dict[str, Any]], target_date: date | str
) -> list[dict[str, Any]]:
    if not games:
        return []

    try:
        kbo_game_list = fetch_kbo_game_list(target_date)
    except RuntimeError as exc:
        logger.warning("%s", exc)
        return [dict(game) for game in games]

    return _merge_kbo_game_list(games, kbo_game_list)


def normalize_channel(tv_text: str | None) -> str:
    parts = _split_channel_parts(tv_text)
    if not parts:
        return "확인 필요"

    formatted_parts = [_format_olleh_channel(part) for part in parts]
    if any(formatted == part for part, formatted in zip(parts, formatted_parts)):
        try:
            guide = fetch_olleh_channel_guide()
        except RuntimeError as exc:
            logger.warning("%s", exc)
            guide = {}
        formatted_parts = [_format_olleh_channel(part, guide) for part in parts]

    deduped_parts: list[str] = []
    seen_parts: set[str] = set()
    for part in formatted_parts:
        dedupe_key = _canonical_channel_key(part)
        if dedupe_key in seen_parts:
            continue
        seen_parts.add(dedupe_key)
        deduped_parts.append(part)
    return ", ".join(deduped_parts)


def normalize_game_snapshot(game: dict[str, Any]) -> dict[str, Any]:
    status_reason = _normalize_status_reason(game.get("status_reason") or game.get("etc"))
    starter_matchup = _format_starting_pitcher_matchup(game)
    return {
        "date": _date_to_str(game.get("date")),
        "season_type": game.get("season_type") or "",
        "game_label": game.get("game_label") or "단일경기",
        "opponent": _display_team(game.get("opponent")) or "상대팀 확인 필요",
        "matchup": _format_matchup(game),
        "starting_pitchers": starter_matchup,
        "game_text": _clean_line(game.get("game_text")),
        "time": _display_value(game.get("time")),
        "location": _display_location(game.get("location")),
        "tv": normalize_channel(game.get("tv")),
        "status_reason": status_reason or "-",
    }


def make_snapshot_hash(snapshot: dict[str, Any]) -> str:
    watched_snapshot = {
        "time": snapshot.get("time") or "",
        "tv": snapshot.get("tv") or "",
        "status_reason": snapshot.get("status_reason") or "",
    }
    if snapshot.get("starting_pitchers"):
        watched_snapshot["starting_pitchers"] = snapshot.get("starting_pitchers") or ""
    payload = json.dumps(watched_snapshot, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_state(state_date: date | str) -> dict[str, Any]:
    path = _state_path(state_date)
    if not path.exists():
        return _empty_state(state_date)

    try:
        with path.open("r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("State file could not be read; starting fresh: %s", exc)
        return _empty_state(state_date)

    default_state = _empty_state(state_date)
    default_state.update(state)
    default_state["games_by_key"] = state.get("games_by_key") or {}
    return default_state


def save_state(state_date: date | str, state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _state_path(state_date)
    temp_path = path.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
    temp_path.replace(path)


def _games_before_start(
    now: datetime, games: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    now_kst = now.astimezone(KST)
    unstarted_games = []

    for game in sort_games_by_time(games):
        start_at = _game_start_datetime(game)
        status_reason = normalize_game_snapshot(game).get("status_reason")
        if start_at and now_kst >= start_at and not _is_disrupted_status(status_reason):
            logger.info("Skip started game for initial: %s", game.get("game_key"))
            continue
        unstarted_games.append(game)

    return unstarted_games


def should_send_initial(
    now: datetime, games: list[dict[str, Any]], state: dict[str, Any]
) -> bool:
    if not games:
        return False
    if state.get("first_sent"):
        return False
    if not _games_before_start(now, games):
        return False
    return now.astimezone(KST).time() >= FIRST_CHECK_TIME


def get_changed_games_before_start(
    now: datetime, games: list[dict[str, Any]], state: dict[str, Any]
) -> list[dict[str, Any]]:
    changed_games = []
    now_kst = now.astimezone(KST)
    games_by_key = state.get("games_by_key") or {}

    for game in sort_games_by_time(games):
        game_key = game.get("game_key")
        fallback_game_key = _build_fallback_game_key(game)
        previous_entry = (
            games_by_key.get(game_key) or games_by_key.get(fallback_game_key) or {}
        )
        current_snapshot = normalize_game_snapshot(game)
        previous_snapshot = previous_entry.get("last_snapshot") or {}
        start_at = _game_start_datetime(game)
        if (
            start_at
            and now_kst >= start_at
            and not _is_disrupted_status(current_snapshot.get("status_reason"))
            and not _is_disrupted_status(previous_snapshot.get("status_reason"))
        ):
            logger.info("Skip started game: %s", game.get("game_key"))
            continue

        current_hash = make_snapshot_hash(current_snapshot)
        previous_hash = previous_entry.get("last_sent_hash")

        if previous_hash == current_hash:
            continue

        changed_game = dict(game)
        changed_game["_previous_snapshot"] = previous_entry.get("last_snapshot") or {}
        changed_game["_current_snapshot"] = current_snapshot
        changed_game["_current_hash"] = current_hash
        changed_game["_change_number"] = int(previous_entry.get("resend_count") or 0) + 1
        changed_games.append(changed_game)

    return changed_games


def build_initial_message(games: list[dict[str, Any]]) -> str:
    sorted_games = sort_games_by_time(games)
    is_doubleheader = len(sorted_games) >= 2 or any(
        _clean_line(game.get("game_label")).startswith("DH ") for game in sorted_games
    )
    sections = [_build_initial_section(game, is_doubleheader) for game in sorted_games]
    sections.append("※ 편성 및 경기 진행 여부는 변경될 수 있습니다.")
    return "\n\n".join(sections)


def build_today_reply_message(games: list[dict[str, Any]]) -> str:
    if not games:
        return "오늘은 KIA 타이거즈 경기가 없습니다."
    return build_initial_message(games)


def build_change_message(
    changed_games: list[dict[str, Any]], state: dict[str, Any]
) -> str:
    _ = state
    sorted_changed_games = sorted(
        changed_games,
        key=lambda game: (_time_sort_value(game.get("time")), game.get("source_order", 0)),
    )
    return "\n\n".join(_build_change_section(game) for game in sorted_changed_games)


def send_telegram_message(text: str, chat_id: str | int | None = None) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    target_chat_id = str(chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
    if not token or not target_chat_id:
        logger.error("Telegram secrets are missing; message was not sent.")
        return False

    url = f"{TELEGRAM_API_BASE_URL}/bot{token}/sendMessage"
    payload = _build_telegram_send_message_payload(
        text, target_chat_id, include_method=False
    )
    headers = {"User-Agent": USER_AGENT}

    try:
        response = HTTP_SESSION.post(
            url,
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.error("Telegram send failed: %s", exc)
        return False

    if not body.get("ok"):
        logger.error("Telegram API returned not ok: %s", body.get("description", body))
        return False
    return True


def _build_telegram_send_message_payload(
    text: str, chat_id: str | int | None = None, include_method: bool = True
) -> dict[str, Any]:
    target_chat_id = str(chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
    payload: dict[str, Any] = {
        "chat_id": target_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if include_method:
        payload["method"] = "sendMessage"
    return payload


def run_scheduled_check() -> int:
    now = get_now_kst()
    today = now.date()
    state = load_state(today)

    games: list[dict[str, Any]] = []
    daily_schedule_error: RuntimeError | None = None
    try:
        schedule_html = fetch_kbo_daily_schedule()
        games = get_kia_games_for_date(schedule_html, today)
    except RuntimeError as exc:
        daily_schedule_error = exc
        logger.warning("%s", exc)

    if not games:
        try:
            games = get_kia_games_from_kbo_game_list(fetch_kbo_game_list(today))
        except RuntimeError as exc:
            logger.error("KBO game list fallback failed: %s", exc)
            if daily_schedule_error is not None:
                return 1

    logger.info("Found %d KIA game(s) for %s", len(games), today.isoformat())

    initial_games = _games_before_start(now, games)

    if should_send_initial(now, initial_games, state):
        message = build_initial_message(initial_games)
        if send_telegram_message(message):
            state["first_sent"] = True
            state["no_game_sent"] = False
            _record_sent_games(state, initial_games, now, initial=True)
            _save_after_successful_send(today, state)
            logger.info("Initial message sent.")
            return 0
        logger.error("Initial message could not be sent.")
        return 1

    if games and state.get("first_sent"):
        changed_games = get_changed_games_before_start(now, games, state)
        if changed_games:
            message = build_change_message(changed_games, state)
            if send_telegram_message(message):
                _record_sent_games(state, changed_games, now, initial=False)
                _save_after_successful_send(today, state)
                logger.info("Change message sent for %d game(s).", len(changed_games))
                return 0
            logger.error("Change message could not be sent.")
            return 1
        else:
            logger.info("No changes before game start.")
        return 0

    if not games:
        return 0 if _maybe_send_no_game_message(today, now, state) else 1

    logger.info("Initial message is not due yet.")
    return 0


def run_command_polling() -> int:
    command_state = load_command_state()
    last_update_id = command_state.get("last_update_id")
    offset = int(last_update_id) + 1 if last_update_id is not None else None

    try:
        updates = fetch_telegram_updates(offset=offset)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    if not updates:
        logger.info("No Telegram command updates.")
        return 0

    highest_processed_id = int(last_update_id) if last_update_id is not None else -1
    for update in updates:
        update_id = update.get("update_id")
        if update_id is None:
            continue

        if not process_telegram_update(update):
            logger.error("Telegram update was not fully processed: %s", update_id)
            return 1

        highest_processed_id = max(highest_processed_id, int(update_id))

    command_state["last_update_id"] = highest_processed_id
    command_state["last_checked_at_kst"] = get_now_kst().isoformat(timespec="seconds")
    save_command_state(command_state)
    logger.info("Processed Telegram updates through %s.", highest_processed_id)
    return 0


def fetch_telegram_updates(offset: int | None = None) -> list[dict[str, Any]]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing.")

    params: dict[str, Any] = {
        "timeout": 0,
        "allowed_updates": json.dumps(["message"]),
    }
    if offset is not None:
        params["offset"] = offset

    try:
        response = HTTP_SESSION.get(
            f"{TELEGRAM_API_BASE_URL}/bot{token}/getUpdates",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 409:
            logger.info("Telegram webhook is active; skipping getUpdates polling.")
            return []
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"Telegram getUpdates failed: {exc}") from exc

    if not payload.get("ok"):
        raise RuntimeError(f"Telegram getUpdates returned not ok: {payload}")
    return payload.get("result") or []


def process_telegram_update(update: dict[str, Any]) -> bool:
    message = update.get("message") or {}
    text = _clean_line(message.get("text"))
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if not text or chat_id is None:
        return True

    if not _is_allowed_chat(chat_id):
        logger.warning("Ignoring Telegram command from unauthorized chat_id=%s", chat_id)
        return True

    if _is_today_command(text):
        return send_today_reply(chat_id)

    return True


def build_telegram_webhook_response(update: dict[str, Any]) -> dict[str, Any] | None:
    message = update.get("message") or {}
    text = _clean_line(message.get("text"))
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if not text or chat_id is None:
        return None

    if not _is_allowed_chat(chat_id):
        logger.warning("Ignoring Telegram command from unauthorized chat_id=%s", chat_id)
        return None

    if _is_today_command(text):
        return _build_telegram_send_message_payload(
            build_today_reply_text(), chat_id=chat_id
        )
    return None


def build_today_reply_text() -> str:
    today = get_today_kst()
    try:
        kbo_game_list = fetch_kbo_game_list(today)
        if kbo_game_list:
            games = get_kia_games_from_kbo_game_list(kbo_game_list)
            return build_today_reply_message(games)
        logger.info("KBO game list was empty; falling back to daily schedule.")
    except RuntimeError as exc:
        logger.warning("Fast KBO game list path failed; falling back: %s", exc)

    try:
        schedule_html = fetch_kbo_daily_schedule()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return "KBO 일정 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."

    games = get_kia_games_for_date(schedule_html, today)
    return build_today_reply_message(games)


def send_today_reply(chat_id: str | int) -> bool:
    return send_telegram_message(build_today_reply_text(), chat_id=chat_id)


def get_kia_games_for_date(schedule_html: str, target_date: date | str) -> list[dict[str, Any]]:
    parsed_target_date = _coerce_date(target_date)
    games = parse_kbo_schedule(schedule_html, parsed_target_date)
    games = filter_valid_season_games(games)
    games = sort_games_by_time(find_kia_games(games))
    games = enrich_games_with_starting_pitchers(games, parsed_target_date)
    return sort_games_by_time(games)


def load_command_state() -> dict[str, Any]:
    if not COMMAND_STATE_PATH.exists():
        return {"last_update_id": None, "last_checked_at_kst": None}

    try:
        with COMMAND_STATE_PATH.open("r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Command state file could not be read; starting fresh: %s", exc)
        return {"last_update_id": None, "last_checked_at_kst": None}

    return {
        "last_update_id": state.get("last_update_id"),
        "last_checked_at_kst": state.get("last_checked_at_kst"),
    }


def save_command_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = COMMAND_STATE_PATH.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
    temp_path.replace(COMMAND_STATE_PATH)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("scheduled", "commands"),
        default=os.environ.get("BOT_MODE", "scheduled"),
    )
    args = parser.parse_args()

    if args.mode == "commands":
        return run_command_polling()
    return run_scheduled_check()


def cleanup_old_state_files(retention_days: int = 30, today: date | None = None) -> None:
    if not STATE_DIR.exists():
        return

    base_date = today or get_today_kst()
    cutoff = base_date - timedelta(days=retention_days)
    for path in STATE_DIR.glob("kia_*.json"):
        match = re.fullmatch(r"kia_(\d{4}-\d{2}-\d{2})\.json", path.name)
        if not match:
            continue
        try:
            file_date = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if file_date < cutoff:
            path.unlink(missing_ok=True)


def _parse_table_schedule(soup: BeautifulSoup, target_date: date) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    source_order = 0

    for table in soup.find_all("table"):
        table_text = _clean_line(table.get_text(" "))
        upper_text = table_text.upper()
        if not all(label in upper_text for label in ("DATE", "TIME", "GAME")):
            continue

        current_date: date | None = None
        current_season_text = ""

        for row in table.find_all("tr"):
            cells = [_clean_cell(cell) for cell in row.find_all(["th", "td"])]
            if not any(cells):
                continue

            if _is_header_row(cells):
                continue

            row_date = _extract_date_from_text(cells[0], target_date.year)
            rest = cells
            if row_date:
                current_date = row_date
                rest = cells[1:]
            elif rest and not rest[0] and current_date:
                rest = rest[1:]

            if rest and _looks_like_season(rest[0]):
                current_season_text = rest[0]
                rest = rest[1:]
            elif rest and not rest[0] and current_season_text:
                rest = rest[1:]

            if current_date != target_date:
                continue

            split_game = _parse_split_game_cells(rest)
            if split_game:
                time_text, game_text, tv_text, location, etc = split_game
            elif len(rest) >= 6:
                time_text, game_text, tv_text, _radio, location, etc = rest[:6]
            elif len(rest) >= 5:
                time_text, game_text, tv_text, location, etc = rest[:5]
            else:
                continue

            source_order += 1
            games.append(
                _make_game(
                    game_date=current_date,
                    season_text=current_season_text,
                    time_text=time_text,
                    game_text=game_text,
                    tv_text=tv_text,
                    location=location,
                    etc=etc,
                    source_order=source_order,
                    game_id=_extract_game_id(row),
                )
            )

    return games


def _parse_text_schedule(text: str, target_date: date) -> list[dict[str, Any]]:
    lines = [_clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    games: list[dict[str, Any]] = []
    current_date: date | None = None
    current_season_text = ""
    source_order = 0
    index = 0

    while index < len(lines):
        line = lines[index]
        date_match = re.match(
            r"^(?P<date>\d{2}\.\d{2}\([^)]+\))\s+(?P<season>\S+)\s+(?P<rest>.+)$",
            line,
        )
        if date_match:
            current_date = _extract_date_from_text(
                date_match.group("date"), target_date.year
            )
            current_season_text = date_match.group("season")
            line = date_match.group("rest")
        elif _looks_like_time_line(line) and current_date:
            pass
        else:
            index += 1
            continue

        if not _looks_like_time_line(line):
            index += 1
            continue

        continuation: list[str] = []
        lookahead = index + 1
        while lookahead < len(lines):
            next_line = lines[lookahead]
            if re.match(r"^\d{2}\.\d{2}\([^)]+\)\s+", next_line) or _looks_like_time_line(
                next_line
            ):
                break
            continuation.append(next_line)
            lookahead += 1

        if current_date == target_date:
            parsed = _parse_text_game_line(
                current_date=current_date,
                season_text=current_season_text,
                line=line,
                continuation=continuation,
                source_order=source_order + 1,
            )
            if parsed:
                source_order += 1
                games.append(parsed)
        index = lookahead

    return games


def _parse_text_game_line(
    current_date: date,
    season_text: str,
    line: str,
    continuation: list[str],
    source_order: int,
) -> dict[str, Any] | None:
    time_match = re.match(r"^(?P<time>\d{1,2}:\d{2})\s+(?P<body>.+)$", line)
    if not time_match:
        return None

    body = time_match.group("body")
    teams = _extract_teams(body)
    if len(teams) < 2:
        return None

    first_team_position = _team_position(body, teams[0])
    second_team_position = _team_position(body, teams[1], start=first_team_position + 1)
    if first_team_position < 0 or second_team_position < 0:
        game_text = body
        tv_text = ""
    else:
        second_team_end = second_team_position + len(teams[1])
        game_text = body[:second_team_end].strip()
        tv_text = body[second_team_end:].strip()

    location = ""
    etc = ""
    extra_tv_lines = list(continuation)
    if extra_tv_lines and not _looks_like_channel_only(extra_tv_lines[-1]):
        location_line = extra_tv_lines.pop()
        location, etc = _split_location_etc(location_line)

    if extra_tv_lines:
        tv_text = "\n".join([tv_text, *extra_tv_lines]).strip()

    return _make_game(
        game_date=current_date,
        season_text=season_text,
        time_text=time_match.group("time"),
        game_text=game_text,
        tv_text=tv_text,
        location=location,
        etc=etc,
        source_order=source_order,
        game_id=None,
    )


def _parse_split_game_cells(rest: list[str]) -> tuple[str, str, str, str, str] | None:
    if len(rest) < 8:
        return None
    if not _parse_time(rest[0]):
        return None

    away_team = _canonical_team(rest[1])
    home_team = _canonical_team(rest[3])
    if away_team not in TEAM_ALIASES or home_team not in TEAM_ALIASES:
        return None

    score_or_vs = _clean_line(rest[2]) or ":"
    if score_or_vs.upper() in {"VS", "V"}:
        score_or_vs = ":"

    return (
        rest[0],
        f"{away_team} {score_or_vs} {home_team}",
        rest[4],
        rest[6],
        rest[7],
    )


def _make_game(
    game_date: date,
    season_text: str,
    time_text: str,
    game_text: str,
    tv_text: str,
    location: str,
    etc: str,
    source_order: int,
    game_id: str | None,
) -> dict[str, Any]:
    teams = _extract_teams(game_text)
    opponent = _find_kia_opponent(teams)
    away_team = teams[0] if len(teams) >= 1 else ""
    home_team = teams[1] if len(teams) >= 2 else ""
    return {
        "date": game_date,
        "season_raw": _clean_line(season_text),
        "season_type": _normalize_season_type(season_text),
        "time": _clean_line(time_text),
        "game_text": _clean_line(game_text),
        "teams": teams,
        "away_team": away_team,
        "home_team": home_team,
        "opponent": opponent,
        "tv": _clean_multiline(tv_text),
        "location": _clean_line(location),
        "etc": _clean_line(etc),
        "status_reason": _normalize_status_reason(etc, game_text),
        "source_order": source_order,
        "official_game_id": game_id,
    }


def _merge_kbo_game_list(
    games: list[dict[str, Any]], kbo_game_list: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    parsed_rows = _parse_kbo_game_list_rows(kbo_game_list)
    if not parsed_rows:
        return [dict(game) for game in games]

    enriched_games: list[dict[str, Any]] = []
    used_row_indexes: set[int] = set()
    for game in games:
        enriched_game = dict(game)
        match_index = _find_matching_kbo_game_row(
            enriched_game, parsed_rows, used_row_indexes
        )
        if match_index is not None:
            used_row_indexes.add(match_index)
            _apply_kbo_game_row(enriched_game, parsed_rows[match_index])
        enriched_games.append(enriched_game)
    return enriched_games


def _games_from_kbo_game_list(kbo_game_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    parsed_rows = _parse_kbo_game_list_rows(kbo_game_list)
    for source_order, row in enumerate(parsed_rows, start=1):
        game_text = f"{row['away_team']} : {row['home_team']}"
        games.append(
            {
                "date": row["date"],
                "season_raw": row.get("season_raw") or "",
                "season_type": row.get("season_type") or "",
                "time": row.get("time") or "",
                "game_text": game_text,
                "teams": row.get("teams") or [],
                "away_team": row.get("away_team") or "",
                "home_team": row.get("home_team") or "",
                "opponent": row.get("opponent") or "",
                "tv": row.get("tv") or "",
                "location": row.get("location") or "",
                "etc": row.get("status_reason") or "-",
                "status_reason": row.get("status_reason") or "-",
                "source_order": source_order,
                "official_game_id": row.get("official_game_id") or "",
                "away_pitcher": row.get("away_pitcher") or "",
                "home_pitcher": row.get("home_pitcher") or "",
                "starting_pitchers_checked": True,
            }
        )
    return games


def _parse_kbo_game_list_rows(
    kbo_game_list: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in kbo_game_list:
        game_date = _parse_kbo_yyyymmdd(row.get("G_DT"))
        away_team = _canonical_team_from_kbo_row(row, "AWAY")
        home_team = _canonical_team_from_kbo_row(row, "HOME")
        if not game_date or not away_team or not home_team:
            continue

        status_reason = _normalize_kbo_game_status(row)
        rows.append(
            {
                "date": game_date,
                "season_raw": _clean_line(row.get("GAME_SC_NM")),
                "season_type": _normalize_kbo_season_type(row),
                "time": _clean_line(row.get("G_TM")),
                "official_game_id": _clean_line(row.get("G_ID")),
                "away_team": away_team,
                "home_team": home_team,
                "teams": [away_team, home_team],
                "opponent": _find_kia_opponent([away_team, home_team]),
                "away_pitcher": _clean_line(row.get("T_PIT_P_NM")),
                "home_pitcher": _clean_line(row.get("B_PIT_P_NM")),
                "location": _clean_line(row.get("S_NM")),
                "tv": _clean_multiline(row.get("TV_IF")),
                "status_reason": status_reason,
                "header_no": row.get("HEADER_NO"),
                "game_state": row.get("GAME_STATE_SC"),
            }
        )
    return rows


def _find_matching_kbo_game_row(
    game: dict[str, Any],
    parsed_rows: list[dict[str, Any]],
    used_row_indexes: set[int],
) -> int | None:
    official_game_id = _clean_line(game.get("official_game_id"))
    if official_game_id:
        for index, row in enumerate(parsed_rows):
            if (
                index not in used_row_indexes
                and row.get("official_game_id") == official_game_id
            ):
                return index

    game_date = _date_to_str(game.get("date"))
    game_teams = set(game.get("teams") or [])
    if not game_teams:
        game_teams = {
            _canonical_team(game.get("away_team") or ""),
            _canonical_team(game.get("home_team") or ""),
        }
        game_teams.discard("")

    candidates: list[tuple[int, dict[str, Any]]] = []
    for index, row in enumerate(parsed_rows):
        if index in used_row_indexes:
            continue
        if _date_to_str(row.get("date")) != game_date:
            continue
        if "KIA" not in row.get("teams", []):
            continue
        row_teams = set(row.get("teams") or [])
        if game_teams and not game_teams.issubset(row_teams):
            continue
        candidates.append((index, row))

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0][0]

    game_time = _display_value(game.get("time"))
    game_location = _display_location(game.get("location"))
    game_order = int(game.get("game_order") or 0)
    scored_candidates: list[tuple[int, int]] = []
    for index, row in candidates:
        score = 0
        if row.get("time") and row.get("time") == game_time:
            score += 4
        if row.get("location") and row.get("location") == game_location:
            score += 3
        if game_order and _clean_line(row.get("header_no")) == str(game_order):
            score += 2
        scored_candidates.append((score, index))

    scored_candidates.sort(reverse=True)
    best_score, best_index = scored_candidates[0]
    if best_score > 0:
        return best_index

    if game_order:
        ordered_candidates = sorted(
            candidates,
            key=lambda item: (
                _time_sort_value(item[1].get("time")),
                int(item[1].get("header_no") or 0),
            ),
        )
        if 1 <= game_order <= len(ordered_candidates):
            return ordered_candidates[game_order - 1][0]
    return None


def _apply_kbo_game_row(game: dict[str, Any], row: dict[str, Any]) -> None:
    game["official_game_id"] = row.get("official_game_id") or game.get("official_game_id")
    game["away_team"] = row.get("away_team") or game.get("away_team")
    game["home_team"] = row.get("home_team") or game.get("home_team")
    game["teams"] = row.get("teams") or game.get("teams")
    game["opponent"] = row.get("opponent") or game.get("opponent")
    game["away_pitcher"] = row.get("away_pitcher") or ""
    game["home_pitcher"] = row.get("home_pitcher") or ""
    game["starting_pitchers_checked"] = True

    if not _clean_line(game.get("tv")) and row.get("tv"):
        game["tv"] = row["tv"]
    if not _clean_line(game.get("location")) and row.get("location"):
        game["location"] = row["location"]
    if row.get("status_reason") not in {"", "-"}:
        game["status_reason"] = row["status_reason"]


def _canonical_team_from_kbo_row(row: dict[str, Any], side: str) -> str:
    team_id = _clean_line(row.get(f"{side}_ID")).upper()
    if team_id in KBO_TEAM_ID_MAP:
        return KBO_TEAM_ID_MAP[team_id]
    return _canonical_team(row.get(f"{side}_NM") or team_id)


def _normalize_kbo_game_status(row: dict[str, Any]) -> str:
    cancel_status = _clean_line(row.get("CANCEL_SC_NM"))
    game_status = _clean_line(row.get("GAME_SC_NM"))
    if cancel_status and cancel_status not in {"정상경기", "정규경기"}:
        return cancel_status
    if game_status and game_status not in {"정상경기", "정규경기"}:
        return game_status
    return "-"


def _normalize_kbo_season_type(row: dict[str, Any]) -> str:
    text = " ".join(
        _clean_line(row.get(key))
        for key in ("GAME_SC_NM", "SERIES_NM", "ROUND_NM", "G_NM")
        if _clean_line(row.get(key))
    )
    normalized = _normalize_season_type(text)
    if normalized in VALID_SEASON_TYPES:
        return normalized

    sr_id = _clean_line(row.get("SR_ID"))
    if sr_id == "0":
        return "정규시즌"
    return normalized


def _parse_kbo_yyyymmdd(value: Any) -> date | None:
    text = _clean_line(value)
    if not re.fullmatch(r"\d{8}", text):
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _parse_olleh_channel_guide(html_text: str) -> dict[str, tuple[str, str]]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    guide: dict[str, tuple[str, str]] = {}
    for raw_line in soup.get_text("\n").splitlines():
        line = _clean_line(raw_line)
        match = re.match(r"^(?P<number>\d{1,3})\s+(?P<name>.+)$", line)
        if not match:
            continue

        number = match.group("number")
        name = re.sub(r"\s+(?:U|유료)$", "", match.group("name")).strip()
        if not name:
            continue

        channel_info = (name, number)
        guide[_canonical_channel_key(name)] = channel_info
        guide[_canonical_channel_key(_canonical_channel_name(name))] = channel_info
    return guide


def _normalize_season_type(season_text: str | None) -> str:
    text = _clean_line(season_text).upper().replace("-", " ")
    compact = re.sub(r"\s+", "", text)
    if not text:
        return ""
    if "REGULAR" in text or "정규" in text:
        return "정규시즌"
    if "WILD" in text or compact in {"WC", "와일드카드"}:
        return "WC"
    if "SEMI" in text or "준" in text or compact in {"준PO", "준플레이오프"}:
        return "준PO"
    if "KOREAN" in text or compact in {"KS", "한국시리즈"}:
        return "KS"
    if "PLAYOFF" in text or compact in {"PO", "플레이오프"}:
        return "PO"
    return _clean_line(season_text)


def _normalize_status_reason(*values: str | None) -> str:
    for index, value in enumerate(values):
        text = _clean_line(value)
        if not text or text == "-":
            continue

        upper_text = text.upper()
        if index == 0:
            return text
        if any(keyword in upper_text or keyword in text for keyword in STATUS_KEYWORDS):
            return text
    return "-"


def _is_disrupted_status(value: Any) -> bool:
    text = _clean_line(value)
    if not text or text == "-":
        return False

    upper_text = text.upper()
    return any(
        keyword in upper_text or keyword in text for keyword in STATUS_KEYWORDS
    )


def _split_channel_parts(tv_text: str | None) -> list[str]:
    raw = _clean_multiline(tv_text)
    if not raw or raw == "-":
        return []

    chunks = [
        _clean_line(chunk)
        for chunk in re.split(r"[\n,/]+", raw)
        if _clean_line(chunk)
    ]
    parts: list[str] = []
    for chunk in chunks:
        tokens = chunk.split()
        if len(tokens) >= 2 and all(token.upper() in CHANNEL_MAP for token in tokens):
            parts.extend(tokens)
        else:
            parts.append(chunk)
    return parts


def _extract_teams(game_text: str | None) -> list[str]:
    if not game_text:
        return []

    teams = []
    for match in TEAM_PATTERN.finditer(game_text):
        canonical = _canonical_team(match.group(1))
        if canonical and canonical not in teams:
            teams.append(canonical)
        if len(teams) == 2:
            break
    return teams


def _canonical_team(team_text: str) -> str:
    normalized = _clean_line(team_text).upper()
    for canonical, aliases in TEAM_ALIASES.items():
        if normalized in {alias.upper() for alias in aliases}:
            return canonical
    return normalized


def _find_kia_opponent(teams: list[str]) -> str:
    if not any(_is_kia_team(team) for team in teams):
        return ""
    for team in teams:
        if not _is_kia_team(team):
            return team
    return ""


def _is_kia_team(team_text: str | None) -> bool:
    return _canonical_team(team_text or "") == "KIA"


def _contains_kia(text: str | None) -> bool:
    return any(_is_kia_team(team) for team in _extract_teams(text or ""))


def _is_today_command(text: str) -> bool:
    first_token = _clean_line(text).split(maxsplit=1)[0].lower()
    command = first_token.split("@", 1)[0]
    return command == "/today"


def _is_allowed_chat(chat_id: str | int) -> bool:
    allowed_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not allowed_chat_id:
        return True
    return str(chat_id).strip() == allowed_chat_id


def _build_game_key(game: dict[str, Any]) -> str:
    official_game_id = _clean_line(game.get("official_game_id"))
    if official_game_id:
        return f"official:{official_game_id}"
    return _build_fallback_game_key(game)


def _build_fallback_game_key(game: dict[str, Any]) -> str:
    date_part = _date_to_str(game.get("date"))
    opponent = _clean_line(game.get("opponent")) or "UNKNOWN"
    location = _clean_line(game.get("location")) or "UNKNOWN"
    label = _clean_line(game.get("game_label")) or "단일경기"
    return f"{date_part}|KIA|{opponent}|{location}|{label}"


def _record_sent_games(
    state: dict[str, Any],
    games: list[dict[str, Any]],
    now: datetime,
    initial: bool,
) -> None:
    state.setdefault("games_by_key", {})
    for game in games:
        game_key = game.get("game_key") or _build_game_key(game)
        fallback_game_key = _build_fallback_game_key(game)
        snapshot = game.get("_current_snapshot") or normalize_game_snapshot(game)
        snapshot_hash = game.get("_current_hash") or make_snapshot_hash(snapshot)
        previous_entry = (
            state["games_by_key"].get(game_key)
            or state["games_by_key"].get(fallback_game_key)
            or {}
        )
        resend_count = (
            int(previous_entry.get("resend_count") or 0)
            if initial
            else int(game.get("_change_number") or 1)
        )
        state["games_by_key"][game_key] = {
            "game_key": game_key,
            "last_sent_hash": snapshot_hash,
            "resend_count": resend_count,
            "last_snapshot": snapshot,
        }
        if fallback_game_key != game_key:
            state["games_by_key"].pop(fallback_game_key, None)
    state["last_sent_at_kst"] = now.astimezone(KST).isoformat(timespec="seconds")


def _maybe_send_no_game_message(
    today: date, now: datetime, state: dict[str, Any]
) -> bool:
    send_no_game = os.environ.get("SEND_NO_GAME", "").strip().lower() == "true"
    if not send_no_game:
        logger.info("No KIA game today; SEND_NO_GAME is not true.")
        return True
    if state.get("no_game_sent"):
        logger.info("No-game message already sent today.")
        return True
    if now.astimezone(KST).time() < FIRST_CHECK_TIME:
        logger.info("No-game message is not due yet.")
        return True

    if send_telegram_message("오늘은 KIA 타이거즈 경기가 없습니다."):
        state["no_game_sent"] = True
        state["last_sent_at_kst"] = now.astimezone(KST).isoformat(timespec="seconds")
        _save_after_successful_send(today, state)
        logger.info("No-game message sent.")
        return True

    logger.error("No-game message could not be sent.")
    return False


def _save_after_successful_send(today: date, state: dict[str, Any]) -> None:
    cleanup_old_state_files(today=today)
    save_state(today, state)


def _build_initial_section(game: dict[str, Any], is_doubleheader: bool) -> str:
    snapshot = normalize_game_snapshot(game)
    lines = []
    if is_doubleheader:
        lines.append(_escape(f"<더블헤더 {snapshot['game_label']}>"))
    lines.extend(
        [
            "🐯 KIA 타이거즈 중계 알림",
            f"📅 날짜: {_escape(snapshot['date'])}",
            f"⚾ 경기: {_escape(snapshot['matchup'])}",
            f"🕡 시간: {_escape(snapshot['time'])}",
            f"🏟 구장: {_escape(snapshot['location'])}",
            f"📺 TV 중계: {_escape(snapshot['tv'])}",
            "📱 온라인: TVING KBO",
            f"🔗 KBO 일정: <a href=\"{html.escape(KBO_KOREAN_SCHEDULE_URL, quote=True)}\">KBO 경기일정/결과 보기</a>",
        ]
    )
    if snapshot["status_reason"] not in {"", "-"}:
        lines.append(f"📌 상태/사유: {_escape(snapshot['status_reason'])}")
    return "\n".join(lines)


def _build_change_section(game: dict[str, Any]) -> str:
    previous = game.get("_previous_snapshot") or {}
    current = game.get("_current_snapshot") or normalize_game_snapshot(game)
    change_number = int(game.get("_change_number") or 1)
    change_lines = _build_change_lines(previous, current)

    lines = [
        "🚨 KIA 타이거즈 중계/경기 변동 알림",
        f"변경차수: {change_number}차",
        f"대상경기: {_escape(current.get('game_label') or '단일경기')}",
        "변경항목:",
    ]
    lines.extend(change_lines)
    lines.extend(
        [
            "",
            "현재 기준:",
            f"📅 날짜: {_escape(current['date'])}",
            f"⚾ 경기: {_escape(current['matchup'])}",
            f"🕡 시간: {_escape(current['time'])}",
            f"🏟 구장: {_escape(current['location'])}",
            f"📺 TV 중계: {_escape(current['tv'])}",
            f"📌 상태/사유: {_escape(current['status_reason'])}",
        ]
    )
    return "\n".join(lines)


def _build_change_lines(
    previous: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    field_map = (
        ("time", "경기시간"),
        ("starting_pitchers", "선발투수"),
        ("tv", "TV 중계"),
        ("status_reason", "경기상태/사유"),
    )
    lines = []
    for key, label in field_map:
        if key == "starting_pitchers" and not (
            previous.get(key) or current.get(key)
        ):
            continue
        previous_value = previous.get(key) or "확인 불가"
        current_value = current.get(key) or "확인 필요"
        if previous_value != current_value:
            lines.append(
                f"- {label}: {_escape(previous_value)} → {_escape(current_value)}"
            )
    return lines or ["- 변경항목: 확인 필요"]


def _game_start_datetime(game: dict[str, Any]) -> datetime | None:
    game_date = _coerce_date(game.get("date"))
    game_time = _parse_time(game.get("time"))
    if not game_date or not game_time:
        return None
    return datetime.combine(game_date, game_time, tzinfo=KST)


def _parse_time(value: Any) -> time | None:
    text = _clean_line(value)
    match = re.search(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def _time_sort_value(value: Any) -> tuple[int, int]:
    parsed_time = _parse_time(value)
    if not parsed_time:
        return (99, 99)
    return (parsed_time.hour, parsed_time.minute)


def _state_path(state_date: date | str) -> Path:
    return STATE_DIR / f"kia_{_date_to_str(state_date)}.json"


def _empty_state(state_date: date | str) -> dict[str, Any]:
    return {
        "date": _date_to_str(state_date),
        "first_sent": False,
        "no_game_sent": False,
        "games_by_key": {},
        "last_sent_at_kst": None,
    }


def _coerce_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"Unsupported date value: {value!r}")


def _date_to_str(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return _clean_line(value)


def _clean_cell(cell: Any) -> str:
    return _clean_multiline(cell.get_text("\n", strip=True))


def _clean_multiline(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [_clean_line(line) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _clean_line(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _format_olleh_channel(
    channel_text: str, guide: dict[str, tuple[str, str]] | None = None
) -> str:
    raw = _clean_line(channel_text)
    if not raw:
        return "확인 필요"

    canonical_name = _canonical_channel_name(raw)
    channel_info = OLLEH_CHANNEL_MAP.get(canonical_name)
    if not channel_info and guide:
        channel_info = guide.get(_canonical_channel_key(canonical_name)) or guide.get(
            _canonical_channel_key(raw)
        )
    if channel_info:
        name, number = channel_info
        return f"{name} ({number}번)"
    return raw


def _canonical_channel_name(channel_text: str) -> str:
    normalized = _clean_line(channel_text).upper()
    return CHANNEL_MAP.get(normalized, normalized)


def _canonical_channel_key(channel_text: str) -> str:
    return re.sub(r"[^0-9A-Z가-힣+&]+", "", _clean_line(channel_text).upper())


def _format_matchup(game: dict[str, Any]) -> str:
    starter_matchup = _format_starting_pitcher_matchup(game)
    if starter_matchup:
        return starter_matchup
    return f"KIA vs {_display_team(game.get('opponent')) or '상대팀 확인 필요'}"


def _format_starting_pitcher_matchup(game: dict[str, Any]) -> str:
    away_team, home_team = _game_team_pair(game)
    opponent = _display_team(game.get("opponent")) or "상대팀 확인 필요"
    away_pitcher = _clean_line(game.get("away_pitcher"))
    home_pitcher = _clean_line(game.get("home_pitcher"))

    if not (game.get("starting_pitchers_checked") or away_pitcher or home_pitcher):
        return ""

    if away_team == "KIA":
        kia_pitcher = away_pitcher
        opponent_pitcher = home_pitcher
    elif home_team == "KIA":
        kia_pitcher = home_pitcher
        opponent_pitcher = away_pitcher
    else:
        kia_pitcher = ""
        opponent_pitcher = away_pitcher or home_pitcher

    return (
        f"KIA({_display_pitcher(kia_pitcher)}) "
        f"vs {opponent}({_display_pitcher(opponent_pitcher)})"
    )


def _game_team_pair(game: dict[str, Any]) -> tuple[str, str]:
    teams = game.get("teams") or []
    away_team = _canonical_team(
        game.get("away_team") or (teams[0] if len(teams) >= 1 else "")
    )
    home_team = _canonical_team(
        game.get("home_team") or (teams[1] if len(teams) >= 2 else "")
    )
    return away_team, home_team


def _display_pitcher(value: Any) -> str:
    text = _clean_line(value)
    return text if text and text != "-" else "확인 필요"


def _display_value(value: Any) -> str:
    text = _clean_line(value)
    return text if text and text != "-" else "확인 필요"


def _display_team(value: Any) -> str:
    text = _clean_line(value)
    canonical = _canonical_team(text) if text else ""
    return TEAM_DISPLAY_NAMES.get(canonical, text)


def _display_location(value: Any) -> str:
    text = _display_value(value)
    return LOCATION_MAP.get(text.upper(), text)


def _escape(value: Any) -> str:
    return html.escape(_clean_line(value), quote=False)


def _is_header_row(cells: list[str]) -> bool:
    upper = " ".join(cells).upper()
    return "DATE" in upper and "TIME" in upper and "GAME" in upper


def _extract_date_from_text(value: str, year: int) -> date | None:
    match = re.search(r"(\d{2})\.(\d{2})", value or "")
    if not match:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _looks_like_season(value: str) -> bool:
    text = _clean_line(value).upper()
    return bool(
        text
        and not _looks_like_time_line(text)
        and (
            "REGULAR" in text
            or "POST" in text
            or "WILD" in text
            or "PLAYOFF" in text
            or "KOREAN" in text
            or "SERIES" in text
            or text in {"WC", "PO", "KS"}
            or "정규" in text
            or "준" in text
            or "한국시리즈" in text
        )
    )


def _looks_like_time_line(value: str) -> bool:
    return bool(re.match(r"^\d{1,2}:\d{2}\s+", _clean_line(value)))


def _looks_like_channel_only(value: str) -> bool:
    parts = _split_channel_parts(value)
    return bool(parts) and all(part.upper() in CHANNEL_MAP for part in parts)


def _split_location_etc(value: str) -> tuple[str, str]:
    text = _clean_line(value)
    if not text:
        return "", ""
    tokens = text.split()
    if len(tokens) == 1:
        return tokens[0], ""
    if tokens[-1] == "-" or any(
        keyword in tokens[-1].upper() or keyword in tokens[-1] for keyword in STATUS_KEYWORDS
    ):
        return " ".join(tokens[:-1]), tokens[-1]
    return text, ""


def _team_position(text: str, canonical_team: str, start: int = 0) -> int:
    for match in TEAM_PATTERN.finditer(text, pos=start):
        if _canonical_team(match.group(1)) == canonical_team:
            return match.start()
    return -1


def _extract_game_id(row: Any) -> str | None:
    for key, value in getattr(row, "attrs", {}).items():
        key_text = str(key).lower()
        if "game" in key_text and "id" in key_text and value:
            return _clean_line(value)

    link = row.find("a", href=True) if hasattr(row, "find") else None
    if link:
        match = re.search(r"(?:gameId|game_id|gmkey)=([^&]+)", link["href"], re.I)
        if match:
            return match.group(1)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
