# SYSTEM.md — Gpt-Agreement-Payment 系统文档

## 项目目标

自动化 ChatGPT 账号注册 + 订阅支付（Stripe / PayPal / GoPay）的全流水线系统，含 WebUI 管理界面。

## 核心架构

```
用户 → WebUI (FastAPI:8765)
         ↓
    runner.py (子进程管理，自动重启)
         ↓
    pipeline.py (调度器：注册 → 支付 → 后处理)
         ↓
    ┌────────────┬──────────────┐
    CTF-reg/     CTF-pay/
    (注册模块)    (支付模块)
    browser_     card.py
    register.py  gopay.py
                 adb_otp_provider.py
```

## 目录结构

| 目录/文件 | 职责 |
|-----------|------|
| `pipeline.py` | 主调度器：注册→支付→team导入→sub2api推送 |
| `error_logger.py` | 结构化错误日志，写入 `output/error_logs/` |
| `CTF-pay/` | 支付模块（card.py=Stripe, gopay.py=GoPay） |
| `CTF-pay/adb_otp_provider.py` | ADB 读取 WhatsApp OTP |
| `CTF-reg/` | 注册模块（浏览器自动化） |
| `webui/` | Web 管理界面 |
| `webui/server.py` | FastAPI 应用入口（含 gost 自动启动） |
| `webui/backend/runner.py` | 子进程管理（含自动重启） |
| `webui/backend/runner_helpers.py` | runner 辅助：命令构建 + OTP 检测 |
| `webui/backend/gost_manager.py` | gost 代理中继管理器 |
| `webui/backend/preflight/adb.py` | ADB 设备检测（WSL 自动探测） |
| `webui/backend/preflight/proxy.py` | 代理预检 + gost 中继 |
| `webui/frontend/` | React 前端 |
| `output/` | 运行产出（日志、数据库、错误日志） |

## 关键模块说明

### gost 代理中继 (`webui/backend/gost_manager.py`)

- **启动时机**: WebUI 服务启动时自动调用 `ensure_gost_alive()`
- **触发条件**: `config.paypal.json` 的 `webshare.enabled=true` 且有 `api_key`
- **监听端口**: SOCKS5 (:18898) + HTTP (:18899)
- **代理链**: gost → [WSL Clash 7897] → Webshare 上游代理
- **自动检测**: WSL 环境下自动探测宿主机 Clash 作为链式代理

### ADB 设备检测 (`webui/backend/preflight/adb.py`)

- **WSL 自动探测**: 读取 `/etc/resolv.conf` 获取宿主机 IP
- **已知端口**: MuMu 6 (7555), MuMu 12 (16384/16416/16448/16480/5555/5557), Nox, LDPlayer, BlueStacks
- **自动连接**: `list_devices()` 无在线设备时自动尝试 `adb connect` 已知端口
- **端口转发**: WSL2 环境需 `netsh portproxy` 将 MuMu 端口从 localhost 转发到 0.0.0.0

### ADB OTP Provider (`CTF-pay/adb_otp_provider.py`)

- **设备验证**: IP:PORT 格式自动执行 `adb connect`
- **OTP 获取策略**:
  1. 通知栏 `dumpsys notification`（优先）
  2. UI 自动化 `uiautomator dump`（回退，延迟基线对比）
- **去重机制**:
  - 预扫描通知栏 OTP → `seen` 集合
  - 预扫描后**清除 WhatsApp 通知**（任何新通知必定是当前 OTP）
  - UI fallback 采用**基线对比策略**：第一次拍快照（`ui_seen`），后续找不在 `seen∪ui_seen` 中的新码
- **配置**: `config.paypal.json` → `gopay.otp.adb_serial`

### 无人值守容错 (`runner.py` + `pipeline.py`)

- **支付重试（pipeline 模式）**: `pipeline()` 中支付失败自动重试 3 次（同一账号，不重新注册）
- **支付重试（pay-only 模式）**: `pay_only()` 中支付失败同样自动重试 3 次（同一账号），每次生成全新 checkout session
- **midtrans 429 限流**: `LINK_429_RETRY_LIMIT=5`（10s/次），超过后立即失败交由 pipeline 重走完整支付流程
- **进程自动重启**: `runner.py` 子进程非零退出后 15s 自动重启
  - `stop()` 主动停止时不自动重启
  - 可配置 `max_restarts`（0=无限）
  - 状态 API 返回 `auto_restart` 和 `restart_count`
