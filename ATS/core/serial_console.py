"""串口通信层（核心）。

实现设计文档第 3 章：
- **常驻读线程**：持续采集串口字节，全量写日志 + 喂环形缓冲，避免漏掉异步后台日志。
- **哨兵机制**：发命令时附加 ``; echo <TOKEN>``，等 TOKEN 出现即定界命令结束，
  解决 msh 提示符被后台日志/回显打碎粘连的问题（``msh />[32m...``、``msh />wifi scan``）。
- **自动探测**：未指定端口时扫描 ``/dev/ttyUSB*``+``/dev/ttyACM*``，按候选波特率
  逐个尝试，用 EVB 指纹（JX009 / msh /> / Some IC design company.cn Build）匹配。
- **波特率回退**：默认 2000000 探不到时回退 [250000, 115200, 921600]。

对外只暴露 ``SerialConsole`` 和 ``detect_port``，上层模块通过 ``exec_sync``/``exec_async``
发命令，不感知底层细节。
"""
import os
import re
import time
import glob
import threading
import secrets
from collections import deque

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None

from . import ansi
from . import logger
from .result import Response, Timer

# EVB 指纹：启动日志或 msh 提示符，用于自动探测识别 EVB 串口
_EVB_FINGERPRINTS = [
    r"JX009\b",
    r"GravityXR\.cn\s+Build",
    r"msh\s+/[^>]*>|msh\s*/>",
]
_FINGERPRINT_RE = re.compile("|".join(_EVB_FINGERPRINTS))

# msh 就绪标志：提示符可能是 msh />(根目录) 或 msh /xxx>(子目录)
_READY_RE = re.compile(r"FW\s+start\s+ok|msh\s+/[^>]*>|msh\s*/>")

# 默认错误关键字（exec_sync 未提供 expect 时据此判定失败）
_ERROR_RE = re.compile(
    r"\b(error|failed|fail|cannot|no such|not found|invalid|exception)\b",
    re.IGNORECASE,
)

# 哨兵 token 前缀，避免与正常输出混淆
_SENTINEL_PREFIX = "__EVBTEST_END_"

# 探测候选波特率（默认值优先，回退到手册值与常见值）
DEFAULT_BAUD_CANDIDATES = [2000000, 250000, 115200, 921600]


class SerialError(Exception):
    """串口通信异常。"""


