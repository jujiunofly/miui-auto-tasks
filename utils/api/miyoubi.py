"""米游币任务：大别野打卡、浏览、点赞、分享。

逻辑参考 Yoimiya-993/Miyoushe-Auto，使用 stoken + mid/stuid。
"""

import hashlib
import json
import random
import re
import string
import time
import uuid
from typing import Optional

from ..logger import log
from ..report import MihoyoAccountReport, TaskResult
from ..request import get, post

BBS_HOST = "bbs-api.miyoushe.com"
APP_VERSION = "2.117.0"
CLIENT_TYPE = "2"
SALT_DS1 = "xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs"
SALT_DS2 = "t0qEgfub6cvueAPgR5m9aQWWVciEer7v"
CHANNEL_ID = "5"  # 大别野
FORUM_ID = "34"  # 大别野板块（MihoyoBBSTools 当前配置）

VERIFY_URL = "https://api-takumi.mihoyo.com/auth/api/getCookieAccountInfoBySToken"
LIST_URL = (
    f"https://{BBS_HOST}/post/api/getForumPostList"
    f"?forum_id={FORUM_ID}&is_good=false&is_hot=false&page_size=20&sort_type=1"
)
DETAIL_URL = f"https://{BBS_HOST}/post/api/getPostFull?post_id={{}}"
SHARE_URL = f"https://{BBS_HOST}/apihub/api/getShareConf?entity_id={{}}&entity_type=1"
VOTE_URL = f"https://{BBS_HOST}/apihub/sapi/upvotePost"
SIGN_URL = f"https://{BBS_HOST}/apihub/app/api/signIn"
TASK_LIST_URL = f"https://{BBS_HOST}/apihub/wapi/getUserMissionsState"
TASK_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 12; Unspecified Device) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Version/4.0 Chrome/103.0.5060.129 Mobile Safari/537.36 miHoYoBBS/{APP_VERSION}"
)

_DEVICE_ID = str(uuid.uuid4()).upper()


def _random_str(length: int) -> str:
    return "".join(
        random.choices(string.ascii_letters + string.digits, k=length)
    )


def _ds1() -> str:
    timestamp = int(time.time())
    nonce = _random_str(6)
    raw = f"salt={SALT_DS1}&t={timestamp}&r={nonce}"
    return f"{timestamp},{nonce},{hashlib.md5(raw.encode('utf-8')).hexdigest()}"


def _ds2(body: str = "", query: str = "") -> str:
    timestamp = int(time.time())
    nonce = random.randint(100001, 200000)
    raw = f"salt={SALT_DS2}&t={timestamp}&r={nonce}&b={body}&q={query}"
    return f"{timestamp},{nonce},{hashlib.md5(raw.encode('utf-8')).hexdigest()}"


def _headers(ds: str) -> dict:
    return {
        "User-Agent": "okhttp/4.9.3",
        "DS": ds,
        "x-rpc-client_type": CLIENT_TYPE,
        "x-rpc-app_version": APP_VERSION,
        "x-rpc-sys_version": "12",
        "x-rpc-channel": "miyousheluodi",
        "x-rpc-device_id": _DEVICE_ID,
        "x-rpc-device_name": "HUAWEI LIO-AN00",
        "x-rpc-device_model": "LIO-AN00",
        "x-rpc-h265_supported": "1",
        "x-rpc-verify_key": "bll8iq97cem8",
        "x-rpc-csm_source": "discussion",
        "Content-Type": "application/json; charset=UTF-8",
        "Referer": "https://app.mihoyo.com",
        "Host": BBS_HOST,
    }


