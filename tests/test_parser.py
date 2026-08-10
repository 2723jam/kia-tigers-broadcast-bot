from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import kia_broadcast_bot as bot  # noqa: E402


KST = ZoneInfo("Asia/Seoul")
TARGET_DATE = date(2026, 5, 27)


def schedule_html(rows: str) -> str:
    return f"""
    <html>
      <body>
        <table>
          <tr>
            <th>DATE</th><th>TYPE</th><th>TIME</th><th>GAME</th>
            <th>TV</th><th>RADIO</th><th>LOCATION</th><th>ETC</th>
          </tr>
          {rows}
        </table>
      </body>
    </html>
    """


def row(
    game_date: str = "05.27(WED)",
    season: str = "REGULAR",
    start: str = "18:30",
    game: str = "KIA : KIWOOM",
    tv: str = "KN-T",
    location: str = "GOCHEOKSKY",
    etc: str = "-",
) -> str:
    return (
        f"<tr><td>{game_date}</td><td>{season}</td><td>{start}</td>"
        f"<td>{game}</td><td>{tv}</td><td></td><td>{location}</td><td>{etc}</td></tr>"
    )


def kbo_game_list_row(
    game_id: str = "20260527HTWO0",
    away_id: str = "HT",
    away_name: str = "KIA",
    home_id: str = "WO",
    home_name: str = "키움",
    away_pitcher: str = "네일 ",
    home_pitcher: str = "알칸타라 ",
    game_name: str = "정규경기",
    game_date: str = "20260527",
    game_time: str = "18:30",
    cancel_status: str = "정상경기",
) -> dict:
    return {
        "G_DT": game_date,
        "G_ID": game_id,
        "G_TM": game_time,
        "S_NM": "고척",
        "AWAY_ID": away_id,
        "AWAY_NM": away_name,
        "HOME_ID": home_id,
        "HOME_NM": home_name,
        "T_PIT_P_NM": away_pitcher,
        "B_PIT_P_NM": home_pitcher,
        "TV_IF": "KN-T",
        "CANCEL_SC_NM": cancel_status,
        "GAME_SC_NM": game_name,
        "HEADER_NO": 0,
        "SR_ID": 0,
    }


def parse_kia_games(rows: str):
    games = bot.parse_kbo_schedule(schedule_html(rows), TARGET_DATE)
    games = bot.filter_valid_season_games(games)
    return bot.sort_games_by_time(bot.find_kia_games(games))


def state_for_games(games):
    state = {
        "first_sent": True,
        "no_game_sent": False,
        "games_by_key": {},
        "last_sent_at_kst": "2026-05-27T10:00:00+09:00",
    }
    for game in games:
        snapshot = bot.normalize_game_snapshot(game)
        state["games_by_key"][game["game_key"]] = {
            "game_key": game["game_key"],
            "last_sent_hash": bot.make_snapshot_hash(snapshot),
            "resend_count": 0,
            "last_snapshot": snapshot,
        }
    return state


def test_regular_season_single_kia_game_initial_message():
    games = parse_kia_games(row())

    assert len(games) == 1
    assert games[0]["season_type"] == "정규시즌"

    message = bot.build_initial_message(games)
    assert "🐯 KIA 타이거즈 중계 알림" in message
    assert "KIA vs 키움" in message
    assert "KBS N SPORTS (59번)" in message
    assert "KBO 경기일정/결과 보기" in message
    assert "&lt;더블헤더" not in message
    assert bot.normalize_game_snapshot(games[0])["status_reason"] == "-"


def test_doubleheader_two_games_are_sent_in_time_order():
    rows = (
        row(start="18:30", game="KIA : KIWOOM", tv="MS-T")
        + row(start="14:00", game="KIA : KIWOOM", tv="KN-T")
    )
    games = parse_kia_games(rows)
    message = bot.build_initial_message(games)

    assert [game["time"] for game in games] == ["14:00", "18:30"]
    assert games[0]["game_label"] == "DH 1차"
    assert games[1]["game_label"] == "DH 2차"
    assert message.index("DH 1차") < message.index("DH 2차")


def test_late_initial_send_skips_started_games_only():
    games = parse_kia_games(
        row(start="14:00", game="KIA : KIWOOM", tv="KN-T")
        + row(start="18:30", game="KIA : KIWOOM", tv="MS-T")
    )
    now = datetime(2026, 5, 27, 15, 0, tzinfo=KST)
    state = {"first_sent": False, "games_by_key": {}}

    sendable_games = bot._games_before_start(now, games)

    assert bot.should_send_initial(now, games, state)
    assert [game["game_label"] for game in sendable_games] == ["DH 2차"]
    message = bot.build_initial_message(sendable_games)
    assert "DH 2차" in message
    assert "DH 1차" not in message