- **错误日志**: 所有异常写入 `output/error_logs/YYYY-MM-DD.jsonl`

### Pipeline 运行模式

| 模式 | 命令 | 行为 |
|------|------|------|
| single | 无额外参数 | 单次注册+支付 |
| batch | `--batch N` | N 次循环，错误不中断 |
| daemon | `--daemon` | 无限循环+智能冷却+IP轮换 |
| register_only | `--register-only` | 仅注册 |
| pay_only | `--pay-only` | 仅支付（复用已注册账号） |

## 当前配置要点

### 端口映射 (netsh portproxy)

```
0.0.0.0:16416 → 127.0.0.1:16416  (MuMu 12 实例 1)
0.0.0.0:5557  → 127.0.0.1:5557   (MuMu 12 ADB)
```

### 代理链路

```
card.py → socks5://127.0.0.1:18898 (gost)
  → [http://宿主机IP:7897 (Clash Verge)]
  → http://user:pass@proxy:port (Webshare)
```

## 最近变更记录

### 2026-05-06: gost 自动启动 + ADB 修复 + 无人值守容错

**变更文件**:

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `webui/backend/gost_manager.py` | gost 代理中继管理器 |
| 新建 | `webui/backend/runner_helpers.py` | 从 runner.py 提取的辅助函数 |
| 新建 | `error_logger.py` | 结构化错误日志 |
| 修改 | `webui/server.py` | 添加 lifespan 启动 gost |
| 修改 | `webui/backend/preflight/adb.py` | MuMu 12 端口 + 自动探测 |
| 修改 | `webui/backend/runner.py` | 自动重启 + 拆分辅助函数 |
| 修改 | `webui/backend/routes/run.py` | build_cmd 导入路径更新 |
| 修改 | `pipeline.py` | 支付重试 + 错误日志集成 |
| 修改 | `CTF-pay/adb_otp_provider.py` | 设备验证 + 日志去重 + 配置修复 |
| 修改 | `CTF-pay/config.paypal.json` | 添加 adb_serial 配置 |

**变更原因**:

1. gost 代理中继不会随 webui 启动 → 支付连不上代理
2. MuMu 12 ADB 端口 (16416) 绑 localhost → WSL 无法访问
3. 支付/注册失败直接崩溃 → 需要容错重试机制
4. ADB OTP 用错误的 serial (emulator-5554) → 通知轮询永远失败

### 2026-05-06: midtrans 429 重试上限调整 + pay-only 重试机制

**变更文件**:

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `CTF-pay/gopay.py` | `LINK_429_RETRY_LIMIT` 从 20 降为 3 |
| 修改 | `pipeline.py` | `pay_only()` + `pipeline()` 新增重试循环 + IP 轮换 |
| 修改 | `SYSTEM.md` | 同步更新文档 |

**变更原因**:

1. midtrans linking 429 重试上限调整为 5 次/10s 间隔（原 20 次/20s）
2. `pay_only()` 缺少重试循环，429 exhausted 后直接崩溃不会重走支付流程
3. 每次支付重试前自动调用 `_rotate_webshare_ip()` 获取新出口 IP（best-effort，失败不阻塞重试）
4. 修改后流程：429×5(50s) → GoPayError → PaymentError → 轮换IP → pay_only 重试(新checkout) → 最多 3 轮

### 2026-05-06: ADB OTP 获取逻辑重构

**变更文件**:

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `CTF-pay/adb_otp_provider.py` | OTP 轮询逻辑重构 |
| 修改 | `SYSTEM.md` | 同步更新文档 |

**变更原因**:

1. 预扫描阶段 `_dump_whatsapp_ui()` 打开 WhatsApp 到前台 → OTP 到达时不产生通知 → 通知轮询永远找不到
2. `notify_miss` 计数器在 dump 非空时重置为 0 → UI fallback 永远不触发
3. UI fallback 返回旧 OTP（聊天记录里的历史码未被 `seen` 过滤）

**修复方案**:

- 移除预扫描阶段的 UI dump，只预扫描通知栏
- 预扫描后清除 WhatsApp 通知，确保新通知是当前 OTP
- `notify_miss` 只要没找到新 OTP 就递增（不区分 dump 空/非空）
- UI fallback 采用基线对比策略：第一次只拍快照（`ui_seen`），后续才找新码
