import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from generated import killswitch_pb2
from streams import subscribe_flags, stream_audit, monitor_grus_status, IdleTracker

log = logging.getLogger(__name__)

_state: dict = {'cfg': None, 'grpc_client': None, 'idle_tracker': None, 'shutdown_event': None}

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')


@asynccontextmanager
async def _lifespan(app: FastAPI):
    gc = _state['grpc_client']
    it = _state['idle_tracker']
    cfg = _state['cfg']
    shutdown_event = asyncio.Event()
    _state['shutdown_event'] = shutdown_event
    await gc.start()
    tasks = [
        asyncio.create_task(subscribe_flags(sio, gc, it, shutdown_event)),
        asyncio.create_task(stream_audit(sio, gc, it, shutdown_event)),
        asyncio.create_task(monitor_grus_status(sio, cfg)),
    ]
    try:
        yield
    finally:
        shutdown_event.set()
        for t in tasks:
            t.cancel()
        await gc.close()


_fastapi = FastAPI(lifespan=_lifespan)
app = socketio.ASGIApp(sio, other_asgi_app=_fastapi)


def setup(cfg: dict, grpc_client, idle_tracker: IdleTracker, dist_dir: str = None) -> None:
    _state['cfg'] = cfg
    _state['grpc_client'] = grpc_client
    _state['idle_tracker'] = idle_tracker
    if dist_dir and os.path.isfile(os.path.join(dist_dir, 'index.html')):
        _fastapi.mount('/', StaticFiles(directory=dist_dir, html=True), name='static')
        log.info("Serving React UI from %s", dist_dir)


def _op() -> str:
    return _state['cfg'].get('operator', {}).get('name', 'surg-operator')


async def _fetch_context_flags(gc) -> list:
    try:
        fl = await _retry(lambda: gc.flag_store.ListFlags(killswitch_pb2.Empty()))
        return list(fl.flags)
    except Exception:
        return []


async def _auto_validate(
    gc,
    current: killswitch_pb2.Flag,
    proposed: killswitch_pb2.Flag,
    context_override: list | None = None,
) -> tuple[bool, str]:
    context = context_override if context_override is not None else await _fetch_context_flags(gc)
    try:
        resp = await _retry(lambda: gc.policy.ValidateChange(killswitch_pb2.PolicyRequest(
            current_flag=current,
            proposed_change=proposed,
            changed_by=_op(),
            context_flags=context,
        )))
        return resp.approved, resp.denial_reason
    except Exception as e:
        return False, str(e)


async def _check_ports(cfg: dict) -> dict:
    svc = cfg.get('grus', {}).get('services', {})
    addrs = {
        'flag_store':       svc.get('flag_store',       'localhost:50051'),
        'policy_evaluator': svc.get('policy_evaluator', 'localhost:50052'),
        'broadcaster':      svc.get('broadcaster',      'localhost:50053'),
        'audit_logger':     svc.get('audit_logger',     'localhost:50054'),
    }
    status = {}
    for name, addr in addrs.items():
        host, port = addr.rsplit(':', 1)
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, int(port)), timeout=0.5
            )
            writer.close()
            await writer.wait_closed()
            status[name] = True
        except Exception:
            status[name] = False
    return status


async def _retry(fn, attempts: int = 3, delay: float = 0.5, timeout: float = 2.0):
    last = None
    for _ in range(attempts):
        try:
            return await asyncio.wait_for(fn(), timeout=timeout)
        except Exception as e:
            last = e
            await asyncio.sleep(delay)
    raise last


async def _send_initial_state(sid):
    gc = _state['grpc_client']
    cfg = _state['cfg']
    shutdown_event = _state.get('shutdown_event')
    last_err = None
    for _ in range(60):
        if shutdown_event and shutdown_event.is_set():
            return
        try:
            flag_list = await asyncio.wait_for(
                gc.flag_store.ListFlags(killswitch_pb2.Empty()), timeout=2.0
            )
            flags = [
                {
                    'name':        f.name,
                    'enabled':     f.enabled,
                    'description': f.description,
                    'protected':   f.protected,
                    'mutex_with':  f.mutex_with,
                }
                for f in flag_list.flags
            ]
            try:
                rules = await asyncio.wait_for(
                    gc.policy.GetPolicyRules(killswitch_pb2.Empty()), timeout=2.0
                )
                policy_rules = {
                    'protected_flags': list(rules.protected_flags),
                    'mutex_pairs': [
                        {'flag_a': p.flag_a, 'flag_b': p.flag_b}
                        for p in rules.mutex_pairs
                    ],
                }
            except Exception:
                policy_rules = {'protected_flags': [], 'mutex_pairs': []}
            grus_status = await _check_ports(cfg)
            await sio.emit('initial_state', {
                'flags':        flags,
                'grus_status':  grus_status,
                'policy_rules': policy_rules,
            }, to=sid)
            return
        except Exception as e:
            last_err = e
            await asyncio.sleep(1)
    if last_err:
        log.warning("initial_state failed for %s: %s", sid, last_err)


