"""米游币任务：多分区签到、浏览、点赞、分享。

实现对齐 Womsxd/MihoyoBBSTools 的已验证流程：
- BBS 请求使用 stoken Cookie 与 App 签名盐；
- 任务状态使用完整 Cookie；
- Cookie 失效时用 stoken 自动换票刷新；
- 支持大别野/原神两个分区签到。
"""

import hashlib
import json
import random
import re
import string
import time
import uuid
from typing import Optional

from ..captcha_solver import is_configured as captcha_configured
from ..captcha_solver import solve_geetest
from ..config import ConfigManager
from ..logger import log
from ..report import MihoyoAccountReport, TaskResult
from ..request import get, post

BBS_API = "https://bbs-api.miyoushe.com"
PASSPORT_EXCHANGE_URL = (
    "https://passport-api.mihoyo.com/account/ma-cn-session/app/exchange"
)
COOKIE_TOKEN_URL = (
    "https://api-takumi.mihoyo.com/auth/api/getCookieAccountInfoBySToken"
)

BBS_APP_VERSION = "2.117.0"
PASSPORT_APP_VERSION = "2.44.0"
BBS_CLIENT_TYPE = "2"
BBS_SALT = "9c7b896d7483e9070b27c55f1959c4d5"
BBS_DS2_SALT = "t0qEgfub6cvueAPgR5m9aQWWVciEer7v"
PASSPORT_SALT = "JwYDpKvLj6MrMqqYU6jTKF17KNO2PXoS"
BBS_APP_ID = "bll8iq97cem8"

TASK_LIST_URL = f"{BBS_API}/apihub/wapi/getUserMissionsState"
SIGN_URL = f"{BBS_API}/apihub/app/api/signIn"
POST_LIST_URL = f"{BBS_API}/post/api/getForumPostList"
POST_DETAIL_URL = f"{BBS_API}/post/api/getPostFull"
SHARE_URL = f"{BBS_API}/apihub/api/getShareConf"
LIKE_URL = f"{BBS_API}/apihub/sapi/upvotePost"
CAPTCHA_CREATE_URL = f"{BBS_API}/misc/api/createVerification?is_high=true"
CAPTCHA_VERIFY_URL = f"{BBS_API}/misc/api/verifyVerification"

TASK_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 12; Unspecified Device) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Version/4.0 Chrome/103.0.5060.129 Mobile Safari/537.36 miHoYoBBS/{BBS_APP_VERSION}"
)
APP_USER_AGENT = "okhttp/4.9.3"

# 与 MihoyoBBSTools 当前配置一致：5=大别野，2=原神。
CHECKIN_FORUMS = (("5", "大别野"), ("2", "原神"))

COOKIE_ORDER = (
    "ltoken",
    "ltuid",
    "account_id",
    "cookie_token",
    "login_ticket",
    "ltoken_v2",
    "ltuid_v2",
    "ltmid_v2",
    "cookie_token_v2",
    "account_id_v2",
    "account_mid_v2",
)
V2_TO_V1_ALIASES = (
    ("ltoken_v2", "ltoken"),
    ("ltuid_v2", "ltuid"),
    ("account_id_v2", "account_id"),
    ("cookie_token_v2", "cookie_token"),
)

_LIFECYCLE_ID = str(uuid.uuid4())


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _random_text(length: int) -> str:
    return "".join(
        random.sample(string.ascii_lowercase + string.digits, length)
    )


def _ds() -> str:
    """BBS App 通用签名（salt 跟随 2.117.0）。"""
    timestamp = str(int(time.time()))
    nonce = _random_text(6)
    digest = _md5(f"salt={BBS_SALT}&t={timestamp}&r={nonce}")
    return f"{timestamp},{nonce},{digest}"


def _ds2(body: str, query: str = "") -> str:
    timestamp = str(int(time.time()))
    nonce = str(random.randint(100001, 200000))
    digest = _md5(
        f"salt={BBS_DS2_SALT}&t={timestamp}&r={nonce}&b={body}&q={query}"
    )
    return f"{timestamp},{nonce},{digest}"


