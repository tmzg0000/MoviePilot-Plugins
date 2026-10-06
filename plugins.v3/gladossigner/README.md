# GlaDOS 签到助手（MoviePilot V3）

从 [madrays/MoviePilot-Plugins](https://github.com/madrays/MoviePilot-Plugins/tree/414284db12bab65d1a843b6ed5cb9f47ef095b1c/plugins.v3/gladossign) 搬运，作为本仓库后续二开的基础。

- 上游提交：`414284db12bab65d1a843b6ed5cb9f47ef095b1c`
- 上游目录：`plugins.v3/gladossign`
- 上游版本：3.6.0
- 本地目录：`plugins.v3/gladossigner`

本仓库两版统一版本为 `3.6.0`，插件标识为 `gladossigner`，显示名称为「GlaDOS 签到助手」。保留上游作者署名，未修改签到逻辑。插件支持定时签到、代理、失败重试和可选积分自动兑换；配置入口与凭证提取指引见插件设置页面。

本目录代码遵循上游 [LICENSE](LICENSE)（AGPL-3.0-only 及其附加条款），署名声明见 [NOTICE](NOTICE)。后续修改与分发需保留这两个文件。

## cURL 导入

登录 GlaDOS 后，打开开发者工具 Network，刷新页面，右键一个包含 Cookie 和 Authorization 请求头的同域 `/api/` 请求，选择 Copy → Copy as cURL (bash)。把完整命令粘贴到「一次性凭证 / cURL 请求」栏并保存，即可读取 Cookie、设备指纹、登录域名和 User-Agent；无需另外填写 Cookie。解析只读取文本，不执行命令。Cookie 失效后重新导入。