# ── connect / disconnect ──────────────────────────────────────────────────────

@sio.event
async def connect(sid, environ):
    log.info("Client connected: %s", sid)
    await _state['idle_tracker'].on_connect()
    asyncio.create_task(_send_initial_state(sid))


@sio.event
async def disconnect(sid):
    log.info("Client disconnected: %s", sid)
    await _state['idle_tracker'].on_disconnect()


async def _audit_denied(gc, flag_name: str, old_value: bool, new_value: bool, denial: str):
    now = int(time.time())
    record = killswitch_pb2.AuditRecord(
        flag_name=flag_name,
        old_value=old_value,
        new_value=new_value,
        changed_by=_op(),
        changed_at=now,
        reason=denial,
        policy_result='denied',
    )
    try:
        await _retry(lambda: gc.audit.LogChange(record))
    except Exception as e:
        log.warning("Failed to audit denied attempt for %s: %s", flag_name, e)
    await sio.emit('audit_record', {
        'flag_name':     flag_name,
        'old_value':     old_value,
        'new_value':     new_value,
        'changed_by':    _op(),
        'changed_at':    now,
        'reason':        denial,
        'policy_result': 'denied',
    })


# ── mutations ─────────────────────────────────────────────────────────────────

@sio.event
async def toggle_flag(sid, data):
    gc = _state['grpc_client']
    name    = data.get('name', '')
    enabled = bool(data.get('enabled', False))
    reason  = data.get('reason', '')
    try:
        current = await _retry(lambda: gc.flag_store.GetFlag(killswitch_pb2.FlagQuery(name=name)))
    except Exception:
        current = killswitch_pb2.Flag(name=name, enabled=not enabled)
    proposed = killswitch_pb2.Flag(
        name=name,
        enabled=enabled,
        description=current.description,
        protected=current.protected,
        mutex_with=current.mutex_with,
    )
    context = await _fetch_context_flags(gc)
    mutex_name = (current.mutex_with or '').strip()
    other_enabled = False
    other_desc = ''
    if enabled and mutex_name:
        for flag in context:
            if flag.name == mutex_name:
                other_enabled = flag.enabled
                other_desc = flag.description
                break
    if enabled and mutex_name and other_enabled:
        context_override = [
            killswitch_pb2.Flag(
                name=flag.name,
                enabled=(False if flag.name == mutex_name else flag.enabled),
                description=flag.description,
                protected=flag.protected,
                mutex_with=flag.mutex_with,
            )
            for flag in context
        ]
        approved, denial = await _auto_validate(gc, current, proposed, context_override)
        if not approved:
            await _audit_denied(gc, name, current.enabled, proposed.enabled, denial)
            return {'success': False, 'message': denial}
        disable_reason = reason or f"Auto-disabled due to mutex with {name}"
        try:
            resp = await _retry(lambda: gc.flag_store.SetFlag(killswitch_pb2.FlagChangeRequest(
                flag=killswitch_pb2.Flag(
                    name=mutex_name,
                    enabled=False,
                    description=other_desc,
                ),
                changed_by=_op(),
                reason=disable_reason,
                operation_type=killswitch_pb2.OPERATION_TOGGLE,
            )))
        except Exception as e:
            return {'success': False, 'message': str(e)}
        if not resp.success:
            return {'success': False, 'message': resp.message}
        context = context_override
    approved, denial = await _auto_validate(gc, current, proposed, context)
    if not approved:
        await _audit_denied(gc, name, current.enabled, proposed.enabled, denial)
        return {'success': False, 'message': denial}
    try:
        resp = await _retry(lambda: gc.flag_store.SetFlag(killswitch_pb2.FlagChangeRequest(
            flag=proposed, changed_by=_op(), reason=reason,
            operation_type=killswitch_pb2.OPERATION_TOGGLE,
        )))
        if resp.success:
            await sio.emit('flag_update', {
                'name':        proposed.name,
                'enabled':     proposed.enabled,
                'description': proposed.description,
                'protected':   proposed.protected,
                'mutex_with':  proposed.mutex_with,
                'old_value':   current.enabled,
                'changed_by':  _op(),
                'timestamp':   int(time.time()),
                'change_type': 'ENABLED' if enabled else 'DISABLED',
            })
        return {'success': resp.success, 'message': resp.message}
    except Exception as e:
        return {'success': False, 'message': str(e)}


