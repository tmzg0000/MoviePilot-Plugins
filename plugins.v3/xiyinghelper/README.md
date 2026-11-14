# 栖影签到助手 / xiyinghelper

独立 MoviePilot V2/V3 插件，通过普通 HTTP 请求访问 https://hdhaven.com/me 并复现网页签到操作。无需运行浏览器，无需申请 OpenAPI、应用凭证或授权 Token。

## 使用

1. 浏览器登录栖影，在 CookieCloud 中同步 `hdhaven.com` Cookie。
2. 在 MoviePilot 设置中完成 CookieCloud 配置（远程服务或 MP 本地 CookieCloud 均由宿主处理）。无需添加 PT 站点，也无需在插件重复填写 Cookie、密钥或密码。
3. 安装「栖影签到助手」，启用定时签到并保存。默认普通签到、北京时间每天 **00:10**（Cron：`10 0 * * *`）。可以勾选「保存后立即执行一次」验证。
4. 「使用 MP 设置的代理」默认勾选，使用 MP 当前全局 HTTP 代理；未配置代理或取消勾选时直连，不继承环境代理。

签到方式可选择普通签到或赌狗签到，默认普通签到。赌狗签到按站点规则可能扣除积分。两种签到共用每天一次机会，站点每天北京时间 00:00 重置。

## 工作流程

- 每次运行调用 MP 的 CookieCloudHelper 获取最新 Cookie；不把 Cookie 和 CookieCloud 密钥写入插件配置、历史或日志。
- 使用临时 `requests.Session`，Cookie 仅用于栖影 HTTPS 域名；不跟随重定向，保留 TLS 证书校验。
- 先访问 `/me`，再通过网页自身的 `/api/auth/me` 读取 `data.checkin_today`；已签到则不提交。
- 普通签到发送空正文 `POST /api/account/checkin`，赌狗签到发送空正文 `POST /api/account/checkin/gamble`。这是网页按钮使用的请求，并非 `/api/openapi/` 接入。
- 使用网页请求的 User-Agent、Origin、Referer 与同源 Fetch 请求头，不运行 JavaScript，不调用浏览器。
- 提交后重新读取账户，仅在 `checkin_today` 明确为 `true` 时确认已签到。HTTP 200 或页面可访问本身不代表签到成功。
- 提交前保存北京时间日期。超时、复查失败或进程重启后，当天后续任务只核实账户状态，不再次提交。若提交实际未到达服务器，该日可能漏签，以避免重复操作。
- 本插件针对单个 CookieCloud 栖影账号使用。执行互斥，保留最近 30 次运行记录，可选 MP 通知。
- Cookie 失效、站点拒绝网页直连或要求会话／安全验证时记录原因并停止，不启动浏览器，不切换 OpenAPI。需要时请手动登录／验证后同步 Cookie。

## 验证范围

已通过普通 HTTP 下载站点公开前端脚本，确认网页签到地址、空正文 POST、Cookie 认证及账户状态字段；补全同源请求头后，无 Cookie 请求从 `BROWSER_REQUIRED` 转为正常的 HTTP 401「请先登录」。

离线测试覆盖普通／赌狗签到、账户复查、超时不重发、Cookie 更新、代理开关、计划任务和凭据保护。尚未用真实账号 Cookie 完成联网签到，实际登录与签到效果需在 MP 中执行验证。
