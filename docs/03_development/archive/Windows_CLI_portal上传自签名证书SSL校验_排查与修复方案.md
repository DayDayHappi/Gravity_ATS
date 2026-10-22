# Windows CLI portal 上传自签名证书 SSL 校验失败 排查与修复方案

**日期**: 2026-10-19
**性质**: 脚本侧缺陷（`portal_upload.py` 未处理自签名 HTTPS 证书）+ 环境缺证书
**影响**: 测试结束后结果无法上报 ATS Portal，报 `登记清单失败（重试 3 次）: HTTP -1: b''`
**决策**: 方案 2-b（`upload.ca_cert` 配置项，`ssl.create_default_context(cafile=...)` 精准信任自签证书）

---

## 一、现象

Windows 下跑完 stress 后，上传阶段报：

```
开始上报 ATS Portal | scenario=stress execution_state=completed ...
上报失败（不影响测试结论）: 未读取到上传 token（...）   ← 第一阶段问题
```

token 配好后（工程根目录 `upload.token`），报错变为：

```
登记清单失败（重试 3 次）: HTTP -1: b''
```

`HTTP -1` 是 `portal_upload.py` `_post_json_with_retry` 里对 `PortalUploadError`（网络层）的兜底编码，
真实异常是 `urllib.error.URLError: SSLCertVerificationError(1, 'certificate verify failed: self-signed certificate')`。

---

## 二、根因（证据链）

1. **服务端正常**：`Test-NetConnection 10.1.64.183 -Port 8443` → `TcpTestSucceeded: True`。
2. **token 有效**：改用信任证书后，真实三步协议走通（登记 201 / PUT 200 / finalize 200，见第五节）。
3. **证书是自签名的**：`CN=ats-portal-local`，`subjectAltName` 含 `IP:10.1.64.183 / DNS:localhost / IP:127.0.0.1`，`NotAfter 2036`。
4. **脚本不处理证书**：`portal_upload.py` `_request()` L91 直接 `urllib.request.urlopen(req)`，未传 `context`，
   走 Python 默认 SSL 校验 → 自签证书不受信任 → `SSLCertVerificationError` → `URLError` → 重试 3 次 → `HTTP -1`。

`system.yaml` 配的是 `https://10.1.64.183:8443`（HTTPS + 非本机回环地址），但代码没有 HTTPS 证书处理能力，
「配置」与「代码能力」不匹配。协议文档 `ATS-Portal-Upload-Protocol-v1-20260929.md` L23 明言：
「配套上传工具只允许本机使用明文 HTTP，非本机地址要求 HTTPS」——本机门户用 HTTPS 自签证书属预期场景，脚本却未覆盖。

---

## 三、决策（已定案）

**方案 2-b**：新增 `upload.ca_cert` 配置，`ssl.create_default_context(cafile=...)` 只信任指定 CA（精准、可移植、不改全局安全策略）。

候选对比（已排除）：
- 2-a `verify_ssl: false`（全局禁用校验）：安全弱，弃。
- 2-c 证书装入 Windows 受信任根：环境操作，换机失效，弃。
- SSL_CERT_FILE 环境变量：不改代码但隐式、易漏配，仅作临时 workaround（见第五节）。

---

## 四、修复规格（供 Code Agent 实施）

### 4.1 `ATS/config/system.yaml`（upload 段新增一项）

```yaml
upload:
  enabled: true
  server: "https://10.1.64.183:8443"
  token_file: "upload.token"
  ca_cert: ""               # 自签名证书 PEM 路径（2-b）；空 = 走系统默认校验
  timeout: 60
  artifacts: [ ... ]        # 保持不变
```

### 4.2 `ATS/application/portal_upload.py`

1. 顶部 import 增加 `import ssl`。

2. `_read_token` 之后新增 helper：

```python
def _build_ssl_context(upload_cfg: dict):
    """按 upload.ca_cert 构建 SSL context；空返回 None（urlopen 默认校验）。"""
    ca_cert = upload_cfg.get("ca_cert", "").strip()
    if not ca_cert:
        return None
    return ssl.create_default_context(cafile=ca_cert)
```

3. `_request()` 增加 `ssl_ctx=None` 形参，`urlopen` 传 `context=ssl_ctx`：

```python
def _request(method, url, token, data=None, headers=None, timeout=60.0, ssl_ctx=None):
    ...
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
```

4. 三个 retry helper（`_post_json_with_retry` / `_put_file_with_retry` / `_finalize_with_retry`）
   均增加 `ssl_ctx` 形参并透传给 `_request`。

5. `upload_run()` 开头构建 `ssl_ctx = _build_ssl_context(upload_cfg)`，并传给三个 helper。

### 4.3 边界与测试

- `ca_cert` 支持**绝对路径**或相对工程根目录归一化（与 `token_file` 相对路径问题一并处理，见「附带隐患」）。
- 自签证书已导出至 `C:\Users\x-jwwang\.config\ats-portal\portal.crt`（本机），可直接填入 `ca_cert`。
- 单测：`tests/test_portal_upload.py` 增加 `ca_cert` 分支用例（空→None；有→context.cafile 断言）。
- 真机：配 `ca_cert` 后跑一次，确认 upload.log 走到 `登记清单成功 → 已上传 → upload_state=complete`。

---

## 五、已验证的临时 workaround（零代码，供 Code Agent 实施前先行可用）

已导出自签证书到 `C:\Users\x-jwwang\.config\ats-portal\portal.crt`，运行前设环境变量即可（`ssl.create_default_context` 默认读取 `SSL_CERT_FILE`）：

```powershell
$env:SSL_CERT_FILE = "$env:USERPROFILE\.config\ats-portal\portal.crt"
.\.venv-cli\Scripts\python.exe -m ATS.main --scenario stress --no-interactive-wifi
```

真 token 端到端验证已通过：登记 201 → PUT 200（verified=true）→ finalize 200（upload_state=complete）。

---

## 六、附带隐患（一并报告 Code Agent，非本轮主修）

`portal_upload.py` `_read_token()` L59-61 用 `upload_cfg.get("token_file")`，`system.yaml` 配的是相对路径
`"upload.token"`，`open()` 未归一化到工程根目录 → **随启动脚本时的 cwd 漂移**；且该值非空时「短路」掉
协议文档的标准默认路径 `~/.config/ats-portal/token`（后者永远不被尝试）。建议与 `ca_cert` 一并做路径归一化。

---

## 七、关联文档

- 分支状态：[05_handoff/windows_cli_status.md](../../05_handoff/windows_cli_status.md)（待办已挂）
- 上传协议：根目录 `ATS-Portal-Upload-Protocol-v1-20260929.md`（L23 HTTPS 边界、L33 默认 token 路径）
- 设计决策：[02_design/decision_record/ADR-017-测试结果上传Portal.md](../../02_design/decision_record/ADR-017-测试结果上传Portal.md)
- 源码：`ATS/application/portal_upload.py`（本问题需改此文件）
