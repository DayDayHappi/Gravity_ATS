"""ATS Portal 结果上报（ADR-017）。

运行结束后，把本次运行结果（4 个 log + result.json）通过三步 HTTP 协议上传 ATS Portal：

1. ``POST /api/v1/runs``：登记清单（schema_version/run_id/mode/时间/execution_state/
   source/artifacts，含每文件 size + sha256）。
2. 对每个存在的文件 ``PUT /api/v1/runs/{run_id}/artifacts/{quote(name, safe='')}``：
   ``Content-Type: application/octet-stream``，请求体 = 文件原始字节。
3. ``POST /api/v1/runs/{run_id}/finalize``：确认归档，响应 ``upload_state == "complete"``
   才算成功。

只依赖标准库 ``urllib``（不引入第三方 HTTP 库）。协议唯一来源：根目录
``ATS-Portal-Upload-Protocol-v1-20260929.md``——协议常量（路径/头/字段名）集中在本
模块，业务不内联 URL/头（ADR-011 精神：协议单一来源）。

红线（ADR-017 §6）：
- 上传失败只 ``logger.warn`` 留痕，不改写 ATS 测试结论、不影响退出码。
- token 不写日志、不进仓库（协议 §2）。
- 懒加载文件（power_switch.log / recovery.log）不存在时跳过，登记时只登记实际存在的文件。
- 临时错误（网络超时/5xx/408/429）有限退避重试，复用同一 run_id 与清单。
"""
import datetime
import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from ..core import logger

# token 默认路径（协议 §2）
_DEFAULT_TOKEN_FILE = os.path.expanduser("~/.config/ats-portal/token")

# 工程根目录（本文件 ATS/application/portal_upload.py 向上三级），
# 用于把 token_file / ca_cert 相对路径归一化到工程根，避免随启动 cwd 漂移。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# API 前缀（协议 §1）
_API_PREFIX = "/api/v1"

# 临时错误重试（协议 §9.2 规则 + 配套工具 ats_upload.py：默认超时 60s，最多 3 次，
# 退避 1s / 2s）
_RETRY_MAX = 3
_RETRY_BACKOFF = (1.0, 2.0)

# 可重试的 HTTP 状态码（协议 §9.2）
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504, 507}


class PortalUploadError(Exception):
    """上传过程中的业务/不可重试错误。"""


def _resolve_from_project_root(path: str) -> str:
    """把相对路径归一化到工程根目录；``~`` 展开为用户主目录；绝对路径原样返回。

    token_file / ca_cert 在 system.yaml 配的相对路径（如 ``upload.token``）随启动
    cwd 漂移，统一锚定工程根（见排查文档「附带隐患」）；``~/.config/...`` 这类
    用户级路径先 expanduser（跨机器可移植，不暴露具体用户名）。
    """
    if not path:
        return path
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.join(_PROJECT_ROOT, path)


