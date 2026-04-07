#!/usr/bin/env python3

import datetime
import os
import queue
import subprocess
import sys
import threading
import time

import grpc
from generated import killswitch_pb2
from generated import killswitch_pb2_grpc
from policy_evaluator.engine import MAINTENANCE_WINDOW_LOCAL

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SERVICES = [
    ('Policy Evaluator',  'policy_evaluator.server',  50052),
    ('Audit Logger',      'audit_logger.server',      50054),
    ('Broadcaster',       'broadcaster.server',       50053),
    ('Flag Store',        'flag_store.server',        50051),
]

FLAG_STORE_ADDR  = 'localhost:50051'
BROADCASTER_ADDR = 'localhost:50053'
AUDIT_ADDR       = 'localhost:50054'

PASS = 'PASS'
FAIL = 'FAIL'

def start_services():
    procs = []
    log_dir = os.path.join(REPO_ROOT, 'tests', 'service_logs')
    os.makedirs(log_dir, exist_ok=True)

    for name, script, port in SERVICES:
        log_path = os.path.join(log_dir, f'{port}.log')
        with open(log_path, 'w') as log_fh:
            proc = subprocess.Popen(
                [sys.executable, '-m', script],
                cwd=REPO_ROOT,
                env={**os.environ, 'PYTHONPATH': REPO_ROOT},
                stdout=log_fh,
                stderr=subprocess.STDOUT,
            )
        procs.append((name, proc, port, log_path))
        print(f'  Started {name} (pid {proc.pid}) → {log_path}')

    return procs

def stop_services(procs):
    print('\nShutting down services...')
    for name, proc, port, _ in procs:
        proc.terminate()
    for name, proc, port, _ in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f'  Stopped {name}')


def wait_for_service(addr, name, timeout=15):
    channel = grpc.insecure_channel(addr)
    future = grpc.channel_ready_future(channel)
    try:
        future.result(timeout=timeout)
        print(f'  {name} ready on {addr}')
        return channel
    except grpc.FutureTimeoutError:
        print(f'  {FAIL}: {name} did not become ready within {timeout}s')
        sys.exit(1)


def clean_db_files():
    for path in ('data/flags.db', 'data/audit.db'):
        full = os.path.join(REPO_ROOT, path)
        if os.path.exists(full):
            os.remove(full)

def set_flag(stub, name, enabled, by='integration-test', reason='', desc=''):
    return stub.SetFlag(killswitch_pb2.FlagChangeRequest(
        flag=killswitch_pb2.Flag(name=name, enabled=enabled, description=desc),
        changed_by=by,
        reason=reason,
    ))


def assert_eq(label, actual, expected):
    if actual == expected:
        print(f'  {PASS}  {label}: {actual!r}')
    else:
        print(f'  {FAIL}  {label}: expected {expected!r}, got {actual!r}')
        sys.exit(1)

def scenario_1_set_and_propagate(fs_stub, bc_stub):
    print('\nScenario 1: SetFlag propagates to subscriber')

    received = queue.Queue()

    def subscribe():
        for update in bc_stub.SubscribeFlags(killswitch_pb2.Empty()):
            received.put(update)

    t = threading.Thread(target=subscribe, daemon=True)
    t.start()
    time.sleep(0.3)

    resp = set_flag(fs_stub, 'payment-fallback', True,
                    reason='scenario-1', desc='payment circuit breaker')
    assert_eq('SetFlag success', resp.success, True)

    try:
        update = received.get(timeout=5)
        assert_eq('FlagUpdate flag name',    update.flag.name,    'payment-fallback')
        assert_eq('FlagUpdate flag enabled', update.flag.enabled, True)
        assert_eq('FlagUpdate change_type',  update.change_type,  'ENABLED')
    except queue.Empty:
        print(f'  {FAIL}  No FlagUpdate received within 5s')
        sys.exit(1)


