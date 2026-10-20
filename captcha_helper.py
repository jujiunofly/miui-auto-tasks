"""本机验证码助手。

服务器/容器没有桌面浏览器，验证码页无法在服务端完成。这个脚本在本机运行：
1. 轮询面板上等待处理的验证码；
2. 用本机 Chrome 打开小米验证页；
3. 你完成验证后自动抓取 token 并回传面板，不需要复制粘贴。

依赖：requests、playwright、本机 Chrome（或 Playwright Chromium）。
"""

import argparse
import getpass
import os
import sys
import time
from urllib.parse import parse_qsl, urlparse

try:
    import requests
except ImportError:
    print("缺少 requests，请先执行: pip install requests", file=sys.stderr)
    raise SystemExit(1)


def extract_status_token(url: str) -> str:
    """从小米验证成功后的状态页 URL 中提取最终 token。"""
    parsed = urlparse(url)
    if not parsed.path.endswith("/captcha/status"):
        return ""
    params = dict(parse_qsl(parsed.query))
    if params.get("code") != "0":
        return ""
    return params.get("flag", "")


def solve_manual(url: str, timeout: int = 300) -> str:
    """打开本机浏览器，等待用户完成验证并返回 token。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "缺少 playwright，请先执行: pip install playwright\n"
            "如果还没有浏览器，再执行: playwright install chromium",
            file=sys.stderr,
        )
        return ""

    pending_tokens = []
    browser = None
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(
                    channel="chrome",
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                )
            except Exception:
                print("未检测到本机 Chrome，尝试使用 Playwright Chromium...")
                try:
                    browser = playwright.chromium.launch(
                        headless=False,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                except Exception:
                    print(
                        "浏览器启动失败，请安装 Chrome，或执行: "
                        "playwright install chromium",
                        file=sys.stderr,
                    )
                    return ""

            context = browser.new_context(locale="zh-CN")
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()

            def finish_status_page(route):
                token = extract_status_token(route.request.url)
                if token:
                    pending_tokens.append(token)
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
            print("请在打开的浏览器中完成验证，完成后会自动回传。")

            deadline = time.time() + timeout
            while time.time() < deadline:
                token = extract_status_token(page.url)
                if token:
                    print("验证通过，正在回传...")
                    return token
                if pending_tokens:
                    print("验证通过，正在回传...")
                    return pending_tokens.pop(0)
                try:
                    page.wait_for_timeout(500)
                except Exception:
                    token = extract_status_token(page.url)
                    if token:
                        return token
                    print("验证窗口已关闭。", file=sys.stderr)
                    return ""
            print("等待验证超时。", file=sys.stderr)
            return ""
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"验证流程异常: {exc}", file=sys.stderr)
        return ""
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass


class PanelClient:
    """面板 API 客户端。"""

    def __init__(self, server: str, username: str, password: str, insecure: bool):
        self.server = server.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.verify = not insecure
        if insecure:
            requests.packages.urllib3.disable_warnings()

    def pending(self):
        response = self.session.get(
            f"{self.server}/api/captcha/pending", timeout=15
        )
        if response.status_code == 401:
            raise PermissionError("面板用户名或密码错误")
        response.raise_for_status()
        return response.json().get("captcha", [])

    def submit(self, request_id: str, value: str):
        response = self.session.post(
            f"{self.server}/api/captcha/submit",
            json={"id": request_id, "value": value},
            timeout=15,
        )
        if response.status_code == 401:
            raise PermissionError("面板用户名或密码错误")
        if not response.ok:
            try:
                detail = response.json().get("detail", "")
            except Exception:
                detail = response.text
            raise RuntimeError(detail or f"HTTP {response.status_code}")
        return response.json()


def build_parser():
    parser = argparse.ArgumentParser(description="MIUI 自动任务本机验证码助手")
    parser.add_argument(
        "--server",
        default=os.getenv("MIUI_PANEL_URL", "http://127.0.0.1:8000"),
        help="面板地址，例如 http://1.2.3.4:8000",
    )
    parser.add_argument(
        "--username",
        default=os.getenv("WEB_USERNAME", "admin"),
        help="面板用户名，默认读取 WEB_USERNAME 或 admin",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("WEB_PASSWORD", ""),
        help="面板密码，默认读取 WEB_PASSWORD；未设置时会提示输入",
    )
    parser.add_argument(
        "--timeout", type=int, default=300, help="单次验证最长等待秒数"
    )
    parser.add_argument(
        "--interval", type=float, default=2, help="轮询间隔秒数"
    )
    parser.add_argument("--once", action="store_true", help="处理一次验证后退出")
    parser.add_argument(
        "--insecure", action="store_true", help="忽略 HTTPS 证书校验（自签名证书用）"
    )
    return parser


def main():
    args = build_parser().parse_args()
    password = args.password or getpass.getpass("面板密码: ")
    client = PanelClient(args.server, args.username, password, args.insecure)

    print(f"面板: {client.server}")
    print("等待验证码任务；保持这个窗口运行，Ctrl+C 退出。")
    failed_at = {}
    try:
        while True:
            try:
                pending = client.pending()
            except PermissionError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            except Exception as exc:  # pylint: disable=broad-exception-caught
                print(f"连接面板失败: {exc}", file=sys.stderr)
                time.sleep(max(args.interval, 3))
                continue

            item = pending[0] if pending else None
            if not item:
                failed_at.clear()
                time.sleep(args.interval)
                continue

            request_id = str(item.get("id", ""))
            url = str(item.get("url", ""))
            if not request_id or not url:
                time.sleep(args.interval)
                continue

            last_failed = failed_at.get(request_id, 0)
            if last_failed and time.time() - last_failed < 10:
                time.sleep(args.interval)
                continue

            remaining = int(item.get("expires_in", args.timeout) or args.timeout)
            if remaining <= 5:
                time.sleep(args.interval)
                continue

            print(f"\n收到验证码任务，剩余 {remaining} 秒。")
            token = solve_manual(url, timeout=min(args.timeout, remaining))
            if not token:
                failed_at[request_id] = time.time()
                print("本次验证未完成，等待下一次任务。", file=sys.stderr)
                time.sleep(args.interval)
                continue

            try:
                client.submit(request_id, token)
                print("已自动回传，面板会继续执行任务。")
                failed_at.pop(request_id, None)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                failed_at[request_id] = time.time()
                print(f"回传失败: {exc}", file=sys.stderr)

            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("已退出。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
