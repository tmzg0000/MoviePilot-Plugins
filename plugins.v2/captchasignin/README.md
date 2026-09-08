# 验证码站点签到

MoviePilot V2/V3 通用的 PT 自动签到插件。插件使用 MoviePilot 已保存的站点 Cookie，并通过 Browserless BrowserQL 处理图片验证码、Cloudflare 页面挑战和 Turnstile。

在插件设置中填写 Browserless 地址和 Token，选择已配置 Cookie 的站点。内置 OpenCD、包子、慕雪阁、`dstudio.me`、`mua.xloli.cc` 与 `share.ilolicon.com` 的规则。包子在当天已经签到且验证码图片消失时会直接报告“已签到”。

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

`mode` 支持 `image`、`cloudflare` 和 `open_page`。`cloudflare` 使用 Browserless 自动识别，兼容 Cloudflare 页面挑战与 Turnstile；若站点在 MoviePilot 中设置了 User-Agent，插件会在 Browserless 会话中复用它。Cookie、Browserless Token 与验证码内容均不会写入日志或签到历史。

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
