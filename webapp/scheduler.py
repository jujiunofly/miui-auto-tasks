"""轻量每日定时运行器。"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from utils.config import DATA_PATH, ConfigManager

from .runner import runner

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_STATE_PATH = Path(DATA_PATH) / "schedule_state.json"
_STARTED = False
_LOCK = threading.Lock()


def _load_last_date() -> str:
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        return str(data.get("last_date", ""))
    except Exception:
        return ""


def _save_last_date(value: str):
    try:
        _STATE_PATH.write_text(
            json.dumps({"last_date": value}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _loop():
    last_date = _load_last_date()
    while True:
        try:
            conf = ConfigManager.data_obj
            schedule = getattr(conf, "SCHEDULE", None)
            if schedule and getattr(schedule, "enabled", False):
                scheduled_time = str(getattr(schedule, "time", "")).strip()
                now = datetime.now(LOCAL_TZ)
                if (
                    scheduled_time
                    and now.strftime("%H:%M") == scheduled_time
                    and last_date != now.strftime("%Y-%m-%d")
                ):
                    if runner.start(auto_notify=True):
                        last_date = now.strftime("%Y-%m-%d")
                        _save_last_date(last_date)
        except Exception:
            pass
        time.sleep(15)


def start():
    """启动定时器，进程内只启动一次。"""
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
    thread = threading.Thread(target=_loop, daemon=True, name="daily-scheduler")
    thread.start()
