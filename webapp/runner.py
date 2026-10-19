"""任务运行器"""

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from miuitask import main
from utils.logger import LogCenter, log

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


class Runner:
    """串行执行签到任务，避免多个运行同时修改日志"""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._run_id = 0
        self._last_run = {}

    def start(self, auto_notify: bool = True) -> bool:
        """启动一次任务"""
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._run_id += 1
            run_id = self._run_id
            self._last_run = {
                "id": run_id,
                "status": "running",
                "started": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
                "finished": "",
                "auto_notify": auto_notify,
            }
            LogCenter.clear()
            thread = threading.Thread(
                target=self._run, args=(run_id, auto_notify), daemon=True
            )
            thread.start()
            return True

    def _run(self, run_id: int, auto_notify: bool):
        status = "success"
        error = ""
        try:
            main(auto_notify=auto_notify)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            status = "error"
            error = str(exc)
            log.exception("任务运行异常")
        finally:
            with self._lock:
                if self._run_id == run_id:
                    self._last_run.update(
                        {
                            "status": status,
                            "finished": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
                            "error": error,
                        }
                    )
                self._running = False

    def status(self) -> dict:
        """返回运行状态"""
        with self._lock:
            return {
                "running": self._running,
                "run_id": self._run_id,
                "last_run": dict(self._last_run),
            }


runner = Runner()
