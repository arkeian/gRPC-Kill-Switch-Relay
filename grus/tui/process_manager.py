import os
import signal
import socket
import subprocess
import sys
import time
import logging

log = logging.getLogger(__name__)

SERVICE_MODULES = [
    ('Policy Evaluator', 'policy_evaluator.server', 'policy_evaluator', 50052),
    ('Audit Logger',     'audit_logger.server',     'audit_logger',     50054),
    ('Broadcaster',      'broadcaster.server',      'broadcaster',      50053),
    ('Flag Store',       'flag_store.server',        'flag_store',       50051),
]


class ProcessManager:

    def __init__(self, cfg):
        self._cfg = cfg
        self._project_root = cfg['_project_root']
        self._procs = []

    def start_all(self):
        log_dir = os.path.join(
            self._project_root,
            self._cfg.get('logging', {}).get('directory', 'logs'),
        )
        os.makedirs(log_dir, exist_ok=True)
        os.makedirs(os.path.join(self._project_root, 'data'), exist_ok=True)

        repo_root = self._cfg.get('_repo_root', self._project_root)
        env = {
            **os.environ,
            'PYTHONPATH': f"{repo_root}{os.pathsep}{self._project_root}",
            'GRUS_CONFIG': self._cfg['_config_file'],
        }
        if '_policy_config_file' in self._cfg:
            env['GRUS_POLICY_CONFIG'] = self._cfg['_policy_config_file']

        for name, module, svc_key, default_port in SERVICE_MODULES:
            port = self._cfg.get('services', {}).get(svc_key, {}).get('port', default_port)
            log_file = os.path.join(log_dir, f'{svc_key}.log')

            fh = open(log_file, 'a')
            proc = subprocess.Popen(
                [sys.executable, '-m', module],
                cwd=self._project_root,
                env=env,
                stdout=fh,
                stderr=subprocess.STDOUT,
            )
            self._procs.append({
                'name': name,
                'proc': proc,
                'port': port,
                'log_file': log_file,
                'log_fh': fh,
                'svc_key': svc_key,
            })
            log.info("Started %s (pid %d) -> %s", name, proc.pid, log_file)

            if not self._wait_for_port(port, name):
                self.stop_all()
                print(f"\n[grus] ERROR: {name} did not start on port {port}.")
                print(f"       Check logs at: {log_file}")
                sys.exit(1)

    def _wait_for_port(self, port, name, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                s = socket.socket()
                s.settimeout(1)
                s.connect(('localhost', port))
                s.close()
                log.info("%s ready on port %d", name, port)
                return True
            except (ConnectionRefusedError, OSError):
                time.sleep(0.3)
        return False

    def stop_all(self):
        for entry in self._procs:
            proc = entry['proc']
            if proc.poll() is None:
                proc.terminate()

        deadline = time.time() + 5
        for entry in self._procs:
            proc = entry['proc']
            remaining = max(0, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

            entry['log_fh'].close()
            log.info("Stopped %s (pid %d)", entry['name'], proc.pid)

        self._procs.clear()

    def check_service(self, svc_key):
        for entry in self._procs:
            if entry['svc_key'] == svc_key:
                port = entry['port']
                try:
                    s = socket.socket()
                    s.settimeout(0.5)
                    s.connect(('localhost', port))
                    s.close()
                    return True
                except (ConnectionRefusedError, OSError):
                    return False
        return False

    def service_statuses(self):
        return {
            entry['svc_key']: self.check_service(entry['svc_key'])
            for entry in self._procs
        }
