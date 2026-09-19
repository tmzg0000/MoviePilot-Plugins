# Telegram 自动签到

通过 Telegram 用户会话向配置的机器人发送签到命令，支持 MoviePilot 的定时任务和全局 HTTP 代理。

填写 Telegram API ID、API Hash、可信设备生成的 Telethon StringSession，以及机器人命令。例如：`@example_bot:/qd,@another_bot:sign`。省略命令时使用 `/qd`。

开启“使用 MoviePilot 代理”后，插件读取 MoviePilot 的全局代理配置；关闭时直连 Telegram。StringSession 与 API Hash 是账户凭据，勿在日志、截图或仓库中公开。
