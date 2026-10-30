"""Run official seekdb and PowerContext with a project-local data directory."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

import pylibseekdb

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=ROOT / '.runtime' / 'services')
    parser.add_argument('--ready-file', type=Path, default=ROOT / '.runtime' / 'connection.json')
    parser.add_argument('--port', type=int, default=18800)
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    runtime = args.data_dir.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    stop = runtime / 'stop-request'
    if args.stop:
        stop.touch()
        return
    stop.unlink(missing_ok=True)
    ready = args.ready_file.resolve()
    ready.parent.mkdir(parents=True, exist_ok=True)
    ready.unlink(missing_ok=True)
    server = None
    db = pylibseekdb.open(str(runtime / 'seekdb'))
    try:
        endpoint = db.connection_options()
        # The runtime supplies a random loopback TCP port; only publish nonsecret fields.
        if endpoint.get('host') != '127.0.0.1' or not endpoint.get('port'):
            raise RuntimeError('Expected a loopback seekdb TCP endpoint')
        command = [sys.executable, '-u', str(ROOT / 'tools' / 'powercontext_service.py'),
                   '--port', str(args.port), '--data-dir', str(runtime / 'powercontext')]
        server = subprocess.Popen(command)
        for _ in range(160):
            if server.poll() is not None:
                raise RuntimeError('PowerContext launcher exited')
            try:
                with urlopen(f'http://127.0.0.1:{args.port}/health/ready', timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.25)
        else:
            raise RuntimeError('PowerContext startup timeout')
        value = {'seekdb': {k: endpoint[k] for k in ('host', 'port', 'user')},
                 'powercontext_url': f'http://127.0.0.1:{args.port}', 'launcher_pid': __import__('os').getpid()}
        ready.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        print('SDD services ready; connection: ' + str(ready), flush=True)
        while not stop.exists() and server.poll() is None:
            time.sleep(.2)
    except KeyboardInterrupt:
        pass
    finally:
        ready.unlink(missing_ok=True)
        if server is not None and server.poll() is None:
            (runtime / 'powercontext' / 'stop-request').touch()
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.terminate()
                server.wait()
        db.close()


if __name__ == '__main__':
    main()
