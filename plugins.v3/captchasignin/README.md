# 验证码站点签到

MoviePilot V2/V3 通用的 PT 自动签到插件，复用 MP 已保存的站点 Cookie、User-Agent 和系统 OCR 配置。版本 2.0.0 起，普通图片验证码优先使用 HTTP + MP OCR；未确认成功时，再使用对应站点的 Browserless Token 兜底。新增自由农场 `0ff.cc`、`pt.0ff.cc` 直连签到。

## 使用与站点设置（2.0.0）

配置顺序为：启用/通知/立即执行 → 周期与并发 → 失败重试 → Browserless Token → 签到站点 → 站点设置列表。

1. 在 MP 站点管理中保存站点地址、Cookie。
2. 在重试设置下方的 **Browserless Token（每行一个）** 输入框填写 Token，明文显示，无需分组。非空行从上到下对应 Token 1、Token 2……；可留空。
3. 在“签到站点”多选框选择站点，对应设置卡片立即显示在下方，取消选择即隐藏，列表随选择顺序排列，不需要先保存刷新。
4. 每个站点独立选择 **使用 Token**，可选“不使用 Browserless”或 Token 1、Token 2……。不会轮流分配，也不会在失败后自动换用其他 Token。农场及本地浏览器模式的 Token 选择不可用。
5. 设置该站点的模式、按钮文字、成功确认文字，保存后执行。

| 每站设置 | 选项与含义 |
| --- | --- |
| 模式 | 默认（内置规则）；点击确定 `open_page`；验证码 `image`；CF盾 `cloudflare`；弹窗验证码 `trigger_image`；Altcha 验证 `altcha`；农场直连 `farm`；本地浏览器 `local_browser` |
| 使用 Token | 不使用 Browserless / Token 1 / Token 2……，编号随上方非空行更新 |
| 按钮文字 | 默认 / 自定义；选择自定义后展开文字输入框，例如“立即签到” |
| 成功文字确认 | 默认 / 自定义；选择自定义后展开输入框，每行一个确认文字，匹配任意一项即成功 |

默认选项沿用内置或高级 JSON 规则。自定义按钮会按文字查找按钮，找不到时不会点击其他按钮；自定义成功文字替换该站点的默认成功匹配，不能留空。OpenCD 仍在首页复查确认文字，而不单独依赖 AJAX 返回。

农场固定使用直连模式，不提供按钮文字设置，也不调用 OCR 或 Browserless。其他站点即使不选 Token，仍可运行直连/OCR；确需浏览器处理时才报告无法兜底。

“高级设置”折叠区保留共用 Browserless 地址和自定义 JSON，用于签到路径、验证码选择器等细节。每站点的显式设置优先于高级规则。

旧版单 Token、五组 Token 和直连站点选择自动合并到新界面；按原来的 Token 值保留每站点对应关系，重复选择的站点仍以靠前的组为准。保存后使用新的每站点配置，清空站点选择不会恢复旧分组。

## OCR 与执行顺序

- 普通 `image` 站点：获取签到页 → 识别今日已签到状态 → 提取 `imagehash`、图片和表单 → 同一会话下载验证码 → 调用 MP `OCR_HOST` 的 `/captcha/base64` → 提交识别结果及原表单隐藏字段 → 检查响应、必要时重新查询状态。
- OCR 跟随 MP 系统配置，无需在插件里重复填写地址，也无需安装 `ddddocr`。使用默认服务或自建兼容服务均可。OCR 请求仅包含图片 Base64，不携带站点 Cookie。
- 农场：获取签到页 → 提取 `slide_check_*.js` → 提取同源 `set_access_token-...` 接口 → 请求接口 → 等待 3 秒 → 重新访问签到页确认结果。已签到时直接结束，不要求页面仍包含滑块脚本。
- 农场仅执行直连签到，不调用 OCR 或 Browserless，即使配置了 Token 也不调用。直连失败直接显示失败原因；后续失败重试仍仅执行直连。当前流程依赖站点仍将验证接口放在脚本中。
- 天空 HDSky 虽然页面上使用弹窗验证码，但默认先走专用 HTTP/OCR 接口；失败后才使用原有弹窗 Browserless 流程。其他 `trigger_image`、Cloudflare/Turnstile、Altcha 和需要 JavaScript 交互的流程使用 Browserless；本地浏览器模式除外。
- OpenCD 保留严格复查：只有首页显示“查看簽到記錄”才确认成功，AJAX `state=false` 或单独 `state=success` 均不作为最终成功依据。

内置规则包含农场、OpenCD、包子、OshenPT、Vc-lib、思齐、NovaHD、慕雪阁、LuckPT、YemaPT、HDSky、猪猪 Piggo、`dstudio.me`、`mua.xloli.cc` 与 `share.ilolicon.com`。普通 OCR 路径支持标准 NexusPHP `imagehash` / `imagestring` 表单；其他结构会转交 Browserless，不会猜测提交接口。

