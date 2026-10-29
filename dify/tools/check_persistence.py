"""Real process restart test against an isolated, retained PowerContext database."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from game import adjudicate


def main():
    runtime = ROOT / ".runtime" / ("persistence-" + uuid.uuid4().hex[:8])
    runtime.mkdir(parents=True)
    command = [sys.executable, str(ROOT / "tools/run_local.py"), "--data-dir", str(runtime),
               "--pc-port", "18000", "--port", "18765"]
    client = httpx.Client(trust_env=False, timeout=40)
    runs = []

    def start():
        handle = (runtime / "launcher.log").open("a", encoding="utf-8")
        process = subprocess.Popen(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
        for _ in range(150):
            if process.poll() is not None:
                raise RuntimeError("Launcher exited; inspect " + str(runtime / "launcher.log"))
            try:
                if client.get("http://127.0.0.1:18765/health").status_code == 200:
                    return process, handle
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
        (runtime / "stop-request").touch()
        process.wait(timeout=30)
        handle.close()
        raise RuntimeError("Restart test startup timed out")

    def stop(process, handle):
        (runtime / "stop-request").touch()
        process.wait(timeout=30)
        handle.close()

    payload = {"player_id": "restart-player", "action": "恶作剧", "line": "把算盘换成了爆米花", "request_id": "before-restart"}
    process, handle = start()
    try:
        headers = {"X-Shop-Key": (runtime / "shop-key.txt").read_text().strip()}
        r = client.post("http://127.0.0.1:18765/v1/turns/prepare", json=payload, headers=headers)
        r.raise_for_status()
        packet = json.loads(adjudicate(r.text)["payload"])
        r = client.post("http://127.0.0.1:18765/v1/turns/commit", json=packet, headers=headers)
        r.raise_for_status()
        before = r.json()
        runs.append({"phase": "before_restart", "result": before})
    finally:
        stop(process, handle)
    process, handle = start()
    try:
        r = client.post("http://127.0.0.1:18765/v1/turns/prepare", json=dict(payload, request_id="after-restart", action="打招呼", line=""), headers=headers)
        r.raise_for_status()
        after = r.json()
        assert before["state"] == after["state"], "State changed across restart"
        assert before["memory_ref"] == after["memory_refs"][-1], "Memory identity changed"
        runs.append({"phase": "after_restart", "result": after})
    finally:
        stop(process, handle)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "result": "passed",
              "execution_mode": "real-powercontext-and-bridge-process-restart", "runs": runs}
    path = ROOT / "evidence/persistence.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS: saved state and ArtifactRef survive both service processes restarting.")


if __name__ == "__main__":
    main()
