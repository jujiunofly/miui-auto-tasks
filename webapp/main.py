"""Web 面板入口"""

import json
import os
import platform
import secrets
from html import escape
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory

from utils.captcha_broker import enable as enable_captcha_broker
from utils.captcha_broker import get as get_captcha
from utils.captcha_broker import pending as pending_captcha
from utils.captcha_broker import submit as submit_captcha
from utils.captcha_broker import submit_relay as submit_relay_captcha
from utils.captcha_solver import is_configured as captcha_solver_configured
from utils.captcha_solver import provider as captcha_provider
from utils.config import ConfigManager
from utils.logger import LogCenter, log

from .runner import runner

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR.parent / ".env")
_conf = ConfigManager.data_obj


def _use_web_captcha_broker() -> bool:
    """本地有桌面时用 Playwright 自动捕获，服务器/容器用网页中转。"""
    mode = os.getenv("CAPTCHA_BROKER", "auto").lower()
    if mode in {"1", "true", "yes", "on"}:
        return True
    if mode in {"0", "false", "no", "off"}:
        return False
    system = platform.system().lower()
    if system in {"windows", "darwin"}:
        return False
    return not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))


CAPTCHA_BROKER_ENABLED = _use_web_captcha_broker()
if CAPTCHA_BROKER_ENABLED:
    enable_captcha_broker()


def _captcha_mode() -> str:
    """返回面板展示的验证码处理方式。"""
    if captcha_solver_configured():
        return f"auto:{captcha_provider()}"
    return "web" if CAPTCHA_BROKER_ENABLED else "browser"

TASK_FIELDS = [
    "CheckIn",
    "BrowseUserPage",
    "BrowsePost",
    "BrowseVideoPost",
    "ThumbUp",
    "BrowseSpecialPage",
    "BoardFollow",
    "CarrotPull",
    "WxSign",
]

TASK_LABELS = {
    "CheckIn": "每日签到",
    "BrowseUserPage": "浏览个人主页",
    "BrowsePost": "浏览帖子 10 秒",
    "BrowseVideoPost": "浏览视频帖子",
    "ThumbUp": "点赞帖子",
    "BrowseSpecialPage": "浏览专题页",
    "BoardFollow": "加入圈子",
    "CarrotPull": "拔萝卜",
    "WxSign": "微信小程序签到",
}

app = Flask(
    __name__,
    static_folder=str(BASE_DIR / "static"),
    static_url_path="/static",
)


@app.before_request
def auth_guard():
    """保护面板和 API，静态资源除外。"""
    if request.path in {"/health", "/v2/html/check.html", "/api/captcha/relay-submit"}:
        return None
    if request.path.startswith("/static/"):
        return None
    password = os.getenv("WEB_PASSWORD", "")
    if not password:
        return jsonify({"detail": "未设置 WEB_PASSWORD，请在 .env 中配置登录密码"}), 503
    username = os.getenv("WEB_USERNAME", "admin")
    auth = request.authorization
    valid = (
        auth is not None
        and secrets.compare_digest(auth.username or "", username)
        and secrets.compare_digest(auth.password or "", password)
    )
    if not valid:
        return Response(
            "需要登录",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="MIUI Auto Tasks"'},
        )
    return None


def _mask_uid(uid: str) -> str:
    uid = str(uid or "")
    if len(uid) <= 6:
        return uid
    return f"{uid[:2]}****{uid[-4:]}"


def _accounts_payload():
    accounts = []
    for index, account in enumerate(_conf.accounts):
        accounts.append(
            {
                "index": index,
                "uid": _mask_uid(account.uid),
                "tasks": [
                    {
                        "key": key,
                        "label": TASK_LABELS[key],
                        "enabled": bool(getattr(account, key)),
                    }
                    for key in TASK_FIELDS
                ],
            }
        )
    return accounts


def _telegram_payload():
    notifier = _conf.ONEPUSH.notifier
    params = _conf.ONEPUSH.params or {}
    configured = bool(notifier and params)
    if notifier == "telegram" and not params.get("token"):
        configured = False
    return {
        "configured": configured,
        "notifier": notifier,
        "title": params.get("title") or "",
        "markdown": bool(params.get("markdown", False)),
    }


def _settings_payload():
    accounts = []
    for index, account in enumerate(_conf.accounts):
        accounts.append(
            {
                "index": index,
                "uid": str(account.uid or ""),
                "user_agent": account.user_agent,
                "login_user_agent": account.login_user_agent,
                "device": account.device,
                "device_model": account.device_model,
                "has_password": bool(account.password),
                "has_cookies": bool(account.cookies),
                "cookie_count": len(account.cookies or {}),
            }
        )
    params = _conf.ONEPUSH.params or {}
    return {
        "accounts": accounts,
        "onepush": {
            "notifier": _conf.ONEPUSH.notifier or "",
            "title": params.get("title") or "",
            "userid": params.get("userid") or "",
            "markdown": bool(params.get("markdown", False)),
            "has_token": bool(params.get("token")),
        },
        "captcha_mode": _captcha_mode(),
    }


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/")
def index():
    return send_from_directory(BASE_DIR / "static", "index.html")