def _passport_ds(body: str) -> str:
    timestamp = str(int(time.time()))
    nonce = _random_text(6)
    digest = _md5(
        f"salt={PASSPORT_SALT}&t={timestamp}&r={nonce}&b={body}&q="
    )
    return f"{timestamp},{nonce},{digest}"


def _parse_cookie(cookie: str) -> dict:
    result = {}
    for segment in re.split(r"[;\r\n]+", cookie or ""):
        text = segment.strip()
        if not text or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key, value = key.strip(), value.strip()
        if key and value:
            result[key] = value
    return result


def _format_cookie(fields: dict) -> str:
    ordered = [key for key in COOKIE_ORDER if fields.get(key)]
    ordered += [
        key for key in fields if key not in COOKIE_ORDER and fields[key]
    ]
    return ";".join(f"{key}={fields[key]}" for key in ordered) + ";"


def _sync_cookie_aliases(fields: dict) -> bool:
    changed = False
    for v2_key, v1_key in V2_TO_V1_ALIASES:
        value = fields.get(v2_key)
        if value and fields.get(v1_key) != value:
            fields[v1_key] = value
            changed = True
    return changed


def _account_ids(account) -> tuple[str, str, str]:
    """从 Cookie/账号配置中解析 stuid、mid、stoken。"""
    cookie = str(getattr(account, "cookie", "") or "")
    fields = _parse_cookie(cookie)
    stoken = str(getattr(account, "stoken", "") or "").strip()
    mid = str(getattr(account, "mid", "") or "").strip()
    stuid = str(getattr(account, "stuid", "") or "").strip()

    if not mid:
        for key in ("account_mid_v2", "ltmid_v2", "mid"):
            if fields.get(key):
                mid = fields[key]
                break
    if not stuid:
        for key in ("account_id", "ltuid", "login_uid", "ltuid_v2", "account_id_v2"):
            if fields.get(key):
                stuid = fields[key]
                break

    if not stoken:
        raise ValueError("未配置米游币 stoken")
    if stoken.startswith("v2_"):
        if not mid:
            raise ValueError(
                "Cookie 中没有 mid（account_mid_v2/ltmid_v2），请重新导出米游社 Cookie"
            )
        if not stuid:
            stuid = mid
        return stuid, mid, stoken
    if not stuid:
        stuid = mid
    if not stuid:
        raise ValueError(
            "Cookie 中没有 uid（ltuid/account_id），请重新导出米游社 Cookie"
        )
    return stuid, mid or stuid, stoken


def _device_id(account) -> str:
    seed = str(getattr(account, "cookie", "") or "") + str(
        getattr(account, "stoken", "") or ""
    )
    return str(uuid.uuid3(uuid.NAMESPACE_URL, seed))


def _stoken_cookie(account) -> str:
    stuid, mid, stoken = _account_ids(account)
    parts = [f"stuid={stuid}", f"stoken={stoken}"]
    if stoken.startswith("v2_"):
        parts.append(f"mid={mid}")
    return ";".join(parts)


def _full_cookie(account) -> str:
    cookie = str(getattr(account, "cookie", "") or "").strip()
    if not cookie:
        raise ValueError("未配置米游社 Cookie")
    return cookie


def _app_headers(account) -> dict:
    return {
        "DS": _ds(),
        "cookie": _stoken_cookie(account),
        "x-rpc-client_type": BBS_CLIENT_TYPE,
        "x-rpc-app_version": BBS_APP_VERSION,
        "x-rpc-sys_version": "12",
        "x-rpc-channel": "miyousheluodi",
        "x-rpc-device_id": _device_id(account),
        "x-rpc-device_name": "Xiaomi MI 6",
        "x-rpc-device_model": "Mi 6",
        "x-rpc-h265_supported": "1",
        "Referer": "https://app.mihoyo.com",
        "x-rpc-verify_key": BBS_APP_ID,
        "x-rpc-csm_source": "discussion",
        "Content-Type": "application/json; charset=UTF-8",
        "Host": "bbs-api.miyoushe.com",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "User-Agent": APP_USER_AGENT,
    }


