"""RTMP 接收端：PC 上用 ffmpeg 拉流 + ffprobe 验证。

流程：
1. ``start()``：subprocess 启动 ffmpeg 拉流存盘（用 -rw_timeout 防挂起；拉流端晚于
   推流启动的时序由调用方保证，verify() 时长校验兜底流未到达）。
2. ``verify()``：用 ffprobe 解析存盘文件，确认有视频流、分辨率、编码。
   无独立 ffprobe 时，降级用 ``ffmpeg -i`` 解析或仅校验文件大小。
3. ``stop()``：终止 ffmpeg（保留存盘文件供回放）。

注：当前内置 ffmpeg（BtbN master 构建）的 RTMP 协议不接受 -reconnect 系列参数
（报 "Option not found"），故未使用。

ffmpeg/ffprobe 由脚本自动启停（subprocess），无人值守。
依赖：``ffmpeg`` 可执行文件。自动查找顺序：
  1. 配置指定的路径
  2. PATH 中的 ffmpeg/ffprobe（apt install ffmpeg）
  3. imageio-ffmpeg 包自带的二进制（pip install imageio-ffmpeg）
  4. 常见绝对路径
"""
import os
import json
import re as _re
import time
import shutil
import subprocess

from ..core import logger


def _find_ffmpeg(preferred=None) -> str:
    """按优先级查找 ffmpeg 可执行文件。

    顺序：preferred -> PATH -> imageio-ffmpeg -> 常见路径。
    找不到返回 ""。
    """
    # 1. 指定路径
    if preferred and shutil.which(preferred):
        return preferred
    # 2. PATH
    p = shutil.which("ffmpeg")
    if p:
        return p
    # 3. imageio-ffmpeg 包（自带静态二进制）
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    # 4. 常见绝对路径
    for cand in ("/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg",
                 os.path.expanduser("~/bin/ffmpeg")):
        if os.path.isfile(cand):
            return cand
    return ""


