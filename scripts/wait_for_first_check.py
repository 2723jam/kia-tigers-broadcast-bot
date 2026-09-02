from __future__ import annotations

import time as time_module
from datetime import datetime, time
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
EARLIEST_MORNING_ANCHOR = time(8, 0)
FIRST_CHECK_TIME = time(10, 0)


def seconds_until_first_check(now: datetime) -> float | None:
    now_kst = now.astimezone(KST)
    if now_kst.time() < EARLIEST_MORNING_ANCHOR:
        return None
    if now_kst.time() >= FIRST_CHECK_TIME:
        return 0

    first_check = now_kst.replace(
        hour=FIRST_CHECK_TIME.hour,
        minute=FIRST_CHECK_TIME.minute,
        second=0,
        microsecond=0,
    )
    return max(0, (first_check - now_kst).total_seconds())


def main() -> int:
    wait_seconds = seconds_until_first_check(datetime.now(KST))
    if wait_seconds is None:
        print("run=false")
        return 0

    if wait_seconds > 0:
        time_module.sleep(wait_seconds)
    print("run=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
