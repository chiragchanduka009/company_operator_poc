import json, os, subprocess, sys, time, urllib.request, urllib.error
from pathlib import Path
root=Path(__file__).parent
env=os.environ.copy(); env["PORT"]="8765"
p=subprocess.Popen([sys.executable,str(root/"app.py")],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    for _ in range(40):
        try:
            urllib.request.urlopen("http://127.0.0.1:8765/api/state",timeout=1); break
        except Exception: time.sleep(.15)
    def post(path, obj):
        req=urllib.request.Request("http://127.0.0.1:8765"+path,data=json.dumps(obj).encode(),headers={"Content-Type":"application/json"})
        return json.loads(urllib.request.urlopen(req).read())
    post("/api/reset",{})
    t=post("/api/run",{"goal":"Review invoice INV-1042 and prepare a payment request"})["task"]
    assert t["status"]=="WAITING_APPROVAL", t["status"]
    assert all(t["evidence"]["verification"].values())
    post("/api/approve",{"task_id":t["id"]})
    s=json.loads(urllib.request.urlopen("http://127.0.0.1:8765/api/state").read())
    assert s["tasks"][0]["status"]=="APPROVED"
    post("/api/reset",{})
    t=post("/api/run",{"goal":"Review invoice INV-1044 and prepare a payment request"})["task"]
    assert t["status"]=="BLOCKED", t["status"]
    assert not any(d["invoice_id"]=="INV-1044" for d in json.loads(urllib.request.urlopen("http://127.0.0.1:8765/api/state").read())["drafts"])
    post("/api/reset",{})
    t=post("/api/run",{"goal":"Prepare a payment request"})["task"]
    assert t["status"]=="NEEDS_INPUT", t["status"]
    print("PASS: happy path + verification + approval, missing-evidence block, clarification")
finally:
    p.terminate()
    try: p.wait(timeout=3)
    except: p.kill()
