"""米游社游戏签到与云游戏签到。

游戏签到部分对齐 Womsxd/MihoyoBBSTools 已验证的 2.117.0 Web 接口。
"""

import hashlib
import random
import string
import time
from typing import Optional

from ..config import ConfigManager
from ..captcha_solver import is_configured as captcha_configured
from ..captcha_solver import solve_geetest
from ..logger import log
from ..report import MihoyoAccountReport, TaskResult
from ..request import get, post
from .miyoubi import refresh_account_cookie, run_miyoubi

MYS_HOST = "api-takumi.mihoyo.com"
MYS_APP_VERSION = "2.117.0"
MYS_DS_SALT = "4751cb5557bfad5e249e58462c39fb0a"
MYS_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 12; Unspecified Device) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Version/4.0 Chrome/103.0.5060.129 Mobile Safari/537.36 miHoYoBBS/{MYS_APP_VERSION}"
)

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
        "signgame": "",
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
    """生成米游社 Web 签到 DS 签名。"""
    timestamp = str(int(time.time()))
    nonce = "".join(
        random.sample(string.ascii_lowercase + string.digits, 6)
    )
    raw = f"salt={MYS_DS_SALT}&t={timestamp}&r={nonce}"
    return f"{timestamp},{nonce},{hashlib.md5(raw.encode('utf-8')).hexdigest()}"


def _web_headers(cookie: str, signgame: str = "") -> dict:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "DS": _ds(),
        "x-rpc-channel": "miyousheluodi",
        "x-rpc-app_version": MYS_APP_VERSION,
        "User-Agent": MYS_USER_AGENT,
        "x-rpc-client_type": "5",
        "Referer": "https://act.mihoyo.com/",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,en-US;q=0.8",
        "X-Requested-With": "com.mihoyo.hyperion",
        "Cookie": cookie,
        "x-rpc-device_id": "",
    }
    if signgame:
        headers["x-rpc-signgame"] = signgame
    headers["Origin"] = "https://act.mihoyo.com"
    return {key: str(value) for key, value in headers.items()}


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


def _get_roles(account, game_key: str, retry: bool = True) -> list[dict]:
    game = MYS_GAMES[game_key]
    try:
        response = get(
            f"https://{MYS_HOST}/binding/api/getUserGameRolesByCookie",
            params={"game_biz": game["biz"]},
            headers=_web_headers(account.cookie, game["signgame"]),
            timeout=20,
        )
        payload = response.json()
        log.debug(f"[{game['label']}] 角色接口: {response.text}")
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception(f"[{game['label']}] 获取角色异常")
        return []

    if payload.get("retcode") == -100 and retry:
        try:
            refresh_account_cookie(account)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            log.error(f"[{game['label']}] Cookie 刷新失败: {exc}")
            return []
        return _get_roles(account, game_key, retry=False)
    if payload.get("retcode") != 0:
        log.error(
            f"[{game['label']}] Cookie 无效或获取角色失败: {_message(payload)}"
        )
        return []
    roles = (payload.get("data") or {}).get("list") or []
    if not roles:
        log.error(f"[{game['label']}] Cookie 下没有找到角色")
    return roles


def _get_rewards(account, game_key: str) -> list:
    game = MYS_GAMES[game_key]
    try:
        response = get(
            f"https://{MYS_HOST}/event/luna/home",
            params={"lang": "zh-cn", "act_id": game["act_id"]},
            headers=_web_headers(account.cookie, game["signgame"]),
            timeout=20,
        )
        payload = response.json()
        if payload.get("retcode") == 0:
            return (payload.get("data") or {}).get("awards") or []
        log.warning(f"[{game['label']}] 获取签到奖励失败: {_message(payload)}")
    except Exception:  # pylint: disable=broad-exception-caught
        log.warning(f"[{game['label']}] 获取签到奖励异常")
    return []


def _checkin_info(
    account, game_key: str, role: dict, retry: bool = True
) -> dict:
    game = MYS_GAMES[game_key]
    response = get(
        f"https://{MYS_HOST}/event/luna/info",
        params={
            "lang": "zh-cn",
            "act_id": game["act_id"],
            "region": role.get("region") or game["region"],
            "uid": role.get("game_uid", ""),
        },
        headers=_web_headers(account.cookie, game["signgame"]),
        timeout=20,
    )
    payload = response.json()
    log.debug(f"[{game['label']}] 签到信息: {response.text}")
    if payload.get("retcode") == -100 and retry:
        refresh_account_cookie(account)
        return _checkin_info(account, game_key, role, retry=False)
    if payload.get("retcode") != 0:
        raise RuntimeError(_message(payload) or "获取签到状态失败")
    return payload.get("data") or {}