class SerialConsole:
    """串口控制台：封装与 EVB msh 的命令-响应交互。

    线程模型：``open()`` 后启动一个常驻读线程，持续把串口字节写入
    ``serial.log`` 并存入环形缓冲；``exec_sync``/``exec_async`` 从缓冲匹配哨兵/期望。
    ``close()`` 停止线程。
    """

    def __init__(self, port, baudrate=2000000, timeout=2.0,
                 ready_timeout=60, sentinel_timeout=5.0):
        if serial is None:
            raise SerialError("缺少 pyserial 依赖，请先 pip install pyserial")
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ready_timeout = ready_timeout
        self.sentinel_timeout = sentinel_timeout

        self._ser = None
        self._reader_thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        # 环形缓冲：存最近收到的文本（剥离 ANSI 前），供命令匹配
        self._buffer = deque(maxlen=65536)
        self._buffer_lock = threading.Lock()
        self._cond = threading.Condition(self._buffer_lock)  # 缓冲有新数据时通知

    # ---------- 生命周期 ----------

    def open(self):
        """打开串口并启动读线程。"""
        try:
            self._ser = serial.Serial(
                self.port, self.baudrate,
                timeout=self.timeout,  # read 超时
                write_timeout=self.timeout,
            )
        except Exception as e:
            raise SerialError(f"打开串口 {self.port} 失败: {e}")
        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer()
        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="serial-reader", daemon=True
        )
        self._reader_thread.start()
        logger.info(f"串口已打开: {self.port} @ {self.baudrate} bps")

    def close(self):
        """停止读线程并关闭串口。"""
        self._stop_event.set()
        self._notify_all()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        logger.debug("串口已关闭")

    # ---------- 常驻读线程 ----------

    def _reader_loop(self):
        """后台线程：持续读串口，写日志 + 喂缓冲。"""
        while not self._stop_event.is_set():
            try:
                if self._ser is None or not self._ser.is_open:
                    time.sleep(0.05)
                    continue
                # 按块读，timeout 控制单次等待
                chunk = self._ser.read(256)
                if not chunk:
                    continue
                text = chunk.decode("utf-8", errors="replace")
                # 写全量日志（保留 ANSI 原始字节）
                logger.log_serial_raw("RX<", chunk)
                # 喂缓冲（保留原始，匹配时再按需剥离 ANSI）
                with self._cond:
                    self._buffer.append(text)
                    self._cond.notify_all()
            except Exception as e:
                if not self._stop_event.is_set():
                    logger.warn(f"串口读异常: {e}")
                time.sleep(0.1)

    def _buffer_text(self) -> str:
        """获取当前缓冲全部文本（线程安全）。"""
        with self._buffer_lock:
            return "".join(self._buffer)

    def _drain_buffer_from(self, marker: str) -> str:
        """从缓冲中截取 marker 之后的内容作为新命令的响应起点。

        为简化实现，命令匹配基于"自命令发出后累积的全部新输出"。
        本方法在发命令前记录当前缓冲快照起点。
        """
        return marker

    def _notify_all(self):
        with self._cond:
            self._cond.notify_all()

    # ---------- 底层发送 ----------

    def _write(self, text: str):
        if self._ser is None:
            raise SerialError("串口未打开")
        data = text.encode("utf-8")
        with self._lock:
            self._ser.write(data)
            self._ser.flush()
        logger.log_serial("TX>", text.rstrip("\n"))

    def send_raw(self, data):
        """裸发送（如复位后发回车唤醒 shell）。"""
        if isinstance(data, str):
            data = data.encode("utf-8")
        with self._lock:
            if self._ser:
                self._ser.write(data)
                self._ser.flush()
        logger.log_serial_raw("TX>", data)

    # ---------- 哨兵匹配核心 ----------

    def _gen_sentinel(self) -> str:
        return f"{_SENTINEL_PREFIX}{secrets.token_hex(4)}__"

    def _wait_pattern(self, pattern: str, timeout: float, start_snapshot: str) -> tuple:
        """等待 pattern 出现在"start_snapshot 之后的新输出"中。

        哨兵 pattern 会出现在两处：(1) 命令回显行 ``cmd; echo <TOKEN>``，
        (2) echo 的真正输出行 ``<TOKEN>``。这里匹配行首的真正输出，避免命中回显。

        Returns:
            (matched_bool, new_text)：new_text 为本次新增的输出（含哨兵行）。
        """
        deadline = time.monotonic() + timeout
        # 匹配行首的哨兵（前面是换行或字符串开头），不匹配回显行里的 "; echo TOKEN"
        pat = re.compile(r"(?:^|\n)" + re.escape(pattern))
        while True:
            full = self._buffer_text()
            new = full[len(start_snapshot):] if full.startswith(start_snapshot) else full
            m = pat.search(new)
            if m:
                # 截到哨兵结束位置
                end = m.end()
                return True, new[:end]
            if time.monotonic() >= deadline:
                return False, new
            with self._cond:
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._cond.wait(timeout=remaining)

    def _wait_regex(self, regex: str, timeout: float, start_snapshot: str) -> tuple:
        """等待正则 regex 匹配新输出，返回 (是否匹配, match对象, 新输出)。"""
        deadline = time.monotonic() + timeout
        pat = re.compile(regex)
        while True:
            full = self._buffer_text()
            new = full[len(start_snapshot):] if full.startswith(start_snapshot) else full
            m = pat.search(ansi.strip(new))
            if m:
                return True, m, new
            if time.monotonic() >= deadline:
                return False, None, new
            with self._cond:
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._cond.wait(timeout=remaining)

    # ---------- 命令执行 ----------

    def exec_sync(self, cmd: str, expect=None, timeout: float = 10.0,
                  error_on_no_sentinel: bool = True) -> Response:
        """执行同步命令：发 ``cmd; echo <TOKEN>``，等哨兵出现定界。

        Args:
            cmd: 要发送的命令（不含换行）。
            expect: 成功判据正则；None 则看无 error 关键字。
            timeout: 等哨兵超时（秒）。
            error_on_no_sentinel: 哨兵超时是否判失败。

        Returns:
            Response：含 raw/clean/success/elapsed_ms/matched/error。
        """
        timer = Timer().start()
        sentinel = self._gen_sentinel()
        # 记录发命令前的缓冲快照，作为"新输出"起点
        snapshot = self._buffer_text()
        # 该 msh 不支持 `;` 分隔命令，改用换行分隔：先发 cmd，再发 echo "TOKEN"
        # echo 必须带引号（固件 echo "string" 用法）
        full_cmd = f'{cmd}\necho "{sentinel}"\n'
        try:
            self._write(full_cmd)
        except SerialError as e:
            return Response(error=str(e), elapsed_ms=timer.elapsed_ms())

        ok, new = self._wait_pattern(sentinel, timeout, snapshot)
        elapsed = timer.elapsed_ms()

        # 响应 = 哨兵前的新输出，去掉回显的命令本身和哨兵行
        resp_raw = self._extract_response(new, cmd, sentinel)
        resp_clean = ansi.strip(resp_raw)

        res = Response(raw=resp_raw, clean=resp_clean, elapsed_ms=elapsed)
        if not ok:
            res.error = f"哨兵超时({timeout}s)，命令可能未执行完"
            if error_on_no_sentinel:
                res.success = False
                return res
            # 否则继续按已有输出判定
        res.success = self._judge(resp_clean, expect)
        if expect and res.success:
            m = re.search(expect, resp_clean)
            if m:
                res.matched = m.group(1) if m.groups() else m.group(0)
        return res

    def exec_async(self, cmd: str, expect: str, send_timeout: float = 5.0,
                   result_timeout: float = 30.0) -> Response:
        """执行异步命令（如 wifi join）。

        该类命令（wifi join）会阻塞 shell 直到连接动作完成，echo 哨兵要等命令
        返回后才输出；而真正的异步结果（Got IP）在 connect 之后才来。故采用
        "发命令+哨兵，直接在 result_timeout 内同时等哨兵和期望正则"的策略：
        只要期望正则出现即判成功，不强制先等哨兵。

        Args:
            cmd: 命令。
            expect: 异步结果的正则（如 Got IP address）。
            send_timeout: 兼容旧参数（已并入 result_timeout）。
            result_timeout: 等待期望结果的总超时（秒）。
        """
        timer = Timer().start()
        sentinel = self._gen_sentinel()
        snapshot = self._buffer_text()
        full_cmd = f'{cmd}\necho "{sentinel}"\n'
        try:
            self._write(full_cmd)
        except SerialError as e:
            return Response(error=str(e), elapsed_ms=timer.elapsed_ms())

        # 直接在 result_timeout 内等期望正则（命令执行期间持续读流）
        matched, m, new = self._wait_regex(expect, result_timeout, snapshot)
        elapsed = timer.elapsed_ms()
        res = Response(raw=new, clean=ansi.strip(new), elapsed_ms=elapsed)
        if matched:
            res.success = True
            res.matched = m.group(1) if m.groups() else m.group(0)
        else:
            res.success = False
            res.error = f"期望结果未出现({result_timeout}s): {expect}"
        return res

    def _extract_response(self, new_text: str, cmd: str, sentinel: str) -> str:
        """从新输出中提取响应：截到"行首哨兵"之前，去掉命令回显行和哨兵行。

        哨兵出现两处：(1) 回显行 ``cmd; echo <sentinel>``，(2) echo 的真正输出行
        ``<sentinel>``。取行首哨兵（前面是换行或串首）作为命令结束标志。
        """
        # 找行首哨兵位置（跳过回显行里的 "; echo sentinel"）
        m = re.search(r"(?:^|\n)" + re.escape(sentinel), new_text)
        if m:
            text = new_text[:m.start()]
        else:
            text = new_text
        # 去掉命令回显行（msh 会回显 "cmd; echo TOKEN"）
        lines = text.splitlines()
        out = []
        for ln in lines:
            if sentinel in ln:
                continue
            clean_ln = ansi.strip(ln).strip()
            if clean_ln and (clean_ln.startswith(cmd) or cmd in clean_ln):
                continue
            out.append(ln)
        return "\n".join(out)

    def _judge(self, clean_text: str, expect) -> bool:
        """判定命令是否成功。"""
        if expect:
            return re.search(expect, clean_text) is not None
        # 无 expect：无 error 关键字即视为成功
        return not _ERROR_RE.search(clean_text)

    # ---------- 启动就绪 ----------

    def wait_for_ready(self, timeout: float = None) -> bool:
        """等待 EVB 启动就绪（FW start ok 或 msh 提示符）。

        若串口打开时已在缓冲中看到就绪标志，立即返回。
        """
        timeout = timeout or self.ready_timeout
        # 主动发回车唤醒 shell，触发提示符输出（EVB 可能已启动完，不再主动打印）
        try:
            self.send_raw("\n")
        except Exception:
            pass
        deadline = time.monotonic() + timeout
        # 先看已有缓冲
        if _READY_RE.search(ansi.strip(self._buffer_text())):
            logger.info("EVB 已就绪")
            return True
        while time.monotonic() < deadline:
            snapshot = self._buffer_text()
            matched, _, _ = self._wait_regex(_READY_RE.pattern, 1.0, snapshot)
            if matched:
                logger.info("EVB 已就绪")
                return True
            # 仍无提示符，再发回车
            try:
                self.send_raw("\n")
            except Exception:
                pass
        logger.error(f"等待 EVB 就绪超时({timeout}s)")
        return False

    # ---------- 自检 ----------

    def health_check(self) -> bool:
        """打开后的自检：发一次 echo，确认收发链路正常（波特率对、不乱码）。

        用于验证非标波特率 250000/2000000 是否被 USB-串口芯片支持。
        echo 命令必须带引号（该固件 echo "string" 用法）。
        """
        try:
            r = self.exec_sync('echo "EVBTEST_HELLO"', expect=r"EVBTEST_HELLO", timeout=5.0)
            if not r.success:
                logger.error(f"串口自检失败: 收发异常或波特率不匹配。输出: {r.clean!r}")
                return False
            logger.debug("串口自检通过")
            return True
        except Exception as e:
            logger.error(f"串口自检异常: {e}")
            return False