def scenario_2_policy_denial(fs_stub):
    print('\nScenario 2: Policy denial (protected flag)')

    resp = set_flag(fs_stub, 'payment-fallback', False,
                    reason='scenario-2-should-fail')
    assert_eq('SetFlag success',  resp.success, False)
    assert_eq('denial message contains "protected"',
              'protected' in resp.message.lower(), True)
    print(f'  denial message: {resp.message!r}')


def scenario_3_audit_history(fs_stub, audit_stub):
    print('\nScenario 3: Audit history persisted')

    resp = set_flag(fs_stub, 'disable-recommendations', True,
                    by='sre-oncall', reason='reducing load', desc='rec engine kill switch')
    assert_eq('SetFlag success', resp.success, True)

    time.sleep(0.2)

    history = audit_stub.GetHistory(
        killswitch_pb2.AuditQuery(flag_name='disable-recommendations', limit=5)
    )
    assert_eq('record count >= 1', len(history.records) >= 1, True)

    rec = history.records[0]
    assert_eq('audit flag_name',   rec.flag_name,  'disable-recommendations')
    assert_eq('audit new_value',   rec.new_value,  True)
    assert_eq('audit changed_by',  rec.changed_by, 'sre-oncall')
    assert_eq('audit policy_result', rec.policy_result, 'approved')


def scenario_4_multi_flag_stream(fs_stub, bc_stub):
    print('\nScenario 4: Multi-flag stream delivery')

    FLAGS_TO_SET = [
        ('cache-only-mode',         True,  'ENABLED'),
        ('disable-recommendations', False, 'DISABLED'),
        ('payment-fallback',        True,  'ENABLED'),
    ]

    received = queue.Queue()

    def subscribe():
        for update in bc_stub.SubscribeFlags(killswitch_pb2.Empty()):
            received.put(update)

    t = threading.Thread(target=subscribe, daemon=True)
    t.start()
    time.sleep(0.3)

    for name, enabled, _ in FLAGS_TO_SET:
        resp = set_flag(fs_stub, name, enabled, reason='scenario-4')
        assert_eq(f'SetFlag {name} success', resp.success, True)

    collected = []
    deadline = time.time() + 5
    while len(collected) < len(FLAGS_TO_SET) and time.time() < deadline:
        try:
            collected.append(received.get(timeout=1.0))
        except queue.Empty:
            continue

    assert_eq('updates received', len(collected), len(FLAGS_TO_SET))
    for i, (name, enabled, change_type) in enumerate(FLAGS_TO_SET):
        assert_eq(f'update[{i}] flag name',    collected[i].flag.name,    name)
        assert_eq(f'update[{i}] flag enabled', collected[i].flag.enabled, enabled)
        assert_eq(f'update[{i}] change_type',  collected[i].change_type,  change_type)


def scenario_5_delete_flag(fs_stub, bc_stub, audit_stub):
    print('\nScenario 5: Delete flag removes it and broadcasts DELETED')

    received = queue.Queue()

    def subscribe():
        for update in bc_stub.SubscribeFlags(killswitch_pb2.Empty()):
            received.put(update)

    t = threading.Thread(target=subscribe, daemon=True)
    t.start()
    time.sleep(0.3)

    resp = set_flag(fs_stub, 'payment-fallback', False,
                    reason='Deleted via Grus TUI')
    assert_eq('SetFlag delete success', resp.success, True)

    try:
        update = received.get(timeout=5)
        assert_eq('Delete FlagUpdate flag name', update.flag.name, 'payment-fallback')
        assert_eq('Delete FlagUpdate flag enabled', update.flag.enabled, False)
        assert_eq('Delete FlagUpdate change_type', update.change_type, 'DELETED')
    except queue.Empty:
        print(f'  {FAIL}  No delete FlagUpdate received within 5s')
        sys.exit(1)

    history = audit_stub.GetHistory(
        killswitch_pb2.AuditQuery(flag_name='payment-fallback', limit=5)
    )
    assert_eq('audit delete record count >= 1', len(history.records) >= 1, True)
    rec = history.records[0]
    assert_eq('delete audit flag_name', rec.flag_name, 'payment-fallback')
    assert_eq('delete audit new_value', rec.new_value, False)
    assert_eq('delete audit reason contains deleted', 'deleted via grus tui' in rec.reason.lower(), True)


