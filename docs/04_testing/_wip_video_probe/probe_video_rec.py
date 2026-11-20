import serial, time, re, json, sys, os

PORT="COM23"; BAUD=2000000
OUT="C:/Users/x-jwwang/AppData/Local/Temp/video_rec_results.jsonl"
ANSI=re.compile(r'\x1b\[[0-9;]*m')
NOISE=("AE]","perf]","DfsSend","NO_TAG","I/cam","W/cam","D/cam","E/cam","I/NO_TAG")
def strip(x): return ANSI.sub('',x)

class B:
    def __init__(s):
        s.s=serial.Serial(PORT,BAUD,timeout=0.1,write_timeout=2.0)
        s.s.reset_input_buffer()
    def wr(s,t):
        d=t.encode()
        for i in range(0,len(d),32):
            s.s.write(d[i:i+32]); s.s.flush(); time.sleep(0.06)
    def rd(s,sec):
        t=time.time();b=""
        while time.time()-t<sec:
            c=s.s.read(8192)
            if c: b+=strip(c.decode('utf-8','ignore'))
            else: time.sleep(0.02)
        return b
    def ctl(s):  # control-plane lines only
        return lambda txt: [l.strip() for l in txt.split("\n")
                            if l.strip() and not any(n in l for n in NOISE)]
    def close(s):
        try:s.s.close()
        except:pass

def ping(b,tmo=4.0):
    b.s.reset_input_buffer()
    tok=f"VG{int(time.time()*1000)%999999}"
    b.wr(f'echo "{tok}"\n')
    end=time.time()+tmo
    while time.time()<end:
        if tok in b.rd(0.3): return True
    return False

def record(b, setcmd):
    # 1. SET
    b.s.reset_input_buffer()
    b.wr(setcmd+"\n")
    setr=b.rd(1.0)
    setlines=[l.strip() for l in setr.split("\n") if l.strip() and not any(n in l for n in NOISE)]
    smsg=next((l for l in setlines if "video:" in l), None)
    serr=next((l for l in setlines if any(k in l for k in ["Too many","needs a value","unknown","not supported","not allowed"])), None)
    applied=smsg.split("video:")[-1].strip() if smsg else None
    if not smsg:
        return {"result":"SET_FAIL","applied":None,"detail":serr or (setlines[-1] if setlines else "no reply")}
    # 2. START
    b.s.reset_input_buffer()
    b.wr("cam_run video start\n")
    startr=b.rd(6.0)
    if "cam start success" not in startr and "Record Start" not in startr and "f_index" not in startr:
        alive=ping(b)
        return {"result":"START_FAIL" if alive else "HANG","applied":applied,
                "detail":_lastctl(startr)}
    # 3. let it run a bit to produce frames
    time.sleep(3.0)
    # 4. STOP
    b.s.reset_input_buffer()
    b.wr("cam_run video stop\n")
    stopr=b.rd(10.0)
    if "Video recording completed successfully." in stopr:
        m=re.search(r'Save Video Successful:\s*(\S+)', stopr)
        return {"result":"OK","applied":applied,"file":(m.group(1) if m else None),"detail":""}
    alive=ping(b)
    err=next((l.strip() for l in stopr.split("\n") if any(k in l for k in ["E/","fail","error","failed","not supported"]) and not any(n in l for n in NOISE)), None)
    return {"result":"REC_FAIL" if alive else "HANG","applied":applied,"detail":err or _lastctl(stopr)}

def _lastctl(txt):
    ls=[l.strip() for l in txt.split("\n") if l.strip() and not any(n in l for n in NOISE)]
    return " | ".join(ls[-3:])[:160]

# ---- grid ----
# unique valid res/fps/eis (from SET sweep)
VALID=[("3k",30,2),
       ("1080p",30,0),("1080p",30,1),("1080p",30,2),
       ("sd1080p",30,0),("sd1080p",30,1),("sd1080p",30,2),
       ("sd1080p",60,0),("sd1080p",60,1),("sd1080p",60,2),
       ("720p",30,0),("720p",30,1),("720p",30,2),
       ("720p",60,0),("720p",60,1),("720p",60,2),
       ("480p",30,0),("480p",30,1),("480p",30,2),
       ("480p",60,0),("480p",60,1),("480p",60,2)]

FMT=[("h264","h265")]
VUI=[("709","6010","6011")]

tasks=[]
# family A: format
for res,fps,eis in VALID:
    for fmt in ["h264","h265"]:
        tasks.append((f"cam_set video {res} fps {fps} eis {eis} format {fmt}",
                      {"res":res,"fps":fps,"eis":eis,"fmt":fmt,"vui":None}))
# family B: vui
for res,fps,eis in VALID:
    for vui in ["709","6010","6011"]:
        tasks.append((f"cam_set video {res} fps {fps} eis {eis} vui {vui}",
                      {"res":res,"fps":fps,"eis":eis,"fmt":None,"vui":vui}))

# family selectable via argv: --family A|B, --limit N, --append (resume: skip done)
fam = "A"; lim=None; append=False
for a in sys.argv[1:]:
    if a.startswith("--family="): fam=a.split("=",1)[1]
    elif a.startswith("--limit="): lim=int(a.split("=",1)[1])
    elif a=="--append": append=True
if fam=="A":
    tasks=[t for t in tasks if t[1]["fmt"] is not None]
elif fam=="B":
    tasks=[t for t in tasks if t[1]["vui"] is not None]

OUT=f"C:/Users/x-jwwang/AppData/Local/Temp/video_rec_{fam}.jsonl"
# 断点续跑：--append 时读已完成的 jsonl，跳过已跑组合（status 非 OK 的也跳过，避免重复跑坏档）
done=set()
if append and os.path.exists(OUT):
    for line in open(OUT,encoding="utf-8"):
        try:
            j=json.loads(line); done.add((j["res"],j["fps"],j["eis"],j["fmt"],j["vui"]))
        except Exception: pass
    tasks=[t for t in tasks if (t[1]["res"],t[1]["fps"],t[1]["eis"],t[1]["fmt"],t[1]["vui"]) not in done]
    print(f"[resume] 已完成 {len(done)} 条，跳过；本轮待跑 {len(tasks)} 条",flush=True)
if lim: tasks=tasks[:lim]

out=open(OUT,"a" if append else "w",encoding="utf-8")
b=B(); results=[]; stop=False
for i,(cmd,meta) in enumerate(tasks,1):
    if stop:
        results.append({**meta,"result":"SKIPPED"});
        out.write(json.dumps({**meta,"result":"SKIPPED"},ensure_ascii=False)+"\n"); continue
    r=record(b,cmd)
    rec={**meta, **r}
    results.append(rec); out.write(json.dumps(rec,ensure_ascii=False)+"\n"); out.flush()
    print(f"[{i:3d}/{len(tasks)}] {r['result']:10s} {cmd[15:]}  {('| applied='+r['applied']) if r.get('applied') else ''} {r.get('detail','')[:60]}",flush=True)
    if r["result"]=="HANG":
        print("  !! board HANG -> stop",flush=True); stop=True
    time.sleep(0.5)
b.close(); out.close()
ok=sum(1 for r in results if r["result"]=="OK")
print(f"\nDONE total={len(results)} OK={ok}")
