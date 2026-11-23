"""录像固件协议定义：命令、判据、参数取值域与校验的唯一维护位置。

本文件不发送串口、不连接 FTP、不读取 YAML，也不安排测试次数或时长。
新固件采用**关键字式** ``cam_set video`` 语法（每个参数都带 key，如
``cam_set video <res> fps <N> eis <N> format <codec> bitrate <N> gop <N> vui <N>``）；
本文件是取值域、命令拼装与合法性校验的唯一来源，场景只选择参数组合，不内联协议
字符串（ADR-011）。
"""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

# ---------------------------------------------------------------------------
# 参数取值域（用户 2026-11-10 确认）
# ---------------------------------------------------------------------------
VIDEO_RESOLUTIONS = ("4k", "3k", "1080p", "sd1080p", "720p", "480p")
VIDEO_FPS = (30, 60)
VIDEO_EIS_MODES = (0, 1, 2)
VIDEO_CODECS = ("h264", "h265")
VIDEO_VUI = ("709", "6010", "6011")
VIDEO_BITRATE_RANGE = (50000, 25000000)
VIDEO_GOP_RANGE = (0, 1000)

# 分辨率对其它参数的硬约束：
# - 3k 只允许 eis 2（离线防抖）；
# - 4k / 3k / 1080p 不支持 60fps（真机 2026-11-23 确认 1080p 亦不支持）。
VIDEO_EIS_FORCED_OFFLINE: Mapping[str, int] = MappingProxyType({"3k": 2})
VIDEO_FPS_FORCED: Mapping[str, tuple] = MappingProxyType(
    {"4k": (30,), "3k": (30,), "1080p": (30,)})

# 关键字式（2026-11-23 真机实测确认固件唯一接受的写法）。
# 旧位置式（``{res} {fps} eis {eis} {codec}``，res 后裸数字当 fps）已被固件拒绝：
# ``I/CtrlCfg: bare number 30 not allowed, use "fps 30" or a keyword``。
# 固定字段顺序；即使取值等于固件默认也必须写出（不依赖固件缺省值）。
VIDEO_SET_COMMAND = (
    "cam_set video {res} fps {fps} eis {eis} format {codec} "
    "bitrate {bitrate} gop {gop} vui {vui}"
)

VIDEO_START_COMMAND = "cam_run video start"
VIDEO_STOP_COMMAND = "cam_run video stop"
VIDEO_START_EXPECT = r"Record Start|f_index\s*="
VIDEO_STOP_EXPECT = r"Video recording completed successfully."
VIDEO_CLEANUP_EXPECT = r"Save Video|Please start|recording completed"
# exec_sync 无 expect 时并不必然识别 Usage；设置失败绝不接着录旧参数。
# busy：固件在录制/推流中拒绝 cam_set 时返回。宽匹配先止血，真机原文到手后
# 只需收紧本常量（TODO-CONFIRM，用户 2026-11-10）。
VIDEO_SET_ERROR = (
    r"(?i)\b(?:usage|error|failed|fail|invalid|unknown|unsupported|busy)\b"
    r"|command not found"
)
VIDEO_SET_TIMEOUT = 10.0
VIDEO_START_TIMEOUT = 25.0
VIDEO_STOP_TIMEOUT = 25.0
VIDEO_CLEANUP_TIMEOUT = 8.0

_FIELDS = ("res", "fps", "eis", "codec", "bitrate", "gop", "vui")


class VideoParamsError(ValueError):
    """非法的录像参数组合（枚举外 / 越界 / 缺键 / 分辨率冲突）。"""


@dataclass(frozen=True)
class VideoParams:
    """一条完整录像参数组合（对应一条 cam_set video 命令）。"""

    res: str
    fps: int
    eis: int
    codec: str
    bitrate: int
    gop: int
    vui: str

    @property
    def key(self) -> str:
        """报告/文件名用短键，如 ``4k-30-e0-h265-b8m-g30-v709``。"""
        if self.bitrate % 1_000_000 == 0:
            bitrate = f"{self.bitrate // 1_000_000}m"
        else:
            bitrate = str(self.bitrate)
        return (
            f"{self.res}-{self.fps}-e{self.eis}-{self.codec}"
            f"-b{bitrate}-g{self.gop}-v{self.vui}"
        )

    @property
    def command(self) -> str:
        """按固定字段顺序拼完整命令。"""
        return VIDEO_SET_COMMAND.format(
            res=self.res, fps=self.fps, eis=self.eis, codec=self.codec,
            bitrate=self.bitrate, gop=self.gop, vui=self.vui,
        )