def _task_headers(account) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://webstatic.mihoyo.com",
        "User-Agent": TASK_USER_AGENT,
        "Referer": "https://webstatic.mihoyo.com",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,en-US;q=0.8",
        "X-Requested-With": "com.mihoyo.hyperion",
        "Cookie": _full_cookie(account),
    }


def _payload(response, action: str) -> dict:
    try:
        data = response.json()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise RuntimeError(f"{action}返回格式异常") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{action}返回格式异常")
    return data


def _message(data: dict) -> str:
    return str(data.get("message") or data.get("msg") or "未知错误")


def _check(data: dict, action: str):
    if data.get("retcode") != 0:
        raise RuntimeError(
            f"{action}失败: {_message(data)} (code {data.get('retcode')})"
        )


def _cookie_invalid(data: dict) -> bool:
    message = _message(data)
    return data.get("retcode") == -100 or "err" in message.lower()


def refresh_account_cookie(account) -> str:
    """用 stoken 换票刷新米游社 Cookie，并写回配置。"""
    stuid, mid, stoken = _account_ids(account)
    fields = _parse_cookie(getattr(account, "cookie", "") or "")

    if stoken.startswith("v2_"):
        body = json.dumps(
            {
                "dst_token_type": 4,
                "src_token": {"token": stoken, "token_type": 1},
                "mid": mid,
            },
            separators=(",", ":"),
        )
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "DS": _passport_ds(body),
            "x-rpc-app_id": BBS_APP_ID,
            "x-rpc-client_type": "2",
            "x-rpc-app_version": BBS_APP_VERSION,
            "x-rpc-game_biz": "bbs_cn",
            "x-rpc-sys_version": "12",
            "x-rpc-sdk_version": PASSPORT_APP_VERSION,
            "x-rpc-account_version": PASSPORT_APP_VERSION,
            "x-rpc-lifecycle_id": _LIFECYCLE_ID,
            "x-rpc-device_id": _device_id(account),
            "x-rpc-device_name": "Xiaomi MI 6",
            "x-rpc-device_model": "Mi 6",
            "User-Agent": APP_USER_AGENT,
        }
        response = post(
            PASSPORT_EXCHANGE_URL,
            headers=headers,
            data=body.encode("utf-8"),
            timeout=20,
        )
        data = _payload(response, "刷新 Cookie")
        if data.get("retcode") != 0:
            raise RuntimeError(
                f"刷新 Cookie 失败: {_message(data)} (code {data.get('retcode')})"
            )
        token = ((data.get("data") or {}).get("token") or {}).get("token")
        if not token:
            raise RuntimeError("刷新 Cookie 失败: 响应缺少 cookie_token")
        fields["cookie_token_v2"] = token
        fields["account_id_v2"] = stuid
        fields["account_mid_v2"] = mid
        fields.setdefault("ltuid_v2", stuid)
        fields.setdefault("ltmid_v2", mid)
    else:
        response = get(
            COOKIE_TOKEN_URL,
            headers={"User-Agent": APP_USER_AGENT},
            cookies={"stuid": stuid, "stoken": stoken},
            timeout=20,
        )
        data = _payload(response, "刷新 Cookie")
        if data.get("retcode") != 0:
            raise RuntimeError(
                f"刷新 Cookie 失败: {_message(data)} (code {data.get('retcode')})"
            )
        token = (data.get("data") or {}).get("cookie_token")
        if not token:
            raise RuntimeError("刷新 Cookie 失败: 响应缺少 cookie_token")
        fields["cookie_token"] = token
        fields.setdefault("account_id", stuid)

    _sync_cookie_aliases(fields)
    account.cookie = _format_cookie(fields)
    ConfigManager.write_plugin_data()
    log.success("米游社 Cookie 已自动刷新")
    return account.cookie


