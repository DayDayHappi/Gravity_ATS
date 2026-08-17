"""RTMP 接收端：PC 上用 ffprobe 实时探测 RTMP 流 + 可选 ffplay 播放画面验证。

流程：
1. ``probe(url)``：subprocess.run ffprobe 实时探测 RTMP url，确认有视频流、编码、
   分辨率。带 ``-rw_timeout`` 防挂起（无流时 ffprobe 会立即 I/O error 退出，有流时
   才解析成功），外层 subprocess timeout 双保险。带重试——推流上线有缓冲延迟。
2. ``verify()``：用最近一次 probe 的结果判据通过与否（有视频流 + codec + 分辨率）。

注：不再 ffmpeg 拉流存盘（MediaMTX 时代用存盘 + ffprobe 解析文件验证流可解码；
nginx-rtmp 方案改为 ffprobe 直接探测实时 url，更轻量，无需落盘文件）。
ffprobe 由脚本自动调用（subprocess），无人值守。
ffplay 画面确认由模块层（modules/rtmp.py）管理，不在此类。

依赖：``ffprobe`` 可执行文件（必需）。自动查找顺序：
  1. 配置指定的路径
  2. PATH 中的 ffprobe（apt install ffmpeg 自带）
  3. 常见绝对路径
"""
import os
import json
import time
import shutil
import subprocess

from ..core import logger


def _find_ffprobe(preferred=None) -> str:
    """查找 ffprobe 可执行文件。顺序：preferred -> PATH -> 常见绝对路径。"""
    if preferred and (shutil.which(preferred) or os.path.isfile(preferred)):
        return preferred
    p = shutil.which("ffprobe")
    if p:
        return p
    for cand in ("/usr/bin/ffprobe", "/usr/local/bin/ffprobe",
                 os.path.expanduser("~/bin/ffprobe")):
        if os.path.isfile(cand):
            return cand
    return ""


class RtmpReceiverError(Exception):
    pass


