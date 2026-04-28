import grpc.aio

from generated import killswitch_pb2_grpc


class GrpcClient:
    def __init__(self, cfg: dict):
        svc = cfg.get('grus', {}).get('services', {})
        self._addrs = {
            'flag_store':       svc.get('flag_store',       'localhost:50051'),
            'policy_evaluator': svc.get('policy_evaluator', 'localhost:50052'),
            'broadcaster':      svc.get('broadcaster',      'localhost:50053'),
            'audit_logger':     svc.get('audit_logger',     'localhost:50054'),
        }
        self.flag_store = None
        self.policy     = None
        self.broadcaster = None
        self.audit      = None
        self._channels  = []

    async def start(self) -> None:
        channels = {k: grpc.aio.insecure_channel(addr) for k, addr in self._addrs.items()}
        self._channels = list(channels.values())
        self.flag_store  = killswitch_pb2_grpc.FlagStoreStub(channels['flag_store'])
        self.policy      = killswitch_pb2_grpc.PolicyEvaluatorStub(channels['policy_evaluator'])
        self.broadcaster = killswitch_pb2_grpc.BroadcasterStub(channels['broadcaster'])
        self.audit       = killswitch_pb2_grpc.AuditLoggerStub(channels['audit_logger'])

    async def close(self) -> None:
        for ch in self._channels:
            try:
                await ch.close()
            except Exception:
                pass
