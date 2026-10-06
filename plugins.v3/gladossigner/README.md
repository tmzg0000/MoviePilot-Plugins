# GlaDOS 签到助手（MoviePilot V3）

从 [madrays/MoviePilot-Plugins](https://github.com/madrays/MoviePilot-Plugins/tree/414284db12bab65d1a843b6ed5cb9f47ef095b1c/plugins.v3/gladossign) 搬运，作为本仓库后续二开的基础。

- 上游提交：`414284db12bab65d1a843b6ed5cb9f47ef095b1c`
- 上游目录：`plugins.v3/gladossign`
- 上游版本：3.6.0
- 本地目录：`plugins.v3/gladossigner`

本仓库两版统一版本为 `3.6.0`，插件标识为 `gladossigner`，显示名称为「GlaDOS 签到助手」。本仓库维护作者为 `tmzg0000`，保留上游来源与许可证署名，未修改签到逻辑。插件支持定时签到、代理、失败重试和可选积分自动兑换；配置入口与凭证提取指引见插件设置页面。

本目录代码遵循上游 [LICENSE](LICENSE)（AGPL-3.0-only 及其附加条款），署名声明见 [NOTICE](NOTICE)。后续修改与分发需保留这两个文件。

## 凭证设置

1. 在已登录的 GlaDOS 页面执行设备指纹提取代码，将完整 JSON 粘贴到「① 一次性凭证 JSON」。设备指纹、登录域名、User-Agent 均由 JSON 提供。
2. Cookie 二选一：将 Network 中 Copy as cURL (bash) 的完整命令粘贴到「② Cookie cURL 导入」，或在「③ 完整 Cookie」手动填写 `koa:sess`、`koa:sess.sig`、`gld:sess`、`gld:sess.sig` 四项，以分号分隔。

Cookie 优先级：手动填写 > cURL > JSON 自带 Cookie。使用 cURL 时请清空手动 Cookie 栏。cURL 仅解析 Cookie，不执行命令，不要求 Authorization。所有凭证须来自同一浏览器、同一登录域名；失效后重新获取。
