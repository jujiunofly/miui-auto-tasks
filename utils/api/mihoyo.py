"""米游社社区签到与云原神/云崩铁签到。

逻辑参考 GildedFlames/MYS_Game_Singin，改写为 Python，避免额外引入 Node 依赖。
"""

import hashlib
import random
import string
import time
import uuid
from typing import Optional

from ..config import ConfigManager
from ..logger import log
from ..report import MihoyoAccountReport, TaskResult
from ..request import get, post

MYS_HOST = "api-takumi.mihoyo.com"
MYS_APP_VERSION = "2.81.1"
MYS_DS_SALT = "yUZ3s0Sna1IrSNfk29Vo6vRapdOyqyhB"

MYS_GAMES = {
    "Genshin": {
        "label": "米游社原神",
        "biz": "hk4e_cn",
        "act_id": "e202311201442471",
        "region": "cn_gf01",
        "signgame": "hk4e",
    },
    "StarRail": {
        "label": "米游社崩铁",
        "biz": "hkrpg_cn",
        "act_id": "e202304121516551",
        "region": "prod_gf_cn",
        "signgame": "hkrpg",
    },
}

CLOUD_GAMES = {
    "CloudGenshin": {
        "label": "云原神",
        "token_field": "genshin_token",
        "base_url": "https://api-cloudgame.mihoyo.com/hk4e_cg_cn",
        "headers": {
            "Host": "api-cloudgame.mihoyo.com",
            "Origin": "https://ys.mihoyo.com",
            "Referer": "https://ys.mihoyo.com/",
            "x-rpc-app_id": 4,
            "x-rpc-app_version": "6.0.0",
            "x-rpc-cg_game_biz": "hk4e_cn",
            "x-rpc-op_biz": "clgm_cn",
        },
    },
    "CloudStarRail": {
        "label": "云崩铁",
        "token_field": "starrail_token",
        "base_url": "https://cg-hkrpg-api.mihoyo.com/hkrpg_cn/cg",
        "headers": {
            "Host": "cg-hkrpg-api.mihoyo.com",
            "Origin": "https://sr.mihoyo.com",
            "Referer": "https://sr.mihoyo.com/",
            "x-rpc-app_id": 8,
            "x-rpc-app_version": "3.5.0",
            "x-rpc-cg_game_biz": "hkrpg_cn",
            "x-rpc-op_biz": "clgm_hkrpg-cn",
        },
    },
}


def _ds() -> str:
    """生成米游社 DS 签名。"""
    timestamp = int(time.time())
    nonce = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    raw = f"salt={MYS_DS_SALT}&t={timestamp}&r={nonce}"
    return f"{timestamp},{nonce},{hashlib.md5(raw.encode('utf-8')).hexdigest()}"


def _mys_headers(cookie: str, extra: Optional[dict] = None) -> dict:
    headers = {
        "DS": _ds(),
        "Cookie": cookie,
        "Host": MYS_HOST,
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            f"miHoYoBBS/{MYS_APP_VERSION}"
        ),
        "x-rpc-app_version": MYS_APP_VERSION,
        "x-rpc-client_type": 5,
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "Accept": "application/json, text/plain, */*",
    }
    if extra:
        headers.update(extra)
    return {key: str(value) for key, value in headers.items()}


def _role_headers() -> dict:
    return {
        "Referer": "https://webstatic.mihoyo.com/",
        "x-rpc-device_id": str(uuid.uuid4()),
        "Origin": "https://webstatic.mihoyo.com",
        "x-rpc-challenge": "null",
        "Accept-Encoding": "gzip, deflate, br",
    }


def _sign_headers(signgame: str) -> dict:
    return {
        "Referer": "https://act.mihoyo.com/",
        "x-rpc-device_model": "iPhone14,4",
        "x-rpc-device_id": str(uuid.uuid4()),
        "x-rpc-platform": 1,
        "x-rpc-device_name": "iPhone",
        "Origin": "https://act.mihoyo.com",
        "Sec-Fetch-Site": "same-site",
        "Connection": "keep-alive",
        "Content-Type": "application/json;charset=utf-8",
        "x-rpc-signgame": signgame,
    }


