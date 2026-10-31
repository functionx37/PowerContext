"""Run SmartStudy and the official PowerContext server with persistent local data."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def wait_ready(url, process, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("服务启动失败，请检查数据目录中的日志。")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError("服务就绪超时，请检查数据目录中的日志。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pc-port", type=int, default=8000)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".runtime")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    runtime = args.data_dir.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    stop = runtime / "stop-request"
    if args.stop:
        stop.touch()
        return
    if args.pc_port == args.port:
        parser.error("两个服务必须使用不同端口。")
    for port in (args.pc_port, args.port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"端口 {port} 已被占用，请用 --pc-port / --port 指定空闲端口。")
    load_dotenv(ROOT / ".env")
    # A local run is explicit and isolated from other projects' PC/model settings.
    env = {key: value for key, value in os.environ.items() if not key.startswith("POWERCONTEXT_")}
    env.update(
        POWERCONTEXT_HOME=str(runtime / "powercontext"),
        POWERCONTEXT_SERVER_WORKSPACE=str(runtime),
        POWERCONTEXT_SERVER_DATABASE_KIND="sqlite",
        POWERCONTEXT_SERVER_DATABASE_URL="sqlite+aiosqlite:///" + (runtime / "state.db").as_posix(),
        POWERCONTEXT_SERVER_ACCESS_MODE="disabled",
        POWERCONTEXT_SERVER_MCP_ENABLED="false",
        POWERCONTEXT_SERVER_DASHBOARD_ENABLED="false",
        POWERCONTEXT_URL=f"http://127.0.0.1:{args.pc_port}",
        POWERCONTEXT_SCOPE_ID=os.getenv("POWERCONTEXT_SCOPE_ID", "smartstudy-default"),
        POWERCONTEXT_TOKEN="",
        PYTHONIOENCODING="utf-8",
        PYTHONUNBUFFERED="1",
    )
    commands = [
        [sys.executable, "-c", "from powercontext.cli.app import main; main()", "server", "run",
         "--host", "127.0.0.1", "--port", str(args.pc_port), "--no-env-file"],
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(args.port)],
    ]
    processes, logs = [], []
    stop.unlink(missing_ok=True)
    try:
        for command, name, cwd, ready in zip(
            commands, ("powercontext", "smartstudy"), (runtime, ROOT),
            (f"http://127.0.0.1:{args.pc_port}/health/ready", f"http://127.0.0.1:{args.port}/api/health"),
        ):
            log = (runtime / f"{name}.log").open("a", encoding="utf-8")
            logs.append(log)
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
            processes.append(process)
            wait_ready(ready, process)
        with urlopen(f"http://127.0.0.1:{args.port}/api/health", timeout=30) as response:
            health = json.load(response)
        if health.get("powercontext") != "connected":
            raise RuntimeError(f"学习数据空间初始化失败：{health.get('detail', '请检查日志')}")
        print(f"SmartStudy: http://127.0.0.1:{args.port}", flush=True)
        print(f"PowerContext: http://127.0.0.1:{args.pc_port} | data: {runtime}", flush=True)
        print("Ctrl+C 停止；再次运行会保留学习记录。", flush=True)
        while not stop.exists():
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("有服务提前退出，请检查日志。")
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
