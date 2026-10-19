"""
Date: 2023-11-13 19:55:22
LastEditors: Night-stars-1 nujj1042633805@gmail.com
LastEditTime: 2025-02-11 00:59:19
"""

import json
import time
from traceback import print_exc
from urllib.parse import parse_qsl, urlparse

from jsonpath_ng import parse
from jsonpath_ng.exceptions import JsonPathParserError

from .config import ConfigManager
from .data_model import GeetestResult
from .logger import log
from .request import request

_conf = ConfigManager.data_obj


def _extract_status_token(url: str) -> str:
    """从小米验证成功后的状态页 URL 中提取最终 token"""
    parsed = urlparse(url)
    if not parsed.path.endswith("/captcha/status"):
        return ""
    params = dict(parse_qsl(parsed.query))
    if params.get("code") != "0":
        return ""
    return params.get("flag", "")


def solve_recaptcha_manual(
    url: str, timeout: int = 180, headless: bool = False
) -> str:
    """打开浏览器，由用户手动完成 reCAPTCHA，并返回小米最终 token"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("未安装 playwright，无法进行人工验证。请执行: pip install playwright")
        return ""

    pending_tokens = []
    browser = None
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(
                    channel="chrome",
                    headless=headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
            except Exception:
                log.warning("未检测到本机 Chrome，尝试使用 Playwright Chromium")
                try:
                    browser = playwright.chromium.launch(
                        headless=headless,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                except Exception:
                    log.error(
                        "浏览器启动失败，请安装 Chrome 或执行: playwright install chromium"
                    )
                    return ""

            context = browser.new_context(locale="zh-CN")
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()

            def finish_status_page(route):
                token = _extract_status_token(route.request.url)
                if token:
                    pending_tokens.append(token)
                    # 小米状态页本身可能返回 404，拦截后避免 Chrome 跳到错误页。
                    route.fulfill(
                        status=200,
                        content_type="text/html",
                        body="<html><body>OK</body></html>",
                    )
                else:
                    route.continue_()

            page.route("**/captcha/status*", finish_status_page)
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.bring_to_front()
            log.info(f"请在打开的浏览器中完成人机验证，最多等待 {timeout} 秒")

            deadline = time.time() + timeout
            while time.time() < deadline:
                token = _extract_status_token(page.url)
                if token:
                    log.success("人机验证通过")
                    return token
                if pending_tokens:
                    log.success("人机验证通过")
                    return pending_tokens.pop(0)
                try:
                    page.wait_for_timeout(500)
                except Exception:
                    token = _extract_status_token(page.url)
                    if token:
                        log.success("人机验证通过")
                        return token
                    log.error(f"验证页异常，当前页面: {page.url}")
                    return ""
            log.error("人机验证超时或已取消")
            return ""
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception("人工验证流程异常")
        return ""
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass


def find_key(data: dict, key: str):
    """递归查找字典中的key"""
    for dkey, dvalue in data.items():
        if dkey == key:
            return dvalue
        if isinstance(dvalue, dict):
            find_key(dvalue, key)
    return None


def get_validate_other(
    gt: str, challenge: str, result: str
) -> GeetestResult:  # pylint: disable=invalid-name
    """获取人机验证结果"""
    try:
        validate = ""
        if _conf.preference.get_geetest_url:
            params = _conf.preference.get_geetest_params.copy()
            params = json.loads(
                json.dumps(params)
                .replace("{gt}", gt)
                .replace("{challenge}", challenge)
                .replace("{result}", str(result))
            )
            data = _conf.preference.get_geetest_data.copy()
            data = json.loads(
                json.dumps(data)
                .replace("{gt}", gt)
                .replace("{challenge}", challenge)
                .replace("{result}", str(result))
            )
            for i in range(_conf.preference.get_geetest_try_count):
                log.info(f"第{i}次获取结果")
                response = request(
                    _conf.preference.get_geetest_method,
                    _conf.preference.get_geetest_url,
                    params=params,
                    json=data,
                )
                log.debug(response.text)
                result = response.json()
                geetest_validate_expr = parse(
                    _conf.preference.get_geetest_validate_path
                )
                geetest_validate_match = geetest_validate_expr.find(result)
                if len(geetest_validate_match) > 0:
                    validate = geetest_validate_match[0].value
                geetest_challenge_expr = parse(
                    _conf.preference.get_geetest_challenge_path
                )
                geetest_challenge_match = geetest_challenge_expr.find(result)
                if len(geetest_challenge_match) > 0:
                    challenge = geetest_challenge_match[0].value
                if validate and challenge:
                    return GeetestResult(challenge=challenge, validate=validate)
                time.sleep(1)
            return GeetestResult(challenge="", validate="")
        else:
            return GeetestResult(challenge="", validate="")
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception("获取人机验证结果异常")
        return GeetestResult(challenge="", validate="")


def get_validate(
    gt: str, challenge: str
) -> GeetestResult:  # pylint: disable=invalid-name
    """创建人机验证并结果"""
    try:
        validate = ""
        result = ""
        if _conf.preference.geetest_url:
            params = _conf.preference.geetest_params.copy()
            params = json.loads(
                json.dumps(params).replace("{gt}", gt).replace("{challenge}", challenge)
            )
            data = _conf.preference.geetest_data.copy()
            data = json.loads(
                json.dumps(data).replace("{gt}", gt).replace("{challenge}", challenge)
            )
            response = request(
                _conf.preference.geetest_method,
                _conf.preference.geetest_url,
                params=params,
                json=data,
            )
            log.debug(response.text)
            result = response.json()
            try:
                geetest_validate_expr = parse(_conf.preference.geetest_validate_path)
                geetest_validate_match = geetest_validate_expr.find(result)
                if len(geetest_validate_match) > 0:
                    validate = geetest_validate_match[0].value
                geetest_challenge_expr = parse(_conf.preference.geetest_challenge_path)
                geetest_challenge_match = geetest_challenge_expr.find(result)
                if len(geetest_challenge_match) > 0:
                    challenge = geetest_challenge_match[0].value
                geetest_result_expr = parse(_conf.preference.geetest_result_path)
                geetest_result_match = geetest_result_expr.find(result)
                if len(geetest_result_match) > 0:
                    result = geetest_result_match[0].value
            except JsonPathParserError:
                print_exc()
            if validate and challenge:
                return GeetestResult(challenge=challenge, validate=validate)
            else:
                return get_validate_other(gt=gt, challenge=challenge, result=result)
        else:
            return GeetestResult(challenge="", validate="")
    except Exception:  # pylint: disable=broad-exception-caught
        log.exception("获取人机验证结果异常")
        return GeetestResult(challenge="", validate="")
