"""Start real PowerContext and the bridge, keeping all data inside this project."""
import argparse
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pc-port", type=int, default=8000)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1", help="Docker Dify 访问宿主机时用 0.0.0.0")
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".runtime")
    parser.add_argument("--stop", action="store_true", help="停止使用同一 data-dir 启动的本项目服务")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    runtime = args.data_dir.resolve()
    runtime.mkdir(exist_ok=True)
    stop_file = runtime / "stop-request"
    if args.stop:
        stop_file.touch()
        return
    key_file = runtime / "shop-key.txt"
    token = os.getenv("SHOP_API_KEY") or (key_file.read_text().strip() if key_file.exists() else secrets.token_urlsafe(32))
    if len(token) < 16:
        parser.error("SHOP_API_KEY 至少需要 16 字符。")
    key_file.write_text(token, encoding="utf-8")
    for port in (args.pc_port, args.port):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"端口 {port} 已被占用，请选择空闲端口；不会复用或结束已有服务。")
    stop_file.unlink(missing_ok=True)
    env = os.environ.copy()
    env.update(POWERCONTEXT_HOME=str(runtime / "powercontext"),
               POWERCONTEXT_SERVER_WORKSPACE=str(runtime),
               POWERCONTEXT_SERVER_MCP_ENABLED="false",
               POWERCONTEXT_SERVER_DASHBOARD_ENABLED="false",
               SHOP_API_KEY=token, POWERCONTEXT_URL=f"http://127.0.0.1:{args.pc_port}",
               PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    # Only bind PowerContext to loopback. Only the authenticated bridge may be exposed.
    pc_command = [sys.executable, "-c", "from powercontext.cli.app import main; main()",
                  "server", "run", "--host", "127.0.0.1", "--port", str(args.pc_port), "--no-env-file"]
    bridge_command = [sys.executable, "-m", "uvicorn", "server:app", "--host", args.host,
                      "--port", str(args.port), "--workers", "1"]
    processes = []
    try:
        with (runtime / "powercontext.log").open("a", encoding="utf-8") as pc_log:
            process = subprocess.Popen(pc_command, cwd=runtime, env=env, stdout=pc_log, stderr=subprocess.STDOUT)
            processes.append(process)
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError("PowerContext 启动失败，请检查 .runtime/powercontext.log")
                try:
                    with urlopen(f"http://127.0.0.1:{args.pc_port}/health/ready", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.5)
            else:
                raise RuntimeError("PowerContext 就绪超时，请检查 .runtime/powercontext.log")
            processes.append(subprocess.Popen(bridge_command, cwd=ROOT, env=env))
            print(f"PowerContext: http://127.0.0.1:{args.pc_port}", flush=True)
            print(f"Bridge: http://127.0.0.1:{args.port}/docs", flush=True)
            print("Dify SHOP_API_KEY：读取 dify/.runtime/shop-key.txt（请勿提交）。", flush=True)
            print("按 Ctrl+C 停止；存档保留在 dify/.runtime/powercontext。", flush=True)
            while all(p.poll() is None for p in processes) and not stop_file.exists():
                time.sleep(0.5)
            if not stop_file.exists():
                raise RuntimeError("有服务提前退出，请检查运行日志。")
    except KeyboardInterrupt:
        print("正在停止本次启动的服务。")
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
