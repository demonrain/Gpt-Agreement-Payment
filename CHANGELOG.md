# Changelog

记录 webui / pipeline / scripts 的功能与协议改动，按 commit 倒序。

---

## [dev] pipeline Webshare 全面修复：WSL 链式代理 + backbone 模式 + Rotating Residential 支持

### pipeline.py WebshareClient / gost 修复（4 个问题）

- **WSL 代理检测**：`WebshareClient.__init__` 只检查环境变量 `HTTPS_PROXY`，WSL 下外网不通。新增 `_resolve_outbound_proxy()` 函数，自动探测宿主 Clash 代理
- **API mode 硬编码**：`get_current_proxy()` / `get_proxy_by_country()` 硬编码 `mode=direct`，住宅代理返回 400。新增 `_list_proxies()` 统一处理 backbone 优先回退 direct
- **gost 链式代理**：WSL 下 gost 无法直连 Webshare upstream。`_swap_gost_relay()` 检测到本地代理时自动插入 `-F={local_proxy}` 形成 `Clash → Webshare` 链式代理
- **gost backbone 兜底**：住宅代理 `proxy_address` 为 null 时，`_ensure_gost_alive()` / `_rotate_webshare_ip()` 自动使用 `p.webshare.io:80` 作为上游
- **Rotating Residential 跳过 refresh**：`total=0` 时识别为 Rotating 计划，跳过 `refresh_pool()` API 调用，直接重启 gost 获取新连接。启动日志不再显示误导性的"无剩余替换次数"警告

- **gost 双端口监听**：`_swap_gost_relay()` 同时启动 SOCKS5(`:18898`) + HTTP(`:18899`)，curl_cffi 使用 HTTP 端口避免 SOCKS5 链式 TLS 握手失败
- **curl_cffi TLS 修复**：`card.py` 的 `_derive_proxy_for_session()` 和 `gopay.py` 的 `_derive_http_proxy()` 自动将 `socks5://host:port` 转为 `http://host:{port+1}` 供 curl_cffi 使用
- **Midtrans 429 重试增强**：`LINK_429_RETRY_LIMIT` 3→20，固定 20s 间隔，总等待时间从 ~60s 增至 ~400s
- **ADB OTP 旧码误读修复**：`adb_otp_provider.py` 预扫描阶段新增 UI dump 扫描，将 WhatsApp 聊天界面中所有已有的 6 位数字加入 `seen` 集合，避免 UI 回退策略拿到历史旧 OTP

**涉及文件：**
- `pipeline.py` — 新增 `_resolve_outbound_proxy()` / `_list_proxies()`；重构 `WebshareClient.__init__` / `get_current_proxy` / `get_proxy_by_country` / `_swap_gost_relay` / `_ensure_gost_alive` / `_rotate_webshare_ip` / daemon 启动额度日志
- `CTF-pay/card.py` — 新增 `_derive_proxy_for_session()`，curl_cffi 自动使用 HTTP 代理端口
- `CTF-pay/gopay.py` — 新增 `_derive_http_proxy()`，429 重试上限 20 次
- `CTF-pay/adb_otp_provider.py` — 预扫描增加 UI dump 全量标记旧 OTP

---

## [dev] Webshare preflight 修复 + daemon 三维计数导出修复

### Webshare Preflight 修复（3 个问题）

- **WSL 网络不通**：新增 `_common.resolve_system_proxy()`，WSL 环境下自动检测 Windows 宿主 Clash 代理（扫描 7897/7890/7891 端口），`webshare.py` 改用此公共函数
- **API mode 不兼容**：住宅代理不支持 `mode=direct`，改为先尝试 `backbone`（住宅代理必须），400 时回退 `direct`（数据中心代理）
- **错误信息不明确**：`message` 直接显示具体原因（如 `HTTP 401: Invalid token`），不再笼统的 `0/1 ok`；异常捕获范围从 `httpx.HTTPError` 扩展到 `Exception`
- **前端新增 API 使用说明**：Step 05 Webshare 区块新增 API Key 获取步骤 + backbone 连接方式 + 文档链接