def _cloud_headers(game: dict, token: str) -> dict:
    headers = {
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip, deflate, br",
        "accept-language": "zh-CN,zh;q=0.9",
        "Accept": "application/json, text/plain, */*",
        "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "x-rpc-channel": "mihoyo",
        "x-rpc-client_type": 17,
        "x-rpc-combo_token": token,
        "x-rpc-cps": "mac_mihoyo",
        "x-rpc-device_id": "1b252815-b2df-494f-8c84-a93e1a6d3479",
        "x-rpc-device_model": "Macintosh",
        "x-rpc-device_name": "Apple Macintosh",
        "x-rpc-language": "zh-cn",
        "x-rpc-sys_version": "Mac OS 10.15.7",
        "x-rpc-vendor_id": 2,
    }
    headers.update(game["headers"])
    return {key: str(value) for key, value in headers.items()}


def _is_ok(payload: dict) -> bool:
    return payload.get("retcode") == 0 or payload.get("message") == "OK"


def _message(payload: dict) -> str:
    return str(payload.get("message") or payload.get("msg") or "")


def _get_role(cookie: str, game_key: str) -> Optional[dict]:
    game = MYS_GAMES[game_key]
    try:
        response = get(
            f"https://{MYS_HOST}/binding/api/getUserGameRolesByCookie",
            params={"game_biz": game["biz"]},
            headers=_mys_headers(cookie, _role_headers()),
            timeout=20,
        )
        payload = response.json()
        log.debug(f"[{game['label']}] 角色接口: {response.text}")
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception(f"[{game['label']}] 获取角色异常")
        return None

    if payload.get("retcode") != 0:
        log.error(f"[{game['label']}] Cookie 无效或获取角色失败: {_message(payload)}")
        return None
    roles = (payload.get("data") or {}).get("list") or []
    if not roles:
        log.error(f"[{game['label']}] Cookie 下没有找到角色")
        return None
    role = roles[0]
    log.info(
        f"[{game['label']}] 角色: {role.get('nickname', '')}"
        f"({role.get('game_uid', '')})"
    )
    return role


def _sign_community(cookie: str, game_key: str, role: dict) -> tuple[bool, str]:
    game = MYS_GAMES[game_key]
    data = {
        "act_id": game["act_id"],
        "region": game["region"],
        "uid": role.get("game_uid", ""),
        "lang": "zh-cn",
    }
    try:
        response = post(
            f"https://{MYS_HOST}/event/luna/{game['signgame']}/sign",
            headers=_mys_headers(cookie, _sign_headers(game["signgame"])),
            json=data,
            timeout=20,
        )
        payload = response.json()
        log.debug(f"[{game['label']}] 签到接口: {response.text}")
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception(f"[{game['label']}] 签到异常")
        return False, "签到请求异常"

    message = _message(payload)
    success = payload.get("retcode") == 0 or "已签到" in message or "already" in message.lower()
    return success, message or ("签到成功" if success else "签到失败")


def _run_community(account, game_key: str, report: MihoyoAccountReport):
    game = MYS_GAMES[game_key]
    label = game["label"]
    if not account.cookie:
        log.warning(f"[{label}] 未配置米游社 Cookie，跳过")
        report.executed.append(TaskResult(name=label, success=False, message="未配置 Cookie"))
        return
    role = _get_role(account.cookie, game_key)
    if not role:
        report.executed.append(TaskResult(name=label, success=False, message="Cookie 无效或未找到角色"))
        return
    success, message = _sign_community(account.cookie, game_key, role)
    detail = f"{role.get('nickname', '')}({role.get('game_uid', '')}) {message}".strip()
    report.executed.append(TaskResult(name=label, success=success, message=detail))
    if success:
        log.success(f"[{label}] {detail}")
    else:
        log.error(f"[{label}] {detail}")


