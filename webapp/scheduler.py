"""每日定时任务"""

import os
import random
import threading
import time
from datetime import datetime, timedelta

from utils.logger import log

from .runner import runner

_started = False


def _enabled() -> bool:
    return os.getenv("SCHEDULE_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def _loop(hour: int, minute: int, jitter_minutes: int):
    while True:
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        jitter = random.randint(0, max(0, jitter_minutes) * 60)
        wait_seconds = max(0, int((target - now).total_seconds()) + jitter)
        log.info(
            "下一次定时任务: "
            f"{target.strftime('%Y-%m-%d %H:%M')} + 随机延迟 {jitter // 60} 分钟"
        )
        while wait_seconds > 0:
            time.sleep(min(wait_seconds, 60))
            wait_seconds -= 60
        if not runner.start(auto_notify=True):
            log.warning("定时任务启动失败：已有任务正在运行")


def start():
    """启动后台定时线程"""
    global _started
    if _started or not _enabled():
        return
    _started = True
    hour = int(os.getenv("SCHEDULE_HOUR", "4"))
    minute = int(os.getenv("SCHEDULE_MINUTE", "0"))
    jitter_minutes = int(os.getenv("SCHEDULE_JITTER_MINUTES", "30"))
    threading.Thread(
        target=_loop,
        args=(hour, minute, jitter_minutes),
        daemon=True,
        name="miui-scheduler",
    ).start()