@sio.event
async def add_flag(sid, data):
    gc = _state['grpc_client']
    name        = data.get('name', '')
    description = data.get('description', '')
    enabled     = bool(data.get('enabled', False))
    reason      = data.get('reason', '')
    proposed = killswitch_pb2.Flag(name=name, enabled=enabled, description=description)
    current  = killswitch_pb2.Flag(name=name, enabled=False, description='')
    approved, denial = await _auto_validate(gc, current, proposed)
    if not approved:
        await _audit_denied(gc, name, False, proposed.enabled, denial)
        return {'success': False, 'message': denial}
    try:
        resp = await _retry(lambda: gc.flag_store.SetFlag(killswitch_pb2.FlagChangeRequest(
            flag=proposed, changed_by=_op(), reason=reason,
            operation_type=killswitch_pb2.OPERATION_ADD,
        )))
        if resp.success:
            await sio.emit('flag_update', {
                'name':        proposed.name,
                'enabled':     proposed.enabled,
                'description': proposed.description,
                'protected':   proposed.protected,
                'mutex_with':  proposed.mutex_with,
                'old_value':   False,
                'changed_by':  _op(),
                'timestamp':   int(time.time()),
                'change_type': 'CREATED',
            })
        return {'success': resp.success, 'message': resp.message}
    except Exception as e:
        return {'success': False, 'message': str(e)}


@sio.event
async def edit_flag(sid, data):
    gc = _state['grpc_client']
    name        = data.get('name', '')
    description = data.get('description', '')
    enabled     = bool(data.get('enabled', False))
    reason      = data.get('reason', '')
    try:
        current = await _retry(lambda: gc.flag_store.GetFlag(killswitch_pb2.FlagQuery(name=name)))
    except Exception:
        current = killswitch_pb2.Flag(name=name, enabled=enabled, description='')
    proposed = killswitch_pb2.Flag(
        name=name,
        enabled=enabled,
        description=description,
        protected=current.protected,
        mutex_with=current.mutex_with,
    )
    approved, denial = await _auto_validate(gc, current, proposed)
    if not approved:
        await _audit_denied(gc, name, current.enabled, proposed.enabled, denial)
        return {'success': False, 'message': denial}
    try:
        resp = await _retry(lambda: gc.flag_store.SetFlag(killswitch_pb2.FlagChangeRequest(
            flag=proposed, changed_by=_op(), reason=reason,
            operation_type=killswitch_pb2.OPERATION_EDIT,
        )))
        if resp.success:
            await sio.emit('flag_update', {
                'name':        proposed.name,
                'enabled':     proposed.enabled,
                'description': proposed.description,
                'protected':   proposed.protected,
                'mutex_with':  proposed.mutex_with,
                'old_value':   current.enabled,
                'changed_by':  _op(),
                'timestamp':   int(time.time()),
                'change_type': 'UPDATED',
            })
        return {'success': resp.success, 'message': resp.message}
    except Exception as e:
        return {'success': False, 'message': str(e)}


@sio.event
async def delete_flag(sid, data):
    gc = _state['grpc_client']
    name   = data.get('name', '')
    reason = data.get('reason', '')
    try:
        current = await _retry(lambda: gc.flag_store.GetFlag(killswitch_pb2.FlagQuery(name=name)))
    except Exception:
        current = killswitch_pb2.Flag(name=name, enabled=False)
    proposed = killswitch_pb2.Flag(
        name=name,
        enabled=False,
        description=current.description,
        protected=current.protected,
        mutex_with=current.mutex_with,
    )
    approved, denial = await _auto_validate(gc, current, proposed)
    if not approved:
        await _audit_denied(gc, name, current.enabled, False, denial)
        return {'success': False, 'message': denial}
    try:
        resp = await _retry(lambda: gc.flag_store.SetFlag(killswitch_pb2.FlagChangeRequest(
            flag=proposed, changed_by=_op(), reason=reason,
            operation_type=killswitch_pb2.OPERATION_DELETE,
        )))
        if resp.success:
            await sio.emit('flag_update', {
                'name':        proposed.name,
                'enabled':     proposed.enabled,
                'description': proposed.description,
                'protected':   proposed.protected,
                'mutex_with':  proposed.mutex_with,
                'old_value':   current.enabled,
                'changed_by':  _op(),
                'timestamp':   int(time.time()),
                'change_type': 'DELETED',
            })
            try:
                current_rules = await _retry(lambda: gc.policy.GetPolicyRules(killswitch_pb2.Empty()))
                protected_set = set(current_rules.protected_flags)
                protected_set.discard(name)
                pairs = [(p.flag_a, p.flag_b) for p in current_rules.mutex_pairs
                         if p.flag_a != name and p.flag_b != name]
                new_rules = killswitch_pb2.PolicyRules(
                    protected_flags=list(protected_set),
                    mutex_pairs=[killswitch_pb2.MutexPair(flag_a=a, flag_b=b) for a, b in pairs],
                )
                rule_resp = await _retry(lambda: gc.policy.SetPolicyRules(new_rules))
                if rule_resp.success:
                    await sio.emit('policy_update', {
                        'protected_flags': list(protected_set),
                        'mutex_pairs': [{'flag_a': a, 'flag_b': b} for a, b in pairs],
                    })
            except Exception as pe:
                log.warning("Failed to prune policy for deleted flag %s: %s", name, pe)
        return {'success': resp.success, 'message': resp.message}
    except Exception as e:
        return {'success': False, 'message': str(e)}


