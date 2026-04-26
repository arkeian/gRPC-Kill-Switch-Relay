import os
import logging
from concurrent import futures

import grpc

from generated import killswitch_pb2
from generated import killswitch_pb2_grpc

from .store import FlagStore

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

PORT = _cfg.get('services', {}).get('flag_store', {}).get('port', 50051)
DB_PATH = _cfg.get('services', {}).get('flag_store', {}).get('db_path', 'data/flags.db')

_pe = _cfg.get('services', {}).get('policy_evaluator', {})
_bc = _cfg.get('services', {}).get('broadcaster', {})
_al = _cfg.get('services', {}).get('audit_logger', {})

POLICY_EVALUATOR_ADDR = f"{_pe.get('host', 'localhost')}:{_pe.get('port', 50052)}"
BROADCASTER_ADDR = f"{_bc.get('host', 'localhost')}:{_bc.get('port', 50053)}"
AUDIT_LOGGER_ADDR = f"{_al.get('host', 'localhost')}:{_al.get('port', 50054)}"

_log_cfg = _cfg.get('logging', {})
_log_dir = _log_cfg.get('directory', 'logs')
os.makedirs(_log_dir, exist_ok=True)

_handlers = [logging.StreamHandler()]
if _cfg:
    _handlers.append(logging.FileHandler(os.path.join(_log_dir, 'flag_store.log')))

logging.basicConfig(
    level=getattr(logging, _log_cfg.get('level', 'INFO')),
    format='%(asctime)s [flag_store] %(levelname)s %(message)s',
    handlers=_handlers,
)
log = logging.getLogger(__name__)


class FlagStoreServicer(killswitch_pb2_grpc.FlagStoreServicer):

    def __init__(self, store, policy_stub, broadcaster_stub, audit_stub):
        self._store = store
        self._policy_stub = policy_stub
        self._broadcaster_stub = broadcaster_stub
        self._audit_stub = audit_stub

    def SetFlag(self, request, context):
        log.info("SetFlag: flag='%s' enabled=%s by='%s'",
                 request.flag.name, request.flag.enabled, request.changed_by)
        success, message = self._store.set_flag(
            request,
            self._policy_stub,
            self._broadcaster_stub,
            self._audit_stub,
        )
        if not success:
            log.info("SetFlag result: success=False message='%s'", message)
        return killswitch_pb2.FlagChangeResponse(success=success, message=message)

    def GetFlag(self, request, context):
        row = self._store.get_flag(request.name)
        if row is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"Flag '{request.name}' not found")
        return killswitch_pb2.Flag(
            name=row['name'],
            enabled=row['enabled'],
            description=row['description'],
        )

    def ListFlags(self, request, context):
        rows = self._store.list_flags()
        flags = [
            killswitch_pb2.Flag(name=r['name'], enabled=r['enabled'], description=r['description'])
            for r in rows
        ]
        return killswitch_pb2.FlagList(flags=flags)


def serve():
    os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
    store = FlagStore(db_path=DB_PATH)

    policy_channel = grpc.insecure_channel(POLICY_EVALUATOR_ADDR)
    broadcaster_channel = grpc.insecure_channel(BROADCASTER_ADDR)
    audit_channel = grpc.insecure_channel(AUDIT_LOGGER_ADDR)

    policy_stub = killswitch_pb2_grpc.PolicyEvaluatorStub(policy_channel)
    broadcaster_stub = killswitch_pb2_grpc.BroadcasterStub(broadcaster_channel)
    audit_stub = killswitch_pb2_grpc.AuditLoggerStub(audit_channel)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    killswitch_pb2_grpc.add_FlagStoreServicer_to_server(
        FlagStoreServicer(store, policy_stub, broadcaster_stub, audit_stub),
        server,
    )
    server.add_insecure_port(f'[::]:{PORT}')
    server.start()
    log.info("Flag Store listening on port %d", PORT)
    log.info("  -> Policy Evaluator : %s", POLICY_EVALUATOR_ADDR)
    log.info("  -> Broadcaster      : %s", BROADCASTER_ADDR)
    log.info("  -> Audit Logger     : %s", AUDIT_LOGGER_ADDR)
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
