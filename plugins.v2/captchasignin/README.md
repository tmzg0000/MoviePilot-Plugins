# 验证码站点签到

MoviePilot V2/V3 通用的 PT 自动签到插件。插件使用 MoviePilot 已保存的站点 Cookie，并通过 Browserless BrowserQL 处理图片验证码、Cloudflare 页面挑战和 Turnstile。

在插件设置中填写 Browserless 地址和 Token，选择已配置 Cookie 的站点。内置 OpenCD、包子、`dstudio.me`、`mua.xloli.cc` 与 `share.ilolicon.com` 的规则。

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

`mode` 支持 `image`、`cloudflare` 和 `open_page`。Cookie、Browserless Token 与验证码内容均不会写入日志或签到历史。