def _cookie_dict(account) -> dict:
    stoken = str(getattr(account, "stoken", "") or "").strip()
    cookie = str(getattr(account, "cookie", "") or "")
    mid = str(getattr(account, "mid", "") or "").strip()
    stuid = str(getattr(account, "stuid", "") or "").strip()
    if not mid:
        mid_match = re.search(
            r"(?:account_mid_v2|ltmid_v2|mid)=([^;]+)", cookie
        )
        if mid_match:
            mid = mid_match.group(1).strip()
    if not stuid:
        stuid_match = re.search(
            r"(?:account_id|ltuid|login_uid|ltuid_v2|account_id_v2)=(\d+)",
            cookie,
        )
        if stuid_match:
            stuid = stuid_match.group(1).strip()
    if not stoken:
        raise ValueError("未配置米游币 stoken")
    if stoken.startswith("v2_"):
        if not mid:
            raise ValueError(
                "Cookie 中没有 mid（account_mid_v2/ltmid_v2），请重新导出米游社 Cookie"
            )
        return {"stoken": stoken, "mid": mid}
    if not stuid:
        stuid = mid
    if not stuid:
        raise ValueError(
            "Cookie 中没有 uid（ltuid/account_id），请重新导出米游社 Cookie"
        )
    return {"stoken": stoken, "stuid": stuid}


def _payload(response, action: str) -> dict:
    try:
        data = response.json()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise RuntimeError(f"{action}返回格式异常") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{action}返回格式异常")
    return data


def _check(data: dict, action: str):
    if data.get("retcode") != 0:
        message = data.get("message") or data.get("msg") or "未知错误"
        raise RuntimeError(f"{action}失败: {message} (code {data.get('retcode')})")


def _verify_stoken(cookies: dict):
    response = get(
        VERIFY_URL,
        headers={"User-Agent": "okhttp/4.9.3"},
        cookies=cookies,
        timeout=20,
    )
    data = _payload(response, "验证登录状态")
    if data.get("retcode") == -100:
        raise RuntimeError("stoken 已失效")
    _check(data, "验证登录状态")


def _get_posts(cookies: dict) -> list[dict]:
    response = get(
        LIST_URL,
        headers=_headers(_ds1()),
        cookies=cookies,
        timeout=20,
    )
    data = _payload(response, "获取大别野帖子")
    _check(data, "获取大别野帖子")
    posts = []
    for item in (data.get("data") or {}).get("list") or []:
        post = item.get("post") or {}
        if post.get("post_id"):
            posts.append(
                {
                    "post_id": post.get("post_id"),
                    "subject": post.get("subject") or "帖子",
                }
            )
        if len(posts) >= 5:
            break
    if not posts:
        raise RuntimeError("没有获取到大别野帖子")
    return posts


def _read_post(cookies: dict, item: dict):
    response = get(
        DETAIL_URL.format(item["post_id"]),
        headers=_headers(_ds1()),
        cookies=cookies,
        timeout=20,
    )
    _check(_payload(response, "浏览帖子"), "浏览帖子")


def _upvote(cookies: dict, item: dict):
    response = post(
        VOTE_URL,
        headers=_headers(_ds1()),
        cookies=cookies,
        json={"post_id": item["post_id"], "is_cancel": False},
        timeout=20,
    )
    _check(_payload(response, "点赞帖子"), "点赞帖子")


def _share(cookies: dict, item: dict):
    response = get(
        SHARE_URL.format(item["post_id"]),
        headers=_headers(_ds1()),
        cookies=cookies,
        timeout=20,
    )
    _check(_payload(response, "分享帖子"), "分享帖子")


def _sign_in(cookies: dict):
    body = {"gids": CHANNEL_ID}
    response = post(
        SIGN_URL,
        headers=_headers(_ds2(json.dumps(body))),
        cookies=cookies,
        json=body,
        timeout=20,
    )
    _check(_payload(response, "大别野打卡"), "大别野打卡")


def _task_headers(account) -> dict:
    cookie = str(getattr(account, "cookie", "") or "").strip()
    if not cookie:
        raise ValueError("未配置米游社 Cookie")
    return {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://webstatic.mihoyo.com",
        "User-Agent": TASK_USER_AGENT,
        "Referer": "https://webstatic.mihoyo.com",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,en-US;q=0.8",
        "X-Requested-With": "com.mihoyo.hyperion",
        "Cookie": cookie,
    }


