# ATS Portal 脚本日志上传协议 v1

文档日期：2026-09-29。适用于当前已交付的 ATS Portal 本机版本；依据现有后端实现编写。

## 1. 接收能力与协议

**当前网站已具备接收脚本发送的日志、结构化测试报告和人工问题记录的能力。** 脚本无需把文件复制进网站目录，而是调用下列 HTTP 接口。

| 项目 | 当前约定 |
| --- | --- |
| 本机服务地址 | `http://127.0.0.1:8080`，以实际启动端口为准 |
| 传输协议 | HTTP，客户端可使用 HTTP/1.1 |
| API 前缀 | `/api/v1` |
| 清单和响应格式 | UTF-8 JSON |
| 文件传输格式 | 每个文件使用一次 PUT，请求体为文件原始二进制字节 |
| 上传鉴权 | `Authorization: Bearer <token>` |
| 文件完整性 | 文件字节数与 SHA-256 双重校验 |
| 归档流程 | 登记清单 → 上传所有文件 → 确认归档 |
| 当前能力边界 | 整文件归档；不提供日志追加、实时流式展示或文件分片断点续传接口 |

文件 PUT 的请求体不是 JSON、Base64 或 `multipart/form-data`。即使上传的是 `result.json`，也按文件原始字节上传。

当前 `scripts/start.sh` 监听 `127.0.0.1`，适用于 ATS 和网站运行在同一台 Ubuntu 的情况。其他电脑的 `127.0.0.1` 指向它自己，不能访问这台网站主机。跨机接入需另行配置可访问的入口、Host 白名单和 HTTPS；当前安装默认不提供外机入口。配套上传工具只允许本机使用明文 HTTP，非本机地址要求 HTTPS。

## 2. 鉴权与通用要求

所有上传请求都必须带：

```http
Authorization: Bearer <网站配置的上传 token>
```

默认 token 文件位于网站运行用户的：

```text
~/.config/ats-portal/token
```

安装程序创建凭据。若配置了 `ATS_PORTAL_TOKEN` 或 `ATS_PORTAL_TOKEN_FILE`，应使用服务实际采用的值。上传不需要先调用网页登录接口；网页登录 cookie 不能代替上传 Bearer token。不要将 token 写入日志或提交到代码仓库。

请求约定：

- 登记清单：`Content-Type: application/json`。
- 上传文件：`Content-Type: application/octet-stream`；建议发送与实际文件字节数一致的 `Content-Length`。
- `run_id` 和文件名作为 URL 路径片段时分别编码。文件名有中文、空格、`#`、`%` 等字符时，使用 UTF-8 百分号编码；Python 可用 `urllib.parse.quote(name, safe='')`。
- 请求来自普通 Python、curl 等脚本时无需发送 `Origin`；如发送了该头，必须与访问服务的协议、主机和端口一致，否则写请求返回 403。
- 先等待测试结束并关闭/刷新日志文件，再计算大小和摘要。登记后，待上传文件内容必须保持不变。

## 3. 接口总览

| 顺序 | 方法 | 路径 | 作用 |
| --- | --- | --- | --- |
| 可选 | GET | `/api/health` | 检查服务是否在线，无需鉴权 |
| 1 | POST | `/api/v1/runs` | 登记本次运行及全部文件清单 |
| 2 | PUT | `/api/v1/runs/{run_id}/artifacts/{name}` | 上传清单中的一个文件；对每个文件重复调用 |
| 3 | POST | `/api/v1/runs/{run_id}/finalize` | 检查文件齐全，解析报告，完成归档 |
| 可选 | GET | `/api/v1/runs/{run_id}` | 查询归档状态和各文件接收情况 |

**仅文件 PUT 成功还不代表本次运行归档成功。** 必须调用 finalize，并确认响应中的 `upload_state` 为 `complete`。

## 4. 第一步：登记清单

```http
POST /api/v1/runs
Authorization: Bearer <token>
Content-Type: application/json
```

### 4.1 请求字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `schema_version` | integer | 建议显式填写 | 当前仅支持 `1`，省略时默认 `1` |
| `run_id` | string | 是 | 本次测试的全局唯一标识；同一次归档重试复用此值 |
| `mode` | object | 是 | 压测模式，包含 `id`、`name` |
| `started_at` | string | 是 | 实际测试开始时间，ISO 8601，必须带时区 |
| `ended_at` | string / null | 否 | 实际结束时间；必须带时区且不早于开始时间；缺省为 null |
| `execution_state` | string | 否 | `completed` / `aborted` / `unknown`，缺省为 `unknown` |
| `source` | object | 否 | 字符串键值对，缺省 `{}`；可记录 host、device、firmware 等 |
| `artifacts` | array | 是 | 本次归档的全部文件，1～100 个 |