# ---------- 自动探测 ----------

def _list_candidate_ports() -> list:
    """枚举当前用户可访问的 /dev/ttyUSB* 和 /dev/ttyACM*。"""
    ports = sorted(set(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")))
    accessible = []
    for p in ports:
        if os.access(p, os.R_OK | os.W_OK):
            accessible.append(p)
    return accessible


def _probe_port_baud(port: str, baudrate: int, detect_timeout: float = 2.0) -> bool:
    """用指定端口+波特率探测是否为 EVB：发 \\n 后读输出匹配指纹。"""
    if serial is None:
        return False
    try:
        s = serial.Serial(port, baudrate, timeout=detect_timeout, write_timeout=1.0)
    except Exception:
        return False
    try:
        s.reset_input_buffer()
        # 发回车唤醒 shell
        s.write(b"\n")
        s.flush()
        time.sleep(0.3)
        data = b""
        end = time.monotonic() + detect_timeout
        while time.monotonic() < end:
            chunk = s.read(256)
            if chunk:
                data += chunk
            else:
                break
        if not data:
            return False
        text = data.decode("utf-8", errors="replace")
        return bool(_FINGERPRINT_RE.search(ansi.strip(text)))
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def detect_port(baudrate: int = 2000000,
                baud_candidates=None,
                interactive: bool = True,
                detect_timeout: float = 2.0):
    """自动探测 EVB 串口。

    遍历候选端口 × 候选波特率，用指纹匹配。默认波特率优先，探不到则回退候选列表。

    Args:
        baudrate: 优先尝试的波特率（配置里的默认值）。
        baud_candidates: 回退候选波特率列表；None 用默认 [2000000,250000,115200,921600]。
        interactive: 多个匹配时是否交互让用户选。
        detect_timeout: 每个组合的探测超时。

    Returns:
        (port, baudrate) 元组；未探测到返回 (None, None)。
    """
    if serial is None:
        raise SerialError("缺少 pyserial 依赖，请先 pip install pyserial")
    candidates = list(baud_candidates) if baud_candidates else list(DEFAULT_BAUD_CANDIDATES)
    # 优先尝试默认波特率，再去重其余候选
    ordered = [baudrate] + [b for b in candidates if b != baudrate]

    ports = _list_candidate_ports()
    if not ports:
        logger.error("未发现任何可访问的串口设备 (/dev/ttyUSB* /dev/ttyACM*)")
        logger.error("请检查: 1) EVB 已上电并连接  2) 当前用户在 dialout 组  3) USB-串口驱动已加载")
        return None, None

    logger.info(f"开始自动探测 EVB 串口，候选端口 {ports}，候选波特率 {ordered}")
    matches = []
    for port in ports:
        for baud in ordered:
            logger.debug(f"探测 {port} @ {baud} ...")
            if _probe_port_baud(port, baud, detect_timeout):
                logger.info(f"  命中 EVB 指纹: {port} @ {baud}")
                matches.append((port, baud))
                break  # 该端口已命中，不再试其他波特率

    if not matches:
        logger.error("未探测到 EVB 串口（无指纹匹配）。请确认 EVB 已启动到 msh。")
        return None, None
    if len(matches) == 1:
        port, baud = matches[0]
        logger.info(f"探测到 EVB: {port} @ {baud}")
        return port, baud
    # 多个匹配：交互选择
    logger.info("探测到多个候选 EVB 串口:")
    for i, (p, b) in enumerate(matches):
        print(f"  [{i}] {p} @ {b}")
    if not interactive:
        return matches[0]
    while True:
        try:
            sel = input(f"请选择 [0-{len(matches)-1}] (默认0): ").strip()
            sel = int(sel) if sel else 0
            return matches[sel]
        except (ValueError, IndexError):
            print("输入无效，请重试")
