# Proxy Logic Fix

## Root Cause

- `webui/server.py` used to call `ensure_gost_alive()` in FastAPI lifespan.
- That meant opening the WebUI service could query Webshare and start `gost` immediately.
- Registration/payment already has its own runtime hook in `pipeline.py` before account registration, so the WebUI startup hook was redundant and could waste Webshare traffic.
- The 18:18 log (`查询 Webshare IP 失败` + `无可用缓存代理`) happened because the current pay config has Webshare enabled and has an API key, but has no `webshare.last_proxy`, no `webshare.manual_proxy`, and no `webshare.api_proxy`. If the machine cannot reach `proxy.webshare.io` directly, the program cannot fetch the Webshare proxy username/password needed to start `gost`.
- Turning a local desktop proxy on/off did not help before because the main helper ignored environment proxy variables by default, and there was no explicit `webshare.api_proxy` path for the Webshare API lookup.

## Changed

- WebUI startup no longer starts Webshare/gost by default.
- Optional startup warm-up is now explicit: set `WEBUI_AUTOSTART_GOST=1` only when you really want WebUI boot to pre-start the relay.
- `pipeline.py` still starts/checks gost right before registration/payment flows, so proxy use is delayed until the account run begins.
- `pipeline.py` now mirrors the WSL host-IP detection logic used by ADB preflight, preferring the detected Windows host IP before the WSL gateway.
- `pipeline.py` now uses an 8s default Webshare API timeout and falls back to `webshare.last_proxy` when Webshare API lookup times out.
- `pipeline.py` and `webui/backend/gost_manager.py` now prefer `webshare.manual_proxy` or `webshare.last_proxy` before querying Webshare API. This lets `gost` start even when the Webshare API is temporarily unreachable.
- Successful Webshare API lookups are persisted into `webshare.last_proxy`, so the next run can start from cache if the API times out.
- Webshare API lookup now supports an explicit `webshare.api_proxy`, plus `WEBSHARE_API_PROXY` / `GPT_PAY_WEBSHARE_API_PROXY` environment overrides.
- If no explicit `api_proxy` is configured, the first Webshare API request still tries direct access. Only after that direct lookup fails does it retry the Webshare API through detected local/host proxy candidates. This keeps the default path low-traffic and avoids unnecessary Windows network probing.
- Webshare IP rotation (`_rotate_webshare_ip`) uses the same Webshare API proxy retry behavior.
- The WebUI Webshare test button now sends `api_proxy` to the backend preflight check.
- The wizard export now preserves existing `webshare.last_proxy` so re-exporting config does not discard a working cached proxy.
- `pipeline.py` now probes an existing local gost listener before reusing it; if `127.0.0.1:18898` is listening but the upstream cannot reach the internet, the relay is restarted.
- WSL host-proxy auto-detection is now opt-in with `GPT_PAY_AUTO_DETECT_HOST_PROXY=1`. This avoids repeatedly calling Windows network-interface enumeration and avoids accidentally chaining Webshare through a slow or wrong Windows proxy.
- Environment proxy variables are ignored by gost/Webshare helper code unless `GPT_PAY_USE_ENV_PROXY=1` is set explicitly.
- ADB/Windows host IP detection is cached for 300 seconds by default to reduce `iphlpsvc` CPU pressure.
- WebUI bind host/port can now be set via `WEBUI_HOST` and `WEBUI_PORT`; use `WEBUI_HOST=0.0.0.0` for direct LAN access from a bridged WSL address.
- `CTF-reg/browser_register.py` now logs the last outbound-IP lookup error type/message when geoip lookup fails, so failures like port closed, SOCKS support missing, or network timeout are visible.
- `webui/requirements.txt` now declares `requests[socks]` so new environments support `socks5h://` proxy checks.
- `webui/backend/gost_manager.py` comments were updated to say the relay starts on demand, not by default WebUI startup.
- Tests now override pytest temp paths to `output/pytest-tmp`, avoiding the Windows user Temp permission error seen on this machine.

## Current Intended Flow

1. Start WebUI: no Webshare API call, no gost auto-start, no billed Webshare traffic from startup.
2. Click/run registration/payment: `pipeline._ensure_gost_alive()` checks local listener and starts gost only if Webshare is enabled and the run needs it.
3. If `webshare.manual_proxy` or `webshare.last_proxy` exists, start `gost` from that proxy without calling Webshare API.
4. If no cached/manual proxy exists, query Webshare API. Direct access is tried first; if it times out and no explicit `api_proxy` is set, the API query retries through local/host proxy candidates.
5. Browser registration uses `socks5h://127.0.0.1:18898` from config to run through the local gost relay.

## Recommended Config

Best option for your current WSL + Windows setup:

```json
{
  "webshare": {
    "enabled": true,
    "api_proxy": "http://<windows-host-ip>:<local-proxy-port>"
  }
}
```

Use this only for querying Webshare API. It does not mean service startup or every request consumes Webshare traffic.

If you already know one Webshare proxy credential pair, you can bypass the API lookup entirely:

```json
{
  "webshare": {
    "enabled": true,
    "manual_proxy": {
      "proxy_address": "p.webshare.io",
      "port": 80,
      "username": "<webshare-username>",
      "password": "<webshare-password>",
      "country_code": "US"
    }
  }
}
```

Do not put secrets in source control. The real config file is ignored by git.

## Useful Checks

- If registration still logs `无法通过代理获取出口 IP`, check the appended error after that message.
- If the error says connection refused/timeout to `127.0.0.1:18898`, gost did not start or the port is wrong.
- If the error is `ConnectTimeout` to `icanhazip.com` through SOCKS, the local gost port is reachable but the upstream chain is not. Restarting the run now forces a relay egress probe and relaunches gost when needed.
- If the error is `查询 Webshare IP 失败` and then `无可用缓存代理`, confirm that at least one of these exists: `webshare.api_proxy`, `webshare.manual_proxy`, or `webshare.last_proxy`.
- If the error mentions missing SOCKS support, install the requests SOCKS dependency in the Python environment used by the registration subprocess.
- In WSL bridged mode, set `GPT_PAY_ADB_HOST_IP` or `WINDOWS_HOST_IP` if automatic Windows host IP detection chooses the wrong NIC.
- If Windows `iphlpsvc` stays high, stop auto host-proxy detection (`GPT_PAY_AUTO_DETECT_HOST_PROXY` unset) and prefer explicit overrides such as `GPT_PAY_ADB_HOST_IP`.
- For LAN access to WebUI from another machine, start with `WEBUI_HOST=0.0.0.0 python -m webui.server` and use the WSL bridged IP directly.

## Verification

- `python -m pytest -p no:cacheprovider webui/tests/test_preflight_webshare.py webui/tests/test_pipeline_proxy.py webui/tests/test_gost_manager.py`
- `python -m pytest -p no:cacheprovider webui/tests/test_server_startup.py webui/tests/test_browser_register_proxy.py webui/tests/test_preflight_adb.py webui/tests/test_config_writer.py`
