import os
import logging
from concurrent import futures

import grpc

from generated import killswitch_pb2
from generated import killswitch_pb2_grpc

from .engine import validate_change

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

PORT = _cfg.get('services', {}).get('policy_evaluator', {}).get('port', 50052)

_log_cfg = _cfg.get('logging', {})
_log_dir = _log_cfg.get('directory', 'logs')
os.makedirs(_log_dir, exist_ok=True)

_handlers = [logging.StreamHandler()]
if _cfg:
    _handlers.append(logging.FileHandler(os.path.join(_log_dir, 'policy_evaluator.log')))

logging.basicConfig(
    level=getattr(logging, _log_cfg.get('level', 'INFO')),
    format='%(asctime)s [policy_evaluator] %(levelname)s %(message)s',
    handlers=_handlers,
)
log = logging.getLogger(__name__)


class PolicyEvaluatorServicer(killswitch_pb2_grpc.PolicyEvaluatorServicer):

    def ValidateChange(self, request, context):
        proposed = request.proposed_change

        log.info(
            "ValidateChange: flag='%s' enabled=%s changed_by='%s' context_flags=%d",
            proposed.name,
            proposed.enabled,
            request.changed_by,
            len(request.context_flags),
        )

        approved, denial_reason = validate_change(
            proposed_flag=proposed,
            context_flags=list(request.context_flags),
        )

        if approved:
            log.info("Decision: APPROVED flag='%s'", proposed.name)
        else:
            log.info("Decision: DENIED flag='%s' reason='%s'", proposed.name, denial_reason)

        return killswitch_pb2.PolicyResponse(
            approved=approved,
            denial_reason=denial_reason,
        )

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