def _get_tasks(account, retry: bool = True) -> dict:
    log.info("正在获取米游币任务状态")
    response = get(
        TASK_LIST_URL,
        params={"point_sn": "myb"},
        headers=_task_headers(account),
        timeout=20,
    )
    data = _payload(response, "获取米游币任务状态")
    if _cookie_invalid(data):
        if not retry:
            raise RuntimeError("米游社 Cookie 已过期，自动刷新后仍无效")
        try:
            refresh_account_cookie(account)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                f"米游社 Cookie 已过期，自动刷新失败: {exc}"
            ) from exc
        return _get_tasks(account, retry=False)
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


def _get_posts(account, count: int) -> list[dict]:
    log.info("正在获取大别野帖子")
    response = get(
        POST_LIST_URL,
        params={
            "forum_id": "34",
            "is_good": "false",
            "is_hot": "false",
            "page_size": 20,
            "sort_type": 1,
        },
        headers=_app_headers(account),
        timeout=20,
    )
    data = _payload(response, "获取大别野帖子")
    _check(data, "获取大别野帖子")
    items = (data.get("data") or {}).get("list") or []
    posts = []
    seen = set()
    for item in items:
        post = item.get("post") or {}
        post_id = post.get("post_id")
        subject = post.get("subject") or "帖子"
        if post_id and post_id not in seen:
            seen.add(post_id)
            posts.append({"post_id": post_id, "subject": subject})
    if not posts:
        raise RuntimeError("没有获取到大别野帖子")
    random.shuffle(posts)
    return posts[: max(1, count)]


def _read_post(account, item: dict):
    response = get(
        POST_DETAIL_URL,
        params={"post_id": item["post_id"]},
        headers=_app_headers(account),
        timeout=20,
    )
    _check(_payload(response, "浏览帖子"), "浏览帖子")


def _solve_bbs_challenge(account) -> Optional[str]:
    if not captcha_configured():
        log.warning("米游社触发验证码，但未配置自动打码，跳过本次操作")
        return None
    response = get(
        CAPTCHA_CREATE_URL,
        headers=_app_headers(account),
        timeout=20,
    )
    data = _payload(response, "创建米游社验证码")
    if data.get("retcode") != 0:
        log.error(f"创建米游社验证码失败: {_message(data)}")
        return None
    info = data.get("data") or {}
    gt = info.get("gt")
    challenge = info.get("challenge")
    if not gt or not challenge:
        log.error("米游社验证码响应缺少 gt/challenge")
        return None
    solution = solve_geetest(
        "https://bbs.miyoushe.com/",
        str(gt),
        str(challenge),
        user_agent=APP_USER_AGENT,
    )
    if not solution:
        return None
    verify = post(
        CAPTCHA_VERIFY_URL,
        headers=_app_headers(account),
        json={
            "geetest_challenge": solution["challenge"],
            "geetest_seccode": solution["seccode"],
            "geetest_validate": solution["validate"],
        },
        timeout=20,
    )
    result = _payload(verify, "验证米游社验证码")
    if result.get("retcode") != 0:
        log.error(f"米游社验证码校验失败: {_message(result)}")
        return None
    verified = (result.get("data") or {}).get("challenge")
    if not verified:
        log.error("米游社验证码校验成功但缺少 challenge")
        return None
    return str(verified)


def _like_post(account, item: dict, captcha_try: bool = False):
    headers = _app_headers(account)
    if captcha_try:
        challenge = _solve_bbs_challenge(account)
        if not challenge:
            return False
        headers["x-rpc-challenge"] = challenge
    response = post(
        LIKE_URL,
        headers=headers,
        json={"post_id": item["post_id"], "is_cancel": False},
        timeout=20,
    )
    data = _payload(response, "点赞帖子")
    if data.get("retcode") == 0:
        return True
    if data.get("retcode") == 1034 and not captcha_try:
        log.warning("点赞触发米游社验证码")
        return _like_post(account, item, captcha_try=True)
    raise RuntimeError(
        f"点赞帖子失败: {_message(data)} (code {data.get('retcode')})"
    )


