# refresh_token 重新获取逻辑修改说明

## 背景

运行日志显示，支付成功后重新登录获取 `refresh_token` 时，打开 Codex authorize URL 发生：

```text
Page.goto: NS_ERROR_NET_RESET
当前 URL: about:blank
邮箱填写失败: Page.wait_for_selector Timeout
```

原逻辑在 `page.goto()` 抛异常后只记录日志，然后继续等待邮箱输入框。若页面仍停留在 `about:blank`，后续等待邮箱框必然超时，最终表现为 `refresh_token 获取失败`。

## 修改点

修改文件：

- `CTF-pay/card.py`

具体修改：

1. 新增 `_rt_open_authorize_page(...)` helper。
   - 负责打开 Codex authorize URL。
   - 默认最多重试 3 次。
   - 每次失败会记录 `goto 异常(当前次数/总次数)`。
   - 每次导航后会记录当前 URL。
   - 如果 URL 已经离开 `about:blank`，即使 `goto` 曾抛异常，也认为页面可继续处理。
   - 如果多次尝试后仍停留在 `about:blank`，返回失败。

2. 修改 `_exchange_refresh_token_with_session(...)` 中的 authorize 打开流程。
   - 原来是单次 `page.goto(...)`，异常后继续执行。
   - 现在改为调用 `_rt_open_authorize_page(...)`。
   - 如果 authorize URL 多次打开失败，会保存 `/tmp/rt_authorize_blank.png` 截图并直接返回空字符串。
   - 这样可以避免后续错误地进入“邮箱填写失败”的分支。

## 新增点

新增测试文件：

- `webui/tests/test_card_refresh_token_navigation.py`

新增 3 个回归测试：

1. `NS_ERROR_NET_RESET` 后页面仍为 `about:blank`，第二次重试成功。
2. 连续 3 次失败且始终停留在 `about:blank`，helper 返回失败。
3. `goto` 抛异常但页面 URL 已进入 OpenAI 登录页时，helper 继续流程，不误判失败。

## 验证结果

已执行并通过：

```powershell
pytest -p no:cacheprovider webui/tests/test_card_refresh_token_navigation.py
python -m py_compile .\CTF-pay\card.py
```

其中新增导航测试结果为：

```text
3 passed
```

## 验证限制

尝试运行既有支付相关测试：

```powershell
pytest webui/tests/test_pipeline_pay_only.py
```

该测试未能完成，原因是当前环境对 pytest 临时目录创建或访问报：

```text
PermissionError: [WinError 5] 拒绝访问
```

这属于本地测试临时目录权限问题，不是本次修改造成的业务断言失败。