def scenario_6_edit_flag(fs_stub, bc_stub, audit_stub):
    print('\nScenario 6: Edit flag updates properties and broadcasts UPDATED')

    received = queue.Queue()

    def subscribe():
        for update in bc_stub.SubscribeFlags(killswitch_pb2.Empty()):
            received.put(update)

    t = threading.Thread(target=subscribe, daemon=True)
    t.start()
    time.sleep(0.3)

    resp = set_flag(fs_stub, 'cache-only-mode', True,
                    reason='Edited via Grus TUI', desc='Updated cache behavior')
    assert_eq('SetFlag edit success', resp.success, True)

    try:
        update = received.get(timeout=5)
        assert_eq('Edit FlagUpdate flag name', update.flag.name, 'cache-only-mode')
        assert_eq('Edit FlagUpdate flag enabled', update.flag.enabled, True)
        assert_eq('Edit FlagUpdate change_type', update.change_type, 'UPDATED')
    except queue.Empty:
        print(f'  {FAIL}  No edit FlagUpdate received within 5s')
        sys.exit(1)

    history = audit_stub.GetHistory(
        killswitch_pb2.AuditQuery(flag_name='cache-only-mode', limit=5)
    )
    assert_eq('audit edit record count >= 1', len(history.records) >= 1, True)
    rec = history.records[0]
    assert_eq('edit audit flag_name', rec.flag_name, 'cache-only-mode')
    assert_eq('edit audit reason contains edited', 'edited via grus tui' in rec.reason.lower(), True)


def main():
    _tz_jakarta = datetime.timezone(datetime.timedelta(hours=7))
    current_hour = datetime.datetime.now(_tz_jakarta).hour
    mw_start, mw_end = MAINTENANCE_WINDOW_LOCAL
    if mw_start <= current_hour < mw_end:
        print(
            f'ERROR: Current hour is {current_hour:02d}:xx (UTC+7), which falls within the '
            f'maintenance window ({mw_start:02d}:00-{mw_end:02d}:00 UTC+7).\n'
            f'The Policy Evaluator will deny all flag changes.\n'
            f'Re-run this test outside the maintenance window, or shift '
            f'MAINTENANCE_WINDOW_UTC in policy_evaluator/engine.py.'
        )
        sys.exit(1)

    print('Kill Switch Relay - Integration Tests\n')

    clean_db_files()

    print('Starting services...')
    procs = start_services()

    try:
        print('\nWaiting for services...')
        fs_channel = wait_for_service(FLAG_STORE_ADDR,  'Flag Store')
        bc_channel = wait_for_service(BROADCASTER_ADDR, 'Broadcaster')
        au_channel = wait_for_service(AUDIT_ADDR,       'Audit Logger')

        fs_stub    = killswitch_pb2_grpc.FlagStoreStub(fs_channel)
        bc_stub    = killswitch_pb2_grpc.BroadcasterStub(bc_channel)
        audit_stub = killswitch_pb2_grpc.AuditLoggerStub(au_channel)

        scenario_1_set_and_propagate(fs_stub, bc_stub)
    scenario_2_policy_denial(fs_stub)
    scenario_3_audit_history(fs_stub, audit_stub)
    scenario_4_multi_flag_stream(fs_stub, bc_stub)
    scenario_5_delete_flag(fs_stub, bc_stub, audit_stub)
    scenario_6_edit_flag(fs_stub, bc_stub, audit_stub)

    print('\nSUCCESS: All scenarios passed!')

    finally:
        stop_services(procs)
        clean_db_files()


if __name__ == '__main__':
    main()