def _share_post(account, item: dict):
    last_error = ""
    for _ in range(3):
        response = get(
            SHARE_URL,
            params={"entity_id": item["post_id"], "entity_type": 1},
            headers=_app_headers(account),
            timeout=20,
        )
        data = _payload(response, "分享帖子")
        if data.get("retcode") == 0:
            return
        last_error = f"{_message(data)} (code {data.get('retcode')})"
        time.sleep(random.uniform(3, 8))
    raise RuntimeError(f"分享帖子失败: {last_error}")


def _sign_forum(account, forum_id: str, captcha_try: bool = False) -> tuple[bool, str]:
    body = json.dumps({"gids": forum_id})
    headers = _app_headers(account)
    headers["DS"] = _ds2(body)
    if captcha_try:
        challenge = _solve_bbs_challenge(account)
        if not challenge:
            return False, "触发验证码且自动验证失败"
        headers["x-rpc-challenge"] = challenge
    response = post(
        SIGN_URL,
        headers=headers,
        data=body,
        timeout=20,
    )
    data = _payload(response, "米游社签到")
    if data.get("retcode") == 0:
        return True, str(data.get("message") or "签到成功")
    if data.get("retcode") == 1034 and not captcha_try:
        log.warning("米游社签到触发验证码")
        return _sign_forum(account, forum_id, captcha_try=True)
    if data.get("retcode") == -100:
        try:
            refresh_account_cookie(account)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return False, f"Cookie 已过期且刷新失败: {exc}"
        return _sign_forum(account, forum_id, captcha_try)
    return False, f"{_message(data)} (code {data.get('retcode')})"


def _sign_forums(account) -> tuple[list[str], list[str]]:
    signed = []
    failed = []
    for forum_id, name in CHECKIN_FORUMS:
        ok, message = _sign_forum(account, forum_id)
        if ok:
            signed.append(name)
        else:
            failed.append(f"{name}签到失败: {message}")
        time.sleep(random.uniform(3, 8))
    return signed, failed


def _run(account) -> tuple[bool, str]:
    _account_ids(account)
    status = _get_tasks(account)
    if status["can_get"] == 0:
        return True, f"今日米游币任务已完成，当前 {status['total']} 米游币"

    actions = []
    failures = []
    signed = False
    read_done = 0
    like_done = 0
    share_done = False
    posts: list[dict] = []

    for round_index in range(2):
        if round_index:
            time.sleep(random.uniform(3, 8))

        if not status["sign"] and not signed:
            names, errors = _sign_forums(account)
            if names:
                actions.append(f"签到 {'、'.join(names)}")
                if len(names) == len(CHECKIN_FORUMS):
                    signed = True
            failures.extend(errors)

        read_need = max(0, 3 - status["read"] - read_done)
        like_need = max(0, 5 - status["like"] - like_done)
        share_need = not status["share"] and not share_done
        need_posts = max(read_need, like_need, 1 if share_need else 0)
        if need_posts and not posts:
            posts = _get_posts(account, need_posts)

        for item in posts[:read_need]:
            _read_post(account, item)
            read_done += 1
            time.sleep(random.uniform(3, 8))
        if read_need:
            actions.append(f"浏览 {read_need} 篇")

        for item in posts[:like_need]:
            if not _like_post(account, item):
                raise RuntimeError("点赞失败: 米游社验证码未通过")
            like_done += 1
            time.sleep(random.uniform(3, 8))
        if like_need:
            actions.append(f"点赞 {like_need} 篇")

        if share_need and posts:
            _share_post(account, posts[0])
            share_done = True
            actions.append("分享 1 篇")
            time.sleep(random.uniform(3, 8))

        status = _get_tasks(account)
        if status["can_get"] == 0:
            break

    summary = "；".join(actions) if actions else "没有新的可执行任务"
    if failures:
        return (
            False,
            f"{summary}；失败：{'；'.join(failures)}；当前 {status['total']} 米游币",
        )
    if status["can_get"] > 0:
        return (
            False,
            f"{summary}；仍有 {status['can_get']} 米游币未获取，当前 {status['total']} 米游币",
        )
    return True, f"{summary}；当前 {status['total']} 米游币"


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
