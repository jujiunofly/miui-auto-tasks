"""Web 面板人工验证码中转。

CLI 模式不启用，仍然使用 Playwright 打开本机浏览器。
Web 模式启用后，任务线程会等待前端提交验证码最终 token。
"""

import secrets
import threading
import time
import uuid
from urllib.parse import parse_qsl, unquote, urlparse

_lock = threading.Lock()
_enabled = False
_pending = {}
_events = {}
_tokens = {}


def enable():
    """启用 Web 人工验证码中转"""
    global _enabled
    _enabled = True


def disable():
    """关闭 Web 人工验证码中转"""
    global _enabled
    _enabled = False


def is_enabled() -> bool:
    """是否启用 Web 中转"""
    return _enabled


def _extract_token(value: str) -> str:
    """接受完整回调 URL、查询串或裸 token"""
    value = (value or "").strip()
    if not value:
        return ""
    if "flag=" in value:
        query = value.split("?", 1)[1] if "?" in value else value
        params = dict(parse_qsl(query))
        if params.get("flag"):
            return params["flag"]
    parsed = urlparse(value)
    if parsed.query:
        params = dict(parse_qsl(parsed.query))
        if params.get("flag"):
            return params["flag"]
    return unquote(value)


def request_token(url: str, timeout: int = 300):
    """等待 Web 前端提交 token。

    返回 None 表示当前未启用 Web 中转；返回空字符串表示超时或失败。
    """
    if not _enabled:
        return None

    request_id = uuid.uuid4().hex
    event = threading.Event()
    with _lock:
        _pending[request_id] = {
            "id": request_id,
            "url": url,
            "relay_token": secrets.token_urlsafe(24),
            "created": time.time(),
            "expires": time.time() + timeout,
        }
        _events[request_id] = event

    event.wait(timeout)
    with _lock:
        _pending.pop(request_id, None)
        _events.pop(request_id, None)
        return _tokens.pop(request_id, "")


def pending():
    """获取等待处理的验证码请求"""
    now = time.time()
    with _lock:
        return [
            {**item, "expires_in": max(0, int(item["expires"] - now))}
            for item in _pending.values()
        ]


def get(request_id: str):
    """获取单个等待处理的验证码请求。"""
    now = time.time()
    with _lock:
        item = _pending.get(request_id)
        if not item:
            return None
        return {**item, "expires_in": max(0, int(item["expires"] - now))}


def submit_relay(request_id: str, relay_token: str, value: str) -> bool:
    """验证中转页的一次性 token 后提交验证码。"""
    with _lock:
        item = _pending.get(request_id)
        if not item:
            return False
        if not secrets.compare_digest(item.get("relay_token", ""), relay_token or ""):
            return False
    return submit(request_id, value)


def submit(request_id: str, value: str) -> bool:
    """提交验证码最终 token 或回调 URL"""
    token = _extract_token(value)
    if not token:
        return False
    with _lock:
        event = _events.get(request_id)
        if not event:
            return False
        _tokens[request_id] = token
    event.set()
    return True