def _find_ffprobe(preferred=None) -> str:
    """查找 ffprobe。imageio-ffmpeg 不带 ffprobe，故无包级回退。"""
    if preferred and shutil.which(preferred):
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
    """PC 端 RTMP 拉流接收器。

    一次实例对应一次推流测试：start -> (EVB 推流) -> verify -> stop。
    ffmpeg/ffprobe 路径未指定时自动查找。
    """

    def __init__(self, ffmpeg_path="ffmpeg", ffprobe_path="ffprobe",
                 work_dir=None):
        # 自动解析实际路径（找不到则保留原值，check_tools 会报缺失）
        self.ffmpeg_path = _find_ffmpeg(ffmpeg_path if ffmpeg_path != "ffmpeg" else None) or ffmpeg_path
        self.ffprobe_path = _find_ffprobe(ffprobe_path if ffprobe_path != "ffprobe" else None) or ffprobe_path
        self.work_dir = work_dir or os.path.join(os.getcwd(), "logs", "rtmp")
        self._proc = None
        self._outfile = None

    @staticmethod
    def check_tools(ffmpeg_path="ffmpeg", ffprobe_path="ffprobe") -> list:
        """检查 ffmpeg/ffprobe 是否可用，返回缺失项列表。

        ffprobe 缺失不致命（verify 会降级为仅校验大小）。
        """
        missing = []
        if not _find_ffmpeg(ffmpeg_path if ffmpeg_path != "ffmpeg" else None):
            missing.append("ffmpeg")
        if not _find_ffprobe(ffprobe_path if ffprobe_path != "ffprobe" else None):
            missing.append("ffprobe (可选，缺失时仅校验文件大小)")
        return missing

    @property
    def is_running(self) -> bool:
        """ffmpeg 拉流进程是否仍在运行（未退出）。

        拉流端连上无流的 RTMP 源会立即退出(~150ms)，调用方据此判断是否需重试。
        """
        return self._proc is not None and self._proc.poll() is None

    def start(self, url: str, duration: int) -> str:
        """启动 ffmpeg 拉流存盘。

        Args:
            url: RTMP 推流地址（如 ``rtmp://10.1.64.35/live/cam1``）。
            duration: 预期拉流时长（秒），ffmpeg ``-t`` 限制。

        Returns:
            存盘文件路径。
        """
        if self._proc is not None and self._proc.poll() is None:
            logger.warn("ffmpeg 已在运行，先停止")
            self.stop()

        os.makedirs(self.work_dir, exist_ok=True)
        self._outfile = os.path.join(self.work_dir, f"stream_{int(time.time())}.flv")

        # 拉流参数说明：
        # - 不用 -reconnect/-reconnect_streamed：当前内置 ffmpeg（BtbN master 构建）
        #   的 RTMP 协议实现不接受这组参数，会报 "Option not found" 直接退出。
        #   拉流端晚于推流启动的时序由调用方保证（rtmp 模块先 start 拉流再
        #   rtmp_video_start），且 verify() 的时长校验兜底流未到达的情况。
        # -rw_timeout：给 RTMP 读一个超时，避免推流异常时 ffmpeg 永久挂起。
        cmd = [
            self.ffmpeg_path,
            "-rw_timeout", str(int(duration * 1000000) + 5000000),
            "-y",
            "-i", url,
            "-t", str(duration),
            "-c", "copy",
            "-f", "flv",
            self._outfile,
        ]
        logger.info(f"启动 ffmpeg 拉流: {' '.join(cmd)}")
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise RtmpReceiverError(f"ffmpeg 不可用: {e}")
        return self._outfile

    def verify(self, min_duration: float = 1.0) -> dict:
        """验证拉到的流。

        优先用 ffprobe 解析（有视频流/分辨率/编码/时长）；
        ffprobe 不可用时降级为 ``ffmpeg -i`` 解析 stderr；
        两者都不可用时仅校验文件大小。

        Args:
            min_duration: 流的最小有效时长（秒）。

        Returns:
            dict: {has_video, width, height, codec, duration, ok, reason}
        """
        # 等 ffmpeg 自然结束（-t duration）
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._proc.terminate()

        result = {
            "has_video": False, "width": 0, "height": 0,
            "codec": "", "duration": 0.0, "ok": False, "reason": "",
        }
        if not self._outfile or not os.path.isfile(self._outfile):
            result["reason"] = "拉流文件未生成"
            return result
        size = os.path.getsize(self._outfile)
        if size < 1024:
            result["reason"] = f"文件过小({size}B)，推流未到达"
            return result

        # 优先 ffprobe
        if shutil.which(self.ffprobe_path) or os.path.isfile(self.ffprobe_path):
            return self._verify_with_ffprobe(result, min_duration)
        # 降级 ffmpeg -i
        if shutil.which(self.ffmpeg_path) or os.path.isfile(self.ffmpeg_path):
            return self._verify_with_ffmpeg(result, min_duration, size)
        # 仅大小校验
        result["has_video"] = True  # 无法确认，保守认为有
        result["ok"] = True
        result["reason"] = f"仅校验大小 {size//1024}KB（无 ffprobe/ffmpeg）"
        return result

    def _verify_with_ffprobe(self, result: dict, min_duration: float) -> dict:
        try:
            out = subprocess.run(
                [self.ffprobe_path, "-v", "error",
                 "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name,width,height:format=duration",
                 "-of", "json", self._outfile],
                capture_output=True, text=True, timeout=15,
            )
            if out.returncode != 0:
                result["reason"] = f"ffprobe 失败: {out.stderr[:200]}"
                return result
            data = json.loads(out.stdout or "{}")
            streams = data.get("streams", [])
            fmt = data.get("format", {})
            if not streams:
                result["reason"] = "无视频流"
                return result
            s = streams[0]
            result["has_video"] = True
            result["codec"] = s.get("codec_name", "")
            result["width"] = int(s.get("width", 0) or 0)
            result["height"] = int(s.get("height", 0) or 0)
            result["duration"] = float(fmt.get("duration", 0) or 0)
            if result["duration"] < min_duration:
                result["reason"] = f"时长不足: {result['duration']:.1f}s < {min_duration}s"
            elif not result["codec"]:
                result["reason"] = "未识别编码"
            else:
                result["ok"] = True
                result["reason"] = f"{result['codec']} {result['width']}x{result['height']} {result['duration']:.1f}s"
            return result
        except Exception as e:
            result["reason"] = f"ffprobe 异常: {e}"
            return result

    def _verify_with_ffmpeg(self, result: dict, min_duration: float, size: int) -> dict:
        """无 ffprobe 时，用 ffmpeg -i 从 stderr 解析流信息。"""
        try:
            out = subprocess.run(
                [self.ffmpeg_path, "-i", self._outfile],
                capture_output=True, text=True, timeout=15,
            )
            # ffmpeg -i 不带输出文件会返回非0，但 stderr 含流信息
            err = out.stderr or ""
            # 解析 "Video: h264, yuv420p, 1920x1080, ... Duration: 00:00:05.00"
            res_m = _re.search(r"(\d{2,5})x(\d{2,5})", err)
            codec_m = _re.search(r"Video:\s*(\w+)", err)
            dur_m = _re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", err)
            result["has_video"] = "Video:" in err
            if codec_m:
                result["codec"] = codec_m.group(1)
            if res_m:
                result["width"] = int(res_m.group(1))
                result["height"] = int(res_m.group(2))
            if dur_m:
                h, mi, se = dur_m.group(1), dur_m.group(2), dur_m.group(3)
                result["duration"] = int(h) * 3600 + int(mi) * 60 + float(se)
            if not result["has_video"]:
                result["reason"] = "无视频流"
            elif result["duration"] < min_duration:
                result["reason"] = f"时长不足: {result['duration']:.1f}s < {min_duration}s"
            else:
                result["ok"] = True
                result["reason"] = (f"{result['codec']} {result['width']}x{result['height']} "
                                    f"{result['duration']:.1f}s (ffmpeg -i)")
            return result
        except Exception as e:
            result["reason"] = f"ffmpeg 解析异常: {e}"
            return result

    def stop(self):
        """终止 ffmpeg 进程（保留存盘文件供回放）。"""
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