def _solve_game_captcha(
    account, game_key: str, gt: str, challenge: str
) -> Optional[dict]:
    if not captcha_configured():
        log.warning("游戏签到触发验证码，但未配置自动打码")
        return None
    game = MYS_GAMES[game_key]
    solution = solve_geetest(
        "https://act.mihoyo.com/",
        str(gt),
        str(challenge),
        user_agent=MYS_USER_AGENT,
    )
    if not solution:
        log.error(f"[{game['label']}] 自动打码失败")
        return None
    return solution


def _sign_game(account, game_key: str, role: dict) -> tuple[bool, str]:
    game = MYS_GAMES[game_key]
    region = role.get("region") or game["region"]
    uid = role.get("game_uid", "")
    body = {"act_id": game["act_id"], "region": region, "uid": uid}
    captcha_try = False
    captcha_headers = {}
    for attempt in range(3):
        headers = _web_headers(account.cookie, game["signgame"])
        headers.update(captcha_headers)
        try:
            response = post(
                f"https://{MYS_HOST}/event/luna/sign",
                headers=headers,
                json=body,
                timeout=20,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception(f"[{game['label']}] 签到异常")
            return False, "签到请求异常"
        if response.status_code == 429:
            log.warning(f"[{game['label']}] 429 请求过多，10 秒后重试")
            time.sleep(10)
            continue
        try:
            payload = response.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return False, "签到返回格式异常"
        log.debug(f"[{game['label']}] 签到接口: {response.text}")
        retcode = payload.get("retcode")
        data = payload.get("data") or {}
        if retcode == 0 and data.get("success") == 0:
            return True, "签到成功"
        if retcode == -5003 or "已签到" in _message(payload):
            return True, "今日已签到"
        if retcode == -100:
            try:
                refresh_account_cookie(account)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                return False, f"Cookie 已过期且刷新失败: {exc}"
            continue
        if (
            retcode == 0
            and data.get("success") != 0
            and data.get("gt")
            and data.get("challenge")
            and not captcha_try
        ):
            solution = _solve_game_captcha(
                account,
                game_key,
                data["gt"],
                data["challenge"],
            )
            if solution:
                captcha_headers = {
                    "x-rpc-challenge": solution["challenge"],
                    "x-rpc-validate": solution["validate"],
                    "x-rpc-seccode": solution["seccode"],
                }
                captcha_try = True
                time.sleep(random.uniform(6, 15))
                continue
        return False, _message(payload) or f"签到失败 (code {retcode})"
    return False, "签到重试次数已用完"


def _run_community(account, game_key: str, report: MihoyoAccountReport):
    game = MYS_GAMES[game_key]
    label = game["label"]
    if not account.cookie:
        log.warning(f"[{label}] 未配置米游社 Cookie，跳过")
        report.executed.append(TaskResult(name=label, success=False, message="未配置 Cookie"))
        return
    roles = _get_roles(account, game_key)
    if not roles:
        report.executed.append(
            TaskResult(name=label, success=False, message="Cookie 无效或未找到角色")
        )
        return

    rewards = _get_rewards(account, game_key)
    details = []
    failures = []
    for index, role in enumerate(roles):
        nickname = role.get("nickname") or "角色"
        try:
            info = _checkin_info(account, game_key, role)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            failures.append(f"{nickname} 获取签到状态失败: {exc}")
            continue
        if info.get("first_bind"):
            failures.append(f"{nickname} 首次绑定，请手动签到一次")
            continue
        if info.get("is_sign"):
            days = info.get("total_sign_day")
            details.append(f"{nickname} 今日已签到" + (f"（{days} 天）" if days else ""))
            continue
        success, message = _sign_game(account, game_key, role)
        if not success:
            failures.append(f"{nickname} {message}")
            continue
        reward = ""
        if rewards:
            sign_days = int(info.get("total_sign_day") or 0)
            reward_index = min(sign_days, len(rewards) - 1)
            item = rewards[reward_index] or {}
            if item.get("name"):
                reward = f"，获得「{item.get('name')}」x{item.get('cnt', 1)}"
        details.append(f"{nickname} {message}{reward}")
        if index < len(roles) - 1:
            time.sleep(random.uniform(2, 8))

    success = not failures
    detail = "；".join(details + failures) if details or failures else "没有可签到的角色"
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
            if getattr(account, "Miyoubi", False):
                run_miyoubi(account, account_report)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            log.exception(f"[{name}] 米游社任务异常")
            account_report.error = str(exc)
        if index < len(accounts) - 1:
            time.sleep(random.uniform(2, 4))
    log.info("米游社/云游戏任务结束")
