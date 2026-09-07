# MoviePilot-Plugins
MoviePilot官方插件市场：https://github.com/jxxghp/MoviePilot-Plugins

### [媒体库封面生成](https://github.com/justzerock/MoviePilot-Plugins/tree/main/plugins.v2/mediacovergenerator)
  > 参考项目：https://github.com/HappyQuQu/jellyfin-library-poster

  在群里受到这个项目的启发，督促 AI 帮我写封面处理的代码，于是有了这个插件，支持切换风格

  ![插件界面](https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/images/plugin.webp)

### [验证码站点签到](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v3/captchasignin)

  支持 MoviePilot V2 与 V3，通过 Browserless BrowserQL 使用已保存的站点 Cookie 完成 PT 图片验证码、Cloudflare 页面挑战和 Turnstile 签到。

  在插件设置中填写 Browserless 地址和 Token，并选择已经配置 Cookie 的站点。内置 OpenCD、包子、`dstudio.me`、`mua.xloli.cc` 和 `share.ilolicon.com` 的签到规则；其他站点可通过“自定义站点规则 JSON”扩展。

  - V2：[`plugins.v2/captchasignin`](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v2/captchasignin)
  - V3：[`plugins.v3/captchasignin`](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v3/captchasignin)
