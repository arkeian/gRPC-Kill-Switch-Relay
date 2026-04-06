import logging
import threading

import grpc

from generated import killswitch_pb2
from generated import killswitch_pb2_grpc

log = logging.getLogger(__name__)


class GrpcClient:

    def __init__(self, cfg):
        self._cfg = cfg
        self._channels = {}
        self._stubs = {}
        self._lock = threading.Lock()
        self._connect_all()

    def _addr(self, svc_key, default_port):
        svc = self._cfg.get('services', {}).get(svc_key, {})
        host = svc.get('host', 'localhost')
        port = svc.get('port', default_port)
        return f'{host}:{port}'

    def _connect_all(self):
        timeout = self._cfg.get('client', {}).get('connection_timeout', 10)

        addrs = {
            'flag_store': self._addr('flag_store', 50051),
            'policy_evaluator': self._addr('policy_evaluator', 50052),
            'broadcaster': self._addr('broadcaster', 50053),
            'audit_logger': self._addr('audit_logger', 50054),
        }

        for svc_key, addr in addrs.items():
            channel = grpc.insecure_channel(addr)
            self._channels[svc_key] = channel

        self._stubs['flag_store'] = killswitch_pb2_grpc.FlagStoreStub(
            self._channels['flag_store']
        )
        self._stubs['policy_evaluator'] = killswitch_pb2_grpc.PolicyEvaluatorStub(
            self._channels['policy_evaluator']
        )
        self._stubs['broadcaster'] = killswitch_pb2_grpc.BroadcasterStub(
            self._channels['broadcaster']
        )
        self._stubs['audit_logger'] = killswitch_pb2_grpc.AuditLoggerStub(
            self._channels['audit_logger']
        )

    def set_flag(self, name, enabled, description='', changed_by='grus', reason=''):
        req = killswitch_pb2.FlagChangeRequest(
            flag=killswitch_pb2.Flag(name=name, enabled=enabled, description=description),
            changed_by=changed_by,
            reason=reason,
        )
        return self._stubs['flag_store'].SetFlag(req)

    def get_flag(self, name):
        req = killswitch_pb2.FlagQuery(name=name)
        return self._stubs['flag_store'].GetFlag(req)

    def list_flags(self):
        return self._stubs['flag_store'].ListFlags(killswitch_pb2.Empty())

    def validate_change(self, current_flag, proposed_flag, changed_by):
        req = killswitch_pb2.PolicyRequest(
            current_flag=current_flag,
            proposed_change=proposed_flag,
            changed_by=changed_by,
            context_flags=list(self.list_flags().flags),
        )
        return self._stubs['policy_evaluator'].ValidateChange(req)

    def subscribe_flags(self):
        return self._stubs['broadcaster'].SubscribeFlags(killswitch_pb2.Empty())

    def get_history(self, flag_name='', limit=50):
        req = killswitch_pb2.AuditQuery(flag_name=flag_name, limit=limit)
        return self._stubs['audit_logger'].GetHistory(req)

    def stream_history(self):
        return self._stubs['audit_logger'].StreamHistory(killswitch_pb2.Empty())

    def check_connection(self, svc_key):
        channel = self._channels.get(svc_key)
        if channel is None:
            return False
        try:
            future = grpc.channel_ready_future(channel)
            future.result(timeout=0.5)
            return True
        except grpc.FutureTimeoutError:
            return False

    def close(self):
        for channel in self._channels.values():
            channel.close()
