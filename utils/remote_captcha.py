"""服务器端远程验证码浏览器。

服务器用 Playwright 打开小米原验证页，面板显示截图并转发点击。
这样电脑和手机都只需要在面板里点验证码，不需要用户脚本。
"""

import os
import queue
import threading
import time
import uuid
from typing import Optional
from urllib.parse import parse_qsl, urlparse

from .logger import log

_lock = threading.Lock()
_current = None


def enabled() -> bool:
    """是否启用服务器端远程验证码。"""
    try:
        from .config import ConfigManager

        captcha = getattr(ConfigManager.data_obj, "CAPTCHA", None)
        mode = str(getattr(captcha, "mode", "")).strip().lower()
        if mode:
            return mode in {"remote", "auto"}
    except Exception:
        pass
    env_value = os.getenv("CAPTCHA_REMOTE", "").strip().lower()
    return env_value in {"1", "true", "yes", "on"}


def _extract_status_token(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.path.endswith("/captcha/status"):
        return ""
    params = dict(parse_qsl(parsed.query))
    if params.get("code") != "0":
        return ""
    return params.get("flag", "")


def current() -> Optional[dict]:
    """返回当前远程验证会话信息。"""
    with _lock:
        session = _current
    return session.info() if session else None


def screenshot() -> Optional[bytes]:
    """返回当前远程验证画面。"""
    with _lock:
        session = _current
    return session.screenshot() if session else None


def click(x: float, y: float):
    with _lock:
        session = _current
    if session:
        session.click(x, y)


def press(key: str):
    with _lock:
        session = _current
    if session:
        session.press(key)


def type_text(text: str):
    with _lock:
        session = _current
    if session:
        session.type_text(text)


def scroll(delta: int):
    with _lock:
        session = _current
    if session:
        session.scroll(delta)


def start(url: str, timeout: int = 300):
    """启动一个服务器端浏览器会话。"""
    global _current
    with _lock:
        old = _current
    if old:
        old.stop()
    session = RemoteSession(url, timeout)
    with _lock:
        _current = session
    session.start()
    return session


class RemoteSession:
    """在后台线程里运行 Playwright，并接收面板的点击命令。"""

    def __init__(self, url: str, timeout: int = 300):
        self.id = uuid.uuid4().hex
        self.url = url
        self.timeout = timeout
        self.width = 390
        self.height = 844
        self._commands = queue.Queue()
        self._screen = None
        self._screen_lock = threading.Lock()
        self._done = threading.Event()
        self._token = ""
        self._error = ""
        self._active = True
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def info(self) -> dict:
        return {
            "id": self.id,
            "width": self.width,
            "height": self.height,
            "active": self._active,
            "error": self._error,
        }

    def screenshot(self) -> Optional[bytes]:
        with self._screen_lock:
            return self._screen

    def click(self, x: float, y: float):
        self._commands.put(("click", float(x), float(y)))

    def press(self, key: str):
        self._commands.put(("press", str(key)))

    def type_text(self, text: str):
        self._commands.put(("type", str(text)))

    def scroll(self, delta: int):
        self._commands.put(("scroll", int(delta)))

    def stop(self):
        self._active = False
        self._commands.put(("stop",))
        self._done.set()

    def wait(self) -> str:
        self._done.wait(self.timeout + 10)
        return self._token

    def _handle_commands(self, page):
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                if command[0] == "stop":
                    self._active = False
                elif command[0] == "click":
                    page.mouse.click(command[1], command[2])
                elif command[0] == "press":
                    page.keyboard.press(command[1])
                elif command[0] == "type":
                    page.keyboard.type(command[1])
                elif command[0] == "scroll":
                    page.mouse.wheel(0, command[1])
            except Exception:
                pass

    def _run(self):
        browser = None
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._error = "服务器未安装 playwright"
            self._active = False
            self._done.set()
            return

        try:
            with sync_playwright() as playwright:
                launch_args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ]
                try:
                    browser = playwright.chromium.launch(
                        channel="chrome",
                        headless=True,
                        args=launch_args,
                    )
                except Exception:
                    browser = playwright.chromium.launch(
                        headless=True,
                        args=launch_args,
                    )
                context = browser.new_context(
                    viewport={"width": self.width, "height": self.height},
                    locale="zh-CN",
                )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page = context.new_page()
                tokens = []

                def finish_status_page(route):
                    token = _extract_status_token(route.request.url)
                    if token:
                        tokens.append(token)
                        route.fulfill(
                            status=200,
                            content_type="text/html",
                            body="<html><body>OK</body></html>",
                        )
                    else:
                        route.continue_()

                page.route("**/captcha/status*", finish_status_page)
                page.goto(self.url, wait_until="domcontentloaded", timeout=60000)

                deadline = time.time() + self.timeout
                last_shot = 0.0
                while time.time() < deadline and self._active:
                    self._handle_commands(page)
                    token = _extract_status_token(page.url)
                    if not token and tokens:
                        token = tokens[0]
                    if token:
                        self._token = token
                        break
                    now = time.time()
                    if now - last_shot >= 0.6:
                        try:
                            png = page.screenshot(type="png")
                            with self._screen_lock:
                                self._screen = png
                        except Exception:
                            break
                        last_shot = now
                    try:
                        page.wait_for_timeout(200)
                    except Exception:
                        break
                if not self._token:
                    self._error = "验证超时或页面已关闭"
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._error = str(exc)
            log.exception("服务器远程验证码异常")
        finally:
            self._active = False
            self._done.set()
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
