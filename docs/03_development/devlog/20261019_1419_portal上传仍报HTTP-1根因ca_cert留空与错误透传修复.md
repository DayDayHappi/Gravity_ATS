# portal 上传仍报 HTTP -1 的根因修复：ca_cert 留空 + 错误透传诊断 bug

## 问题描述

方案 2-b 代码实施后，真机上传**仍然失败**：

```
[WARN] 结果上报失败（不影响测试结论）: 登记清单失败（重试 3 次）: HTTP -1: b''
```

## 根因分析（两个问题叠加）

1. **`ca_cert` 配置留空（主因）**：`system.yaml` 的 `ca_cert` 仍是 `""`（上一轮交付时
   犹豫证书路径本机特定、未填），导致 `_build_ssl_context` 返回 `None`，`urlopen` 依旧走
   系统默认校验 → 自签证书仍不被信任。**代码修复没有生效，不是代码错，是配置没接上。**

2. **诊断 bug（次因，掩盖真相）**：三个 retry helper（`_post_json_with_retry` /
   `_put_file_with_retry` / `_finalize_with_retry`）中，`except PortalUploadError` 把真实
   异常存进 `last_err` 后，紧接着被 `last_err = f"HTTP {status}: {body[:200]!r}"` 无条件覆盖，
   而 `status == -1` 时 body 恒为 `b""` → 真实 SSL 原因被吞成无意义的 `HTTP -1: b''`。
   用户每次只看到这行无用报错，无法定位「证书校验失败」。

## 修复内容

### 1. `ATS/application/portal_upload.py`
- `_resolve_from_project_root()`：先 `os.path.expanduser(path)` 展开 `~`，再判断绝对/相对。
  使 `ca_cert` 可配 `~/.config/ats-portal/portal.crt` 这种跨机器安全路径（不暴露具体用户名）。
- 三个 retry helper：`status == -1`（网络层错误）时**保留** `last_err` 里的
  `PortalUploadError` 真实原因，不再覆盖成 `HTTP -1: b''`。仅 `status != -1` 的临时错误
  才构造 `HTTP <status>: <body>` 描述。

### 2. `ATS/config/system.yaml`
- `ca_cert` 从 `""` 填为 `~/.config/ats-portal/portal.crt`（空 = 系统默认校验语义保留）。

### 3. `tests/test_portal_upload.py`
- 新增 `test_resolve_from_project_root_expands_tilde`（断言 `~` 展开 + 绝对路径）。
- 测试总数 10 → 11。

## 验证结果

- `python -m unittest tests.test_portal_upload`：**11/11 通过**。
- **真机端到端（真 token + 真证书 + 真 portal 10.1.64.183:8443）**：
  - 配 `~/.config/ats-portal/portal.crt` → `upload_state=complete: True` ✅
  - 故意空 `ca_cert` → 报错透传真实原因
    `网络错误: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate (_ssl.c:1010)>`
    （不再是 `HTTP -1: b''`）✅
- `ssl` 直连 portal 验证：证书 `CN=ats-portal-local`、主机名校验通过。

## 还会再有吗

- 已彻底闭环：真机验证通过 + 错误透传已修，后续再出问题能直接看到真实 SSL/网络原因。
- 注意 `~` 展开依赖运行账户的用户目录；若换机器需确保证书位于 `~/.config/ats-portal/portal.crt`。

## 经验沉淀

- **「错误吞并」是排查大敌**：网络层异常存进变量后，切不可用 `status` 分支再无条件覆盖；
  尤其 `status == -1` 这类兜底编码，body 恒空，会产出 `HTTP -1: b''` 这类零信息报错。
  覆盖前先判断 `status != -1`，保留真实异常。
- **配置开关 + 代码能力要一起交付**：只改代码不改配置，功能等于没上（`ca_cert` 留空 = 关闭）。
- 相对/用户级路径配置项，`expanduser` + 归一化到确定锚点，兼顾可移植与可调试。