def _get_task_status(account) -> dict:
    response = get(
        TASK_LIST_URL,
        params={"point_sn": "myb"},
        headers=_task_headers(account),
        timeout=20,
    )
    data = _payload(response, "获取米游币任务状态")
    if data.get("retcode") == -100:
        raise RuntimeError("米游社 Cookie 已过期")
    _check(data, "获取米游币任务状态")
    info = data.get("data") or {}
    status = {
        "can_get": int(info.get("can_get_points") or 0),
        "already": int(info.get("already_received_points") or 0),
        "total": int(info.get("total_points") or 0),
        "sign": False,
        "read": 0,
        "like": 0,
        "share": False,
    }
    if status["can_get"] == 0:
        status.update({"sign": True, "read": 3, "like": 5, "share": True})
        return status

    for mission in info.get("states") or []:
        try:
            mission_id = int(mission.get("mission_id"))
        except (TypeError, ValueError):
            continue
        awarded = bool(mission.get("is_get_award"))
        happened = int(mission.get("happened_times") or 0)
        if mission_id == 58:
            status["sign"] = awarded
        elif mission_id == 59:
            status["read"] = 3 if awarded else min(3, happened)
        elif mission_id == 60:
            status["like"] = 5 if awarded else min(5, happened)
        elif mission_id == 61:
            status["share"] = awarded
    return status


def _run(account) -> tuple[bool, str]:
    cookies = _cookie_dict(account)
    _verify_stoken(cookies)
    log.info("米游币登录状态正常")
    status = _get_task_status(account)
    if status["can_get"] == 0:
        return True, f"今日米游币任务已完成，当前 {status['total']} 米游币"

    read_need = max(0, 3 - status["read"])
    like_need = max(0, 5 - status["like"])
    need_share = not status["share"]
    need_sign = not status["sign"]
    posts = []
    if read_need or like_need or need_share:
        posts = _get_posts(cookies)
        log.info(f"获取到 {len(posts)} 个大别野帖子")
    if read_need and len(posts) < read_need:
        raise RuntimeError("大别野帖子数量不足，无法完成浏览任务")
    if like_need and len(posts) < like_need:
        raise RuntimeError("大别野帖子数量不足，无法完成点赞任务")
    if need_share and not posts:
        raise RuntimeError("没有可分享的大别野帖子")

    details = []

    if read_need:
        for item in posts[:read_need]:
            _read_post(cookies, item)
            details.append(f"浏览 {item['subject']}")
            time.sleep(2)
    else:
        details.append("浏览已完成")

    if like_need:
        for item in posts[:like_need]:
            _upvote(cookies, item)
            details.append(f"点赞 {item['subject']}")
            time.sleep(2)
    else:
        details.append("点赞已完成")

    if need_share:
        _share(cookies, posts[0])
        details.append("分享 1 篇")
        time.sleep(2)
    else:
        details.append("分享已完成")

    if need_sign:
        try:
            _sign_in(cookies)
            details.append("大别野打卡")
        except RuntimeError as exc:
            log.warning(f"米游币大别野打卡失败: {exc}")
            return False, "；".join(details + [f"打卡失败: {exc}"])
    else:
        details.append("打卡已完成")

    details.append(f"当前 {status['total']} 米游币")
    return True, "；".join(details)


def run_miyoubi(account, report: MihoyoAccountReport):
    """执行单个账号的米游币任务，并把结果写入米游社报告。"""
    try:
        success, message = _run(account)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log.error(f"米游币任务失败: {exc}")
        report.executed.append(
            TaskResult(name="米游币任务", success=False, message=str(exc))
        )
        return
    report.executed.append(
        TaskResult(name="米游币任务", success=success, message=message)
    )
    if success:
        log.success(f"米游币任务完成: {message}")
    else:
        log.error(f"米游币任务未完成: {message}")