def _relay_error(message: str, status: int = 400):
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>验证页加载失败</title></head>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    padding:32px;color:#1d2733;background:#f6f8fb;line-height:1.7">
    <h1 style="font-size:20px">验证页加载失败</h1><p>{escape(message)}</p>
    <p>请回到面板关闭后重试，或使用面板里的“手动提交”。</p></body></html>"""
    return Response(html, status=status, mimetype="text/html")


@app.get("/v2/html/check.html")
def captcha_relay_page():
    """在面板域名下中转小米验证页，成功后自动回传 token。

    路径必须保留 /html/check，小米脚本靠它判断当前是验证页。
    """
    request_id = request.args.get("id", "")
    relay_token = request.args.get("relay_token", "")
    item = get_captcha(request_id)
    if not item or not secrets.compare_digest(
        item.get("relay_token", ""), relay_token or ""
    ):
        return _relay_error("验证请求不存在或已过期。", 404)

    parsed = urlparse(item.get("url", ""))
    if (
        parsed.scheme != "https"
        or parsed.netloc != "static-verify.sec.xiaomi.com"
        or not parsed.path.startswith("/v2/html/check")
    ):
        return _relay_error("验证链接无效。", 400)

    try:
        upstream = requests.get(
            item["url"],
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
                )
            },
        )
        upstream.raise_for_status()
        html = upstream.text
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log.exception("获取小米验证页失败")
        return _relay_error(f"获取验证页失败: {exc}", 502)

    html = html.replace(
        'src="/v2/js/v.js"',
        'src="https://static-verify.sec.xiaomi.com/v2/js/v.js"',
    )
    html = html.replace(
        "src='/v2/js/v.js'",
        "src='https://static-verify.sec.xiaomi.com/v2/js/v.js'",
    )

    relay_script = """<script>
