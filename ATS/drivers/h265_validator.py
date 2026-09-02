"""H.265 码流完整性检测 Driver（PC 端 FFmpeg 诊断）。

职责边界（对应需求文档 §3）：
- 只负责「怎么测本地 H.265 文件」：FFmpeg 子进程管理 + 三阶段诊断 + 结构化结果。
- **不感知** Scenario / Runner / normal / stress / FTP / 串口 / Context；
- **不直接生成** ``TestResult``（映射到 status 是 module 层的事）。

三阶段诊断（需求 §8 / §20.2）：
  Stage 0  文件预检查（存在/普通文件/大小/扩展名/可读）
  Stage 1  全文件 decode（``-v error -err_detect explode``）→ PASS 则结束
  Stage 2  showinfo 定位（仅 Stage1 失败）→ 失败时间轴 + 最后成功 decoded frame
  Stage 3  trace_headers 码流分析（仅 Stage1 失败且支持）→ POC gap 高置信判定

安全/内存要求（§14）：
- 所有 FFmpeg 调用使用 argv list，**无 shell=True**；
- showinfo / trace_headers 海量日志**直接写文件**，Python 按行解析，绝不整段载入内存；
- 所有调用带 timeout，超时后 ``kill`` + ``wait`` 回收，**不留僵尸进程**；
- 路径含空格 / 中文 / 特殊字符由 argv list 天然保证。

POC gap 判定（§9，不要造假精度）：
- 固定 GOP 产品下 POC LSB 序列（去重后）严格分段 +1 递增，回退只发生在 GOP 边界；
- 只有「前进跳过且缺失值从未在文件中出现」时才高置信报 ``MISSING_PICTURE``；
- 无法高置信重建时退化为 ``REFERENCE_CHAIN_ERROR`` / decoder 级分类，绝不硬算全局索引。
"""
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Optional

from ..core import logger

# ---------------------------------------------------------------------------
# 错误分类（需求 §10 + §20.2 补充）
# ---------------------------------------------------------------------------
PASS = "PASS"
TOOL_NOT_FOUND = "TOOL_NOT_FOUND"          # ffmpeg 不存在
INPUT_NOT_FOUND = "INPUT_NOT_FOUND"        # 指定文件不存在
INPUT_NOT_READABLE = "INPUT_NOT_READABLE"  # 文件存在但不可读
INVALID_INPUT = "INVALID_INPUT"            # 非普通文件 / 大小 0 / 扩展名不匹配
NO_MATCHING_VIDEO = "NO_MATCHING_VIDEO"    # 目录下无匹配文件（由 module 层判定）
PROCESS_TIMEOUT = "PROCESS_TIMEOUT"        # ffmpeg 卡住超时
DECODE_ERROR = "DECODE_ERROR"
MISSING_REFERENCE = "MISSING_REFERENCE"    # e.g. Could not find ref with POC 16
REFERENCE_CHAIN_ERROR = "REFERENCE_CHAIN_ERROR"
NAL_PARSE_ERROR = "NAL_PARSE_ERROR"
MISSING_PICTURE = "MISSING_PICTURE"        # 仅 trace_headers 高置信确认 15→17 且 16 缺失
TRACE_HEADERS_UNAVAILABLE = "TRACE_HEADERS_UNAVAILABLE"
UNKNOWN_HEVC_ERROR = "UNKNOWN_HEVC_ERROR"

# IRAP NAL unit type（HEVC BLA_W_LP..RSV_IRAP_VCL23）
_IRAP_NAL_TYPES = set(range(16, 24))

# 解码错误特征 -> 分类（按优先级，只报首个命中）
# 「Could not find ref with POC N」比「Error constructing the frame RPS」更具诊断性
# （后者常是前者的连锁结果），故 MISSING_REFERENCE 优先。
_DECODE_ERR_PATTERNS = [
    (NAL_PARSE_ERROR, re.compile(r"Error parsing NAL unit|Invalid NAL unit", re.I)),
    (MISSING_REFERENCE, re.compile(r"Could not find ref with POC\s*(\d+)", re.I)),
    (REFERENCE_CHAIN_ERROR, re.compile(r"Error constructing the frame RPS", re.I)),
    (DECODE_ERROR, re.compile(
        r"Invalid data found when processing input|Error submitting packet to decoder", re.I)),
]

