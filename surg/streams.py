import asyncio
import logging

from generated import killswitch_pb2

log = logging.getLogger(__name__)


class IdleTracker:
    def __init__(self, cfg: dict, sio):
        behavior = cfg.get('behavior', {})
        self._timeout_secs = int(behavior.get('idle_timeout_minutes', 60)) * 60
        self._warning_secs = int(behavior.get('shutdown_warning_seconds', 60))
        self._sio = sio
        self._clients = 0
        self._task = None
        self._shutdown_cb = None

    def set_shutdown_cb(self, cb) -> None:
        self._shutdown_cb = cb

    async def on_connect(self) -> None:
        self._clients += 1
        self._cancel()

    async def on_disconnect(self) -> None:
        self._clients = max(0, self._clients - 1)
        if self._clients == 0 and self._timeout_secs > 0:
            self._start()

    def on_grus_event(self) -> None:
        if self._clients > 0:
            return
        if self._task and not self._task.done():
            self._cancel()
            self._start()

    def _start(self) -> None:
        if self._timeout_secs <= 0:
            return
        self._task = asyncio.create_task(self._countdown())

    def _cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _countdown(self) -> None:
        try:
            warn_delay = self._timeout_secs - self._warning_secs
            if warn_delay > 0:
                await asyncio.sleep(warn_delay)
            await self._sio.emit('shutdown_warning', {'seconds_remaining': self._warning_secs})
            if self._warning_secs > 0:
                await asyncio.sleep(self._warning_secs)
            if self._shutdown_cb:
                await self._shutdown_cb()
        except asyncio.CancelledError:
            pass


async def subscribe_flags(sio, grpc_client, idle_tracker: IdleTracker, shutdown_event: asyncio.Event) -> None:
    while True:
        if shutdown_event.is_set():
            return
        try:
            log.info("Connecting to Broadcaster.SubscribeFlags...")
            async for update in grpc_client.broadcaster.SubscribeFlags(killswitch_pb2.Empty()):
                idle_tracker.on_grus_event()
                await sio.emit('flag_update', {
                    'name':        update.flag.name,
                    'enabled':     update.flag.enabled,
                    'description': update.flag.description,
                    'protected':   update.flag.protected,
                    'mutex_with':  update.flag.mutex_with,
                    'old_value':   update.old_value,
                    'changed_by':  update.changed_by,
                    'timestamp':   update.timestamp,
                    'change_type': update.change_type,
                })
        except asyncio.CancelledError:
            return
        except Exception as e:
            if shutdown_event.is_set():
                return
            log.warning("Broadcaster stream lost (%s) — retrying in 3s", e)
            await asyncio.sleep(3)


async def stream_audit(sio, grpc_client, idle_tracker: IdleTracker, shutdown_event: asyncio.Event) -> None:
    while True:
        if shutdown_event.is_set():
            return
        try:
            log.info("Connecting to AuditLogger.StreamHistory (live)...")
            req = killswitch_pb2.AuditQuery(flag_name='', limit=0, offset=0)
            async for record in grpc_client.audit.StreamHistory(req):
                idle_tracker.on_grus_event()
                await sio.emit('audit_record', {
                    'flag_name':     record.flag_name,
                    'old_value':     record.old_value,
                    'new_value':     record.new_value,
                    'changed_by':    record.changed_by,
                    'changed_at':    record.changed_at,
                    'reason':        record.reason,
                    'policy_result': record.policy_result,
                })
        except asyncio.CancelledError:
            return
        except Exception as e:
            if shutdown_event.is_set():
                return
            log.warning("AuditLogger stream lost (%s) — retrying in 3s", e)
            await asyncio.sleep(3)


async def monitor_grus_status(sio, cfg: dict) -> None:
    svc = cfg.get('grus', {}).get('services', {})
    services = {
        'flag_store':       svc.get('flag_store',       'localhost:50051'),
        'policy_evaluator': svc.get('policy_evaluator', 'localhost:50052'),
        'broadcaster':      svc.get('broadcaster',      'localhost:50053'),
        'audit_logger':     svc.get('audit_logger',     'localhost:50054'),
    }
    last: dict = {}
    while True:
        try:
            current: dict = {}
            for name, addr in services.items():
                host, port = addr.rsplit(':', 1)
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(host, int(port)), timeout=0.5
                    )
                    writer.close()
                    await writer.wait_closed()
                    current[name] = True
                except Exception:
                    current[name] = False
            if current != last:
                await sio.emit('grus_status', current)
                last = current
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.warning("grus_status monitor error: %s", e)
        await asyncio.sleep(10)