def test_late_initial_send_is_blocked_after_all_games_started():
    games = parse_kia_games(row(start="14:00", game="KIA : KIWOOM", tv="KN-T"))
    now = datetime(2026, 5, 27, 15, 0, tzinfo=KST)
    state = {"first_sent": False, "games_by_key": {}}

    assert bot.should_send_initial(now, games, state) is False


def test_postseason_rounds_are_included_with_required_labels():
    rows = (
        row(season="WC", start="14:00")
        + row(season="준PO", start="15:00")
        + row(season="PLAYOFF", start="16:00")
        + row(season="KOREAN SERIES", start="17:00")
    )
    games = parse_kia_games(rows)

    assert [game["season_type"] for game in games] == ["WC", "준PO", "PO", "KS"]


def test_exhibition_and_international_games_are_excluded():
    rows = (
        row(season="EXHIBITION", start="14:00")
        + row(season="INTERNATIONAL", start="15:00")
        + row(season="ALLSTAR", start="16:00")
        + row(season="REGULAR", start="17:00")
    )

    games = parse_kia_games(rows)

    assert len(games) == 1
    assert games[0]["time"] == "17:00"


def test_no_resend_after_initial_when_snapshot_is_identical():
    games = parse_kia_games(row())
    state = state_for_games(games)
    now = datetime(2026, 5, 27, 10, 30, tzinfo=KST)

    assert not bot.should_send_initial(now, games, state)
    assert bot.get_changed_games_before_start(now, games, state) == []


def test_only_dh_first_game_resends_when_first_game_changes():
    initial = parse_kia_games(
        row(start="14:00", tv="KN-T") + row(start="18:30", tv="MS-T")
    )
    state = state_for_games(initial)
    changed = parse_kia_games(
        row(start="14:00", tv="SPO-T") + row(start="18:30", tv="MS-T")
    )

    changed_games = bot.get_changed_games_before_start(
        datetime(2026, 5, 27, 12, 0, tzinfo=KST), changed, state
    )
    message = bot.build_change_message(changed_games, state)

    assert len(changed_games) == 1
    assert changed_games[0]["game_label"] == "DH 1차"
    assert "대상경기: DH 1차" in message
    assert "대상경기: DH 2차" not in message


def test_only_dh_second_game_resends_when_second_game_changes():
    initial = parse_kia_games(
        row(start="14:00", tv="KN-T") + row(start="18:30", tv="MS-T")
    )
    state = state_for_games(initial)
    changed = parse_kia_games(
        row(start="14:00", tv="KN-T") + row(start="18:00", tv="MS-T")
    )

    changed_games = bot.get_changed_games_before_start(
        datetime(2026, 5, 27, 12, 0, tzinfo=KST), changed, state
    )

    assert len(changed_games) == 1
    assert changed_games[0]["game_label"] == "DH 2차"


def test_time_tv_and_status_reason_changes_trigger_resend():
    initial = parse_kia_games(row(start="18:30", tv="KN-T", etc="-"))
    state = state_for_games(initial)

    for changed_row in (
        row(start="18:00", tv="KN-T", etc="-"),
        row(start="18:30", tv="SPO-T", etc="-"),
        row(start="18:30", tv="KN-T", etc="POSTPONED"),
        row(start="18:30", tv="KN-T", etc="우천취소"),
        row(start="18:30", tv="KN-T", etc="미세먼지"),
    ):
        changed_games = bot.get_changed_games_before_start(
            datetime(2026, 5, 27, 12, 0, tzinfo=KST),
            parse_kia_games(changed_row),
            state,
        )
        assert len(changed_games) == 1


def test_games_do_not_resend_after_each_game_start():
    initial = parse_kia_games(
        row(start="14:00", tv="KN-T") + row(start="18:30", tv="MS-T")
    )
    state = state_for_games(initial)
    changed = parse_kia_games(
        row(start="14:00", tv="SPO-T") + row(start="18:30", tv="SPO-2T")
    )

    changed_games = bot.get_changed_games_before_start(
        datetime(2026, 5, 27, 15, 0, tzinfo=KST), changed, state
    )

    assert len(changed_games) == 1
    assert changed_games[0]["game_label"] == "DH 2차"


def test_cancellation_change_is_sent_after_scheduled_start():
    initial = parse_kia_games(row(start="18:30", etc="-"))
    state = state_for_games(initial)
    changed = parse_kia_games(row(start="18:30", etc="폭염취소"))

    changed_games = bot.get_changed_games_before_start(
        datetime(2026, 5, 27, 19, 0, tzinfo=KST), changed, state
    )
    message = bot.build_change_message(changed_games, state)

    assert len(changed_games) == 1
    assert "- 경기상태/사유: - → 폭염취소" in message


