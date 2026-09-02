"""H.265 视频完整性检测模块（本地文件，PC 端诊断）。

职责边界（需求文档 §3/§4/§12）：
- 选择本次待检测的 H.265 文件（本地目录约定，不 import video.py）；
- 逐个调用 ``H265Validator``（driver），聚合出**单个** aggregate ``TestResult``；
- 维护 ``video_integrity/manifest.json`` 去重（``latest_unchecked``）；
- 写运行日志到 ``run.log`` / ``video_integrity/summary.log``，**绝不写 serial.log**。

与 ``VideoModule`` 通过「本地文件目录约定」解耦：录像落在
``<logger.log_dir()>/videos/Video_<n>_0.h265``，本模块以 ``current_run_subdir: videos``
扫描该目录，**不新增 ctx.latest_video / ctx.video_result 等 Context 契约**（§4）。

深合并（§7 方案 A）：覆盖 ``_merge()``，对 ``input/analysis/hevc/diagnostic`` 等
嵌套 dict 递归合并，避免 ``base._merge`` 顶层浅合并把 override 的 ``input`` 整段
替换掉默认 ``input``（丢失 patterns/recursive/empty_input_policy/current_run_subdir）。
**不改 core/base/runner/config。**
"""
import fnmatch
import json
import os
import re
import time

from .base import TestModule, register
from ..core import logger
from ..core.result import TestResult, PASSED, FAILED, SKIPPED, ERROR

# 需要做递归合并的嵌套配置段（§7）
_DEEP_MERGE_SECTIONS = ("input", "analysis", "hevc", "diagnostic")

# error_type -> TestResult.status 映射（§10 + §20.2）
_ENV_ERRORS = {"TOOL_NOT_FOUND", "INPUT_NOT_FOUND", "INPUT_NOT_READABLE", "INVALID_INPUT"}

# 从 first_decode_error 提取 POC（"Could not find ref with POC 6" -> 6）
_POC_IN_ERR_RE = re.compile(r"Could not find ref with POC\s*(\d+)", re.I)
# ffmpeg 日志行前缀 "[hevc @ 0x...]" 噪声清理
_FFMPEG_PREFIX_RE = re.compile(r"\[[^\]]*\]\s*")


