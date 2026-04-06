import os
import logging
import queue
from concurrent import futures

import grpc

from generated import killswitch_pb2
from generated import killswitch_pb2_grpc

from .subscriber_manager import SubscriberManager, _SENTINEL

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

PORT = _cfg.get('services', {}).get('broadcaster', {}).get('port', 50053)

_log_cfg = _cfg.get('logging', {})
_log_dir = _log_cfg.get('directory', 'logs')
os.makedirs(_log_dir, exist_ok=True)

_handlers = [logging.StreamHandler()]
if _cfg:
    _handlers.append(logging.FileHandler(os.path.join(_log_dir, 'broadcaster.log')))

logging.basicConfig(
    level=getattr(logging, _log_cfg.get('level', 'INFO')),
    format='%(asctime)s [broadcaster] %(levelname)s %(message)s',
    handlers=_handlers,
)
log = logging.getLogger(__name__)


class BroadcasterServicer(killswitch_pb2_grpc.BroadcasterServicer):

    def __init__(self, manager):
        self._manager = manager

    def NotifyChange(self, request, context):
        self._manager.notify_all(request)
        return killswitch_pb2.Empty()

    def SubscribeFlags(self, request, context):
        q = queue.Queue()
        self._manager.add(q)
        try:
            while context.is_active():
                try:
                    update = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if update is _SENTINEL:
                    break
                yield update
        finally:
            self._manager.remove(q)

def serve():
    manager = SubscriberManager()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    killswitch_pb2_grpc.add_BroadcasterServicer_to_server(
        BroadcasterServicer(manager), server
    )
    server.add_insecure_port(f'[::]:{PORT}')
    server.start()
    log.info("Broadcaster listening on port %d", PORT)
    try:
        server.wait_for_termination()
    finally:
        manager.shutdown()


if __name__ == '__main__':
    serve()