def test_cancelled_initial_after_start_includes_status_reason():
    games = parse_kia_games(row(start="18:30", etc="폭염취소"))
    state = {"first_sent": False, "games_by_key": {}}
    now = datetime(2026, 5, 27, 19, 0, tzinfo=KST)

    assert bot.should_send_initial(now, games, state)
    assert "📌 상태/사유: 폭염취소" in bot.build_initial_message(games)


def test_kbo_cancel_reason_overrides_generic_daily_postponed():
    games = parse_kia_games(row(etc="POSTPONED"))
    enriched = bot._merge_kbo_game_list(
        games,
        [kbo_game_list_row(cancel_status="폭염취소")],
    )

    assert enriched[0]["status_reason"] == "폭염취소"


def test_channel_abbreviation_mapping():
    assert bot.normalize_channel("S-T") == "SBS (5번)"
    assert bot.normalize_channel("K-2T") == "KBS2 (7번)"
    assert bot.normalize_channel("K-1T") == "KBS1 (9번)"
    assert bot.normalize_channel("M-T") == "MBC (11번)"
    assert bot.normalize_channel("JTBC") == "JTBC (15번)"
    assert bot.normalize_channel("SPO-T") == "SPOTV (51번)"
    assert bot.normalize_channel("SPO-2T") == "SPOTV2 (52번)"
    assert bot.normalize_channel("SS-T") == "SBS SPORTS (58번)"
    assert bot.normalize_channel("KN-T") == "KBS N SPORTS (59번)"
    assert bot.normalize_channel("MS-T") == "MBC SPORTS+ (60번)"
    assert bot.normalize_channel("KBS LIFE") == "KBS LIFE (158번)"
    assert (
        bot.normalize_channel("KN-T\nSPO-T")
        == "KBS N SPORTS (59번), SPOTV (51번)"
    )
    assert bot.normalize_channel("") == "확인 필요"


def test_unknown_channel_is_looked_up_from_olleh_channel_guide(monkeypatch):
    monkeypatch.setattr(
        bot,
        "fetch_olleh_channel_guide",
        lambda: {"TVNSPORTS": ("tvN SPORTS", "54")},
    )

    assert bot.normalize_channel("tvN SPORTS") == "tvN SPORTS (54번)"


def test_channel_falls_back_to_kbo_text_when_not_on_olleh(monkeypatch):
    monkeypatch.setattr(bot, "fetch_olleh_channel_guide", lambda: {})

    assert bot.normalize_channel("KBO-ONLY") == "KBO-ONLY"


def test_olleh_channel_guide_parser_reads_channel_numbers():
    guide = bot._parse_olleh_channel_guide(
        """
        <ul>
          <li>54 tvN SPORTS</li>
          <li>59 KBS N Sports</li>
          <li>190 SPOTV PRIME 유료</li>
          <li>192 SPOTV PRIME+ 유료</li>
        </ul>
        """
    )

    assert guide["TVNSPORTS"] == ("tvN SPORTS", "54")
    assert guide["KBSNSPORTS"] == ("KBS N Sports", "59")
    assert guide["SPOTVPRIME"] == ("SPOTV PRIME", "190")
    assert guide["SPOTVPRIME+"] == ("SPOTV PRIME+", "192")


def test_empty_tv_cell_is_parsed_as_needs_confirmation():
    games = parse_kia_games(row(tv=""))

    assert len(games) == 1
    assert bot.normalize_game_snapshot(games[0])["tv"] == "확인 필요"


def test_kbo_split_game_columns_are_parsed():
    rows = (
        "<tr><td>05.27(WED)</td><td>REGULAR</td><td>18:30</td>"
        "<td>KIA</td><td>:</td><td>KIWOOM</td><td>KN-T</td><td></td>"
        "<td>GOCHEOKSKY</td><td>-</td></tr>"
    )
    games = parse_kia_games(rows)
    snapshot = bot.normalize_game_snapshot(games[0])

    assert len(games) == 1
    assert games[0]["teams"] == ["KIA", "KIWOOM"]
    assert snapshot["opponent"] == "키움"
    assert snapshot["tv"] == "KBS N SPORTS (59번)"
    assert snapshot["location"] == "고척"