@register("video_integrity")
class VideoIntegrityModule(TestModule):
    """H.265 本地视频完整性检测。"""

    depends = []
    # 本模块不设 duration_key（§7），保持 None 避免 task.duration 误覆盖某参数

    def _merge(self, params: dict = None) -> dict:
        """模块内深合并：嵌套配置段递归合并，override 优先（dict 逐 key，list/scalar 以 override 覆盖）。"""
        base = dict(self.config or {})
        over = dict(params or {})
        for key in _DEEP_MERGE_SECTIONS:
            b = base.get(key)
            o = over.get(key)
            if isinstance(b, dict) and isinstance(o, dict):
                merged = dict(b)
                merged.update(o)
                base[key] = merged
        base.update({k: v for k, v in over.items() if k not in _DEEP_MERGE_SECTIONS})
        return base

    def run(self, ctx, console, params=None):
        # console 可为 None（standalone 场景 prepare=[] 不初始化串口），本模块不依赖串口（§7/§19）
        self.config = self._merge(params)
        input_cfg = self.config.get("input", {}) or {}

        # 选择待检测文件（§5/§6）
        files, sel_error = self._select_files(input_cfg)
        if sel_error is not None:
            return self._finish_env_error(sel_error[0], sel_error[1])

        # 目录无匹配文件 -> empty_input_policy（§15）
        if not files:
            policy = input_cfg.get("empty_input_policy", "fail")
            if policy == "skip":
                logger.info("video_integrity: 本轮无匹配视频文件，SKIP")
                return self._skip("无匹配视频文件（empty_input_policy=skip）")
            return self._fail("无匹配视频文件", "请检查 input.source/directory/patterns 配置")

        from ..drivers.h265_validator import H265Validator
        validator = H265Validator(self.config)

        # 日志目录（§13）：<log_dir>/video_integrity/
        base_work = os.path.join(logger.log_dir() or "logs", "video_integrity")
        os.makedirs(base_work, exist_ok=True)

        results = []
        for fp in files:
            r = self._check_one(validator, fp, base_work)
            results.append(r)
            self._write_summary(base_work, fp, r)

        # 聚合（§12）：任意一个 FAIL -> 整体 FAIL；逐文件进入 detail
        self._record_checked(files, input_cfg)
        return self._aggregate(results, files)

    # ------------------------------------------------------------------
    # 文件选择
    # ------------------------------------------------------------------

    def _select_files(self, input_cfg):
        """按 source/selection 选择文件。返回 (files, error) 或 (files, None)。"""
        source = input_cfg.get("source", "current_run")
        patterns = input_cfg.get("patterns", ["*.h265", "*.hevc"])
        selection = input_cfg.get("selection", "latest_unchecked")

        if source == "directory":
            directory = input_cfg.get("directory", "")
            if not directory:
                return [], ("INPUT_NOT_FOUND", "input.source=directory 但未配置 input.directory")
            if not os.path.isdir(directory):
                return [], ("INPUT_NOT_FOUND", f"目录不存在: {directory}")
            matches = self._scan_dir(directory, patterns, bool(input_cfg.get("recursive", False)))
        else:  # current_run
            subdir = input_cfg.get("current_run_subdir", "videos")
            directory = os.path.join(logger.log_dir() or "logs", subdir)
            matches = self._scan_dir(directory, patterns, bool(input_cfg.get("recursive", False)))

        if selection == "explicit":
            return self._explicit_files(input_cfg, directory, matches), None

        # 去重（latest_unchecked）前置过滤：本次 run 已检测过的剔除（§6）
        if selection == "latest_unchecked":
            checked = self._load_manifest()
            matches = [m for m in matches if not self._is_checked(m, checked)]

        if not matches:
            return [], None

        if selection in ("latest", "latest_unchecked"):
            return [max(matches, key=os.path.getmtime)], None
        # all
        return sorted(matches, key=os.path.getmtime), None

    def _explicit_files(self, input_cfg, base_dir, matches):
        explicit = input_cfg.get("explicit_files", [])
        files = []
        for ef in explicit:
            p = ef if os.path.isabs(ef) else os.path.join(base_dir, ef)
            files.append(p)
        return files

    @staticmethod
    def _scan_dir(directory, patterns, recursive):
        if not os.path.isdir(directory):
            return []
        found = []
        if recursive:
            for root, _dirs, fnames in os.walk(directory):
                for fn in fnames:
                    if fn.startswith(".") or fn.endswith(".part"):
                        continue
                    if any(fnmatch.fnmatch(fn, p) for p in patterns):
                        found.append(os.path.join(root, fn))
        else:
            try:
                for fn in os.listdir(directory):
                    fp = os.path.join(directory, fn)
                    if not os.path.isfile(fp):
                        continue
                    if fn.startswith(".") or fn.endswith(".part"):
                        continue
                    if any(fnmatch.fnmatch(fn, p) for p in patterns):
                        found.append(fp)
            except OSError:
                return []
        return found

    # ------------------------------------------------------------------
    # manifest（去重）
    # ------------------------------------------------------------------

    def _manifest_path(self):
        return os.path.join(logger.log_dir() or "logs", "video_integrity", "manifest.json")

    def _load_manifest(self):
        try:
            with open(self._manifest_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("checked", [])
        except Exception:
            return []

    @staticmethod
    def _identity(fp):
        try:
            st = os.stat(fp)
            return {"path": os.path.abspath(fp), "size": st.st_size, "mtime_ns": st.st_mtime_ns}
        except OSError:
            return {"path": os.path.abspath(fp), "size": -1, "mtime_ns": -1}

    @staticmethod
    def _is_checked(fp, checked):
        ident = VideoIntegrityModule._identity(fp)
        return any(c.get("path") == ident["path"]
                   and c.get("size") == ident["size"]
                   and c.get("mtime_ns") == ident["mtime_ns"]
                   for c in checked)

    def _record_checked(self, files, input_cfg):
        if input_cfg.get("selection") != "latest_unchecked":
            return
        checked = self._load_manifest()
        existing_paths = {(c.get("path"), c.get("size"), c.get("mtime_ns")) for c in checked}
        for fp in files:
            ident = self._identity(fp)
            key = (ident["path"], ident["size"], ident["mtime_ns"])
            if key not in existing_paths:
                checked.append(ident)
                existing_paths.add(key)
        try:
            p = self._manifest_path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"checked": checked}, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warn(f"manifest 写入失败(可忽略): {e}")

    # ------------------------------------------------------------------
    # 单文件检测 + 输出
    # ------------------------------------------------------------------

    def _check_one(self, validator, fp, base_work):
        name = os.path.basename(fp)
        work_dir = os.path.join(base_work, name)
        logger.step(f"  H265 检测: {name}")
        t0 = time.monotonic()
        res = validator.validate(fp, work_dir)
        elapsed = time.monotonic() - t0
        status = self._map_status(res.error_type)
        # 失败/错误时终端行补齐定位字段（POC/全局帧号/时间）；PASS 保持轻量。
        suffix = self._locate_suffix(res) if status in (FAILED, ERROR) else ""
        logger.info(f"    [{status}] {name} {res.error_type}{suffix} ({elapsed:.1f}s)")
        return {"file": fp, "name": name, "res": res, "status": status}

    @staticmethod
    def _map_status(error_type):
        from ..drivers.h265_validator import PASS as D_PASS
        if error_type == D_PASS:
            return PASSED
        if error_type in _ENV_ERRORS:
            return ERROR
        if error_type == "NO_MATCHING_VIDEO":
            return FAILED  # 由 run() 里的 empty_input_policy 提前处理，这里兜底
        return FAILED

    @staticmethod
    def _poc_from_error(first_decode_error):
        """从 first_decode_error 提取 POC（"Could not find ref with POC 6" -> 6）。"""
        m = _POC_IN_ERR_RE.search(first_decode_error or "")
        return int(m.group(1)) if m else None

    @staticmethod
    def _locate_suffix(res) -> str:
        """终端行定位后缀（紧凑）：MISSING_PICTURE 显示 POC+全局帧+时间，
        其它失败显示 first_decode_error 的 POC + last_good 帧/时间。"""
        parts = []
        if res.error_type == "MISSING_PICTURE":
            if res.missing_poc is not None:
                parts.append(f"missing_poc={res.missing_poc}")
            if res.frame_number is not None:
                parts.append(f"全局帧={res.frame_number}")
            elif res.coded_frame_index is not None:
                parts.append(f"coded_frame_index={res.coded_frame_index}")
            if res.approx_timestamp is not None:
                parts.append(f"~{res.approx_timestamp}s")
        else:
            poc = VideoIntegrityModule._poc_from_error(res.first_decode_error)
            if poc is not None:
                parts.append(f"POC={poc}")
            if res.last_good_decoded_frame is not None:
                parts.append(f"last_good_frame={res.last_good_decoded_frame}")
            if res.last_good_pts_time is not None:
                parts.append(f"last_good_pts={res.last_good_pts_time:.3f}s")
        return (" " + " ".join(parts)) if parts else ""

    @staticmethod
    def _detail_fields(res) -> str:
        """detail 行的完整定位字段（含终端未展示的 gop_index/coded_frame_index/frame_number）。"""
        fields = []
        if res.missing_poc is not None:
            fields.append(f"missing_poc={res.missing_poc}")
        if res.gop_index is not None:
            fields.append(f"gop_index={res.gop_index}")
        if res.coded_frame_index is not None:
            fields.append(f"coded_frame_index={res.coded_frame_index}")
        if res.frame_number is not None:
            fields.append(f"frame_number={res.frame_number}")
        if res.approx_timestamp is not None:
            fields.append(f"approx_timestamp={res.approx_timestamp}s")
        if res.last_good_decoded_frame is not None:
            fields.append(f"last_good_decoded_frame={res.last_good_decoded_frame}")
        if res.last_good_pts_time is not None:
            fields.append(f"last_good_pts_time={res.last_good_pts_time:.3f}s")
        poc = VideoIntegrityModule._poc_from_error(res.first_decode_error)
        if poc is not None:
            fields.append(f"decoder_poc={poc}")
        return " ".join(fields)

    def _write_summary(self, base_work, fp, r):
        try:
            res = r["res"]
            with open(os.path.join(base_work, "summary.log"), "a", encoding="utf-8") as f:
                fields = self._detail_fields(res)
                line = (f"[{r['status']}] {r['name']} {res.error_type}"
                        + (f" {fields}" if fields else "")
                        + f" reason={res.reason}\n")
                f.write(line)
        except OSError:
            pass

    def _aggregate(self, results, files):
        n_pass = sum(1 for r in results if r["status"] == PASSED)
        n_fail = sum(1 for r in results if r["status"] == FAILED)
        n_error = sum(1 for r in results if r["status"] == ERROR)
        n_total = len(results)

        # §12：任意 FAIL -> FAIL；否则若存在 ERROR（环境/配置）-> ERROR；全 PASS -> PASS
        if n_fail:
            overall = FAILED
        elif n_error:
            overall = ERROR
        else:
            overall = PASSED

        detail_lines = []
        for r in results:
            res = r["res"]
            tag = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP", "ERROR": "ERROR"}[r["status"]]
            line = f"[{tag}] {r['name']}"
            if res.error_type != "PASS":
                line += f" ({res.error_type}"
                fields = self._detail_fields(res)
                if fields:
                    line += f" {fields}"
                line += ")"
            detail_lines.append(line)

        parts = [f"PASS={n_pass}"]
        if n_fail:
            parts.append(f"FAIL={n_fail}")
        if n_error:
            parts.append(f"ERROR={n_error}")
        message = f"H265检测 {n_total} 个：" + " ".join(parts)
        detail = "\n".join(detail_lines)

        if overall == PASSED:
            return self._pass(message)
        if overall == ERROR:
            return self._error(message, detail)
        return self._fail(message, detail)

    # ------------------------------------------------------------------
    # 结果工厂
    # ------------------------------------------------------------------

    def _finish_env_error(self, error_type, reason):
        # 环境/配置问题统一 ERROR（§10：TOOL_NOT_FOUND/INPUT_NOT_FOUND/INVALID_INPUT → ERROR）
        return self._error(f"H265检测环境问题: {reason}", reason)