`run_id` 必须匹配 `[A-Za-z0-9][A-Za-z0-9_-]{0,95}`。例如 `ats-` 加 UUID 的十六进制文本。不能把包含斜杠的文件路径用作 run_id。

`mode.id` 长度为 1～160 字符，`mode.name` 为 1～200 字符；均不可为空白或含控制字符。模式可自由扩展，服务器没有固定模式枚举。新模式随第一次上报登记，保持同一模式的 ID 稳定即可。

`source` 最多 20 对，每个键最多 80 字符，每个值最多 500 字符；值应为字符串。

`execution_state` 描述测试流程是否完整结束：

| 值 | 含义 |
| --- | --- |
| `completed` | 流程正常结束；其中的用例仍然可能 FAIL |
| `aborted` | 测试中止 |
| `unknown` | 无法确认结束状态 |

顶层请求字段之外的额外字段会被拒绝。客户端应按本表构造清单。

### 4.2 artifacts 中每个文件的字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | 在本次归档中唯一的文件名，1～200 字符 |
| `kind` | string | 否 | `report` / `log` / `note` / `attachment`，缺省为 `log` |
| `size` | integer | 是 | 原始文件字节数，允许 0 |
| `sha256` | string | 是 | 原始文件 SHA-256，64 位小写十六进制 |

`name` 只能是单个文件名，不能是完整路径；禁止 `/`、反斜杠、控制字符，以及 `.`、`..`。不同目录中同名文件必须先确定不冲突的归档名称，再登记和上传。

| kind | 服务器处理方式 |
| --- | --- |
| `report` | 解析为 ATS 结构化报告；每次运行最多一份 |
| `log` | 保存原始日志，提供阅读、搜索与下载 |
| `note` | 文本作为人工问题记录参与分类 |
| `attachment` | 保存附件，提供下载；不解析为测试报告 |

文件用途由 `kind` 决定，不由扩展名决定。若 `result.json` 要生成用例结果，必须标记为 `report`。

服务器接收的是清单中的文件，不会扫描客户端目录或自动排除媒体目录。脚本可只登记 `run.log`、`serial.log`、`power_switch.log`、`recovery.log` 和报告，忽略 `photos/`、`videos/` 等内容。也不需要把整个运行目录打包成 ZIP。

### 4.3 最小清单示例

以下示例只登记一个日志。该文件的精确内容为 UTF-8 的 `ATS upload demo` 加一个 LF 换行，共 16 字节。对自己的日志，必须重新计算 size 和 sha256。

```json
{
  "schema_version": 1,
  "run_id": "ats-protocol-example-001",
  "mode": {"id": "recovery_validation", "name": "恢复验证"},
  "started_at": "2026-09-29T13:00:00+08:00",
  "ended_at": "2026-09-29T13:10:00+08:00",
  "execution_state": "completed",
  "source": {"host": "ubuntu", "device": "EVB-01"},
  "artifacts": [
    {
      "name": "run.log",
      "kind": "log",
      "size": 16,
      "sha256": "b8deda45a26146c177cb46353e7252f912c36d2bb0836683a8bf2369ae2ccbc5"
    }
  ]
}
```

只传日志也是合法归档。由于没有结构化报告，网站不能从日志猜测用例 PASS/FAIL；此例最终测试状态为 `UNKNOWN`，并提示结果不完整，但日志仍可阅读和下载。

### 4.4 登记响应

首次登记返回 **201 Created**。同 run_id、相同清单再次登记返回 **200 OK**。示例：

```json
{
  "run_id": "ats-protocol-example-001",
  "upload_state": "receiving",
  "status": "UNKNOWN",
  "summary": {"total": 0, "passed": 0, "failed": 0, "errored": 0, "skipped": 0, "unknown": 0, "case_elapsed_ms": 0}
}
```

同 run_id 但清单内容不同返回 **409 Conflict**。字段、文件数组顺序和文件摘要应在重试时保持一致；应持久化原清单，而不是重试时重新生成时间或 run_id。已完成的运行再次登记时，响应可能直接是 `upload_state: complete`。