_NAL_RE = re.compile(r"nal_unit_type:\s*(\d+)")
_POC_LSB_RE = re.compile(r"slice_pic_order_cnt_lsb\s+\S+\s*=\s*(\d+)")
_LOG2POC_RE = re.compile(r"log2_max_pic_order_cnt_lsb_minus4\s+\S+\s*=\s*(\d+)")
_SHOWINFO_RE = re.compile(r"n:\s*(\d+)\s+pts:\s*\d+\s+pts_time:(\S+)")


@dataclass
class H265ValidationResult:
    """单文件 H.265 检测的结构化结果（需求 §11）。

    字段命名以 §20.7 为准：``first_decode_error``（非 ``first_decoder_error``）。
    """
    file_path: str
    ok: bool = False
    error_type: str = ""
    reason: str = ""
    decode_returncode: int = 0
    first_decode_error: str = ""
    last_good_decoded_frame: Optional[int] = None
    last_good_pts_time: Optional[float] = None
    missing_poc: Optional[int] = None
    gop_index: Optional[int] = None
    coded_frame_index: Optional[int] = None
    frame_number: Optional[int] = None
    approx_timestamp: Optional[float] = None
    expected_fps: Optional[float] = None
    expected_gop_size: Optional[int] = None
    confidence: str = ""
    diagnostic_logs: list = field(default_factory=list)


