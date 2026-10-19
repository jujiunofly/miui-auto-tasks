'''
Date: 2023-11-12 14:05:06
LastEditors: Night-stars-1 nujj1042633805@gmail.com
LastEditTime: 2023-11-24 17:39:16
'''
import os
import sys
import threading
from collections import deque
from itertools import count

from loguru import logger


class LogCenter:
    """供 Web 面板读取的结构化运行日志"""

    _entries = deque(maxlen=2000)
    _ids = count(1)
    _lock = threading.Lock()

    @classmethod
    def clear(cls):
        """清空当前运行日志"""
        with cls._lock:
            cls._entries.clear()

    @classmethod
    def add(cls, record: dict):
        """追加一条日志"""
        entry = {
            "id": next(cls._ids),
            "time": record["time"].strftime("%H:%M:%S"),
            "level": record["level"].name,
            "module": record["module"],
            "function": record["function"],
            "line": record["line"],
            "message": record["message"],
        }
        with cls._lock:
            cls._entries.append(entry)

    @classmethod
    def entries(cls, after: int = 0):
        """获取指定 ID 之后的日志"""
        with cls._lock:
            return [entry for entry in cls._entries if entry["id"] > after]

    @classmethod
    def get(cls, entry_id: int):
        """按 ID 获取日志"""
        with cls._lock:
            return next(
                (entry for entry in cls._entries if entry["id"] == entry_id), None
            )


path_log = os.path.join("logs", '日志文件.log')
log = logger
log.remove()

log.add(sys.stdout, level="INFO", colorize=True,
        format="<green>{time:HH:mm:ss}</green> - "
               "<level>{level: <5}</level> | "
               "<cyan>{module}</cyan>.<cyan>{function}</cyan>"
               ":<cyan>{line}</cyan> - "
               "<level>{message}</level>")

log.add(path_log, level="DEBUG",
        format="{time:HH:mm:ss} - "
               "{level: <5} | "
               "{module}.{function}:{line} - {message}",
        rotation="1 days", enqueue=True, serialize=False, encoding="utf-8", retention="10 days")

log.add(lambda message: LogCenter.add(message.record), level="INFO")
