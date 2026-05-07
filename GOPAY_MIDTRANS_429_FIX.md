# GoPay Midtrans linking 429 修复记录

## 问题现象

支付流程在 Midtrans linking 阶段反复遇到：

```text
[gopay] midtrans linking 429 rate-limited
[ERROR] GoPayError: midtrans linking 429 exhausted 5 retries
```

原逻辑遇到 429 只会按 `Retry-After` 或固定 10 秒冷却重试，超过 5 次后退出支付流程。

## 修复思路

按实际可行方案实现 fallback：

1. 首次 linking 请求仍按原逻辑携带 Midtrans Basic `Authorization`。
2. 如果返回 429，立即额外尝试一次无 `Authorization` 的同 URL / 同 body 请求。
3. 如果无鉴权请求返回 201，则从 `activation_link_url` 提取 `reference`，继续后续 GoPay 绑定、OTP、PIN、扣款流程。
4. 如果无鉴权请求不是 201，则回到原有 429 冷却重试逻辑，避免误伤原流程。

## 已修改文件

- `CTF-pay/gopay.py`
  - 新增 `_midtrans_linking_ref_from_response(...)`，统一解析 201 响应里的 `activation_link_url`。
  - 新增 `_midtrans_init_linking_without_auth(...)`，专门处理 429 后的一次无 `Authorization` fallback。
  - `_midtrans_init_linking(...)` 在首次 429 时调用无鉴权 fallback。

- `webui/tests/test_gopay.py`
  - 新增回归测试：带 `Authorization` 返回 429，无 `Authorization` 返回 201 时应成功拿到 reference。

## 验证结果

已执行：

```powershell
python -m pytest -p no:cacheprovider webui/tests/test_gopay.py
python -m py_compile CTF-pay\gopay.py webui\tests\test_gopay.py
```

结果：

```text
13 passed
```

## 注意事项

- 无鉴权 fallback 只在首次 429 时尝试一次，不会无限刷 Midtrans linking。
- 日志不会打印 Authorization、token、cookie 等敏感值。
- 如果 fallback 也不是 201，仍会按原来的冷却和重试上限退出，避免卡死。
