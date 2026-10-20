"""轻量每日定时运行器。

每天在配置的时间范围内随机选择一个时间执行一次，并持久化当天状态，
避免进程重启后重复执行。
"""

import json
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from utils.config import DATA_PATH, ConfigManager
from utils.logger import log

from .runner import runner

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_STATE_PATH = Path(DATA_PATH) / "schedule_state.json"
_STARTED = False
_LOCK = threading.Lock()


def _load_state() -> dict:
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        if data.get("date"):
            return data
        if data.get("last_date"):
            return {
                "date": str(data["last_date"]),
                "time": "00:00",
                "ran": True,
                "start": "",
                "end": "",
                "legacy": True,
            }
    except Exception:
        pass
    return {}


def _save_state(state: dict):
    try:
        _STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _random_time(now: datetime, start: str, end: str) -> str:
    """在范围内随机选一个时间；今天已经错过范围则返回空字符串。"""
    try:
        start_min = _minutes(start)
        end_min = _minutes(end)
    except Exception:
        return ""
    if end_min < start_min:
        return ""
    now_min = now.hour * 60 + now.minute
    if now_min > end_min:
        return ""
    low = max(start_min, now_min)
    chosen = random.randint(low, end_min)
    return f"{chosen // 60:02d}:{chosen % 60:02d}"


def _loop():
    state = _load_state()
    while True:
        try:
            conf = ConfigManager.data_obj
            schedule = getattr(conf, "SCHEDULE", None)
            if schedule and getattr(schedule, "enabled", False):
                start = str(getattr(schedule, "start_time", "09:00")).strip()
                end = str(getattr(schedule, "end_time", "11:00")).strip()
                now = datetime.now(LOCAL_TZ)
                today = now.strftime("%Y-%m-%d")

                if (
                    state.get("date") == today
                    and state.get("ran")
                    and not state.get("legacy")
                ):
                    if state.get("start") != start or state.get("end") != end:
                        state.update(
                            {
                                "time": end,
                                "start": start,
                                "end": end,
                            }
                        )
                        _save_state(state)
                elif (
                    state.get("legacy")
                    and state.get("date") == today
                ):
                    state.update(
                        {
                            "time": end,
                            "ran": True,
                            "start": start,
                            "end": end,
                        }
                    )
                    state.pop("legacy", None)
                    _save_state(state)
                elif (
                    state.get("date") != today
                    or state.get("start") != start
                    or state.get("end") != end
                ):
                    chosen = _random_time(now, start, end)
                    if chosen:
                        state = {
                            "date": today,
                            "time": chosen,
                            "ran": False,
                            "start": start,
                            "end": end,
                        }
                        log.info(f"今日定时运行时间已选: {chosen}（范围 {start}-{end}）")
                    else:
                        state = {
                            "date": today,
                            "time": end,
                            "ran": True,
                            "start": start,
                            "end": end,
                        }
                        log.info(f"今天已错过定时范围 {start}-{end}，明天再运行")
                    _save_state(state)

                if not state.get("ran"):
                    now_hm = now.strftime("%H:%M")
                    if now_hm >= str(state.get("time", "")) and now_hm <= end:
                        if runner.start(auto_notify=True):
                            state["ran"] = True
                            _save_state(state)
                            log.info("定时任务已启动")
                    elif now_hm > end:
                        state["ran"] = True
                        _save_state(state)
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
