"""app 重构后固件：关键字式 cam_set video 全 60 组合录制实测。

- 命令模板（用户文件 / Step0-B 已验证可用）：
    cam_set video <res> fps <fps> eis <eis> format <fmt> bitrate 18000000 gop 30 vui 709
- 每条：SET -> cam_run video start -> 录 5s -> cam_run video stop
- 判据：Video recording completed successfully. + 落盘 Save Video Successful: <path>
- 带 HANG 存活检测（ping），HANG 即停。
"""
import serial, time, re, json, sys, os

PORT = os.environ.get("PROBE_PORT", "COM21")
BAUD = 2000000
OUT = "C:/Users/x-jwwang/AppData/Local/Temp/video_rec_kw60.jsonl"
ANSI = re.compile(r'\x1b\[[0-9;]*m')
NOISE = ("AE]", "perf]", "DfsSend", "NO_TAG", "I/cam", "W/cam", "D/cam", "E/cam", "I/NO_TAG")


def strip(x):
    return ANSI.sub('', x)


class B:
    def __init__(s):
        s.s = serial.Serial(PORT, BAUD, timeout=0.1, write_timeout=2.0)
        s.s.reset_input_buffer()

    def wr(s, t):
        d = t.encode()
        for i in range(0, len(d), 32):
            s.s.write(d[i:i + 32])
            s.s.flush()
            time.sleep(0.06)

    def rd(s, sec):
        t = time.time()
        b = ""
        while time.time() - t < sec:
            c = s.s.read(8192)
            if c:
                b += strip(c.decode('utf-8', 'ignore'))
            else:
                time.sleep(0.02)
        return b

    def rd_until(s, sec, pred):
        """读取直到 pred(text) 为真或超时；返回累积文本。"""
        t = time.time()
        b = ""
        while time.time() - t < sec:
            c = s.s.read(8192)
            if c:
                b += strip(c.decode('utf-8', 'ignore'))
                if pred(b):
                    return b
            else:
                time.sleep(0.02)
        return b

    def close(s):
        try:
            s.s.close()
        except Exception:
            pass


def ping(b, tmo=4.0):
    b.s.reset_input_buffer()
    tok = f"VG{int(time.time() * 1000) % 999999}"
    b.wr(f'echo "{tok}"\n')
    end = time.time() + tmo
    while time.time() < end:
        if tok in b.rd(0.3):
            return True
    return False


def _ctl(txt):
    return [l.strip() for l in txt.split("\n")
            if l.strip() and not any(n in l for n in NOISE)]


def _lastctl(txt):
    return " | ".join(_ctl(txt)[-3:])[:200]


ERR_KEYS = ["Too many", "needs a value", "unknown", "not supported",
            "not allowed", "bare number", "invalid", "usage", "error", "failed", "fail"]


def set_video(b, cmd):
    b.s.reset_input_buffer()
    b.wr(cmd + "\n")
    setr = b.rd_until(2.5, lambda t: ("video:" in t) or any(k in t for k in ERR_KEYS))
    lines = _ctl(setr)
    smsg = next((l for l in lines if "video:" in l), None)
    serr = next((l for l in lines if any(k in l for k in ERR_KEYS)), None)
    applied = smsg.split("video:")[-1].strip() if smsg else None
    # 取固件原文（第一个含 E/ 或 I/CtrlCfg 的整行）
    raw = next((l for l in lines if ("CtrlCfg" in l or l.startswith("E/") or "Usage" in l)), (lines[-1] if lines else ""))
    return applied, serr, raw


def record(b, meta):
    cmd = (f"cam_set video {meta['res']} fps {meta['fps']} eis {meta['eis']} "
           f"format {meta['fmt']} bitrate 18000000 gop 30 vui 709")
    applied, serr, raw = set_video(b, cmd)
    if not applied:
        return {"result": "SET_FAIL", "applied": None,
                "detail": serr or raw, "raw": raw}

    # START
    b.s.reset_input_buffer()
    b.wr("cam_run video start\n")
    startr = b.rd(6.0)
    if ("cam start success" not in startr and "Record Start" not in startr
            and "f_index" not in startr):
        alive = ping(b)
        return {"result": "START_FAIL" if alive else "HANG", "applied": applied,
                "detail": _lastctl(startr), "raw": raw}

    # 录 5s
    time.sleep(5.0)
    # STOP
    b.s.reset_input_buffer()
    b.wr("cam_run video stop\n")
    stopr = b.rd_until(12.0, lambda t: "Video recording completed successfully." in t)
    if "Video recording completed successfully." in stopr:
        m = re.search(r'Save Video Successful:\s*(\S+)', stopr)
        return {"result": "OK", "applied": applied,
                "file": (m.group(1) if m else None), "detail": "", "raw": raw}
    alive = ping(b)
    err = next((l.strip() for l in stopr.split("\n")
                if any(k in l for k in ["E/", "fail", "error", "failed", "not supported"])
                and not any(n in l for n in NOISE)), None)
    return {"result": "REC_FAIL" if alive else "HANG", "applied": applied,
            "detail": err or _lastctl(stopr), "raw": raw}


RES = ["3k", "1080p", "sd1080p", "720p", "480p"]
tasks = []
for res in RES:
    for fps in (30, 60):
        for eis in (0, 1, 2):
            for fmt in ("h264", "h265"):
                tasks.append(({"res": res, "fps": fps, "eis": eis, "fmt": fmt}, None))

append = "--append" in sys.argv
lim = None
for a in sys.argv[1:]:
    if a.startswith("--limit="):
        lim = int(a.split("=", 1)[1])

done = set()
if append and os.path.exists(OUT):
    for line in open(OUT, encoding="utf-8"):
        try:
            j = json.loads(line)
            done.add((j["res"], j["fps"], j["eis"], j["fmt"]))
        except Exception:
            pass
    tasks = [t for t in tasks if (t[0]["res"], t[0]["fps"], t[0]["eis"], t[0]["fmt"]) not in done]
    print(f"[resume] 已完成 {len(done)} 条，跳过；本轮待跑 {len(tasks)} 条", flush=True)
if lim:
    tasks = tasks[:lim]

out = open(OUT, "a" if append else "w", encoding="utf-8")
b = B()
stop = False
n_ok = n_setfail = n_recfail = n_hang = 0
for i, (meta, _) in enumerate(tasks, 1):
    if stop:
        out.write(json.dumps({**meta, "result": "SKIPPED"}, ensure_ascii=False) + "\n")
        continue
    r = record(b, meta)
    rec = {**meta, **r}
    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    out.flush()
    cmd = f"video {meta['res']} fps{meta['fps']} eis{meta['eis']} {meta['fmt']}"
    tag = f"applied={r.get('applied')}" if r.get('applied') else ''
    print(f"[{i:2d}/{len(tasks)}] {r['result']:10s} {cmd:40s} {tag} {r.get('detail','')[:70]}", flush=True)
    if r["result"] == "OK":
        n_ok += 1
    elif r["result"] == "SET_FAIL":
        n_setfail += 1
    elif r["result"] == "REC_FAIL":
        n_recfail += 1
    elif r["result"] == "HANG":
        n_hang += 1
        print("  !! board HANG -> stop", flush=True)
        stop = True
    time.sleep(0.5)

b.close()
out.close()
print(f"\nDONE total={len(tasks)} OK={n_ok} SET_FAIL={n_setfail} REC_FAIL={n_recfail} HANG={n_hang}")
