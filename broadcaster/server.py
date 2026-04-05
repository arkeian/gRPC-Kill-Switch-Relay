import sys
import os
import logging
import queue
from concurrent import futures

import grpc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'generated'))
import killswitch_pb2
import killswitch_pb2_grpc

from subscriber_manager import SubscriberManager, _SENTINEL

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [broadcaster] %(levelname)s %(message)s',
)
log = logging.getLogger(__name__)

PORT = 50053


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
