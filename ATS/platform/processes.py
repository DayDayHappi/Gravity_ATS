"""直接子进程的跨平台生命周期（不启动 shell，不管理外部 nginx）。

FFmpeg/ffprobe/ffplay 均直接执行，因此只回收本次创建的 Popen 对象，
不按进程名 taskkill/pkill，不碰用户自己的播放器或 RTMP 服务。
"""
import os
import subprocess

IS_WINDOWS = os.name == "nt"


def spawn(argv, **kwargs):
    """启动 argv 列表；隔离终端 Ctrl+C，由调用方 finally 负责清理。"""
    if isinstance(argv, (str, bytes)) or not argv:
        raise ValueError("子进程必须使用非空 argv 列表")
    if kwargs.pop("shell", False):
        raise ValueError("ATS 工具不允许 shell=True")
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    if IS_WINDOWS:
        # 新进程组避免控制台 Ctrl+C 先杀工具，破坏主进程的报告/清理流程。
        kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
                          | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    else:
        kwargs.setdefault("start_new_session", True)
    return subprocess.Popen(list(argv), shell=False, **kwargs)


def terminate_process(proc, timeout=3.0):
    """终止并等待本次直接子进程；超时升级 kill。幂等，返回是否已退出。"""
    if proc is None:
        return True
    if proc.poll() is not None:
        return True
    try:
        proc.terminate()
    except (ProcessLookupError, OSError):
        pass
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            return False


def run_capture(argv, timeout=30.0):
    """用于小输出命令；超时/异常/KeyboardInterrupt 均回收后再抛出。"""
    proc = spawn(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                 text=True, encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(list(argv), proc.returncode, out, err)
    except BaseException:
        terminate_process(proc)
        raise
    finally:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()
