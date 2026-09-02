from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.wait_for_first_check import seconds_until_first_check


KST = ZoneInfo("Asia/Seoul")


def test_previous_day_late_run_is_skipped_before_morning_window():
    now = datetime(2026, 9, 2, 1, 30, tzinfo=KST)

    assert seconds_until_first_check(now) is None


def test_morning_anchor_waits_until_ten_kst():
    now = datetime(2026, 9, 2, 8, 17, tzinfo=KST)

    assert seconds_until_first_check(now) == 6_180


def test_run_at_or_after_ten_does_not_wait():
    assert seconds_until_first_check(
        datetime(2026, 9, 2, 10, 0, tzinfo=KST)
    ) == 0
    assert seconds_until_first_check(
        datetime(2026, 9, 2, 19, 30, tzinfo=KST)
    ) == 0