(function () {
  var requestId = __REQUEST_ID__;
  var relayToken = __RELAY_TOKEN__;
  var base = window.initMiverify;
  function finish(ok, message) {
    document.title = ok ? "验证成功" : "验证失败";
    document.body.innerHTML = '<div style="min-height:100vh;display:flex;align-items:center;justify-content:center;padding:28px;background:#f6f8fb;color:#1d2733;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;text-align:center"><div id="relay-box" style="max-width:420px"></div></div>';
    var box = document.getElementById("relay-box");
    var icon = document.createElement("div");
    icon.textContent = ok ? "✓" : "!";
    icon.style.cssText = "font-size:42px;line-height:1;margin-bottom:16px;color:" + (ok ? "#12805c" : "#d92d20");
    var title = document.createElement("h1");
    title.textContent = message;
    title.style.cssText = "font-size:22px;margin:0 0 10px";
    var hint = document.createElement("p");
    hint.textContent = ok ? "面板会自动继续执行，可以关闭此页。" : "请回到面板重新打开验证页面。";
    hint.style.cssText = "color:#667085;font-size:14px;line-height:1.7;margin:0";
    box.append(icon, title, hint);
    try {
      if (window.opener) {
        window.opener.postMessage({type: "captcha-complete", ok: ok, id: requestId}, location.origin);
      }
    } catch (e) {}
    if (ok) setTimeout(function () { window.close(); }, 1400);
  }
  if (typeof base !== "function") {
    finish(false, "验证页加载失败");
    return;
  }
  window.initMiverify = function (conf, cb) {
    conf.onSuccess = function (token) {
      var value = token && token.flag ? token.flag : "";
      fetch("/api/captcha/relay-submit", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({id: requestId, relay_token: relayToken, value: value})
      }).then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          if (!response.ok) throw new Error(data.detail || "回传失败");
          finish(true, "验证成功，已自动返回");
        });
      }).catch(function (error) {
        finish(false, "回传失败：" + error.message);
      });
    };
    conf.onClose = function () { finish(false, "验证已取消"); };
    conf.onError = function () { finish(false, "验证失败，请重试"); };
    return base(conf, cb);
  };
})();
</script>
"""
    relay_script = relay_script.replace(
        "__REQUEST_ID__", json.dumps(request_id)
    ).replace("__RELAY_TOKEN__", json.dumps(relay_token))
    marker = '<script type="text/javascript">'
    if marker not in html:
        return _relay_error("验证页格式异常。", 502)
    html = html.replace(marker, relay_script + marker, 1)
    return Response(
        html,
        mimetype="text/html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/captcha-helper.py")
def captcha_helper_file():
    """下载本机验证助手。"""
    return send_from_directory(
        BASE_DIR.parent,
        "captcha_helper.py",
        as_attachment=True,
        download_name="captcha_helper.py",
    )


@app.get("/api/state")
def state():
    after = request.args.get("after", default=0, type=int) or 0
    payload = runner.status()
    payload.update(
        {
            "logs": LogCenter.entries(after),
            "accounts": _accounts_payload(),
            "telegram": _telegram_payload(),
            "captcha": pending_captcha(),
            "captcha_mode": _captcha_mode(),
        }
    )
    return jsonify(payload)


@app.post("/api/run")
def run():
    if not runner.start(auto_notify=True):
        return jsonify({"detail": "已有任务正在运行"}), 409
    return jsonify({"ok": True})


@app.patch("/api/accounts/<int:index>")
def update_account(index: int):
    if runner.status()["running"]:
        return jsonify({"detail": "任务运行中，暂时不能修改配置"}), 409
    if index < 0 or index >= len(_conf.accounts):
        return jsonify({"detail": "账号不存在"}), 404
    data = request.get_json(silent=True) or {}
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        return jsonify({"detail": "tasks 必须是对象"}), 400
    account = _conf.accounts[index]
    for key, value in tasks.items():
        if key not in TASK_FIELDS:
            return jsonify({"detail": f"未知任务: {key}"}), 400
        setattr(account, key, bool(value))
    if not ConfigManager.write_plugin_data():
        return jsonify({"detail": "配置保存失败"}), 500
    return jsonify({"accounts": _accounts_payload()})


@app.get("/api/captcha/pending")
def captcha_pending():
    """返回当前等待处理的验证码，供本机验证助手轮询。"""
    return jsonify(
        {
            "captcha": pending_captcha(),
            "mode": _captcha_mode(),
        }
    )


@app.post("/api/captcha/relay-submit")
def captcha_relay_submit():
    """接收中转页自动回传的验证码 token。"""
    data = request.get_json(silent=True) or {}
    request_id = str(data.get("id") or "")
    relay_token = str(data.get("relay_token") or "")
    value = str(data.get("value") or "")
    if not request_id or not relay_token or not value:
        return jsonify({"detail": "验证码参数不完整"}), 400
    if not submit_relay_captcha(request_id, relay_token, value):
        return jsonify({"detail": "验证码已超时或提交失败"}), 400
    return jsonify({"ok": True})


@app.post("/api/captcha/submit")
def captcha_submit():
    data = request.get_json(silent=True) or {}
    request_id = str(data.get("id") or "")
    value = str(data.get("value") or "")
    if not request_id or not value:
        return jsonify({"detail": "验证码参数不完整"}), 400
    if not submit_captcha(request_id, value):
        return jsonify({"detail": "验证码已超时或提交失败"}), 400
    return jsonify({"ok": True})


@app.get("/api/settings")
def get_settings():
    return jsonify(_settings_payload())


@app.patch("/api/settings")
def update_settings():
    if runner.status()["running"]:
        return jsonify({"detail": "任务运行中，暂时不能修改设置"}), 409
    data = request.get_json(silent=True) or {}
    accounts = data.get("accounts") or []
    onepush = data.get("onepush") or {}
    if not isinstance(accounts, list) or not isinstance(onepush, dict):
        return jsonify({"detail": "设置格式错误"}), 400

    for item in accounts:
        if not isinstance(item, dict):
            return jsonify({"detail": "账号设置格式错误"}), 400
        index = item.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(_conf.accounts):
            return jsonify({"detail": "账号不存在"}), 404
        account = _conf.accounts[index]
        if item.get("uid") is not None and str(item["uid"]).strip():
            account.uid = str(item["uid"]).strip()
        if item.get("password"):
            account.password = account._password(str(item["password"]))
        if item.get("cookies") and str(item["cookies"]).strip():
            try:
                account.cookies = account._cookies(str(item["cookies"]).strip())
            except Exception as exc:  # pylint: disable=broad-exception-caught
                return jsonify({"detail": f"Cookie 格式错误: {exc}"}), 400
        if item.get("user_agent") is not None:
            account.user_agent = str(item["user_agent"]).strip()
        if item.get("login_user_agent") is not None:
            account.login_user_agent = str(item["login_user_agent"]).strip()
        if item.get("device") is not None:
            account.device = str(item["device"]).strip()
        if item.get("device_model") is not None:
            account.device_model = str(item["device_model"]).strip()

    if onepush:
        params = _conf.ONEPUSH.params or {}
        if onepush.get("notifier") is not None:
            _conf.ONEPUSH.notifier = str(onepush["notifier"]).strip()
        if onepush.get("title") is not None:
            params["title"] = str(onepush["title"])
        if onepush.get("userid") is not None:
            params["userid"] = str(onepush["userid"])
        if onepush.get("markdown") is not None:
            params["markdown"] = bool(onepush["markdown"])
        if onepush.get("token"):
            params["token"] = str(onepush["token"]).strip()
        _conf.ONEPUSH.params = params

    if not ConfigManager.write_plugin_data():
        return jsonify({"detail": "设置保存失败"}), 500
    return jsonify(_settings_payload())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
