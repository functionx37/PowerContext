"""Start the official PowerContext server, keeping its data in this project."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18800)
    parser.add_argument('--data-dir', type=Path, default=ROOT / '.runtime' / 'powercontext')
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    runtime = args.data_dir.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    stop = runtime / 'stop-request'
    if args.stop:
        stop.touch()
        return
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', args.port))
    stop.unlink(missing_ok=True)
    # Use only explicit project-local PowerContext settings. Model inference is not
    # needed by the explicit remember/list API used by this module.
    env = {k: v for k, v in os.environ.items() if not k.startswith('POWERCONTEXT_')}
    env.update(POWERCONTEXT_HOME=str(runtime / 'home'), POWERCONTEXT_SERVER_WORKSPACE=str(runtime),
               POWERCONTEXT_SERVER_DATABASE_KIND='sqlite',
               POWERCONTEXT_SERVER_DATABASE_URL='sqlite+aiosqlite:///' + (runtime / 'state.db').as_posix(),
               POWERCONTEXT_SERVER_MCP_ENABLED='false', POWERCONTEXT_SERVER_DASHBOARD_ENABLED='false',
               POWERCONTEXT_SERVER_ACCESS_MODE='disabled', PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    command = [sys.executable, '-c', 'from powercontext.cli.app import main; main()',
               'server', 'run', '--host', '127.0.0.1', '--port', str(args.port), '--no-env-file']
    with (runtime / 'server.log').open('a', encoding='utf-8') as log:
        server = subprocess.Popen(command, cwd=runtime, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(120):
                if server.poll() is not None:
                    raise RuntimeError('PowerContext exited; inspect ' + str(runtime / 'server.log'))
                try:
                    with urlopen(f'http://127.0.0.1:{args.port}/health/ready', timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(.25)
            else:
                raise RuntimeError('PowerContext startup timeout')
            print(f'PowerContext ready: http://127.0.0.1:{args.port}', flush=True)
            while server.poll() is None and not stop.exists():
                time.sleep(.2)
            if server.poll() is not None:
                raise RuntimeError('PowerContext exited unexpectedly')
        except KeyboardInterrupt:
            pass
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == '__main__':
    main()
