import sys
import os
import logging
from concurrent import futures

import grpc

# Menambahkan Folder generated/ ke Python path supaya bisa import hasil protoc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'generated'))

# Mengimpor File protoc yang Dihasilkan

import killswitch_pb2
import killswitch_pb2_grpc

from store import FlagStore

# Setup Logging agar Server Bisa Log Aktivitas Service

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [flag_store] %(levelname)s %(message)s',
)
log = logging.getLogger(__name__)

PORT = 50051

# Alamat Port Service Lain yang Akan Digunakan oleh Flag Store

POLICY_EVALUATOR_ADDR  = 'localhost:50052'
BROADCASTER_ADDR       = 'localhost:50053'
AUDIT_LOGGER_ADDR      = 'localhost:50054'


class FlagStoreServicer(killswitch_pb2_grpc.FlagStoreServicer):

    def __init__(self, store, policy_stub, broadcaster_stub, audit_stub):
        self._store           = store
        self._policy_stub     = policy_stub
        self._broadcaster_stub = broadcaster_stub
        self._audit_stub      = audit_stub

    # Metode RPC untuk Mengubah Status Flag (enable/disable) dengan Validasi Policy, Logging Audit, dan Broadcast ke Subscriber

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

    # Metode RPC untuk Mengambil Detail Status Satu Flag Tertentu

    def GetFlag(self, request, context):
        row = self._store.get_flag(request.name)
        if row is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"Flag '{request.name}' not found")
        return killswitch_pb2.Flag(
            name=row['name'],
            enabled=row['enabled'],
            description=row['description'],
        )

    # Metode RPC untuk Mengambil Daftar Semua Flag yang Tersedia beserta Statusnya

    def ListFlags(self, request, context):
        rows = self._store.list_flags()
        flags = [
            killswitch_pb2.Flag(name=r['name'], enabled=r['enabled'], description=r['description'])
            for r in rows
        ]
        return killswitch_pb2.FlagList(flags=flags)


# Inisialisasi dan menjalankan gRPC server Flag Store, serta menghubungkan ke service lain (Policy Evaluator, Broadcaster, Audit Logger) melalui gRPC stub

def serve():
    store = FlagStore()

    policy_channel      = grpc.insecure_channel(POLICY_EVALUATOR_ADDR)
    broadcaster_channel = grpc.insecure_channel(BROADCASTER_ADDR)
    audit_channel       = grpc.insecure_channel(AUDIT_LOGGER_ADDR)

    policy_stub      = killswitch_pb2_grpc.PolicyEvaluatorStub(policy_channel)
    broadcaster_stub = killswitch_pb2_grpc.BroadcasterStub(broadcaster_channel)
    audit_stub       = killswitch_pb2_grpc.AuditLoggerStub(audit_channel)

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