class RtmpReceiver:
    """PC 端 RTMP 实时流探测器（ffprobe）。

    一次实例对应一次推流测试：probe -> (判据)。
    ffprobe 路径未指定时自动查找。
    """

    def __init__(self, ffprobe_path="ffprobe"):
        # 自动解析实际路径（找不到则保留原值，check_tools 会报缺失）
        self.ffprobe_path = _find_ffprobe(ffprobe_path if ffprobe_path != "ffprobe" else None) or ffprobe_path
        self._last_result = None  # 最近一次 probe 的结果

    @staticmethod
    def check_tools(ffprobe_path="ffprobe") -> list:
        """检查 ffprobe 是否可用，返回缺失项列表。

        ffprobe 在 nginx-rtmp 方案下是必需的（无存盘文件可降级，探测必须靠它）。
        """
        missing = []
        if not _find_ffprobe(ffprobe_path if ffprobe_path != "ffprobe" else None):
            missing.append("ffprobe (必需，验证 RTMP 流)"
                           " — apt install ffmpeg 或用内置 tools/ffmpeg/ffprobe")
        return missing

    def probe(self, url: str, timeout: float = 45.0,
              attempts: int = 4, interval: float = 2.0) -> dict:
        """ffprobe 实时探测 RTMP url，返回流信息 + 判据。

        推流上线有缓冲延迟（nginx-rtmp 中转约 4-6s），故带重试：失败时间隔后重试。
        ffprobe 连无流的源会立即 I/O error 退出（-rw_timeout 兜底防永久挂起）。

        Args:
            url: RTMP 推流地址（如 ``rtmp://10.1.64.35/live/cam``）。
            timeout: 单次 ffprobe subprocess 超时（秒）。
            attempts: 探测重试次数（推流可能上线稍晚）。
            interval: 重试间隔（秒）。

        Returns:
            dict: {has_video, width, height, codec, ok, reason}
        """
        if not self.ffprobe_path or not (shutil.which(self.ffprobe_path)
                                          or os.path.isfile(self.ffprobe_path)):
            self._last_result = {
                "has_video": False, "width": 0, "height": 0,
                "codec": "", "ok": False, "reason": f"ffprobe 不可用: {self.ffprobe_path!r}",
            }
            return self._last_result

        # 参数说明：
        # -rw_timeout 15000000(微秒=15s)：RTMP 读超时。板子推 1080p(1296x2304) 编码慢，
        #   关键帧(IDR)稀疏（严重时数秒~57s 才一个），太短会等不到 IDR 报 Input/output error。
        #   代价：无流时 ffprobe 也会多等，故外层 subprocess timeout 作双保险。
        # -analyzeduration/-probesize：放宽分析窗口与探测缓冲，容忍大帧/慢流首帧（IDR 可达 100KB）。
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

        for i in range(1, attempts + 1):
            try:
                out = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout,
                )
                result = self._parse_probe(out)
                if result["ok"]:
                    self._last_result = result
                    return result
                # 未通过：推流可能还没上线，间隔后重试
                if i < attempts:
                    logger.warn(f"ffprobe 未探测到流({i}/{attempts}): "
                                f"{result['reason']}，{interval}s 后重试")
                    time.sleep(interval)
                else:
                    self._last_result = result
            except subprocess.TimeoutExpired:
                if i < attempts:
                    logger.warn(f"ffprobe 探测超时({i}/{attempts})，{interval}s 后重试")
                    time.sleep(interval)
                else:
                    self._last_result = {
                        "has_video": False, "width": 0, "height": 0,
                        "codec": "", "ok": False, "reason": f"ffprobe 探测超时({timeout}s)",
                    }
            except Exception as e:
                if i < attempts:
                    logger.warn(f"ffprobe 异常({i}/{attempts}): {e}，{interval}s 后重试")
                    time.sleep(interval)
                else:
                    self._last_result = {
                        "has_video": False, "width": 0, "height": 0,
                        "codec": "", "ok": False, "reason": f"ffprobe 异常: {e}",
                    }
        return self._last_result

    def _parse_probe(self, out) -> dict:
        """解析 ffprobe JSON 输出为判据结果。"""
        result = {
            "has_video": False, "width": 0, "height": 0,
            "codec": "", "ok": False, "reason": "",
        }
        if out.returncode != 0:
            err = (out.stderr or "").strip()
            # 无流时常见的 I/O error / Connection refused
            result["reason"] = f"ffprobe 退出码 {out.returncode}: {err[:200]}"
            return result
        try:
            data = json.loads(out.stdout or "{}")
        except Exception as e:
            result["reason"] = f"ffprobe 输出解析失败: {e}"
            return result
        streams = data.get("streams", [])
        if not streams:
            result["reason"] = "无视频流（推流未到达）"
            return result
        s = streams[0]
        result["has_video"] = True
        result["codec"] = s.get("codec_name", "") or ""
        result["width"] = int(s.get("width", 0) or 0)
        result["height"] = int(s.get("height", 0) or 0)
        if not result["codec"]:
            result["reason"] = "未识别编码"
        elif not result["width"] or not result["height"]:
            result["reason"] = "未识别分辨率"
        else:
            result["ok"] = True
            result["reason"] = (f"{result['codec']} {result['width']}x{result['height']}"
                                f" (ffprobe 实时探测)")
        return result

    def verify(self) -> dict:
        """返回最近一次 probe 的结果（供模块层取判据）。

        必须先调用 ``probe(url)``，否则返回未探测。
        """
        if self._last_result is None:
            return {
                "has_video": False, "width": 0, "height": 0,
                "codec": "", "ok": False, "reason": "未执行 probe",
            }
        return self._last_result

    def stop(self):
        """兼容旧接口：探测类无需管理常驻进程，空实现保留以便模块层统一调 stop。"""
        pass
