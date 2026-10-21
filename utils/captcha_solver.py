"""付费打码服务封装，用于服务器/手机端全自动完成验证码。"""

import os
import time
from typing import Optional

import requests

from .logger import log

_PROVIDERS = {
    "2captcha": {
        "create": "https://api.2captcha.com/createTask",
        "result": "https://api.2captcha.com/getTaskResult",
        "geetest_type": {
            "proxyless": "GeeTestTaskProxyless",
            "proxy": "GeeTestTask",
        },
        "recaptcha_type": {
            "proxyless": "RecaptchaV2EnterpriseTaskProxyless",
            "proxy": "RecaptchaV2EnterpriseTask",
        },
    },
    "capsolver": {
        "create": "https://api.capsolver.com/createTask",
        "result": "https://api.capsolver.com/getTaskResult",
        "geetest_type": {
            "proxyless": "GeeTestTaskProxyLess",
            "proxy": "GeeTestTask",
        },
        "recaptcha_type": {
            "proxyless": "ReCaptchaV2EnterpriseTaskProxyLess",
            "proxy": "ReCaptchaV2EnterpriseTask",
        },
    },
    "capzy": {
        "create": "https://api.capzy.ai/createTask",
        "result": "https://api.capzy.ai/getTaskResult",
        "geetest_type": {
            "proxyless": "GeeTestTaskProxyLess",
            "proxy": "GeeTestTask",
        },
        "recaptcha_type": {
            "proxyless": "ReCaptchaV2EnterpriseTaskProxyLess",
            "proxy": "ReCaptchaV2EnterpriseTask",
        },
    },
}


def _captcha_conf():
    try:
        from .config import ConfigManager

        return getattr(ConfigManager.data_obj, "CAPTCHA", None)
    except Exception:
        return None


def mode() -> str:
    """返回验证码模式：remote / auto / capzy。"""
    conf = _captcha_conf()
    if conf and getattr(conf, "mode", ""):
        return str(conf.mode).strip().lower()
    return "remote"


def provider() -> str:
    """返回当前打码服务名称。"""
    conf = _captcha_conf()
    if conf and getattr(conf, "provider", ""):
        return str(conf.provider).strip().lower()
    return os.getenv("CAPTCHA_PROVIDER", "").strip().lower()


def api_key() -> str:
    """返回打码服务 API Key。"""
    conf = _captcha_conf()
    if conf and getattr(conf, "api_key", ""):
        return str(conf.api_key).strip()
    return os.getenv("CAPTCHA_API_KEY", "").strip()


def is_configured() -> bool:
    """是否已配置可用的自动打码服务。"""
    if provider() not in _PROVIDERS or not api_key():
        return False
    conf = _captcha_conf()
    if conf:
        current_mode = str(getattr(conf, "mode", "remote")).strip().lower()
        return current_mode in {"auto", "capzy"}
    return True


def _proxy_payload() -> Optional[dict]:
    """读取可选代理配置；返回 None 表示配置有误。"""
    conf = _captcha_conf()
    if not conf:
        return {}
    address = str(getattr(conf, "proxy_address", "") or "").strip()
    port = str(getattr(conf, "proxy_port", "") or "").strip()
    if not address and not port:
        return {}
    if not address or not port:
        log.error("代理配置不完整：需要同时填写代理地址和端口")
        return None
    try:
        port_number = int(port)
    except (TypeError, ValueError):
        log.error("代理端口无效")
        return None
    if not 1 <= port_number <= 65535:
        log.error("代理端口超出范围")
        return None
    proxy_type = str(getattr(conf, "proxy_type", "http") or "http").strip().lower()
    if proxy_type not in {"http", "https", "socks4", "socks5"}:
        log.error("代理类型无效，可选 http / https / socks4 / socks5")
        return None
    payload = {
        "proxyType": proxy_type,
        "proxyAddress": address,
        "proxyPort": port_number,
    }
    login = str(getattr(conf, "proxy_login", "") or "").strip()
    password = str(getattr(conf, "proxy_password", "") or "")
    if login:
        payload["proxyLogin"] = login
    if password:
        payload["proxyPassword"] = password
    return payload


