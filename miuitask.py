"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-02-21 22:50:45
LastEditTime: 2025-01-19 17:09:37
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from tenacity import Retrying, stop_after_attempt

from utils.api.login import Login
from utils.api.sign import BaseSign, CheckIn
from utils.config import ConfigManager
from utils.logger import LogCenter, log
from utils.request import notify_me
from utils.report import AccountReport, RunReport, TaskResult, normalize_growth
from utils.system_info import print_info
from utils.utils import get_token

_conf = ConfigManager.data_obj
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def main(auto_notify: bool = True):
    """启动签到"""
    LogCenter.clear()
    print_info()
    report = RunReport(started_at=datetime.now(LOCAL_TZ))
    for account in _conf.accounts:
        account_report = AccountReport(uid=str(account.uid))
        report.accounts.append(account_report)
        try:
            for attempt in Retrying(stop=stop_after_attempt(2)):
                with attempt:
                    login_obj = Login(account)
                    if cookies := login_obj.login():
                        login_obj.checkin_info()
                        sign_obj = BaseSign(account)
                        before_info = sign_obj.user_info()
                        account_report.nickname = before_info.nickname
                        if before_info.title != "未知":
                            account_report.title = before_info.title
                            account_report.points_before = before_info.point
                        daily_tasks = sign_obj.check_daily_tasks()
                        sign_task_obj = sign_obj.AVAILABLE_SIGNS  # 签到任务对象合集
                        for task in daily_tasks:
                            log.info(f"开始执行{task.name}任务")
                            if task.showType:
                                account_report.completed.append(task.name)
                                log.info(f"{task.name}任务已完成")
                                continue
                            if not (
                                task_obj := sign_task_obj.get(task.name)
                            ):  # 签到任务对象
                                log.error(f"未找到{task.name}任务")
                                continue
                            if not getattr(account, task_obj.__name__):
                                log.info(f"任务{task.name}被禁用")
                                continue
                            token = (
                                get_token(cookies["cUserId"])
                                if task_obj == CheckIn
                                else None
                            )
                            task_instance = task_obj(account, token)
                            status, reason = task_instance.sign()
                            account_report.executed.append(
                                TaskResult(
                                    name=task.name,
                                    success=status,
                                    growth=normalize_growth(task_instance.last_growth),
                                    message=task_instance.last_message,
                                )
                            )
                            if not status and reason == "cookie":
                                raise ValueError("Cookie失效")
                        after_info = sign_obj.user_info()
                        if after_info.nickname:
                            account_report.nickname = after_info.nickname
                        if after_info.title != "未知":
                            account_report.title = after_info.title
                            account_report.points_after = after_info.point
                        log.info(f"{after_info.title} 成长值: {after_info.point}")
                    else:
                        account_report.error = "登录失败"
        except ValueError as e:
            log.error(e)
            account_report.error = str(e)
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.exception("账号任务异常")
            account_report.error = str(e)
    report.finished_at = datetime.now(LOCAL_TZ)
    executed_count = sum(len(item.executed) for item in report.accounts)
    completed_count = sum(len(item.completed) for item in report.accounts)
    log.info(f"本次执行 {executed_count} 个未完成任务，{completed_count} 个任务已完成")
    if auto_notify:
        notify_me(report.message())


if __name__ == "__main__":
    main()