站点启用代理时，直连使用 MP 全局代理配置。站点图片、表单、验证脚本与接口只允许同源访问，开启 HTTPS 证书验证；跨域跳转会结束直连；农场直接报告失败，其他站点再尝试 Browserless。

## 天空与猪猪专用处理（2.0.0）

**天空 HDSky** `hdsky.me`：保留“弹窗验证码”内置模式，优先通过同一 HTTP 会话访问首页，POST `/image_code_ajax.php`（`action=new`）取得挑战，下载对应图片后调用 MP OCR，再 POST `/showup.php`。仅接受有效的六位识别结果。OCR 结果无效或接口明确返回 `invalid_imagehash` 时，重新获取验证码挑战，最多尝试 3 次；不反复提交同一份失效答案。

接口明确返回成功或 `date_unmatch` 时确认结果。提交超时、响应异常时只读回查首页一次；确认已签到则结束，未确认才进入所选 Browserless 兜底。自定义成功文字仍需回查匹配，不被 JSON 的成功字段绕过。其他模式的手动选择继续优先，不强制覆盖。

**猪猪 Piggo** `piggo.me`：新增默认“本地浏览器”模式，使用 MP `PlaywrightHelper.action()`，复用站点 Cookie、UA 和该站启用的代理。浏览器在 MP 运行环境发出请求；实际出口取决于 MP 部署及代理配置，不等同于必然是家庭网络。它不会使用或轮换 Browserless Token，也不会在失败后自动切换云端 IP。

流程为打开 `/index.php` → 等待页面安全验证放行 → 检查是否已签到 → 按文字点击“签到” → 再次等待安全验证 → 依据明确成功文字确认。两次安全验证分别最多等待 40 秒；仅在能定位到 Cloudflare 验证复选框时尝试点击，不能保证所有挑战可自动通过。异地登录确认不会自动接受，验证未通过、Cookie 失效或本地浏览器能力不可用都会显示失败。按钮消失不会视为成功。

新配置中的猪猪默认选择本地浏览器；若旧配置已显式保存为其他模式，需在该站点设置中改选“本地浏览器”。不安装额外浏览器或 Python OCR 依赖，直接使用 MP 现有能力。

协议与处理思路参考 [qingyukb/PT站点签到](https://github.com/qingyukb/MoviePilot-Plugins/tree/3e2a0f719b793522dc710a38ff822b9bae676e45/plugins.v3/ptsitesignin) 的天空接口及 Piggo 本地浏览器预设，在本插件的每站点配置、MP OCR 与严格结果确认流程中实现；未在真实账号环境验证这些站点当前的协议。

## Browserless 配置

- 默认地址：`https://production-sfo.browserless.io`。也支持自建服务根地址或完整 `/stealth/bql` 地址。
- 首次使用可[注册 Browserless 账号](https://www.browserless.io/signup/email?plan=free)，登录[账户控制台](https://browserless.io/account/)复制 API Key。
- 每个非农场站点仅使用它选定编号的 Token。普通直连/OCR 已成功时，不发起 Browserless 请求。

## 自定义规则

按域名或 MP 站点 ID 填写 JSON，原有配置继续生效；上方每站设置中选择默认即可沿用：

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

`mode` 支持 `image`、`trigger_image`、`cloudflare`、`open_page`、`altcha`、`farm` 和 `local_browser`。图片及按钮选择器供 Browserless 使用；HTTP 路径只解析标准验证码表单。需要单独提交接口时，可配置同源 `http_post_path`，如 OpenCD 的 `/plugin_sign-in.php?cmd=signin`。

YemaPT 使用 Hash 路由、Browserless 原生 Altcha 点击，并等待 `altchaPayload` 后提交。HDSky 的 Browserless 兜底会先打开签到弹窗，再识别图片并点击 “Let's Go”。慕雪阁通过“立即签到”按钮提交；LuckPT 支持领取后的确认对话框。

## 记录、重试与通知

当天成功或已签到的站点会保存本地状态，后续任务跳过 HTTP、OCR 和 Browserless。失败默认等待 10 分钟后额外重试 1 次，仅重试失败站点；可调整等待时间和重试次数，0 次为关闭。

结果页保留站点、状态、最后运行时间和结果；成功与已签到统一显示“签到成功”。失败会说明直连/OCR及 Browserless 的处理结果。通知使用 MP 已配置的通知渠道。Cookie、Token、农场验证接口地址和 OCR 验证码不主动写入日志或签到记录。

当前使用离线模拟验证流程与配置迁移；实际站点验证码、网络、Cookie 与页面结构仍需在 MP 环境执行验证。
