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
        "geetest_type": "GeeTestTaskProxyless",
        "recaptcha_type": "RecaptchaV2EnterpriseTaskProxyless",
    },
    "capsolver": {
        "create": "https://api.capsolver.com/createTask",
        "result": "https://api.capsolver.com/getTaskResult",
        "geetest_type": "GeeTestTaskProxyLess",
        "recaptcha_type": "ReCaptchaV2EnterpriseTaskProxyLess",
    },
}


def provider() -> str:
    """返回当前打码服务名称。"""
    return os.getenv("CAPTCHA_PROVIDER", "").strip().lower()


def api_key() -> str:
    """返回打码服务 API Key。"""
    return os.getenv("CAPTCHA_API_KEY", "").strip()


def is_configured() -> bool:
    """是否已配置可用的自动打码服务。"""
    return provider() in _PROVIDERS and bool(api_key())


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


def _create_task(task: dict) -> Optional[str]:
    config = _PROVIDERS.get(provider())
    if not config:
        return None
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
    config = _PROVIDERS[provider()]
    task = {
        "type": config["geetest_type"],
        "websiteURL": page_url,
        "gt": gt,
        "challenge": challenge,
    }
    if user_agent:
        task["userAgent"] = user_agent

    log.info(f"使用 {provider()} 自动完成验证码")
    task_id = _create_task(task)
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
) -> Optional[str]:
    """调用付费服务完成 reCAPTCHA Enterprise，返回 Google token。"""
    if not is_configured():
        return None
    config = _PROVIDERS[provider()]
    task = {
        "type": config["recaptcha_type"],
        "websiteURL": page_url,
        "websiteKey": site_key,
        "isInvisible": bool(is_invisible),
    }
    log.info(f"使用 {provider()} 自动完成 Google 验证码")
    task_id = _create_task(task)
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