## 5. 第二步：上传文件

对清单中的每个文件执行：

```http
PUT /api/v1/runs/{run_id}/artifacts/{编码后的文件名}
Authorization: Bearer <token>
Content-Type: application/octet-stream
Content-Length: <原始文件字节数>

<文件原始字节>
```

服务器流式接收请求体，计算大小和 SHA-256；两者均符合清单后才将文件正式落盘。上传时不要添加表单包装、编码为 Base64、转换换行或移除日志中的 ANSI 字符。

成功返回 **200 OK**：

```json
{"name": "run.log", "size": 16, "verified": true}
```

文件必须已在清单中登记，否则返回 404。字节数或摘要不符返回 422。上传中断后重试整个文件 PUT；不使用 `Content-Range` 或 offset 续传。同一已登记文件可用相同原始字节重复上传。

## 6. 第三步：确认归档

所有文件上传成功后调用：

```http
POST /api/v1/runs/{run_id}/finalize
Authorization: Bearer <token>
Content-Length: 0
```

无需请求 JSON。服务器同步检查文件齐全、解析报告、生成问题分类并提交归档。成功返回 **200 OK**，响应字段与登记回执相同，`upload_state` 变为 `complete`。

例如，一份含一条 PASS 结果、耗时 1000 ms 的报告归档后：

```json
{
  "run_id": "ats-your-run-id",
  "upload_state": "complete",
  "status": "PASS",
  "summary": {"total": 1, "passed": 1, "failed": 0, "errored": 0, "skipped": 0, "unknown": 0, "case_elapsed_ms": 1000}
}
```

必须分别理解两种状态：

- `upload_state` 是归档状态：`receiving` 或 `complete`。
- `status` 是测试状态，可能为 `PASS`、`FAIL`、`ERROR`、`SKIP`、`ABORTED`、`UNKNOWN`。返回 `FAIL` 不表示上传失败。

缺少清单文件时返回 409，不能当作成功。报告内容不合法时可能返回 422；读取解析大小超限时返回 413。重复 finalize 是幂等的，不会重复生成问题记录。

## 7. 结构化报告 result.json

如需网站展示用例结果、轮次、重复次数和问题分类，应在清单中加入一份 `kind: report` 的 JSON 文件，并像日志一样 PUT 原始字节。

最小可用报告示例：

```json
{
  "results": [
    {
      "name": "video[3k]",
      "module": "video",
      "scenario": "recovery_validation",
      "cycle": 2,
      "rep": 3,
      "status": "FAIL",
      "elapsed_ms": 3000,
      "timestamp": "2026-09-29T13:05:00+08:00",
      "message": "未收到录像完成信号",
      "detail": "TT ERROR camera"
    }
  ],
  "recovery_events": []
}
```

| 字段 | 建议发送的类型 / 含义 |
| --- | --- |
| `results` | 必须是数组；每一项必须是对象 |
| `name`、`module`、`scenario` | 字符串：结果名称、模块名称、场景名称 |
| `cycle` | 非负整数：第几轮；正常从 1 开始，0 表示未标注 |
| `rep` | 非负整数：当前测试项第几次重复；正常从 1 开始，0 表示未标注 |
| `status` | 字符串：使用大写 `PASS`、`FAIL`、`ERROR`、`SKIP`；缺失或未知值会提示待确认 |
| `elapsed_ms` | 非负整数，耗时毫秒 |
| `timestamp` | 结果时间字符串；不会替代清单的 started_at / ended_at |
| `message`、`detail` | 字符串：简要说明与详细记录 |
| `recovery_events` | 可选，对象数组；可记录 task、cycle、rep、reason、recovery_result 等恢复信息 |

除 results 的结构要求外，单条结果字段可省略，但缺失会影响展示精度。当前适配器将缺失文本归一为空字符串、缺失状态归一为 UNKNOWN、缺失 cycle/rep/elapsed_ms 归一为 0。客户端应显式提供真实值。

`rep` 不是配置中第几个测试项。当前协议没有正式的 YAML task ID/序号字段；网页测试项编号根据报告中的首次出现顺序生成。不要在 rep 中填配置项编号。

服务器从 results 重新统计结果，不直接信任报告中额外提供的 summary。问题分类与原始判定独立：PASS 记录如果命中问题规则，仍会关联问题。当前不会自动扫描全部原始日志来生成用例结果或分类。

