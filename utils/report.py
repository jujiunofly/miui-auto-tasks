"""运行汇总与 Telegram 报告"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


def mask_uid(uid: str) -> str:
    """隐藏账号 UID 中间部分"""
    uid = str(uid or "")
    if len(uid) <= 6:
        return uid
    return f"{uid[:2]}****{uid[-4:]}"


def normalize_growth(value) -> Optional[int]:
    """把接口返回的成长值转换为整数"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class TaskResult:
    """单个任务结果"""

    name: str
    success: bool
    growth: Optional[int] = None
    message: str = ""


@dataclass
class AccountReport:
    """单个账号运行结果"""

    uid: str
    nickname: str = ""
    title: str = ""
    points_before: Optional[int] = None
    points_after: Optional[int] = None
    executed: list[TaskResult] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def display_name(self) -> str:
        return self.nickname or "账号"

    @property
    def gained(self) -> Optional[int]:
        if self.points_before is None or self.points_after is None:
            return None
        return max(0, self.points_after - self.points_before)


@dataclass
class RunReport:
    """一次完整运行结果"""

    started_at: datetime
    finished_at: Optional[datetime] = None
    accounts: list[AccountReport] = field(default_factory=list)

    @property
    def duration(self) -> str:
        end = self.finished_at or datetime.now()
        seconds = max(0, int((end - self.started_at).total_seconds()))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def message(self) -> str:
        """生成适合 Telegram 的纯文本报告"""
        lines = ["🍀 小米社区任务报告", "━━━━━━━━━━━━━━"]
        if not self.accounts:
            lines.append("没有可执行的账号")

        for index, account in enumerate(self.accounts):
            if index:
                lines.append("")
            if account.nickname:
                lines.append(f"👤 {account.nickname}（{mask_uid(account.uid)}）")
            else:
                lines.append(f"👤 账号 {mask_uid(account.uid)}")
            if account.title:
                lines.append(f"🏅 等级：{account.title}")

            if account.points_after is not None:
                if account.gained is not None:
                    lines.append(f"📈 成长值：{account.points_after}（本次 +{account.gained}）")
                else:
                    lines.append(f"📈 成长值：{account.points_after}")
            else:
                lines.append("📈 成长值：获取失败")

            if account.error:
                lines.append(f"❌ 异常：{account.error}")

            successes = [item for item in account.executed if item.success]
            failures = [item for item in account.executed if not item.success]
            if successes:
                lines.append("✅ 本次执行")
                for item in successes:
                    if item.growth is not None:
                        detail = f"+{item.growth}"
                    elif item.message and item.message.lower() not in {"ok", "success", "成功"}:
                        detail = item.message
                    else:
                        detail = "完成"
                    lines.append(f"• {item.name}：{detail}")
            if failures:
                lines.append("⚠️ 未完成")
                for item in failures:
                    detail = item.message or "未知原因"
                    lines.append(f"• {item.name}：{detail}")
            if not account.executed:
                lines.append("ℹ️ 本次没有需要执行的未完成任务")

            if account.completed:
                shown = "、".join(account.completed[:6])
                suffix = " 等" if len(account.completed) > 6 else ""
                lines.append(f"📌 此前已完成：{shown}{suffix}")

        lines.extend(
            [
                "━━━━━━━━━━━━━━",
                f"⏱ 用时：{self.duration}",
                f"🕒 {(self.finished_at or datetime.now()).strftime('%Y-%m-%d %H:%M:%S')}",
            ]
        )
        content = "\n".join(lines)
        if len(content) > 3800:
            content = content[:3800] + "\n...(内容过长，已截断)"
        return content
