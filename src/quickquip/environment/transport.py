"""Private local transport; Docker consumers never mount the project environment file."""
import json
import os
from pathlib import Path
import socket
import socketserver

from quickquip.common.env import PROJECT_ROOT
from quickquip.environment.store import Store, EnvironmentError

LIMIT = 2 * 1024 * 1024


def call(action, body=None):
    address = os.environ.get('QUICKQUIP_ENV_SOCKET')
    if action in ('preview', 'changes'):
        address = os.environ.get('QUICKQUIP_ENV_WRITE_SOCKET', address)
    if not address:
        if os.getenv('QUICKQUIP_MANAGED_CONTAINER') == '1':
            raise EnvironmentError('Adopt the environment agent Compose template first')
        return Store(PROJECT_ROOT).execute(action, body)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(15)
        client.connect(address)
        client.sendall(json.dumps({'action': action, 'body': body or {}}).encode() + b'\n')
        with client.makefile('rb') as stream:
            raw = stream.readline(LIMIT + 1)
        if len(raw) > LIMIT:
            raise EnvironmentError('Environment response too large')
    result = json.loads(raw)
    if 'error' in result:
        raise EnvironmentError(result['error'])
    return result


def main():
    root = Path(os.environ['QUICKQUIP_ENV_ROOT'])
    address = Path(os.environ['QUICKQUIP_ENV_SOCKET'])
    address.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = Store(root)

    class Handler(socketserver.StreamRequestHandler):
        writable = False
        def handle(self):
            try:
                self.request.settimeout(15)
                raw = self.rfile.readline(LIMIT + 1)
                if len(raw) > LIMIT:
                    raise EnvironmentError('Request too large')
                if not raw:
                    return
                request = json.loads(raw)
                if request['action'] in ('preview', 'changes') and not self.writable:
                    raise EnvironmentError('Read-only environment endpoint')
                result = store.execute(request['action'], request.get('body'))
            except (ValueError, OSError, KeyError, TypeError):
                result = {'error': 'Environment operation failed; refresh or retry'}
            self.wfile.write(json.dumps(result).encode() + b'\n')

    class Writer(Handler):
        writable = True

    writer = Path(os.environ['QUICKQUIP_ENV_WRITE_SOCKET'])
    writer.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A process lease prevents unlinking another live agent's listening socket.
    from filelock import FileLock
    with FileLock(str(address) + '.lock', timeout=0):
        address.unlink(missing_ok=True)
        writer.unlink(missing_ok=True)
        with (
            socketserver.ThreadingUnixStreamServer(str(address), Handler) as server,
            socketserver.ThreadingUnixStreamServer(str(writer), Writer) as write_server,
        ):
            os.chmod(address, 0o600)
            os.chmod(writer, 0o600)
            import threading
            write_server.daemon_threads = True
            threading.Thread(target=write_server.serve_forever, daemon=True).start()
            server.daemon_threads = True
            server.serve_forever()


if __name__ == '__main__':
    main()