def _get_wallet(game: dict, token: str) -> bool:
    try:
        response = get(
            f"{game['base_url']}/wallet/wallet/get",
            headers=_cloud_headers(game, token),
            timeout=20,
        )
        payload = response.json()
        log.debug(f"[{game['label']}] 云游戏时长: {response.text}")
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception(f"[{game['label']}] 获取云游戏时长异常")
        return False

    if not _is_ok(payload):
        log.error(f"[{game['label']}] 获取云游戏时长失败: {_message(payload)}")
        return False
    data = payload.get("data") or {}
    free_time = (data.get("free_time") or {}).get("free_time")
    total_time = data.get("total_time")
    log.info(f"[{game['label']}] 免费时长: {free_time}, 总时长: {total_time}")
    return True


def _list_notifications(game: dict, token: str) -> Optional[list]:
    try:
        response = get(
            f"{game['base_url']}/gamer/api/listNotifications",
            params={
                "status": "NotificationStatusUnread",
                "type": "NotificationTypePopup",
                "is_sort": "true",
            },
            headers=_cloud_headers(game, token),
            timeout=20,
        )
        payload = response.json()
        log.debug(f"[{game['label']}] 云游戏通知: {response.text}")
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception(f"[{game['label']}] 获取云游戏通知异常")
        return None

    if not _is_ok(payload):
        log.error(f"[{game['label']}] 获取云游戏通知失败: {_message(payload)}")
        return None
    return (payload.get("data") or {}).get("list") or []


def _ack_notification(game: dict, token: str, notification_id) -> bool:
    try:
        response = post(
            f"{game['base_url']}/gamer/api/ackNotification",
            headers=_cloud_headers(game, token),
            json={"id": notification_id},
            timeout=20,
        )
        payload = response.json()
        log.debug(f"[{game['label']}] 确认通知: {response.text}")
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception(f"[{game['label']}] 确认云游戏通知异常")
        return False
    return _is_ok(payload)


def _run_cloud(account, game_key: str, report: MihoyoAccountReport):
    game = CLOUD_GAMES[game_key]
    label = game["label"]
    token = str(getattr(account, game["token_field"], "") or "").strip()
    if not token:
        log.warning(f"[{label}] 未配置云游戏 Token，跳过")
        report.executed.append(TaskResult(name=label, success=False, message="未配置 Token"))
        return

    _get_wallet(game, token)
    notifications = _list_notifications(game, token)
    if notifications is None:
        report.executed.append(TaskResult(name=label, success=False, message="Token 无效或获取通知失败"))
        return
    if not notifications:
        log.info(f"[{label}] 今日没有待领取通知")
        report.executed.append(TaskResult(name=label, success=True, message="无待领取通知"))
        return

    success_count = 0
    for notification in notifications:
        time.sleep(random.uniform(1, 2))
        if _ack_notification(game, token, notification.get("id")):
            success_count += 1
    total = len(notifications)
    success = success_count == total
    message = f"确认 {success_count}/{total} 条通知"
    report.executed.append(TaskResult(name=label, success=success, message=message))
    if success:
        log.success(f"[{label}] {message}")
    else:
        log.error(f"[{label}] {message}")


def run_mihoyo_accounts(report):
    """执行所有米游社/云游戏账号，把结果写入 RunReport。"""
    accounts = getattr(ConfigManager.data_obj, "MIHOYO", []) or []
    if not accounts:
        return
    log.info(f"开始执行米游社/云游戏任务，共 {len(accounts)} 个账号")
    for index, account in enumerate(accounts):
        name = str(getattr(account, "name", "") or "").strip() or f"米游社账号 {index + 1}"
        account_report = MihoyoAccountReport(name=name)
        report.mihoyo_accounts.append(account_report)
        try:
            if getattr(account, "MysGenshin", False):
                _run_community(account, "Genshin", account_report)
            if getattr(account, "MysStarRail", False):
                _run_community(account, "StarRail", account_report)
            if getattr(account, "CloudGenshin", False):
                _run_cloud(account, "CloudGenshin", account_report)
            if getattr(account, "CloudStarRail", False):
                _run_cloud(account, "CloudStarRail", account_report)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            log.exception(f"[{name}] 米游社任务异常")
            account_report.error = str(exc)
        if index < len(accounts) - 1:
            time.sleep(random.uniform(2, 4))
    log.info("米游社/云游戏任务结束")
