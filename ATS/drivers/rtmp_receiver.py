"""PC-side RTMP probing through ffprobe with cancellable process control."""
from __future__ import annotations

import json
import subprocess

from ..core import logger
from ..core.cancellation import OperationCancelled
from ..platform.processes import ProcessController
from ..platform.resources import ResourceLocator


class RtmpReceiverError(Exception):
    pass


class RtmpReceiver:
    def __init__(self, ffprobe_path="ffprobe", *, resource_locator=None,
                 process_controller=None, cancellation_token=None):
        self._resources = resource_locator or ResourceLocator()
        self._processes = process_controller or ProcessController()
        self._token = cancellation_token
        self.ffprobe_path = self._resources.find_tool("ffprobe", ffprobe_path) or ffprobe_path
        self._last_result = None

    @staticmethod
    def check_tools(ffprobe_path="ffprobe", resource_locator=None) -> list:
        locator = resource_locator or ResourceLocator()
        if not locator.find_tool("ffprobe", ffprobe_path):
            return ["ffprobe (required for RTMP stream verification)"]
        return []

    def probe(self, url: str, timeout: float = 45.0,
              attempts: int = 4, interval: float = 2.0) -> dict:
        if not self._resources.find_tool("ffprobe", self.ffprobe_path):
            self._last_result = self._failure(f"ffprobe 不可用: {self.ffprobe_path!r}")
            return self._last_result

        cmd = [
            self.ffprobe_path,
            "-v", "error",
            "-rw_timeout", "15000000",
            "-analyzeduration", "10000000",
            "-probesize", "3000000",
            "-i", url,
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height",
            "-of", "json",
        ]
        logger.info(f"ffprobe 探测 RTMP 流: {url}")
        for attempt in range(1, attempts + 1):
            if self._token is not None:
                self._token.raise_if_cancelled()
            try:
                completed = self._processes.run_capture(
                    cmd,
                    timeout=timeout,
                    cancellation_token=self._token,
                    text=True,
                )
                parsed = self._parse_probe(completed)
                self._last_result = parsed
                if parsed["ok"]:
                    return parsed
            except OperationCancelled:
                raise
            except subprocess.TimeoutExpired:
                self._last_result = self._failure(f"ffprobe 探测超时({timeout}s)")
            except Exception as exc:
                self._last_result = self._failure(f"ffprobe 异常: {exc}")
            if attempt < attempts:
                logger.warn(
                    f"ffprobe 未探测到流({attempt}/{attempts}): "
                    f"{self._last_result['reason']}，{interval}s 后重试"
                )
                if self._token is not None and self._token.wait(interval):
                    self._token.raise_if_cancelled()
                elif self._token is None:
                    import time
                    time.sleep(interval)
        return self._last_result

    @staticmethod
    def _failure(reason):
        return {"has_video": False, "width": 0, "height": 0,
                "codec": "", "ok": False, "reason": reason}

    def _parse_probe(self, completed) -> dict:
        result = self._failure("")
        if completed.returncode != 0:
            result["reason"] = f"ffprobe 退出码 {completed.returncode}: {(completed.stderr or '').strip()[:200]}"
            return result
        try:
            streams = json.loads(completed.stdout or "{}").get("streams", [])
        except Exception as exc:
            result["reason"] = f"ffprobe 输出解析失败: {exc}"
            return result
        if not streams:
            result["reason"] = "无视频流（推流未到达）"
            return result
        stream = streams[0]
        result.update(
            has_video=True,
            codec=stream.get("codec_name", "") or "",
            width=int(stream.get("width", 0) or 0),
            height=int(stream.get("height", 0) or 0),
        )
        if not result["codec"]:
            result["reason"] = "未识别编码"
        elif not result["width"] or not result["height"]:
            result["reason"] = "未识别分辨率"
        else:
            result["ok"] = True
            result["reason"] = f"{result['codec']} {result['width']}x{result['height']} (ffprobe 实时探测)"
        return result

    def verify(self) -> dict:
        return self._last_result or self._failure("未执行 probe")

    def stop(self):
        # Every probe process is bounded and reaped by ProcessController.run_capture.
        return None
