# MIUI Task（自动打码轻量版）

一个适用于小米社区 4.0 的任务脚本。当前分支 `codex/auto-captcha-only` 只保留自动打码，不安装 Playwright/Chromium，不弹人工验证窗口，适合 1 核 1GB 小机子部署。

![GitHub](https://img.shields.io/github/license/0-8-4/miui-auto-tasks)
![Python](https://img.shields.io/badge/python-3.11+-blue)

## 关于项目

受 `東雲研究所` 的某位大佬启发，最初的源码由大佬授权 `0-8-4` 使用 `MIT` 开源。项目初期由 `0-8-4` 和 `TardisLX` 进行维护，现已逐渐转为社区驱动。

> [!WARNING]
> 虽然理论上本脚本不会影响社区账户安全，但您需要自行承担使用本脚本的后果。
> **我们不鼓励，不支持一切商业使用。**

## 这个分支有什么不同

- 只保留付费打码：Capzy / 2Captcha / CapSolver。
- 移除 Playwright、Chromium、油猴脚本、验证码中转页和人工验证弹窗。
- 镜像更小，内存占用更低，适合 1 核 1GB 服务器。
- 自动打码失败时跳过签到，不会卡住等待人工处理。
- 支持可选代理，用于解决打码服务出口 IP 被 Google 封禁的问题。

## 本机运行

```shell
conda activate AutoXiaomi
pip install -r requirements.txt
cp .env.example .env
# 修改 .env 中的 WEB_PASSWORD
python -m waitress --listen=127.0.0.1:8000 --threads=2 webapp.main:app
```

打开 `http://127.0.0.1:8000`，使用 `.env` 里的账号密码登录。

## Docker Compose 部署

```shell
cp .env.example .env
# 修改 .env 中的 WEB_PASSWORD
docker compose up -d --build
```

Compose 默认限制为 1 CPU、512MB 内存。首次构建只需要安装 Python 依赖，不再下载 Chromium。

## 配置修改后如何生效

- 在面板里保存设置：立即生效，不需要重启。
- 手动编辑 `data/config.yaml`：在面板设置里点“重新加载配置”，或执行 `docker compose restart`。
- 修改 `.env`：执行 `docker compose up -d --force-recreate`。
- 修改代码：执行 `docker compose up -d --build`。

不需要执行 `docker compose down`，也不需要删除容器或镜像。`data/` 是挂载目录，配置会保留。

## 自动打码配置

打开面板右上角“设置”，在“自动打码与定时运行”里填写：

- 打码服务商：Capzy / 2Captcha / CapSolver
- 打码 API Key
- 可选代理：类型、地址、端口、用户名、密码

配置保存后，每日签到遇到极验或 Google reCAPTCHA 时会自动调用打码服务。未配置打码服务或打码失败时，日志会提示原因并跳过签到。

如果服务商提示 `reCAPTCHA's audio challenge was blocked by Google on this exit IP`，说明服务商默认出口 IP 被 Google 封了。填写一个能访问 Google 的代理后，打码器会自动切换到带代理的任务类型。

代理只作为 `proxyAddress` 传给打码服务商，用于访问验证码页面，不会代理本应用的其他请求。

## 每日定时运行

在“设置 -> 自动打码与定时运行”里开启定时，并设置开始/结束时间（Asia/Shanghai）。服务器每天会在该范围内随机选择一个时间运行一次；重启不会重复跑当天。

## 登录说明

这个分支不启动浏览器。如果小米要求短信/邮箱验证，请在本地完成登录，把有效 Cookie 写入面板或 `data/config.yaml`，再在服务器运行任务。

## 配置文件

- 配置：`data/config.yaml`
- 日志：`logs/`
- 环境变量：`.env`

不要提交 `.env`、`data/`、`logs/`。

## 项目介绍

- [x] 支持多账号配置
- [x] 支持 Docker 部署
- [x] 支持自动登录账号刷新社区 Cookie
- [x] 绝大多数功能均可在配置文件中自行开关启用

> [!WARNING]
> 配置文件默认禁用了 MIUI Task 绝大多数模拟网络请求的功能能力，请注意修改配置文件按需启用。根据社区相关规则，模拟这些功能的网络请求可能存在一定风险。您需要自行承担使用本脚本的后果。

## 其他

- 在使用本脚本时请临时关闭网络代理工具及广告拦截程序。
- 在服务器上使用前建议先使用服务器 IP 登录 `https://account.xiaomi.com`。
- 欢迎提供思路、提交 BUG 以及更多完成社区其他任务的方式。

## 贡献

如果你在使用过程中发现任何问题，可以使用模板 [提交 issue](https://github.com/0-8-4/miui-auto-tasks/issues/new) 或自行 Fork 修改后提交 Pull request。

如果你要提交 Pull request，请确保你的代码风格和项目已有的代码保持一致，遵循 [PEP 8](https://www.python.org/dev/peps/pep-0008)，变量命名清晰，有适当的注释。

## 鸣谢

感谢由 [Xiaomi-Community-AutoTask](https://github.com/CMDQ8575/Xiaomi-Community-AutoTask) 启发的部分相关功能代码。

感谢所有贡献者、提交 issue 的人和帮助项目发展的人。

<a href="https://github.com/0-8-4/miui-auto-tasks/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=0-8-4/miui-auto-tasks" />
</a>

### 本项目所有贡献者感谢所有 Star 了本项目的人
