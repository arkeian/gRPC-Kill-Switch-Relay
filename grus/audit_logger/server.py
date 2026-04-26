import os
import logging
import queue
from concurrent import futures

import grpc

from generated import killswitch_pb2
from generated import killswitch_pb2_grpc

from .logger import AuditLogger, _SENTINEL

try:
    import tomli
except ModuleNotFoundError:
    import tomllib as tomli

def _load_config():
    config_path = os.environ.get('GRUS_CONFIG', '')
    if config_path and os.path.isfile(config_path):
        with open(config_path, 'rb') as f:
            return tomli.load(f)
    return {}

_cfg = _load_config()

PORT = _cfg.get('services', {}).get('audit_logger', {}).get('port', 50054)
DB_PATH = _cfg.get('services', {}).get('audit_logger', {}).get('db_path', 'data/audit.db')

_log_cfg = _cfg.get('logging', {})
_log_dir = _log_cfg.get('directory', 'logs')
os.makedirs(_log_dir, exist_ok=True)

_handlers = [logging.StreamHandler()]
if _cfg:
    _handlers.append(logging.FileHandler(os.path.join(_log_dir, 'audit_logger.log')))

logging.basicConfig(
    level=getattr(logging, _log_cfg.get('level', 'INFO')),
    format='%(asctime)s [audit_logger] %(levelname)s %(message)s',
    handlers=_handlers,
)
log = logging.getLogger(__name__)


class AuditLoggerServicer(killswitch_pb2_grpc.AuditLoggerServicer):

    def __init__(self, audit_logger):
        self._logger = audit_logger

    def LogChange(self, request, context):
        self._logger.log_change(request)
        return killswitch_pb2.Empty()

    def GetHistory(self, request, context):
        rows = self._logger.get_history(
            flag_name=request.flag_name,
            limit=request.limit,
        )
        records = [
            killswitch_pb2.AuditRecord(
                flag_name=row['flag_name'],
                old_value=row['old_value'],
                new_value=row['new_value'],
                changed_by=row['changed_by'],
                changed_at=row['changed_at'],
                reason=row['reason'],
                policy_result=row['policy_result'],
            )
            for row in rows
        ]
        return killswitch_pb2.AuditHistoryResponse(records=records)

    def StreamHistory(self, request, context):
        q = queue.Queue()
        self._logger.add_subscriber(q)
        try:
            while context.is_active():
                try:
                    record = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if record is _SENTINEL:
                    break
                yield record
        finally:
            self._logger.remove_subscriber(q)

def serve():
    os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
    audit_logger = AuditLogger(db_path=DB_PATH)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    killswitch_pb2_grpc.add_AuditLoggerServicer_to_server(
        AuditLoggerServicer(audit_logger), server
    )
    server.add_insecure_port(f'[::]:{PORT}')
    server.start()
    log.info("Audit Logger listening on port %d", PORT)
    try:
        server.wait_for_termination()
    finally:
        audit_logger.shutdown()


if __name__ == '__main__':
    serve()