def test_kbo_game_list_starting_pitchers_are_merged_into_matchup():
    games = parse_kia_games(row())
    enriched = bot._merge_kbo_game_list(games, [kbo_game_list_row()])
    enriched = bot.sort_games_by_time(enriched)
    snapshot = bot.normalize_game_snapshot(enriched[0])
    message = bot.build_initial_message(enriched)

    assert enriched[0]["official_game_id"] == "20260527HTWO0"
    assert snapshot["starting_pitchers"] == "KIA(네일) vs 키움(알칸타라)"
    assert "⚾ 경기: KIA(네일) vs 키움(알칸타라)" in message


def test_kbo_game_list_fast_today_path_builds_full_kia_message():
    games = bot.get_kia_games_from_kbo_game_list([kbo_game_list_row()])
    snapshot = bot.normalize_game_snapshot(games[0])
    message = bot.build_today_reply_message(games)

    assert len(games) == 1
    assert games[0]["season_type"] == "정규시즌"
    assert games[0]["official_game_id"] == "20260527HTWO0"
    assert snapshot["matchup"] == "KIA(네일) vs 키움(알칸타라)"
    assert snapshot["tv"] == "KBS N SPORTS (59번)"
    assert "📺 TV 중계: KBS N SPORTS (59번)" in message


def test_home_kia_starting_pitchers_keep_kia_first_in_matchup():
    games = parse_kia_games(row(game="KIWOOM : KIA", location="GWANGJU"))
    enriched = bot._merge_kbo_game_list(
        games,
        [
            kbo_game_list_row(
                game_id="20260527WOHT0",
                away_id="WO",
                away_name="키움",
                home_id="HT",
                home_name="KIA",
                away_pitcher="알칸타라 ",
                home_pitcher="네일 ",
            )
        ],
    )
    snapshot = bot.normalize_game_snapshot(enriched[0])

    assert snapshot["matchup"] == "KIA(네일) vs 키움(알칸타라)"


def test_starting_pitcher_change_triggers_resend_before_start():
    initial = bot._merge_kbo_game_list(parse_kia_games(row()), [kbo_game_list_row()])
    initial = bot.sort_games_by_time(initial)
    state = state_for_games(initial)

    changed = bot._merge_kbo_game_list(
        parse_kia_games(row()),
        [kbo_game_list_row(away_pitcher="양현종 ", home_pitcher="알칸타라 ")],
    )
    changed = bot.sort_games_by_time(changed)
    changed_games = bot.get_changed_games_before_start(
        datetime(2026, 5, 27, 12, 0, tzinfo=KST), changed, state
    )
    message = bot.build_change_message(changed_games, state)

    assert len(changed_games) == 1
    assert "- 선발투수: KIA(네일) vs 키움(알칸타라) → KIA(양현종) vs 키움(알칸타라)" in message


def test_official_game_id_enrichment_reuses_existing_fallback_state():
    state = state_for_games(parse_kia_games(row()))
    enriched = bot._merge_kbo_game_list(parse_kia_games(row()), [kbo_game_list_row()])
    enriched = bot.sort_games_by_time(enriched)

    changed_games = bot.get_changed_games_before_start(
        datetime(2026, 5, 27, 12, 0, tzinfo=KST), enriched, state
    )
    message = bot.build_change_message(changed_games, state)

    assert len(changed_games) == 1
    assert "- 선발투수: 확인 불가 → KIA(네일) vs 키움(알칸타라)" in message
    assert "- 경기시간:" not in message
    assert "- TV 중계:" not in message


def test_today_reply_message_uses_initial_message_format():
    games = parse_kia_games(row())
    message = bot.build_today_reply_message(games)

    assert "🐯 KIA 타이거즈 중계 알림" in message
    assert "📺 TV 중계: KBS N SPORTS (59번)" in message


def test_today_reply_message_for_no_game():
    assert bot.build_today_reply_message([]) == "오늘은 KIA 타이거즈 경기가 없습니다."


def test_today_command_detection():
    assert bot._is_today_command("/today")
    assert bot._is_today_command("/today@kia_channel_bot")
    assert bot._is_today_command("/today   now")
    assert not bot._is_today_command("/start")


def test_process_today_command_replies_to_allowed_chat(monkeypatch):
    calls = []
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "8124393248")
    monkeypatch.setattr(bot, "send_today_reply", lambda chat_id: calls.append(chat_id) or True)

    ok = bot.process_telegram_update(
        {
            "update_id": 1,
            "message": {
                "text": "/today",
                "chat": {"id": 8124393248},
            },
        }
    )

    assert ok is True
    assert calls == [8124393248]