## 8. 查询上传结果

```http
GET /api/v1/runs/{run_id}
Authorization: Bearer <token>
```

默认读取接口无需鉴权，但脚本统一携带 Bearer 可兼容开启读取鉴权的部署。响应包含运行详情、`upload_state`、`status`、`summary`、`results`、`issues`、`artifacts` 等。每个 artifact 还包含 `received`，便于判断哪些文件尚需补传。

需要核对原文件时，可调用：

```http
GET /api/v1/runs/{run_id}/artifacts/{编码后的文件名}/download
Authorization: Bearer <token>
```

该接口返回保存的原始字节。收到 finalize 的成功回执后，网页刷新即可看到归档结果。

## 9. 大小限制与错误处理

### 9.1 当前默认限制

| 对象 | 限制 |
| --- | --- |
| 登记请求 JSON | 256 KiB |
| 单次运行文件数 | 1～100 个，名称不能重复 |
| 单个文件 | 512 MiB；可用 `ATS_PORTAL_MAX_FILE_MB` 调整 |
| 单次运行文件总大小 | 2 GiB；可用 `ATS_PORTAL_MAX_RUN_MB` 调整，默认 2048 MiB |
| 结构化 report | 最多 1 份，默认最多 16 MiB |
| 单个 note | 解析上限 1 MiB，在 finalize 阶段检查 |

这里的大小均为原始文件字节数；1 MiB = 1024 × 1024 字节。改变服务配置后，以实际服务限制为准。

### 9.2 状态码

业务错误响应通常形如：

```json
{"detail": "尚缺文件：serial.log"}
```

| 状态码 | 含义 | 客户端处理 |
| --- | --- | --- |
| 200 / 201 | 请求成功 | 检查响应内容后进入下一步 |
| 400 | 例如 Host 白名单不允许 | 核对访问地址及部署配置；响应不一定是 JSON |
| 401 | token 缺失或不正确 | 修正凭据后再试 |
| 403 | 跨源写入被拒绝 | 核对 Origin；普通脚本通常无需该头 |
| 404 | 运行不存在，或文件未登记 | 先登记运行，核对 run_id 和文件名 |
| 409 | 清单冲突或 finalize 缺文件 | 根据 detail 区分；缺文件则补传，清单变更需新 run_id |
| 413 | 超出大小限制 | 调整内容或服务允许的限制；相同输入不应盲目重试 |
| 422 | 参数、文件校验或报告结构错误 | 修正原因；已登记的清单和文件内容需改变时，新建 run_id |
| 507 | 本机存储错误 | 修复磁盘空间或权限后重试 |
| 网络超时、408、429、其他 5xx | 连接或临时服务错误 | 有限次数退避重试，继续复用本次清单和 run_id |

客户端先检查 HTTP 状态，再解析响应。服务器框架或代理的错误不一定遵循统一 JSON 格式。

重试规则：

1. 一次测试只生成一次 run_id，保存清单、文件稳定副本和上传进度。
2. 登记超时：用原清单再次 POST；相同清单幂等。
3. 文件上传超时：用原文件完整重发同一个 PUT；也可先查询详情。
4. finalize 超时：重复调用 finalize，或查询 upload_state。响应丢失不等于归档失败。
5. 清单确定后不可新增、删除或修改文件。确需改变本次资料时，使用新 run_id；这会成为另一条归档记录。
6. 只有确认 upload_state=complete 才标记“已上报”。上传失败不应改写 ATS 本身的测试结论。

配套 `tools/ats_upload.py` 已实现此流程：单次请求默认超时 60 秒，临时错误最多尝试 3 次，两次等待分别为 1 秒和 2 秒。自建客户端可选择自己的合理超时及重试策略。

## 10. 可运行的 curl 协议示例

此示例在本机临时目录生成一份演示日志和一份 PASS 报告，按真实文件计算清单，然后完成三步上传。**执行后会新增一条名为“协议上传示例”的演示运行，不是你的真实 ATS 测试。** 需要网站已启动，系统有 Python 3 和 curl。

示例没有依赖网站配套的上传脚本，可用于验证其他脚本应该如何调用 HTTP 接口。默认读取本机安装生成的 token；如果地址或 token 路径不同，可先设置 `ATS_UPLOAD_SERVER`、`ATS_UPLOAD_TOKEN_FILE`。

