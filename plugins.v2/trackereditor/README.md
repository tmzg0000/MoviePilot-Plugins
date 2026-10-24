# Tracker替换

版本 **2.0.0**，支持 MoviePilot V2/V3；原插件由 [honue](https://github.com/honue) 编写，本仓库由 `tmzg0000` 维护。上游为 [jxxghp/MoviePilot-Plugins](https://github.com/jxxghp/MoviePilot-Plugins/tree/main/plugins/trackereditor)，来源与修改说明见 [NOTICE](NOTICE)，许可证见仓库根目录 [LICENSE](../../LICENSE)。

批量修改下载器中**已有种子**的 Tracker，支持 qBittorrent 与 Transmission **4.0+**。扫描所连接下载器的所有种子，不按分类或标签筛选。

## 使用

1. 填写下载器地址、端口和认证信息。地址支持 HTTP(S)、IP、主机名和反向代理路径；Transmission 自定义路径需填写完整 RPC 路径，例如 `https://nas.example/tr/transmission/rpc`。
2. 每行一条规则，格式为 `旧文本|新文本`：

   ```text
   old.example.com|new.example.com
   ```

   `https://old.example.com/announce?passkey=xxxx` 会替换成 `https://new.example.com/announce?passkey=xxxx`。可以替换协议、域名、路径或 Passkey；规则为区分大小写的普通字符串替换，不支持正则表达式。每个地址只应用从上往下第一条匹配规则，不连锁替换。空行忽略，两侧不能为空或相同；存在错误行时整轮不连接下载器。

3. 勾选“保存后立即运行一次”，保存后后台执行；或开启“定时执行”并填写五位 Cron。定时任务使用 MoviePilot 的 `TZ` 时区。
4. 插件详情页显示最近一次扫描、修改种子、修改 Tracker 与失败种子的数量；可开启结果通知。

先用测试 Tracker 验证替换结果，再对实际站点执行。只有新地址属于正确站点且仍接受该种子和账号凭据时，替换才可能恢复汇报。

## 适配与行为

- 保留插件 ID `TrackerEditor`、配置前缀和原有连接字段。兼容上游误写入的 `run_cron_enable` / `run_cron`，保存统一使用 `run_con_enable` / `run_con`。
- V3 使用 SDK 的插件基类、配置、日志、一次性调度和消息类型；V2 使用对应宿主接口，两个目录自包含安装。
- 使用宿主已有的 `qbittorrent-api` / `transmission-rpc` 原生客户端，仅发出查询和 Tracker 修改，不调用会同步下载器全局偏好的连接封装。保持 HTTPS 证书验证。
- qBittorrent 逐个替换匹配地址；Transmission 保留原有 Tracker 分组及未匹配地址，仅对确有变化的种子提交新的列表。不自动新增公开 Tracker、重下种子或修改文件。
- 分别统计成功请求对应的种子数和 Tracker 数；一个种子多条 Tracker 不重复计算种子数。一个种子失败后继续处理其他种子，并保留此前成功计数。下载器接受请求不代表 Tracker 已成功连接，实际汇报情况需在下载器核对。
- 插件日志、通知与执行记录不输出完整 Tracker、Passkey、连接密码或替换规则；认证和规则仍由 MoviePilot 保存。

已通过离线原生客户端接口与 V2/V3 入口测试，未连接真实下载器执行替换。
