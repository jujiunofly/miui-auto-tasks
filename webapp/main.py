"""Web 面板入口"""

import os
import platform
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from utils.captcha_broker import enable as enable_captcha_broker
from utils.captcha_broker import pending as pending_captcha
from utils.captcha_broker import submit as submit_captcha
from utils.config import ConfigManager
from utils.logger import LogCenter, log

from .runner import runner
from .scheduler import start as start_scheduler

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

security = HTTPBasic(auto_error=False)


def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)):
    """可选的 HTTP Basic 认证"""
    password = os.getenv("WEB_PASSWORD", "")
    if not password:
        raise HTTPException(
            status_code=503,
            detail="未设置 WEB_PASSWORD，请在 .env 中配置登录密码",
        )
    username = os.getenv("WEB_USERNAME", "admin")
    valid = (
        credentials is not None
        and secrets.compare_digest(credentials.username, username)
        and secrets.compare_digest(credentials.password, password)
    )
    if not valid:
        raise HTTPException(
            status_code=401,
            detail="需要登录",
            headers={"WWW-Authenticate": "Basic"},
        )


app = FastAPI(title="MIUI Auto Tasks", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.on_event("startup")
def startup():
    if CAPTCHA_BROKER_ENABLED:
        enable_captcha_broker()
    start_scheduler()


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


class AccountUpdate(BaseModel):
    tasks: dict[str, bool]


class CaptchaSubmit(BaseModel):
    id: str
    value: str


class AccountSettings(BaseModel):
    index: int
    uid: str | None = None
    password: str | None = None
    cookies: str | None = None
    user_agent: str | None = None
    login_user_agent: str | None = None
    device: str | None = None
    device_model: str | None = None


class PushSettings(BaseModel):
    notifier: str | None = None
    title: str | None = None
    token: str | None = None
    userid: str | None = None
    markdown: bool | None = None


class SettingsUpdate(BaseModel):
    accounts: list[AccountSettings] | None = None
    onepush: PushSettings | None = None


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
        "captcha_mode": "web" if CAPTCHA_BROKER_ENABLED else "browser",
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", dependencies=[Depends(require_auth)])
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/state", dependencies=[Depends(require_auth)])
def state(after: int = 0):
    payload = runner.status()
    payload.update(
        {
            "logs": LogCenter.entries(after),
            "accounts": _accounts_payload(),
            "telegram": _telegram_payload(),
            "captcha": pending_captcha(),
            "captcha_mode": "web" if CAPTCHA_BROKER_ENABLED else "browser",
        }
    )
    return payload


@app.post("/api/run", dependencies=[Depends(require_auth)])
def run():
    if not runner.start(auto_notify=True):
        raise HTTPException(status_code=409, detail="已有任务正在运行")
    return {"ok": True}


@app.patch("/api/accounts/{index}", dependencies=[Depends(require_auth)])
def update_account(index: int, request: AccountUpdate):
    if runner.status()["running"]:
        raise HTTPException(status_code=409, detail="任务运行中，暂时不能修改配置")
    if index < 0 or index >= len(_conf.accounts):
        raise HTTPException(status_code=404, detail="账号不存在")
    account = _conf.accounts[index]
    for key, value in request.tasks.items():
        if key not in TASK_FIELDS:
            raise HTTPException(status_code=400, detail=f"未知任务: {key}")
        setattr(account, key, bool(value))
    if not ConfigManager.write_plugin_data():
        raise HTTPException(status_code=500, detail="配置保存失败")
    return {"accounts": _accounts_payload()}


@app.post("/api/captcha/submit", dependencies=[Depends(require_auth)])
def captcha_submit(request: CaptchaSubmit):
    if not submit_captcha(request.id, request.value):
        raise HTTPException(status_code=400, detail="验证码已超时或提交失败")
    return {"ok": True}


@app.get("/api/settings", dependencies=[Depends(require_auth)])
def get_settings():
    return _settings_payload()


@app.patch("/api/settings", dependencies=[Depends(require_auth)])
def update_settings(request: SettingsUpdate):
    if runner.status()["running"]:
        raise HTTPException(status_code=409, detail="任务运行中，暂时不能修改设置")
    for item in request.accounts or []:
        if item.index < 0 or item.index >= len(_conf.accounts):
            raise HTTPException(status_code=404, detail="账号不存在")
        account = _conf.accounts[item.index]
        if item.uid is not None and item.uid.strip():
            account.uid = item.uid.strip()
        if item.password:
            account.password = account._password(item.password)
        if item.cookies and item.cookies.strip():
            try:
                account.cookies = account._cookies(item.cookies.strip())
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise HTTPException(status_code=400, detail=f"Cookie 格式错误: {exc}") from exc
        if item.user_agent is not None:
            account.user_agent = item.user_agent.strip()
        if item.login_user_agent is not None:
            account.login_user_agent = item.login_user_agent.strip()
        if item.device is not None:
            account.device = item.device.strip()
        if item.device_model is not None:
            account.device_model = item.device_model.strip()

    if request.onepush:
        params = _conf.ONEPUSH.params or {}
        if request.onepush.notifier is not None:
            _conf.ONEPUSH.notifier = request.onepush.notifier.strip()
        if request.onepush.title is not None:
            params["title"] = request.onepush.title
        if request.onepush.userid is not None:
            params["userid"] = request.onepush.userid
        if request.onepush.markdown is not None:
            params["markdown"] = request.onepush.markdown
        if request.onepush.token:
            params["token"] = request.onepush.token.strip()
        _conf.ONEPUSH.params = params

    if not ConfigManager.write_plugin_data():
        raise HTTPException(status_code=500, detail="设置保存失败")
    return _settings_payload()
