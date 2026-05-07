# Webshare / gost 网络问题修复记录

## 问题现象

注册阶段持续出现：

```text
[browser-reg] 无法通过代理获取出口 IP，将跳过 geoip: ConnectTimeout ...
SOCKSHTTPSConnectionPool(host='icanhazip.com', port=443)
```

这表示注册模块能连到本地 SOCKS 代理端口，但本地 `gost` 中继的上游出口没有成功访问公网 IP 探测站点。

## 根因

WSL 里直连 Webshare upstream 时，`p.webshare.io` / `proxy.webshare.io` 的 DNS 或路由解析到了不可用地址，导致 `gost` 直连 Webshare upstream 超时。

本机验证发现，WSL 可以连通 Windows 宿主机上的本地代理 `192.168.0.2:7897`。因此正确链路应为：

```text
注册浏览器 / requests
  -> socks5h://127.0.0.1:18898
  -> gost
  -> http://192.168.0.2:7897
  -> Webshare upstream
  -> internet
```

## 已修改点

- `pipeline.py`
  - `gost` 启动支持 `webshare.gost_chain_proxy`。
  - 已存在 `18898` 监听时，会先探测实际出口；出口不可用则重拉 `gost`。
  - 出口 IP 探测改为多个 endpoint fallback，并优先尝试 HTTP endpoint，降低 HTTPS 探测超时影响。
  - Webshare API 查询支持显式 `api_proxy`，并保留 `last_proxy` 缓存。

- `webui/backend/gost_manager.py`
  - WebUI 侧 `gost` 管理同步支持 `gost_chain_proxy`。
  - Webshare 查询失败时可回退 `last_proxy` 缓存。

- `webui/backend/config_writer.py`
  - 向导导出配置时写入 `api_proxy` / `gost_chain_proxy`。
  - 重新导出时保留已有 `webshare.last_proxy`。

- `webui/frontend/src/components/steps/Step05_Proxy.vue`
  - 代理配置页增加 `api_proxy` 和 `gost_chain_proxy` 高级字段。
  - Webshare 测试按钮会把 `api_proxy` 传给后端预检。

- `CTF-reg/browser_register.py`
  - 注册前出口 IP 探测改为多个 endpoint fallback。
  - 代理出口 IP 探测失败时，Camoufox `geoip` 明确传 `False`，不再让内部 geoip 继续使用错误路径。
  - warning 会带最后一个异常类型，便于判断是端口不可达、SOCKS 依赖缺失还是上游超时。

- `CTF-pay/config.paypal.json`
  - 已增加 `webshare.gost_chain_proxy`，指向当前可达的 Windows 宿主机本地代理。
  - 该文件为本地真实配置，不应提交到仓库。

## 当前验证结果

在 WSL 内确认：

```text
18898 / 18899 已监听
gost 启动参数包含 -F=http://192.168.0.2:7897
192.168.0.2:7897 可连通
```

使用与注册模块相同的代理方式 `socks5h://127.0.0.1:18898` 探测 6 个出口 IP endpoint，结果全部返回 HTTP 200：

```text
http://api.ipify.org          OK
http://checkip.amazonaws.com  OK
http://icanhazip.com          OK
https://api.ipify.org         OK
https://checkip.amazonaws.com OK
https://icanhazip.com         OK
```

直接调用 `CTF-reg/browser_register.py` 里的 `_resolve_proxy_ip("socks5h://127.0.0.1:18898")`，结果为成功。

## 你需要配合确认的点

1. Windows 本地代理需要保持运行，并允许来自 WSL 桥接 IP 的连接。
2. 当前可达地址是 `192.168.0.2:7897`。如果 Windows IP 或代理端口变化，需要同步更新 `CTF-pay/config.paypal.json` 的 `webshare.gost_chain_proxy`。
3. 如果 WebUI / pipeline 是修改代码前启动的，已有长期运行进程不会自动加载新代码。等当前任务结束后，需要重启 WebUI 服务和正在跑的 pipeline 任务。
4. 如果重启后仍出现同样 warning，请先确认当前 `gost` 命令行里是否包含：

```text
-F=http://192.168.0.2:7897
```

并确认 `127.0.0.1:18898` 的出口探测是否成功。

## 不建议的配置

- 不建议依赖 WSL 网关 `192.168.0.1`，当前验证它不是可用的 Windows 代理地址。
- 不建议打开默认自动 host proxy 探测；之前 `iphlpsvc` CPU 占用高与频繁枚举/探测 Windows 网络接口有关。
- 不建议 WebUI 启动时就自动拉起 Webshare/gost。现在逻辑已改为注册/支付运行前才按需检查，避免无关场景消耗 Webshare 流量。

## 验证命令

已通过：

```powershell
python -m pytest -p no:cacheprovider webui/tests/test_browser_register_proxy.py webui/tests/test_pipeline_proxy.py webui/tests/test_gost_manager.py webui/tests/test_preflight_webshare.py
```

结果：

```text
32 passed
```