# ── queries / utility ─────────────────────────────────────────────────────────

@sio.event
async def validate_change(sid, data):
    gc = _state['grpc_client']
    c = data.get('current', {})
    p = data.get('proposed', {})
    current = killswitch_pb2.Flag(
        name=c.get('name', ''), enabled=bool(c.get('enabled', False)),
        description=c.get('description', ''),
    )
    proposed = killswitch_pb2.Flag(
        name=p.get('name', ''), enabled=bool(p.get('enabled', False)),
        description=p.get('description', ''),
    )
    approved, denial = await _auto_validate(gc, current, proposed)
    return {'approved': approved, 'denial_reason': denial}


@sio.event
async def refresh_flags(sid, data):
    gc = _state['grpc_client']
    try:
        fl = await _retry(lambda: gc.flag_store.ListFlags(killswitch_pb2.Empty()))
        return {'flags': [
            {
                'name':        f.name,
                'enabled':     f.enabled,
                'description': f.description,
                'protected':   f.protected,
                'mutex_with':  f.mutex_with,
            }
            for f in fl.flags
        ]}
    except Exception as e:
        return {'flags': [], 'error': str(e)}


@sio.event
async def get_audit_history(sid, data):
    gc = _state['grpc_client']
    req = killswitch_pb2.AuditQuery(
        flag_name=data.get('flag_name', ''),
        limit=int(data.get('limit', 50)),
        offset=int(data.get('offset', 0)),
    )
    try:
        resp = await _retry(lambda: gc.audit.GetHistory(req))
        return {'records': [
            {
                'flag_name':     r.flag_name,
                'old_value':     r.old_value,
                'new_value':     r.new_value,
                'changed_by':    r.changed_by,
                'changed_at':    r.changed_at,
                'reason':        r.reason,
                'policy_result': r.policy_result,
            }
            for r in resp.records
        ]}
    except Exception as e:
        return {'records': [], 'error': str(e)}


@sio.event
async def keep_alive(sid, data):
    _state['idle_tracker'].on_grus_event()


@sio.event
async def set_flag_policy(sid, data):
    gc = _state['grpc_client']
    flag_name    = data.get('flag_name', '')
    is_protected = bool(data.get('protected', False))
    mutex_with   = data.get('mutex_with', '').strip()
    try:
        current_rules = await _retry(lambda: gc.policy.GetPolicyRules(killswitch_pb2.Empty()))
        protected_set = set(current_rules.protected_flags)
        pairs = [(p.flag_a, p.flag_b) for p in current_rules.mutex_pairs]

        if is_protected:
            protected_set.add(flag_name)
        else:
            protected_set.discard(flag_name)

        pairs = [(a, b) for a, b in pairs if a != flag_name and b != flag_name]
        if mutex_with:
            pairs.append((flag_name, mutex_with))

        new_rules = killswitch_pb2.PolicyRules(
            protected_flags=list(protected_set),
            mutex_pairs=[
                killswitch_pb2.MutexPair(flag_a=a, flag_b=b) for a, b in pairs
            ],
        )
        resp = await _retry(lambda: gc.policy.SetPolicyRules(new_rules))
        if resp.success:
            await sio.emit('policy_update', {
                'protected_flags': list(protected_set),
                'mutex_pairs': [{'flag_a': a, 'flag_b': b} for a, b in pairs],
            })
        return {'success': resp.success, 'message': resp.message}
    except Exception as e:
        return {'success': False, 'message': str(e)}