**涉及文件：**
- `webui/backend/preflight/_common.py` — 新增 `resolve_system_proxy()` / `_wsl_host_ip()` / `_probe_wsl_host_proxy()`
- `webui/backend/preflight/webshare.py` — 重构 check()，使用公共代理解析 + backbone 优先 + 详细错误信息
- `webui/frontend/src/components/steps/Step05_Proxy.vue` — 新增 API 使用说明信息块

### Daemon 三维计数导出修复

- **config_writer 丢失字段**：`_project_pay()` 导出 sub2api 配置时遗漏 `count_platform` / `count_status` / `count_group` / `push_group_id`，导致 pipeline.py 永远使用默认值 `openai/active/""`。现已补全导出
- **stats 缺少 status**：`Sub2apiClient.count_usable_accounts()` 返回的 dict 缺少 `status` 字段，daemon 日志无法显示状态过滤条件。现已补全
- **日志增强**：daemon 循环中 sub2api 日志从 `sub2api openai=4/6` 升级为 `sub2api openai/active/group1=4/6`，三个维度全部可见

**涉及文件：**
- `webui/backend/config_writer.py` — `_project_pay()` 补全 `count_platform` / `count_status` / `count_group` / `push_group_id` 导出
- `pipeline.py` — `count_usable_accounts()` 返回值补 `status`；daemon 日志显示三维标签

---

## [0074642] webui 账号面板大升级 + CPA / 注册链路多处修复

> commit message 里漏写了**运行时数据 JSONL → SQLite 大迁移**，这里补全完整范围。详见 `docs/architecture.md` 191 行起的 SQLite 存储说明。

### 运行时数据迁移（之前 message 漏）
- 账号 / 支付 / OAuth 状态从分散的 `output/*.jsonl` 文件迁移到单一 SQLite (`output/webui.db`):
  - `output/registered_accounts.jsonl` → 表 `registered_accounts`
  - `output/results.jsonl` → 表 `pipeline_results` + `card_results`
  - `output/secrets.json` / `daemon_state.json` / `webui_wizard_state.json` / `email_domain_state.json` / `wa_state.json` → 表 `runtime_meta` (key/value JSON)
  - 新表 `oauth_status` 单独跟踪 OAuth 链路状态
- 启动时 `_purge_legacy_runtime_files` 自动清掉旧 jsonl，避免双写造成数据漂移
- pipeline 调用面同步切换：`_append_result` / 读 results.jsonl 等全部走 db 接口

### 新增功能（已在 commit message 里）
- webui 账号库存：批量验证 + 批量删除 + plan 推断（free/plus/team）+ CPA 推送状态展示与"推送→CPA"按钮
- 账号有效性验证三层探活：rt → at → cookie，401/invalid_grant 判 invalid，CF 拦截/超时判 unknown
- CPA preflight 改用 `GET /v0/management/auth-files` + Bearer
- Codex OAuth `client_id` 后端硬编码兜底 `app_EMoamEEZ73f0CkXaXp7hrann`，前端不再让用户手填
- webshare preflight 补 `mode=direct` 查询参数
- `config_writer` webshare 模式自动注入 `socks5://127.0.0.1:18898`，避免 example 模板的 `USER:PASS` 占位透传
- vite `WEBUI_BASE` 修复 + `server.py` 同时挂 `/` 和 `/webui/`，直连和反代都通
- 新 favicon (`webicon.png`) + 右下角 GitHub 链接
- `batch` / `register_only` / `pay_only` 三个 flag 解耦，`batch + register-only` = 批量注册 N 个不付费
- worker OTP 抽取排除 `#XXXXXX` hex 颜色 + `color: / bgcolor=` 上下文（OpenAI 邮件 `#353740` 假阳性根因）
- `browser_register` 检测 OpenAI "Incorrect code" 红字立即 fail，避免触发 `max_check_attempts` 风控

---

## [bf0cca2] WhatsApp relay 支持自由切换引擎
（前略）
