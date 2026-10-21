# MIUI Task
一个适用于 社区 4.0 模拟网络功能请求的脚本

![GitHub](https://img.shields.io/github/license/0-8-4/miui-auto-tasks) 
![Python](https://img.shields.io/badge/python-3.11+-blue)

## **关于项目**:

  受`東雲研究所` 的某位大佬启发  
  最初的源码由大佬授权 `0-8-4` 使用 `MIT` 开源   
  项目初期由`0-8-4` 和 `TardisLX` 进行维护，现已逐渐转为社区驱动
  我们认为社区无权在无任何回报的情况下强制要求内测用户完成 KPI 任务，因此诞生了这个脚本

> [!WARNING]
> 虽然理论上本脚本不会影响社区账户安全，但您需要自行承担使用本脚本的后果
> **我们不鼓励，不支持一切商业使用**
> 鉴于项目的特殊性，我们可能在任何时间 **停止更新** 或 **删除项目**

### **使用说明**：
项目支持本地运行和 Docker Compose 部署，下面给出最小步骤。

### **Web 面板**：
启动可视化面板：

```shell
pip install -r requirements.txt
cp .env.example .env
# 修改 .env 中的 WEB_PASSWORD
python -m waitress --listen=127.0.0.1:8000 webapp.main:app
```

访问 `http://127.0.0.1:8000`。面板支持运行任务、实时日志、账号任务开关、个人信息/推送设置，以及人工验证码处理。本地运行时验证码会自动打开 Chrome，完成后自动捕获 token；服务器或手机通过面板弹窗完成验证，结果自动回传，不需要复制粘贴。

Telegram 每次运行结束只发送账号状态与加分汇总，不再发送完整脚本日志。

面板必须设置 `WEB_PASSWORD` 才能访问；本地启动会自动加载项目根目录的 `.env`，浏览器会弹出 HTTP Basic 登录框。

本机自动捕获验证码需要 `playwright` 和 Chrome；如果浏览器无法启动，可执行 `playwright install chromium`。

Docker Compose 部署：

```shell
cp .env.example .env
# 修改 .env 中的 WEB_PASSWORD
docker compose up -d --build
```

默认不自动运行；打开面板点“立即运行”，或在设置里开启每日定时。

### **服务器 / 手机验证码**：
Docker 容器没有桌面浏览器，服务器用后台 Chromium 打开小米验证页并把画面实时转发到面板。出现验证码时：

1. 手机或电脑打开面板，弹窗会直接显示小米验证页画面。
2. 在画面上点击/输入完成验证。
3. 验证成功后结果自动回传，面板继续执行任务，不需要复制粘贴。

容器默认开启“服务器远程验证”：服务器用 Playwright 打开小米验证页，面板里直接显示画面，你点画面即可完成验证，完成后自动回传。电脑和手机都一样，不需要装脚本、不需要电脑助手、不需要复制粘贴。

面板设置里应显示“验证码方式：服务器远程验证”。如果显示“本机浏览器自动捕获”，说明容器没有启用，请重新执行 `docker compose up -d --build`。

如果远程画面加载失败，弹窗里的“其他方式”仍提供电脑助手和手动提交兜底。电脑助手用法：

```shell
conda activate AutoXiaomi
python captcha_helper.py --server http://你的服务器IP:8000
```

助手依赖本机 `requests`、`playwright` 和 Chrome：

```shell
pip install requests playwright
playwright install chromium
```

### **可选：服务器全自动打码**：
如果连验证码弹窗都不想点，可以在面板“设置 -> 验证码与定时运行”里选择“自动”，并填写服务商 API Key。支持 Capzy、2Captcha、CapSolver。配置后验证码由服务器自动完成，手机只需点“立即运行”。

- Capzy：https://capzy.ai
- 2Captcha：https://2captcha.com
- CapSolver：https://www.capsolver.com

自动打码覆盖极验和 Google reCAPTCHA；选择“自动”时失败会回退到服务器远程验证，“仅自动打码”模式不会弹远程。打码按次收费，具体价格以服务商为准。

如果服务商提示出口 IP 被封，可以在同一设置里填写可选代理。代理只作为 `proxyAddress` 传给打码服务商，用于访问验证码页面，不会代理本应用的其他请求。

### **每日定时运行**：
面板“设置 -> 验证码与定时运行”里可以开启每日定时，并设置开始/结束时间（Asia/Shanghai 时区）。服务器每天会在该范围内随机选择一个时间自动运行一次；即使不打开面板也会执行，重启不会重复跑当天。

首次构建会下载基础镜像、Playwright 和 Chromium，可能持续几分钟，镜像也会变大。`docker compose up -d` 默认不显示构建进度，建议先单独构建：

```shell
docker compose build --progress=plain
docker compose up -d
```

使用 PyPI 官方源。若容器启动后异常，查看 `docker compose logs -f`。

### **项目介绍**：  
- [x] 支持 多账号 配置
- [x] 支持 Docker 部署
- [x] 支持 自动登录账号刷新社区 Cookie 以便于实现自动化   
- [x] 绝大多数功能均可在配置文件中自行开关启用   

&#x26A0; 请注意，配置文件默认禁用了 MIUI Task 绝大多数模拟网络请求的功能能力，请注意修改配置文件按需启用。根据社区相关规则，模拟这些功能的网络请求可能存在一定风险。您需要自行承担使用本脚本的后果

#### **其他**：  
* 在使用本脚本时请临时关闭网络代理工具及广告拦截程序  
* 在服务器上使用前建议先使用服务器IP登录 `https://account.xiaomi.com`  
* **欢迎提供有关的思路，提交BUG以及更多完成社区其他任务方式，我们会认真对待~**

#### **贡献**：

如果你在使用过程中发现任何问题，可以使用模板 [提交 issue](https://github.com/0-8-4/miui-auto-tasks/issues/new) 或自行 Fork 修改后提交 Pull request

如果你要提交 Pull request，请确保你的代码风格和项目已有的代码保持一致，遵循 [PEP 8](https://www.python.org/dev/peps/pep-0008) ，变量命名清晰，有适当的注释

# **鸣谢**
## 技术赞助

[最佳亚洲 CDN、Edge 和安全解决方案 - 腾讯 EdgeOne](https://edgeone.ai/?from=github)
[![](https://edgeone.ai/media/34fe3a45-492d-4ea4-ae5d-ea1087ca7b4b.png)](https://edgeone.ai/?from=github)

## 项目

感谢由 [Xiaomi-Community-AutoTask](https://github.com/CMDQ8575/Xiaomi-Community-AutoTask) 启发的部分相关功能代码

## 社区

感谢以下贡献者对本项目做出的贡献

<a href="https://github.com/0-8-4/miui-auto-tasks/graphs/contributors">

  <img src="https://contrib.rocks/image?repo=0-8-4/miui-auto-tasks" />

</a>

![Alt](https://repobeats.axiom.co/api/embed/073d4816527b3720a03cb44fa876fe0de0216124.svg "Repobeats analytics image")

<br><br>

### 本项目所有贡献者感谢所有Star了本项目的人

[![Star History Chart](https://api.star-history.com/svg?repos=0-8-4/miui-auto-tasks&type=Date)](https://star-history.com/#0-8-4/miui-auto-tasks&Date)
