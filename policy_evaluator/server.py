import logging
from concurrent import futures

import grpc

from generated import killswitch_pb2
from generated import killswitch_pb2_grpc

from .engine import validate_change

# Setup Logging agar Server Bisa Log Aktivitas Service

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [policy_evaluator] %(levelname)s %(message)s',
)
log = logging.getLogger(__name__)

PORT = 50052


class PolicyEvaluatorServicer(killswitch_pb2_grpc.PolicyEvaluatorServicer):

    # Metode RPC untuk memvalidasi perubahan flag berdasarkan policy yang berlaku

    def ValidateChange(self, request, context):
        proposed = request.proposed_change

        # Logging request yang masuk

        log.info(
            "ValidateChange: flag='%s' enabled=%s changed_by='%s' context_flags=%d",
            proposed.name,
            proposed.enabled,
            request.changed_by,
            len(request.context_flags),
        )

        # Memanggil engine policy untuk menentukan apakah perubahan diizinkan

        approved, denial_reason = validate_change(
            proposed_flag=proposed,
            context_flags=list(request.context_flags),
        )

        if approved:
            log.info("Decision: APPROVED flag='%s'", proposed.name)
        else:
            log.info("Decision: DENIED flag='%s' reason='%s'", proposed.name, denial_reason)

        # Mengembalikan hasil evaluasi ke client dalam bentuk response protobuf

        return killswitch_pb2.PolicyResponse(
            approved=approved,
            denial_reason=denial_reason,
        )

# Inisialisasi dan menjalankan gRPC server Policy Evaluator

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    killswitch_pb2_grpc.add_PolicyEvaluatorServicer_to_server(
        PolicyEvaluatorServicer(), server
    )
    server.add_insecure_port(f'[::]:{PORT}')
    server.start()
    log.info("Policy Evaluator listening on port %d", PORT)
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