```bash
(
  set -euo pipefail
  ATS_UPLOAD_SERVER="${ATS_UPLOAD_SERVER:-http://127.0.0.1:8080}"
  ATS_UPLOAD_TOKEN_FILE="${ATS_UPLOAD_TOKEN_FILE:-$HOME/.config/ats-portal/token}"
  ATS_UPLOAD_TOKEN="$(cat "$ATS_UPLOAD_TOKEN_FILE")"
  ATS_UPLOAD_DIR="$(mktemp -d)"
  ATS_UPLOAD_RUN_ID="ats-protocol-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"

  python3 - "$ATS_UPLOAD_DIR" "$ATS_UPLOAD_RUN_ID" <<'PY'
import datetime
import hashlib
import json
import sys
from pathlib import Path

folder, run_id = Path(sys.argv[1]), sys.argv[2]
stamp = datetime.datetime.now().astimezone().isoformat()
(folder / "run.log").write_bytes(b"ATS upload demo\n")
report = {"results": [{"name": "protocol-check", "module": "demo",
    "scenario": "protocol-demo", "cycle": 1, "rep": 1, "status": "PASS",
    "elapsed_ms": 1000, "message": "协议演示记录"}], "recovery_events": []}
(folder / "result.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
artifacts = []
for name, kind in [("run.log", "log"), ("result.json", "report")]:
    path = folder / name
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    artifacts.append({"name": name, "kind": kind, "size": path.stat().st_size,
                      "sha256": digest.hexdigest()})
manifest = {"schema_version": 1, "run_id": run_id,
    "mode": {"id": "protocol-demo", "name": "协议上传示例"},
    "started_at": stamp, "ended_at": stamp, "execution_state": "completed",
    "source": {"host": "protocol-demo"}, "artifacts": artifacts}
(folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
PY

  printf '本次运行：%s\n清单位置：%s/manifest.json\n' "$ATS_UPLOAD_RUN_ID" "$ATS_UPLOAD_DIR"

  # 1. 登记：清单内容是 JSON。
  curl --fail-with-body --silent --show-error \
    -X POST "$ATS_UPLOAD_SERVER/api/v1/runs" \
    -H "Authorization: Bearer $ATS_UPLOAD_TOKEN" \
    -H 'Content-Type: application/json' \
    --data-binary "@$ATS_UPLOAD_DIR/manifest.json"

  # 2. 文件：每个请求体只放该文件的原始字节。
  for ATS_UPLOAD_NAME in run.log result.json; do
    curl --fail-with-body --silent --show-error \
      -X PUT "$ATS_UPLOAD_SERVER/api/v1/runs/$ATS_UPLOAD_RUN_ID/artifacts/$ATS_UPLOAD_NAME" \
      -H "Authorization: Bearer $ATS_UPLOAD_TOKEN" \
      -H 'Content-Type: application/octet-stream' \
      --data-binary "@$ATS_UPLOAD_DIR/$ATS_UPLOAD_NAME"
  done

  # 3. 归档：应返回 upload_state=complete、status=PASS。
  curl --fail-with-body --silent --show-error \
    -X POST "$ATS_UPLOAD_SERVER/api/v1/runs/$ATS_UPLOAD_RUN_ID/finalize" \
    -H "Authorization: Bearer $ATS_UPLOAD_TOKEN"
)
```

示例固定使用两个 ASCII 文件名，所以 URL 无需额外编码；真实客户端必须遵守第 2 节的路径编码规则。失败重试时复用已打印的运行 ID 和清单；完整重新执行此演示会生成新的 ID 和新记录。

将此流程接入 ATS 时，由 ATS 提供本次真实开始/结束时间、模式和待上传文件路径；协议不要求日志与报告位于客户端的同一个目录。脚本可以在任何工作目录运行，只需读取到对应文件，并能连接网站服务。

## 11. 实现依据与适配边界

本文件对应 ATS Portal 源码提交 `fd393fc8eb2f43016dafc1f360c5593d47887773` 中的现有上传接口，协议版本为 1。核对依据：`ats_portal/web.py`、`models.py`、`service.py`、`storage.py`、`repository.py`、`adapter.py`、`config.py`、`scripts/start.sh` 和 `tools/ats_upload.py`。

这是一份现有接收协议说明，不需要为了采用本文流程再修改网站后端。发送端只要遵守清单、文件校验、Bearer 鉴权和 finalize 顺序，即可自行实现上传。
