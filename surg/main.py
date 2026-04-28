import logging
import os
import socket
import subprocess
import sys
import time

_surg_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(_surg_dir)
for _p in [_repo_root, _surg_dir]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import uvicorn

from config import load_config, ensure_operator_name
from grpc_client import GrpcClient
from socket_server import app, sio, setup
from streams import IdleTracker


def _port_open(host: str, port: str) -> bool:
    try:
        s = socket.socket()
        s.settimeout(1)
        s.connect((host, int(port)))
        s.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False


def _grus_ready(cfg: dict) -> bool:
    svc = cfg.get('grus', {}).get('services', {})
    addrs = [
        svc.get('flag_store',       'localhost:50051'),
        svc.get('policy_evaluator', 'localhost:50052'),
        svc.get('broadcaster',      'localhost:50053'),
        svc.get('audit_logger',     'localhost:50054'),
    ]
    return all(_port_open(*a.rsplit(':', 1)) for a in addrs)


def _spawn_grus(cfg: dict) -> subprocess.Popen:
    executable = cfg.get('grus', {}).get('executable', 'grus')
    print(f'[surg] Starting Grus ({executable} --env prod)...')
    proc = subprocess.Popen(
        [executable, '--env', 'prod'],
        cwd=_repo_root,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        if _grus_ready(cfg):
            print('[surg] Grus is ready.')
            return proc
        time.sleep(0.5)
    print('[surg] WARNING: Grus did not become ready in 30s — proceeding in degraded state.')
    return proc


def main():
    cfg, config_path = load_config(_surg_dir)
    cfg = ensure_operator_name(cfg, config_path)

    os.makedirs(os.path.join(_surg_dir, 'logs'), exist_ok=True)
    log_rel = cfg.get('server', {}).get('log_file', 'logs/surg.log')
    log_path = os.path.join(_surg_dir, log_rel)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [surg] %(levelname)s %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path),
        ],
    )
    log = logging.getLogger(__name__)

    grus_proc = None
    if not _grus_ready(cfg):
        grus_proc = _spawn_grus(cfg)
    else:
        print('[surg] Grus already running — connecting.')

    grpc_client = GrpcClient(cfg)

    async def _on_idle_shutdown():
        log.info('Idle timeout reached — shutting down.')
        if grus_proc and grus_proc.poll() is None:
            log.info('Stopping Grus (pid %d)...', grus_proc.pid)
            grus_proc.terminate()
        os._exit(0)

    idle_tracker = IdleTracker(cfg, sio)
    idle_tracker.set_shutdown_cb(_on_idle_shutdown)

    dist_dir = os.path.join(_surg_dir, 'dist')
    setup(cfg, grpc_client, idle_tracker, dist_dir)

    host = cfg.get('server', {}).get('host', 'localhost')
    port = int(cfg.get('server', {}).get('port', 8080))
    operator = cfg.get('operator', {}).get('name', '?')

    print(f'[surg] Operator : {operator}')
    print(f'[surg] Serving  : http://{host}:{port}')
    print('[surg] Press Ctrl+C to stop.\n')

    try:
        uvicorn.run(app, host=host, port=port, log_level='warning')
    except KeyboardInterrupt:
        pass
    finally:
        if grus_proc and grus_proc.poll() is None:
            log.info('Stopping Grus on Surg exit...')
            grus_proc.terminate()
        print('[surg] Goodbye.')


if __name__ == '__main__':
    main()
