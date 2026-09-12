# 验证码站点签到

MoviePilot V2/V3 通用的 PT 自动签到插件。插件使用 MoviePilot 已保存的站点 Cookie，并通过 Browserless BrowserQL 处理图片验证码、弹窗图片验证码、Cloudflare 页面挑战、Turnstile 与 Altcha。

在插件设置中填写 Browserless 地址和 Token，选择已配置 Cookie 的站点。内置 OpenCD、包子、慕雪阁、LuckPT、OshenPT、YemaPT、HDSky、`dstudio.me`、`mua.xloli.cc` 与 `share.ilolicon.com` 的规则。包子在当天已经签到且验证码图片消失时会直接报告“已签到”。

## Browserless 配置

- 默认云端地址：`https://production-sfo.browserless.io`（配置页会自动填入，只需填写 Token）。
- 地址也可填写自建 Browserless 的服务根地址，或完整的 `/stealth/bql` 地址；插件会自动补齐所需路径。
- 首次使用请先[注册 Browserless 账号](https://www.browserless.io/signup/email?plan=free)，登录[账户控制台](https://browserless.io/account/)，在 **API Key** 区域复制 Token 后填入插件设置。

其它站点可在“自定义站点规则 JSON”按域名或 MoviePilot 站点 ID 配置：

```json
{
  "pt.example.org": {
    "mode": "image",
    "path": "/attendance.php",
    "captcha_selector": "#captcha-image",
    "captcha_input_selector": "#captcha-answer",
    "submit_selector": "#submit"
  }
}
```

`mode` 支持 `image`、`trigger_image`、`cloudflare`、`open_page` 和 `altcha`。`trigger_image` 会先点击 `trigger_selector` 打开弹窗，再识别图片验证码并提交；`cloudflare` 使用 Browserless 自动识别，兼容 Cloudflare 页面挑战与 Turnstile；`altcha` 在站点页面内完成 Altcha 验证后再点击签到。若站点在 MoviePilot 中设置了 User-Agent，插件会在 Browserless 会话中复用它。Cookie、Browserless Token 与验证码内容均不会写入日志或签到历史。

YemaPT 已内置 Hash 路由和 Altcha 签到规则：使用 Browserless 原生点击“我不是机器人”，等待 `altchaPayload` 生成后才点击签到；当天页面显示“已签到”时会直接结束，不重复验证或点击。

HDSky 已内置弹窗图片验证码规则：先点击“签到”打开验证码对话框，再由 Browserless 填写并点击 “Let's Go”。
页面返回“已签到”会识别为签到成功；若 Browserless 在打开页面时导航超时，请改用可访问 HDSky 的 Browserless 节点后再试。

结果页中的成功与已签到均显示“签到成功”；失败时保留详细错误。每次执行后，站点名称可在新标签页打开该站首页，并显示最后运行时间。

失败重试默认等待 10 分钟后额外执行 1 次，且只处理失败站点；可在设置中将重试次数设为 0–5 次，0 表示关闭重试。

慕雪阁无需 Cloudflare 或图片验证码；如配置过自定义规则，请删除该项以使用内置规则，或改为：

```json
{
  "pt.muxuege.org": {
    "mode": "open_page",
    "path": "/attendance.php",
    "submit_selector": "input[type='submit'], button[type='submit']",
    "submit_text": "立即签到"
  }
}
```

## 结果页

结果页按 `AutoSignIn` 的信息层级展示本次处理站点数、成功/已签到数、待处理数，以及每个站点的状态和原因。保存配置后可勾选“保存后立即执行一次”进行连通性验证。