class H265Validator:
    """H.265 本地文件完整性检测器（FFmpeg 三阶段诊断）。

    一个实例按一份 ``config``（模块 yaml 展开后的 ``analysis/hevc/diagnostic/ffmpeg_path``）
    工作，可复用于多个文件；``validate()`` 为单文件入口。
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.ffmpeg = self._resolve_ffmpeg(self.config.get("ffmpeg_path", "tools/ffmpeg/ffmpeg"))
        self.analysis = self.config.get("analysis", {}) or {}
        self.hevc = self.config.get("hevc", {}) or {}
        self.diagnostic = self.config.get("diagnostic", {}) or {}
        self._trace_supported = None  # lazy 探测缓存

    # ------------------------------------------------------------------
    # 工具与预检查
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_ffmpeg(path: str) -> str:
        if not path:
            return ""
        if shutil.which(path) or os.path.isfile(path):
            return path
        sysp = shutil.which("ffmpeg")
        if sysp:
            return sysp
        return path  # 保留原值，validate 时报 TOOL_NOT_FOUND

    def tool_available(self) -> bool:
        return bool(self.ffmpeg) and (shutil.which(self.ffmpeg) or os.path.isfile(self.ffmpeg))

    def _trace_available(self) -> bool:
        if self._trace_supported is None:
            try:
                out = subprocess.run(
                    [self.ffmpeg, "-hide_banner", "-bsfs"],
                    capture_output=True, text=True, timeout=30,
                )
                self._trace_supported = "trace_headers" in (out.stdout or "")
            except Exception:
                self._trace_supported = False
        return self._trace_supported

    def _precheck(self, file_path: str) -> Optional[str]:
        """Stage 0 文件预检查（§20.2）。返回 error_type 或 None（通过）。"""
        if not os.path.exists(file_path):
            return INPUT_NOT_FOUND
        if not os.path.isfile(file_path):
            return INVALID_INPUT
        try:
            size = os.path.getsize(file_path)
        except OSError:
            return INPUT_NOT_READABLE
        if size <= 0:
            return INVALID_INPUT
        ext = os.path.splitext(file_path)[1].lower()
        patterns = self.config.get("input", {}).get("patterns", ["*.h265", "*.hevc"])
        if not self._matches_ext(ext, patterns):
            return INVALID_INPUT
        if not os.access(file_path, os.R_OK):
            return INPUT_NOT_READABLE
        return None

    @staticmethod
    def _matches_ext(ext: str, patterns: list) -> bool:
        import fnmatch
        for pat in patterns:
            pext = os.path.splitext(pat)[1].lower()
            if pext and fnmatch.fnmatch(ext, pext) or fnmatch.fnmatch(ext, pat):
                return True
        return False

    # ------------------------------------------------------------------
    # 子进程执行器（内存安全）
    # ------------------------------------------------------------------

    def _spawn(self, argv, timeout, log_path, collector=None):
        """运行 FFmpeg，stderr 写文件 + 逐行回调。返回 ``(returncode, timed_out)``。

        collector(line) 在独立读线程内被调用，用于按行解析（海量日志不载入内存）。
        """
        os.makedirs(os.path.dirname(log_path), exist_ok=True) if log_path else None
        fh = open(log_path, "w", encoding="utf-8", errors="replace") if log_path else None
        timed_out = False
        try:
            proc = subprocess.Popen(
                argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, bufsize=1, errors="replace",
            )

            def _reader():
                try:
                    for line in proc.stderr:
                        if fh:
                            fh.write(line)
                        if collector:
                            try:
                                collector(line)
                            except Exception:
                                pass
                except Exception:
                    pass

            t = threading.Thread(target=_reader, daemon=True)
            t.start()
            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
                rc = proc.returncode if proc.returncode is not None else -9
            finally:
                t.join(timeout=2)
        finally:
            if fh:
                fh.close()
        return rc, timed_out

    # ------------------------------------------------------------------
    # 三阶段
    # ------------------------------------------------------------------

    def _run_decode(self, file_path, log_path, timeout):
        argv = [
            self.ffmpeg, "-hide_banner", "-v", "error", "-err_detect", "explode",
            "-i", file_path, "-f", "null", "-",
        ]
        errors = []

        def collect(line):
            s = line.strip()
            if s and s not in errors and len(errors) < 100:
                errors.append(s)

        rc, timed_out = self._spawn(argv, timeout, log_path, collect)
        return rc, timed_out, errors

    def _run_showinfo(self, file_path, log_path, timeout):
        argv = [
            self.ffmpeg, "-hide_banner", "-threads", "1", "-loglevel", "info",
            "-err_detect", "explode", "-i", file_path, "-vf", "showinfo", "-f", "null", "-",
        ]
        state = {"last_frame": None, "last_pts": None}

        def collect(line):
            m = _SHOWINFO_RE.search(line)
            if m:
                state["last_frame"] = int(m.group(1))
                try:
                    state["last_pts"] = float(m.group(2))
                except ValueError:
                    pass

        rc, timed_out = self._spawn(argv, timeout, log_path, collect)
        return rc, timed_out, state

    def _run_trace(self, file_path, log_path, timeout):
        argv = [
            self.ffmpeg, "-hide_banner", "-loglevel", "debug", "-i", file_path,
            "-map", "0:v:0", "-c:v", "copy", "-bsf:v", "trace_headers", "-f", "null", "-",
        ]
        state = {"pocs": [], "last_poc": None, "poc_width": None}

        def collect(line):
            m = _LOG2POC_RE.search(line)
            if m and state["poc_width"] is None:
                state["poc_width"] = int(m.group(1)) + 4
            m = _POC_LSB_RE.search(line)
            if m:
                poc = int(m.group(1))
                if poc != state["last_poc"]:
                    state["pocs"].append(poc)
                    state["last_poc"] = poc

        rc, timed_out = self._spawn(argv, timeout, log_path, collect)
        return rc, timed_out, state

    # ------------------------------------------------------------------
    # 解析与分类
    # ------------------------------------------------------------------

    def _classify_decode_error(self, text: str):
        for err_type, pattern in _DECODE_ERR_PATTERNS:
            if pattern.search(text):
                return err_type
        return DECODE_ERROR

    def _extract_missing_poc(self, text: str) -> Optional[int]:
        m = re.search(r"Could not find ref with POC\s*(\d+)", text, re.I)
        return int(m.group(1)) if m else None

    def _detect_missing_poc(self, pocs, expected_gop_size):
        """从 trace 解析出的 POC 序列里高置信检测缺失 POC。

        返回 ``(missing_poc, gop_index)`` 或 ``(None, None)``。
        固定 GOP 下 POC 序列分段严格 +1 递增，回退即 GOP 边界；只有
        「前进跳过且缺失值从未在文件其它位置出现」才判缺失。
        """
        if not pocs:
            return None, None
        seen = set(pocs)
        prev = pocs[0]
        gop_index = 0
        run = 1
        first_missing = None
        missing_gop = None
        for i in range(1, len(pocs)):
            cur = pocs[i]
            if cur > prev:
                if cur - prev == 1:
                    run += 1
                else:
                    gap = prev + 1
                    if first_missing is None and gap not in seen and run >= 3:
                        first_missing = gap
                        missing_gop = gop_index
                    run = 1
            elif cur < prev:
                # 回退：GOP 边界（IDR reset / wrap）
                gop_index += 1
                run = 1
            prev = cur
        return first_missing, missing_gop

    # ------------------------------------------------------------------
    # 单文件入口
    # ------------------------------------------------------------------

    def validate(self, file_path: str, work_dir: str = "") -> H265ValidationResult:
        """对单个 H.265 文件执行完整检测，返回结构化结果。"""
        res = H265ValidationResult(file_path=file_path)
        res.expected_fps = float(self.hevc.get("expected_fps", 30) or 30)
        res.expected_gop_size = int(self.hevc.get("expected_gop_size", 30) or 30)

        # Stage 0
        pre_err = self._precheck(file_path)
        if pre_err:
            res.error_type = pre_err
            res.reason = {
                INPUT_NOT_FOUND: f"文件不存在: {file_path}",
                INPUT_NOT_READABLE: f"文件不可读: {file_path}",
                INVALID_INPUT: f"非有效输入文件（非普通文件/大小0/扩展名不匹配）: {file_path}",
            }.get(pre_err, pre_err)
            return res

        if not self.tool_available():
            res.error_type = TOOL_NOT_FOUND
            res.reason = f"ffmpeg 不存在: {self.ffmpeg!r}"
            return res

        if work_dir:
            os.makedirs(work_dir, exist_ok=True)

        decode_log = os.path.join(work_dir, "decode.log") if work_dir else ""
        decode_timeout = float(self.analysis.get("decode_timeout", 900))
        rc, timed_out, decode_errors = self._run_decode(file_path, decode_log, decode_timeout)
        res.decode_returncode = rc
        res.first_decode_error = decode_errors[0] if decode_errors else ""
        if decode_log:
            res.diagnostic_logs.append(decode_log)

        # Stage 1 PASS（§8）：rc==0 且 error stderr 为空（无解码错误）且未超时。
        # 注意：ffmpeg 带错误隐错机制时即使解码报错 returncode 仍可能为 0，
        # 必须额外判 stderr（-v error 只输出 error 级，errors 列表即 error stderr 内容）。
        if rc == 0 and not decode_errors and not timed_out:
            res.ok = True
            res.error_type = PASS
            res.reason = "全文件解码通过"
            self._write_diagnostic(res, work_dir)
            return res

        # Stage 1 失败 -> 详细诊断
        if timed_out:
            res.error_type = PROCESS_TIMEOUT
            res.reason = f"全文件解码超时（>{decode_timeout:g}s），ffmpeg 已终止"
            self._write_diagnostic(res, work_dir)
            return res

        err_text = "\n".join(decode_errors)
        err_type = self._classify_decode_error(err_text)
        decoder_poc = self._extract_missing_poc(err_text)

        # Stage 2 showinfo 定位
        locate_on_error = bool(self.analysis.get("locate_on_error", True))
        if locate_on_error and work_dir:
            showinfo_log = os.path.join(work_dir, "showinfo.log")
            showinfo_timeout = float(self.analysis.get("showinfo_timeout", 900))
            try:
                _, si_timed, si = self._run_showinfo(file_path, showinfo_log, showinfo_timeout)
                if si_timed:
                    res.error_type = PROCESS_TIMEOUT
                    res.reason = f"showinfo 定位超时（>{showinfo_timeout:g}s）"
                    res.diagnostic_logs.append(showinfo_log)
                    self._write_diagnostic(res, work_dir)
                    return res
                res.last_good_decoded_frame = si["last_frame"]
                res.last_good_pts_time = si["last_pts"]
                res.diagnostic_logs.append(showinfo_log)
            except Exception as e:
                logger.warn(f"showinfo 定位失败(可忽略): {e}")

        # Stage 3 trace_headers 码流分析
        trace_on_error = bool(self.analysis.get("trace_headers_on_error", True))
        if trace_on_error and self._trace_available():
            trace_log = os.path.join(work_dir, "trace_headers.log") if work_dir else ""
            trace_timeout = float(self.analysis.get("trace_timeout", 900))
            try:
                _, tr_timed, tr = self._run_trace(file_path, trace_log, trace_timeout)
                if tr_timed:
                    res.error_type = PROCESS_TIMEOUT
                    res.reason = f"trace_headers 分析超时（>{trace_timeout:g}s）"
                    if trace_log:
                        res.diagnostic_logs.append(trace_log)
                    self._write_diagnostic(res, work_dir)
                    return res
                if trace_log:
                    res.diagnostic_logs.append(trace_log)

                missing, gop_idx = self._detect_missing_poc(
                    tr["pocs"], res.expected_gop_size)
                if missing is not None:
                    res.error_type = MISSING_PICTURE
                    res.missing_poc = missing
                    res.gop_index = gop_idx
                    res.confidence = "fixed_gop"
                    # 全局 coded index 仅在固定 GOP + gop size 确认时计算（§9）
                    if res.expected_gop_size and res.expected_fps and gop_idx is not None:
                        res.coded_frame_index = gop_idx * res.expected_gop_size + missing
                        res.frame_number = res.coded_frame_index + 1
                        res.approx_timestamp = round(res.coded_frame_index / res.expected_fps, 3)
                    res.reason = (
                        f"码流确认缺失 POC {missing}"
                        + (f"（decoder 报缺 ref POC {decoder_poc}）" if decoder_poc else "")
                        + self._frame_loc(res)
                    )
                else:
                    # 无高置信 gap：沿用 decode 级分类
                    res.error_type = err_type
                    res.confidence = "decode_only"
                    res.reason = self._decode_reason(err_type, err_text)
            except Exception as e:
                logger.warn(f"trace_headers 分析异常(可忽略): {e}")
                res.error_type = err_type
                res.reason = self._decode_reason(err_type, err_text)
        elif not self._trace_available():
            # trace 不可用：仍 FAIL，详细诊断降级，不得 PASS（§Case H）
            res.error_type = err_type
            res.confidence = "decode_only"
            res.reason = (self._decode_reason(err_type, err_text)
                          + "；trace_headers 不可用，仅 decode 级诊断")
        else:
            res.error_type = err_type
            res.confidence = "decode_only"
            res.reason = self._decode_reason(err_type, err_text)

        self._write_diagnostic(res, work_dir)
        return res

    # ------------------------------------------------------------------
    # 输出辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _frame_loc(res: H265ValidationResult) -> str:
        if res.approx_timestamp is not None:
            return f" | 约 {res.approx_timestamp}s (coded_frame_index={res.coded_frame_index})"
        return ""

    @staticmethod
    def _decode_reason(err_type, err_text):
        first = err_text.splitlines()[0] if err_text.splitlines() else ""
        return f"{err_type}" + (f": {first[:200]}" if first else "")

    def _write_diagnostic(self, res: H265ValidationResult, work_dir: str):
        if not work_dir:
            return
        path = os.path.join(work_dir, "diagnostic.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"file: {res.file_path}\n")
                f.write(f"ok: {res.ok}\n")
                f.write(f"error_type: {res.error_type}\n")
                f.write(f"reason: {res.reason}\n")
                f.write(f"decode_returncode: {res.decode_returncode}\n")
                f.write(f"first_decode_error: {res.first_decode_error}\n")
                f.write(f"last_good_decoded_frame: {res.last_good_decoded_frame}\n")
                f.write(f"last_good_pts_time: {res.last_good_pts_time}\n")
                f.write(f"missing_poc: {res.missing_poc}\n")
                f.write(f"gop_index: {res.gop_index}\n")
                f.write(f"coded_frame_index: {res.coded_frame_index}\n")
                f.write(f"frame_number: {res.frame_number}\n")
                f.write(f"approx_timestamp: {res.approx_timestamp}\n")
                f.write(f"confidence: {res.confidence}\n")
            res.diagnostic_logs.append(path)
        except OSError:
            pass
