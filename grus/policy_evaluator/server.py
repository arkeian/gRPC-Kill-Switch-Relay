import os
import logging
import time
import threading
from concurrent import futures

import grpc

from generated import killswitch_pb2
from generated import killswitch_pb2_grpc

from . import engine

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

_bc = _cfg.get('services', {}).get('broadcaster', {})
BROADCASTER_ADDR = f"{_bc.get('host', 'localhost')}:{_bc.get('port', 50053)}"

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

        approved, denial_reason = engine.validate_change(
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

    def GetPolicyRules(self, request, context):
        rules = engine.get_policy_rules()
        log.info("GetPolicyRules: protected=%d mutex_pairs=%d",
                 len(rules['protected_flags']), len(rules['mutex_pairs']))
        return killswitch_pb2.PolicyRules(
            protected_flags=rules['protected_flags'],
            mutex_pairs=[
                killswitch_pb2.MutexPair(flag_a=a, flag_b=b)
                for a, b in rules['mutex_pairs']
            ],
        )

    def SetPolicyRules(self, request, context):
        mutex_pairs = [(p.flag_a, p.flag_b) for p in request.mutex_pairs]
        try:
            engine.set_policy_rules(
                protected_flags=list(request.protected_flags),
                mutex_pairs=mutex_pairs,
            )
            log.info("SetPolicyRules: protected=%d mutex_pairs=%d",
                     len(request.protected_flags), len(mutex_pairs))
            return killswitch_pb2.PolicyRulesResponse(success=True, message='ok')
        except Exception as e:
            log.error("SetPolicyRules failed: %s", e)
            return killswitch_pb2.PolicyRulesResponse(success=False, message=str(e))


def _auto_prune_loop(broadcaster_addr: str) -> None:
    while True:
        try:
            channel = grpc.insecure_channel(broadcaster_addr)
            stub = killswitch_pb2_grpc.BroadcasterStub(channel)
            log.info("Auto-prune: subscribing to Broadcaster at %s", broadcaster_addr)
            for update in stub.SubscribeFlags(killswitch_pb2.Empty()):
                if update.change_type == 'DELETED':
                    flag_name = update.flag.name
                    log.info("Auto-prune: removing deleted flag '%s' from policy rules", flag_name)
                    engine.prune_flag(flag_name)
        except Exception as e:
            log.warning("Auto-prune stream lost (%s) — retrying in 5s", e)
            time.sleep(5)


def serve():
    prune_thread = threading.Thread(
        target=_auto_prune_loop,
        args=(BROADCASTER_ADDR,),
        daemon=True,
        name='auto-prune',
    )
    prune_thread.start()

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
