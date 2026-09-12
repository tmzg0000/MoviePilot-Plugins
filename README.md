# MoviePilot-Plugins
MoviePilot官方插件市场：https://github.com/jxxghp/MoviePilot-Plugins

### [媒体库封面生成](https://github.com/justzerock/MoviePilot-Plugins/tree/main/plugins.v2/mediacovergenerator)
  > 参考项目：https://github.com/HappyQuQu/jellyfin-library-poster

  在群里受到这个项目的启发，督促 AI 帮我写封面处理的代码，于是有了这个插件，支持切换风格

  ![插件界面](https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/images/plugin.webp)

### [验证码站点签到](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v3/captchasignin)

  支持 MoviePilot V2 与 V3，通过 Browserless BrowserQL 使用已保存的站点 Cookie 完成 PT 图片验证码、弹窗图片验证码、Cloudflare 页面挑战、Turnstile 与 Altcha 签到。

  在插件设置中填写 Browserless 地址和 Token，并选择已经配置 Cookie 的站点。默认云端地址为 `https://production-sfo.browserless.io`，也可使用自建服务根地址或完整 `/stealth/bql` 地址。首次使用请先[注册 Browserless 账号](https://www.browserless.io/signup/email?plan=free)，登录[账户控制台](https://browserless.io/account/)并在 **API Key** 区域复制 Token。内置 OpenCD、包子、慕雪阁、OshenPT、LuckPT、YemaPT、HDSky、`dstudio.me`、`mua.xloli.cc` 和 `share.ilolicon.com` 的签到规则；YemaPT 支持 Hash 路由、Browserless 原生 Altcha 点击与 payload 等待，HDSky 支持先打开签到弹窗再处理图片验证码，并以“已签到”判定成功。结果表按“站点、状态、最后运行时间、结果”展示，成功状态统一显示“签到成功”，站点名称可在新标签页直接打开对应签到页面。当天成功或已签到的站点会被本地记录并跳过后续 Browserless 调用，失败站点才会继续执行与重试。失败站点默认会在 10 分钟后额外重试 1 次，可在设置中调整或关闭。其他站点可通过“自定义站点规则 JSON”扩展。包子在当天已签到时会直接报告状态，慕雪阁点击“立即签到”即可完成。

  - V2：[`plugins.v2/captchasignin`](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v2/captchasignin)
  - V3：[`plugins.v3/captchasignin`](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v3/captchasignin)