def _read_token(upload_cfg: dict) -> str:
    """读取上传 token（优先级：ATS_PORTAL_TOKEN → ATS_PORTAL_TOKEN_FILE →
    token_file 配置 → 默认 ~/.config/ats-portal/token）。不写日志。"""
    env_token = os.environ.get("ATS_PORTAL_TOKEN", "").strip()
    if env_token:
        return env_token
    token_file = (os.environ.get("ATS_PORTAL_TOKEN_FILE", "").strip()
                  or upload_cfg.get("token_file", "").strip()
                  or _DEFAULT_TOKEN_FILE)
    token_file = _resolve_from_project_root(token_file)
    try:
        with open(token_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _build_ssl_context(upload_cfg: dict):
    """按 upload.ca_cert 构建 SSL context；空返回 None（urlopen 默认系统校验）。

    方案 2-b：``ssl.create_default_context(cafile=...)`` 只信任指定自签证书，
    不全局禁用校验；相对路径归一化到工程根。
    """
    ca_cert = (upload_cfg.get("ca_cert") or "").strip()
    if not ca_cert:
        return None
    ca_cert = _resolve_from_project_root(ca_cert)
    return ssl.create_default_context(cafile=ca_cert)


def _sha256_size(path: str) -> tuple:
    """计算文件 SHA-256（64 位小写 hex）与字节数。"""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _request(method: str, url: str, token: str, data: bytes = None,
             headers: dict = None, timeout: float = 60.0, ssl_ctx=None) -> tuple:
    """发一个带 Bearer 的 HTTP 请求，返回 (status, body_bytes)。

    data 为 None 时不带请求体（GET / finalize 用 Content-Length: 0 时传 b""）。
    ssl_ctx 为 None 时走 urlopen 默认系统校验；非 None 时用指定 SSL context
    （方案 2-b：``ssl.create_default_context(cafile=...)`` 信任自签证书）。
    """
    req_headers = {"Authorization": f"Bearer {token}"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        return e.code, body
    except urllib.error.URLError as e:
        raise PortalUploadError(f"网络错误: {e}") from e


def _is_retryable(status: int) -> bool:
    return status in _RETRYABLE_STATUS


def _post_json_with_retry(url: str, token: str, payload: dict,
                          timeout: float, ssl_ctx=None) -> dict:
    """POST JSON（登记清单），临时错误退避重试并复用原清单。返回解析后的响应 dict。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    last_err = None
    for attempt in range(1, _RETRY_MAX + 1):
        try:
            status, body = _request("POST", url, token, data=data,
                                    headers=headers, timeout=timeout, ssl_ctx=ssl_ctx)
        except PortalUploadError as e:
            last_err = e
            status = -1
            body = b""
        if status in (200, 201):
            try:
                return json.loads(body.decode("utf-8") or "{}")
            except Exception:
                return {}
        if _is_retryable(status) or status == -1:
            # status == -1 是网络层错误（如 SSL 校验失败）：last_err 已是
            # PortalUploadError（含真实原因），不要覆盖成无意义的 "HTTP -1: b''"。
            if status != -1:
                last_err = f"HTTP {status}: {body[:200]!r}"
            if attempt < _RETRY_MAX:
                time.sleep(_RETRY_BACKOFF[attempt - 1] if attempt - 1 < len(_RETRY_BACKOFF) else 2.0)
                continue
            raise PortalUploadError(f"登记清单失败（重试 {_RETRY_MAX} 次）: {last_err}")
        # 非临时错误（400/401/403/404/409/413/422）：不盲目重试
        raise PortalUploadError(f"登记清单失败 HTTP {status}: {body[:200]!r}")
    raise PortalUploadError(f"登记清单失败: {last_err}")


def _put_file_with_retry(url: str, token: str, path: str, size: int,
                         timeout: float, ssl_ctx=None) -> None:
    """PUT 单个文件（原始字节），临时错误退避重试（完整重发同一 PUT）。"""
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(size),
    }
    with open(path, "rb") as f:
        file_bytes = f.read()

    last_err = None
    for attempt in range(1, _RETRY_MAX + 1):
        try:
            status, body = _request("PUT", url, token, data=file_bytes,
                                    headers=headers, timeout=timeout, ssl_ctx=ssl_ctx)
        except PortalUploadError as e:
            last_err = e
            status = -1
            body = b""
        if status == 200:
            return
        if _is_retryable(status) or status == -1:
            if status != -1:
                last_err = f"HTTP {status}: {body[:200]!r}"
            if attempt < _RETRY_MAX:
                time.sleep(_RETRY_BACKOFF[attempt - 1] if attempt - 1 < len(_RETRY_BACKOFF) else 2.0)
                continue
            raise PortalUploadError(f"上传文件失败（重试 {_RETRY_MAX} 次）: {last_err}")
        raise PortalUploadError(f"上传文件失败 HTTP {status}: {body[:200]!r}")
    raise PortalUploadError(f"上传文件失败: {last_err}")


def _finalize_with_retry(url: str, token: str, timeout: float, ssl_ctx=None) -> dict:
    """POST finalize（无请求体），临时错误退避重试。返回解析后的响应 dict。"""
    last_err = None
    for attempt in range(1, _RETRY_MAX + 1):
        try:
            status, body = _request("POST", url, token, data=b"", timeout=timeout,
                                    ssl_ctx=ssl_ctx)
        except PortalUploadError as e:
            last_err = e
            status = -1
            body = b""
        if status == 200:
            try:
                return json.loads(body.decode("utf-8") or "{}")
            except Exception:
                return {}
        if _is_retryable(status) or status == -1:
            if status != -1:
                last_err = f"HTTP {status}: {body[:200]!r}"
            if attempt < _RETRY_MAX:
                time.sleep(_RETRY_BACKOFF[attempt - 1] if attempt - 1 < len(_RETRY_BACKOFF) else 2.0)
                continue
            raise PortalUploadError(f"finalize 失败（重试 {_RETRY_MAX} 次）: {last_err}")
        raise PortalUploadError(f"finalize 失败 HTTP {status}: {body[:200]!r}")
    raise PortalUploadError(f"finalize 失败: {last_err}")


def _resolve_artifact_path(name: str, kind: str, log_dir: str, report_dir: str) -> str:
    """按 kind 解析文件绝对路径：report → report_dir；其余 → log_dir。"""
    base = report_dir if kind == "report" else log_dir
    return os.path.join(base, name)


def upload_run(upload_cfg: dict, scenario_name: str, log_dir: str, report_dir: str,
               started_at: str, ended_at: str, execution_state: str) -> bool:
    """执行三步上传协议，返回是否成功（upload_state == complete）。

    Args:
        upload_cfg: system.yaml 的 upload 段（含 enabled/server/token_file/ca_cert/timeout/artifacts）。
        scenario_name: 场景名（mode.id / mode.name）。
        log_dir: 日志目录（run.log/serial.log/power_switch.log/recovery.log 所在）。
        report_dir: 报告目录（result.json 所在）。
        started_at / ended_at: ISO 8601 带时区字符串。
        execution_state: completed / aborted。

    Returns:
        True 表示归档成功（finalize 响应 upload_state == "complete"）。
        任何失败抛 PortalUploadError（由 main 捕获后 warn，不改写测试结论）。
    """
    server = upload_cfg.get("server", "http://127.0.0.1:8080").rstrip("/")
    timeout = float(upload_cfg.get("timeout", 60))
    artifacts_cfg = upload_cfg.get("artifacts", [])

    # 方案 2-b：upload.ca_cert 非空时只信任指定自签证书，否则走系统默认校验
    ssl_ctx = _build_ssl_context(upload_cfg)

    token = _read_token(upload_cfg)
    if not token:
        raise PortalUploadError("未读取到上传 token（检查 ATS_PORTAL_TOKEN / token_file）")

    # 收集实际存在的文件（懒加载缺失则跳过），计算 size + sha256
    run_id = "ats-" + uuid.uuid4().hex
    artifacts = []
    for item in artifacts_cfg:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        kind = item.get("kind", "log")
        path = _resolve_artifact_path(name, kind, log_dir, report_dir)
        if not os.path.isfile(path):
            # 懒加载文件不存在：跳过（ADR §3 / TC-UP-005）
            logger.log_upload(f"跳过缺失文件: {name}")
            continue
        sha256, size = _sha256_size(path)
        artifacts.append({"name": name, "kind": kind, "size": size, "sha256": sha256})

    if not artifacts:
        raise PortalUploadError("无可上传文件（清单为空或全部缺失）")

    logger.log_upload(f"run_id={run_id} | 待上传 {len(artifacts)} 个文件: "
                      f"{[a['name'] for a in artifacts]}")

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": {"id": scenario_name, "name": scenario_name},
        "started_at": started_at,
        "ended_at": ended_at,
        "execution_state": execution_state,
        "source": {},
        "artifacts": artifacts,
    }

    # 1. 登记清单
    _post_json_with_retry(f"{server}{_API_PREFIX}/runs", token, manifest, timeout, ssl_ctx)
    logger.log_upload("登记清单成功（POST /runs）")

    # 2. 逐个上传文件
    for art in artifacts:
        name = art["name"]
        path = _resolve_artifact_path(name, art["kind"], log_dir, report_dir)
        encoded_name = urllib.parse.quote(name, safe="")
        put_url = f"{server}{_API_PREFIX}/runs/{run_id}/artifacts/{encoded_name}"
        _put_file_with_retry(put_url, token, path, art["size"], timeout, ssl_ctx)
        logger.log_upload(f"已上传: {name}（{art['size']} bytes）")

    # 3. finalize，确认 upload_state == complete
    resp = _finalize_with_retry(f"{server}{_API_PREFIX}/runs/{run_id}/finalize",
                                token, timeout, ssl_ctx)
    state = resp.get("upload_state")
    logger.log_upload(f"finalize 响应 upload_state={state}")
    return state == "complete"
