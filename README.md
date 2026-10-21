# MoviePilot-Plugins
MoviePilot官方插件市场：https://github.com/jxxghp/MoviePilot-Plugins

### [抢车位助手](plugins.v3/qcwautopark)

  支持 MoviePilot V2/V3，直接调用抢车位游戏 HTTP 接口，无需浏览器常驻。每轮读取 MP 躺平 PT 主站的最新 Cookie，经主站登录入口取得游戏会话。默认每5分钟检查：自己私家车位上他人的车预估收益 **≥1000** 时贴条，自己的车基础收益 **>2000** 时收车，再自动停车。停车目标必须同时满足 **等级≤3、金币≤3000**，阈值均可配置。所有请求完成后至少间隔10秒，防止接口响应慢时连续操作；结果页保留最近20轮记录。

  - V2：[`plugins.v2/qcwautopark`](plugins.v2/qcwautopark)
  - V3：[`plugins.v3/qcwautopark`](plugins.v3/qcwautopark)

### [媒体库封面生成](https://github.com/justzerock/MoviePilot-Plugins/tree/main/plugins.v2/mediacovergenerator)
  > 参考项目：https://github.com/HappyQuQu/jellyfin-library-poster

  在群里受到这个项目的启发，督促 AI 帮我写封面处理的代码，于是有了这个插件，支持切换风格

  ![插件界面](https://raw.githubusercontent.com/justzerock/MoviePilot-Plugins/main/images/plugin.webp)

### [验证码站点签到](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v3/captchasignin)

  支持 MoviePilot V2/V3，复用站点 Cookie。普通图片验证码优先调用 MP 系统配置的 OCR 服务（`OCR_HOST`），失败后使用对应站点的 Browserless Token 兜底，无需额外安装 OCR 模型。新增自由农场 `0ff.cc` / `pt.0ff.cc` 仅直连签到，失败直接报告，不调用 Browserless；保留 OpenCD 首页签到记录严格复查。

  配置以站点为中心：Browserless Token 明文每行一个，选择签到站点后立即显示对应设置；每站独立选择 Token 编号、签到模式、默认或自定义按钮文字与成功确认文字。旧版单 Token、五组分组及直连配置自动迁移并保留对应关系。弹窗验证码、Cloudflare、Turnstile、Altcha 等需要浏览器交互的流程继续使用 Browserless。内置农场、OpenCD、包子、OshenPT、Vc-lib、思齐、NovaHD、慕雪阁、LuckPT、YemaPT、HDSky 等规则。当日已成功站点跳过所有网络签到，失败站点默认 10 分钟后额外重试 1 次，结果通过 MP 通知渠道发送。详情见插件目录 README。

  天空 HDSky 优先使用专用 HTTP/MP OCR 接口，验证码被拒绝时有限次刷新，提交异常时回查确认，失败后再用所选 Browserless Token。猪猪 Piggo 新增“本地浏览器”模式，使用 MP 运行环境及站点代理的出口处理签到，不自动切换云端 Browserless；旧配置可在每站模式中改选。

  - V2：[`plugins.v2/captchasignin`](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v2/captchasignin)
  - V3：[`plugins.v3/captchasignin`](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v3/captchasignin)

### [Telegram 自动签到](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v3/telegramautosignin)

  支持 MoviePilot V2 与 V3。通过 Telegram 用户会话向少量指定机器人发送命令，并由 MoviePilot 的 Cron 定时任务运行。默认执行周期为北京时间每天 00:25、12:25、23:25；可在插件设置中调整。

  填写 Telegram API ID、API Hash、Telethon StringSession 与机器人命令。命令格式为 `@bot1:/qd,@bot2:sign`，未写命令时默认发送 `/qd`。可选择复用 MoviePilot 的全局 HTTP 代理；通知开关默认关闭。StringSession 与 API Hash 是账户凭据，不能提交到仓库或写入日志。

  - V2：[`plugins.v2/telegramautosignin`](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v2/telegramautosignin)
  - V3：[`plugins.v3/telegramautosignin`](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v3/telegramautosignin)

### [GlaDOS 签到助手](https://github.com/tmzg0000/MoviePilot-Plugins/tree/main/plugins.v3/gladossigner)

  从 [madrays/MoviePilot-Plugins](https://github.com/madrays/MoviePilot-Plugins) 搬运，保留原作者署名，作为后续二开的基础。支持每日签到、定时任务、代理、失败重试及可选积分兑换套餐。

  - V2（3.6.1）：[`plugins.v2/gladossigner`](plugins.v2/gladossigner)
  - V3（3.6.1）：[`plugins.v3/gladossigner`](plugins.v3/gladossigner)
  - 来源提交、许可证与署名声明见各插件目录中的 README、LICENSE 和 NOTICE。

### [自动限速](plugins.v2/limit)

  从 [aClarkChen/MoviePilot-Plugins](https://github.com/aClarkChen/MoviePilot-Plugins/tree/main/plugins.v2/limit) 导入并二开，本仓库维护作者为 `tmzg0000`，保留原作者来源说明。支持 qBittorrent、Transmission 的按标签及所有种子上传限速，以及 Cron、固定间隔和运行一次；所有种子模式可筛选仅新增种子，按下载器持久化记录，逐个设置上传上限，不修改下载器全局限速。

  - V2（1.1.7）：[`plugins.v2/limit`](plugins.v2/limit)，配置与日志单位统一为 `KiB/s`。
  - V3（1.1.7）：[`plugins.v3/limit`](plugins.v3/limit)，支持相同的限速与新增筛选功能。
  - 来源提交与许可证说明见插件目录中的 README 和 NOTICE。