def test_process_today_command_ignores_other_chat(monkeypatch):
    calls = []
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "8124393248")
    monkeypatch.setattr(bot, "send_today_reply", lambda chat_id: calls.append(chat_id) or True)

    ok = bot.process_telegram_update(
        {
            "update_id": 1,
            "message": {
                "text": "/today",
                "chat": {"id": 111111},
            },
        }
    )

    assert ok is True
    assert calls == []


def test_send_today_reply_uses_fast_kbo_game_list_without_daily_schedule(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(bot, "get_today_kst", lambda: TARGET_DATE)
    monkeypatch.setattr(bot, "fetch_kbo_game_list", lambda target_date: [kbo_game_list_row()])
    monkeypatch.setattr(
        bot,
        "fetch_kbo_daily_schedule",
        lambda: (_ for _ in ()).throw(AssertionError("daily schedule should not be fetched")),
    )
    monkeypatch.setattr(
        bot,
        "send_telegram_message",
        lambda text, chat_id=None: sent_messages.append((text, chat_id)) or True,
    )

    assert bot.send_today_reply(8124393248) is True
    assert sent_messages[0][1] == 8124393248
    assert "KIA(네일) vs 키움(알칸타라)" in sent_messages[0][0]


def test_command_state_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "STATE_DIR", tmp_path / ".bot_state")
    monkeypatch.setattr(
        bot, "COMMAND_STATE_PATH", tmp_path / ".bot_state" / "telegram_updates.json"
    )

    bot.save_command_state(
        {"last_update_id": 123, "last_checked_at_kst": "2026-05-27T09:00:00+09:00"}
    )
    loaded = bot.load_command_state()

    assert loaded["last_update_id"] == 123
    assert loaded["last_checked_at_kst"] == "2026-05-27T09:00:00+09:00"


def test_state_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "STATE_DIR", tmp_path / ".bot_state")
    state = {
        "first_sent": True,
        "no_game_sent": False,
        "games_by_key": {
            "game-key": {
                "game_key": "game-key",
                "last_sent_hash": "abc",
                "resend_count": 1,
                "last_snapshot": {"time": "18:30"},
            }
        },
        "last_sent_at_kst": "2026-05-27T10:00:00+09:00",
    }

    bot.save_state(TARGET_DATE, state)
    loaded = bot.load_state(TARGET_DATE)

    assert loaded["first_sent"] is True
    assert loaded["games_by_key"]["game-key"]["resend_count"] == 1

def test_scheduled_check_sends_cancellations_on_consecutive_days(
    tmp_path, monkeypatch
):
    current = {"now": datetime(2026, 8, 1, 19, 0, tzinfo=KST)}
    sent_messages = []

    monkeypatch.setattr(bot, "STATE_DIR", tmp_path / ".bot_state")
    monkeypatch.setattr(bot, "get_now_kst", lambda: current["now"])
    monkeypatch.setattr(bot, "fetch_kbo_daily_schedule", lambda: schedule_html(""))

    def game_list_for_date(target_date):
        game_date = target_date.strftime("%Y%m%d")
        return [
            kbo_game_list_row(
                game_id=f"{game_date}HTNC0",
                game_date=game_date,
                game_time="18:00",
                cancel_status="폭염취소",
                home_id="NC",
                home_name="NC",
            )
        ]

    monkeypatch.setattr(bot, "fetch_kbo_game_list", game_list_for_date)
    monkeypatch.setattr(
        bot,
        "send_telegram_message",
        lambda text, chat_id=None: sent_messages.append(text) or True,
    )

    assert bot.run_scheduled_check() == 0
    current["now"] = datetime(2026, 8, 2, 19, 0, tzinfo=KST)
    assert bot.run_scheduled_check() == 0

    assert len(sent_messages) == 2
    assert all("폭염취소" in message for message in sent_messages)
    assert (tmp_path / ".bot_state" / "kia_2026-08-01.json").exists()
    assert (tmp_path / ".bot_state" / "kia_2026-08-02.json").exists()


def test_scheduled_check_fails_when_initial_telegram_send_fails(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(bot, "STATE_DIR", tmp_path / ".bot_state")
    monkeypatch.setattr(
        bot,
        "get_now_kst",
        lambda: datetime(2026, 5, 27, 10, 0, tzinfo=KST),
    )
    monkeypatch.setattr(bot, "fetch_kbo_daily_schedule", lambda: schedule_html(row()))
    monkeypatch.setattr(
        bot, "fetch_kbo_game_list", lambda target_date: [kbo_game_list_row()]
    )
    monkeypatch.setattr(bot, "send_telegram_message", lambda text, chat_id=None: False)

    assert bot.run_scheduled_check() == 1
    assert not (tmp_path / ".bot_state" / "kia_2026-05-27.json").exists()
