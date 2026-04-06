import logging
import queue
from concurrent import futures

import grpc

from generated import killswitch_pb2
from generated import killswitch_pb2_grpc

from .subscriber_manager import SubscriberManager, _SENTINEL

# Setup Logging agar Server Bisa Log Aktivitas Service

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [broadcaster] %(levelname)s %(message)s',
)
log = logging.getLogger(__name__)

PORT = 50053


class BroadcasterServicer(killswitch_pb2_grpc.BroadcasterServicer):

    def __init__(self, manager):
        self._manager = manager

    # Metode RPC untuk Mengirim Notifikasi Perubahan Flag ke Subscriber

    def NotifyChange(self, request, context):
        self._manager.notify_all(request)
        return killswitch_pb2.Empty()

    # Server-streaming RPC: Client subscribe dan Server mengirim update flag secara kontinu sampai client disconnect atau server shutdown

    def SubscribeFlags(self, request, context):
        q = queue.Queue() # Setiap subscriber mendapat queue sendiri untuk menerima update
        self._manager.add(q)
        try:
            while context.is_active():
                try:
                    update = q.get(timeout=1.0) # Ambil update dengan timeout agar tetap bisa cek status koneksi
                except queue.Empty:
                    continue
                if update is _SENTINEL: # Jika menerima sentinel: Hentikan stream (shutdown signal)
                    break
                yield update
        finally:    
            self._manager.remove(q)

# Inisialisasi dan menjalankan gRPC server Broadcaster

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