def _post_json(url: str, payload: dict) -> Optional[dict]:
    try:
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            log.error("打码服务返回格式异常")
            return None
        return data
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log.error(f"打码服务请求失败: {exc}")
        return None


def _create_task(task: dict, kind: str) -> Optional[str]:
    config = _PROVIDERS.get(provider())
    if not config:
        return None
    proxy = _proxy_payload()
    if proxy is None:
        return None
    task = dict(task)
    if proxy:
        task.update(proxy)
        task["type"] = config[f"{kind}_type"]["proxy"]
        log.info("自动打码使用自定义代理")
    else:
        task["type"] = config[f"{kind}_type"]["proxyless"]
    data = _post_json(
        config["create"],
        {"clientKey": api_key(), "task": task},
    )
    if not data:
        return None
    if data.get("errorId"):
        log.error(
            "打码服务创建任务失败: "
            f"{data.get('errorDescription') or data.get('errorCode') or '未知错误'}"
        )
        return None
    task_id = data.get("taskId")
    if not task_id:
        log.error("打码服务没有返回 taskId")
        return None
    return str(task_id)


def _wait_result(task_id: str, timeout: int = 180) -> Optional[dict]:
    config = _PROVIDERS.get(provider())
    if not config:
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = _post_json(
            config["result"],
            {"clientKey": api_key(), "taskId": task_id},
        )
        if not data:
            return None
        if data.get("errorId"):
            log.error(
                "打码服务返回错误: "
                f"{data.get('errorDescription') or data.get('errorCode') or '未知错误'}"
            )
            return None
        status = data.get("status")
        if status == "ready":
            solution = data.get("solution")
            if isinstance(solution, dict):
                return solution
            log.error("打码服务没有返回 solution")
            return None
        if status != "processing":
            log.error(f"打码服务返回未知状态: {status}")
            return None
        time.sleep(3)
    log.error("打码服务等待结果超时")
    return None


def solve_geetest(
    page_url: str,
    gt: str,
    challenge: str,
    user_agent: str = "",
) -> Optional[dict]:
    """调用付费服务完成 GeeTest v3，返回小米校验所需字段。"""
    if not is_configured():
        return None
    task = {
        "websiteURL": page_url,
        "gt": gt,
        "challenge": challenge,
    }
    if user_agent:
        task["userAgent"] = user_agent

    log.info(f"使用 {provider()} 自动完成验证码")
    task_id = _create_task(task, "geetest")
    if not task_id:
        return None
    solution = _wait_result(task_id)
    if not solution:
        return None

    result_challenge = (
        solution.get("challenge")
        or solution.get("geetest_challenge")
        or challenge
    )
    validate = (
        solution.get("validate")
        or solution.get("geetest_validate")
        or ""
    )
    seccode = (
        solution.get("seccode")
        or solution.get("geetest_seccode")
        or (f"{validate}|jordan" if validate else "")
    )
    if not seccode:
        log.error("打码服务没有返回 seccode")
        return None
    return {
        "challenge": str(result_challenge),
        "validate": str(validate),
        "seccode": str(seccode),
    }


def solve_recaptcha(
    page_url: str,
    site_key: str,
    is_invisible: bool = False,
    user_agent: str = "",
) -> Optional[str]:
    """调用付费服务完成 reCAPTCHA Enterprise，返回 Google token。"""
    if not is_configured():
        return None
    task = {
        "websiteURL": page_url,
        "websiteKey": site_key,
        "isInvisible": bool(is_invisible),
    }
    if user_agent:
        task["userAgent"] = user_agent
    log.info(f"使用 {provider()} 自动完成 Google 验证码")
    task_id = _create_task(task, "recaptcha")
    if not task_id:
        return None
    solution = _wait_result(task_id)
    if not solution:
        return None
    token = (
        solution.get("gRecaptchaResponse")
        or solution.get("token")
        or solution.get("recaptchaResponse")
        or ""
    )
    if not token:
        log.error("打码服务没有返回 reCAPTCHA token")
        return None
    return str(token)