def _as_int(name: str, value, low: int = None, high: int = None) -> int:
    # bool 是 int 子类，必须显式拒绝（True 不能当 fps/eis）。
    if isinstance(value, bool) or not isinstance(value, int):
        raise VideoParamsError(f"{name} 必须是整数，实际 {value!r}")
    if low is not None and value < low:
        raise VideoParamsError(f"{name}={value} 小于下限 {low}")
    if high is not None and value > high:
        raise VideoParamsError(f"{name}={value} 大于上限 {high}")
    return value


def _as_vui(value) -> str:
    # YAML 里 vui: 709 会被解析成 int；与 "709" 语义相同，归一化为字符串后严格判枚举。
    if isinstance(value, str):
        normalized = value
    elif isinstance(value, bool) or not isinstance(value, int):
        raise VideoParamsError(f"vui 必须是字符串或整数，实际 {value!r}")
    else:
        normalized = str(value)
    if normalized not in VIDEO_VUI:
        raise VideoParamsError(
            f"vui={value!r} 不在取值域 {VIDEO_VUI}；请显式选择")
    return normalized


def resolve_video_params(params) -> VideoParams:
    """校验并构造 ``VideoParams``；不合法直接抛错（拒绝执行，不静默猜测）。

    ``params`` 必须是包含全部 7 个键的映射（模块 ``_merge`` 是浅合并，override 的
    ``video_params`` 会整体替换默认值，因此缺键必须报错而不是用默认值补齐）。
    """
    if not isinstance(params, Mapping):
        raise VideoParamsError(
            "video_params 必须是包含 res/fps/eis/codec/bitrate/gop/vui 的映射")
    missing = [key for key in _FIELDS if key not in params]
    if missing:
        raise VideoParamsError(
            f"video_params 缺少键: {', '.join(missing)}；7 个参数必须全部显式写出")

    res = params["res"]
    if not isinstance(res, str) or res not in VIDEO_RESOLUTIONS:
        raise VideoParamsError(
            f"res={res!r} 不在取值域 {VIDEO_RESOLUTIONS}")

    fps = _as_int("fps", params["fps"])
    allowed_fps = VIDEO_FPS_FORCED.get(res, VIDEO_FPS)
    if fps not in allowed_fps:
        raise VideoParamsError(f"{res} 不支持 fps={fps}；允许 {allowed_fps}")

    eis = _as_int("eis", params["eis"])
    forced_eis = VIDEO_EIS_FORCED_OFFLINE.get(res)
    allowed_eis = (forced_eis,) if forced_eis is not None else VIDEO_EIS_MODES
    if eis not in allowed_eis:
        raise VideoParamsError(f"{res} 不支持 eis={eis}；允许 {allowed_eis}")

    codec = params["codec"]
    if not isinstance(codec, str) or codec not in VIDEO_CODECS:
        raise VideoParamsError(f"codec={codec!r} 不在取值域 {VIDEO_CODECS}")

    bitrate = _as_int("bitrate", params["bitrate"],
                      VIDEO_BITRATE_RANGE[0], VIDEO_BITRATE_RANGE[1])
    gop = _as_int("gop", params["gop"], VIDEO_GOP_RANGE[0], VIDEO_GOP_RANGE[1])
    vui = _as_vui(params["vui"])

    return VideoParams(res=res, fps=fps, eis=eis, codec=codec,
                       bitrate=bitrate, gop=gop, vui=vui)


def iter_video_params(bitrates=(8000000,), gops=(30,)):
    """按固定顺序枚举全部合法组合（供矩阵生成与离线计数使用）。

    顺序：res（VIDEO_RESOLUTIONS 顺序）→ fps 升序 → eis 升序 → codec（h264, h265）
    → bitrate → gop → vui（709, 6010, 6011）。
    默认 bitrate/gop 各单值（方案 A），6 档：4k/3k/1080p 仅 30fps（各 3/1/3 eis），
    sd1080p/720p/480p 支持 30/60fps，每档 3 eis → 共 150 条。
    """
    for res in VIDEO_RESOLUTIONS:
        forced_eis = VIDEO_EIS_FORCED_OFFLINE.get(res)
        eis_modes = (forced_eis,) if forced_eis is not None else VIDEO_EIS_MODES
        for fps in VIDEO_FPS_FORCED.get(res, VIDEO_FPS):
            for eis in eis_modes:
                for codec in VIDEO_CODECS:
                    for bitrate in bitrates:
                        for gop in gops:
                            for vui in VIDEO_VUI:
                                yield resolve_video_params({
                                    "res": res, "fps": fps, "eis": eis,
                                    "codec": codec, "bitrate": bitrate,
                                    "gop": gop, "vui": vui,
                                })
