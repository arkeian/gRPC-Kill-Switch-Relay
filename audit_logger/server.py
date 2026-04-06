import sys
import os
import logging
import queue
from concurrent import futures

import grpc

# Menambahkan Folder generated/ ke Python path supaya bisa import hasil protoc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'generated'))

# Mengimpor File protoc yang Dihasilkan

import killswitch_pb2
import killswitch_pb2_grpc

# Sentinel object: Penanda khusus untuk menghentikan streaming (Graceful Shutdown)

from logger import AuditLogger, _SENTINEL

# Setup Logging agar Server Bisa Log Aktivitas Service

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [audit_logger] %(levelname)s %(message)s',
)
log = logging.getLogger(__name__)

PORT = 50054


class AuditLoggerServicer(killswitch_pb2_grpc.AuditLoggerServicer):

    def __init__(self, audit_logger):
        self._logger = audit_logger

    # Metode RPC untuk Mencatat satu Perubahan Flag ke Database

    def LogChange(self, request, context):
        self._logger.log_change(request)
        return killswitch_pb2.Empty()

    # Metode RPC untuk Mengambil Riwayat Perubahan Flag dari Database dan Meng-formatnya ke dalam Response protobuf yang Sesuai

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

    # Client Subscribe ke Server untuk Menerima Log Perubahan secara Real-time

    def StreamHistory(self, request, context):
        q = queue.Queue()
        self._logger.add_subscriber(q) # Register subscriber agar mendapatkan update log terbaru
        try:
            while context.is_active():
                try:
                    record = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if record is _SENTINEL: # Sentinel = sinyal shutdown: Hentikan stream (Graceful Shutdown)
                    break
                yield record # Kirim Log ke Client (streaming)
        finally:
            self._logger.remove_subscriber(q) # Cleanup: Pastikan subscriber dihapus saat Shutdown / Error

# Inisialisasi dan menjalankan gRPC server AuditLogger

def serve():
    audit_logger = AuditLogger()
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
