# Kill Switch Relay

## 1. Project Overview

Kill Switch Relay is a lightweight, real-time operational flag system built for machine-to-machine communication over gRPC. It provides a structured way for infrastructure services to toggle operational behaviors at runtime — kill switches that disable a degraded subsystem, circuit breaker flags that redirect traffic to fallbacks, and mode switches that alter service behavior during incidents. It is not a user-facing feature flag tool and is not designed for A/B testing or product experimentation.

**Who it's for:** Platform engineering teams, SREs, and infrastructure engineers who need a programmable control plane for operational flags between internal services. It is designed to be forked and embedded into an existing system, not run as managed SaaS.

**Core philosophy:** Flags represent operational state, not product decisions. Every flag change is validated by policy before it is accepted, broadcast to all subscribers in real time, and written to an immutable audit trail. The system is intentionally minimal — no web UI, no REST API, no external dependencies beyond grpcio and SQLite.

**Why gRPC and not REST:** gRPC's server-streaming RPC type maps directly onto the push-notification pattern that flag distribution requires. A subscriber opens a single long-lived stream and receives flag updates as they happen, with no polling. Proto contracts enforce the message schema at both ends, catching integration errors at compile time rather than at runtime. For low-latency internal M2M communication, gRPC's binary framing also outperforms JSON/HTTP in both throughput and payload size.

---

## 2. Architecture

### Services

| Service | Port | Role |
|---|---|---|
| Flag Store | 50051 | Source of truth for all flag state. Owns reads, writes, and orchestrates the change flow. |
| Policy Evaluator | 50052 | Stateless gatekeeper. Validates every proposed change against configured rules before it is committed. |
| Broadcaster | 50053 | Manages subscriber streams. Receives change notifications from the Flag Store and fans them out to all connected clients. |
| Audit Logger | 50054 | Persistence layer for the change history. Records every committed change and exposes it via query and live stream. |

### RPC Table

| RPC | Service | Type | Description |
|---|---|---|---|
| `SetFlag` | Flag Store | Unary | Submit a flag change. Triggers the full validate → persist → notify → log flow. |
| `GetFlag` | Flag Store | Unary | Read the current state of a single flag by name. |
| `ListFlags` | Flag Store | Unary | Return all flags. |
| `ValidateChange` | Policy Evaluator | Unary | Evaluate a proposed change against all rules. Returns approved/denied with reason. |
| `SubscribeFlags` | Broadcaster | Server-streaming | Open a live stream. Receive a `FlagUpdate` message each time any flag changes. |
| `NotifyChange` | Broadcaster | Unary | Called by Flag Store to push an update to all active subscribers. |
| `LogChange` | Audit Logger | Unary | Persist a single change record. |
| `GetHistory` | Audit Logger | Unary | Query the audit log, optionally filtered by flag name and limited by count. |
| `StreamHistory` | Audit Logger | Server-streaming | Receive new audit records in real time as they are written. |

### SetFlag Flow (end-to-end)

1. A client sends `SetFlag(FlagChangeRequest)` to the Flag Store (50051).
2. Flag Store reads the current state of the target flag from SQLite. It also reads all flags to build the policy context.
3. Flag Store calls `PolicyEvaluator.ValidateChange` (50052), passing the current flag state, the proposed new state, and all current flags as context. This allows the Policy Evaluator to enforce rules that depend on other flags (e.g., mutex pairs) without querying the database itself.
4. If the Policy Evaluator returns `approved: false`, Flag Store returns `FlagChangeResponse(success: false)` immediately. Nothing is written. Steps 5–7 do not execute.
5. If approved, Flag Store writes the new flag state to SQLite with an upsert.
6. Flag Store calls `Broadcaster.NotifyChange` (50053) with a `FlagUpdate`. The Broadcaster fans it out to every active `SubscribeFlags` stream.
7. Flag Store calls `AuditLogger.LogChange` (50054) with an `AuditRecord` containing the old value, new value, who made the change, why, and the policy result.
8. Flag Store returns `FlagChangeResponse(success: true)` to the caller.

### Failure Handling

Steps 6 and 7 (Broadcaster and Audit Logger) are non-fatal. Each is wrapped in an independent `try/except`. If either service is unreachable or returns an error, the Flag Store logs a warning with the flag name, target service, and error message, then continues. The flag change has already been committed to SQLite at that point and the caller receives `success: true`.

This is a deliberate eventual-consistency trade-off: SQLite is the source of truth. A subscriber that misses an update due to a transient Broadcaster outage can call `GetFlag` or `ListFlags` to catch up. An audit record that fails to write is a visibility gap, not a data integrity problem.

Policy Evaluator failures are fatal to the request. If the Policy Evaluator is unreachable, `SetFlag` returns an error to the caller. No change is written.

---

## 3. Features

### What it can do

- **Real-time flag propagation** — clients subscribe once and receive updates via a persistent server-streaming RPC. No polling.
- **Policy enforcement** — every change is validated before it is committed. Three rule types are supported: protected flags (cannot be disabled), mutex pairs (two flags that cannot both be enabled simultaneously), and time-based maintenance windows.
- **Context-aware policy evaluation** — the Flag Store passes the current state of all flags to the Policy Evaluator on each call, enabling cross-flag rules without giving the Policy Evaluator database access.
- **Full audit trail** — every committed change is recorded in SQLite with old value, new value, who changed it, why, and the policy outcome. Queryable by flag name with optional limit.
- **Live audit streaming** — `StreamHistory` delivers new audit records in real time as they are written, for live monitoring use cases.
- **Graceful degradation** — Broadcaster and Audit Logger outages do not block flag changes. The core read/write path (Flag Store + Policy Evaluator) is the minimal viable system.
- **Independent service deployment and testing** — Policy Evaluator and Audit Logger have no dependencies on other services and can be started and tested in isolation.

### What it cannot do

- **No authentication or authorization** — any caller can submit a flag change. This is a v1 limitation; see Section 9.
- **No TLS or encryption** — all gRPC channels are insecure. Do not expose these ports outside a trusted network.
- **No persistent subscriptions** �� if a `SubscribeFlags` client disconnects, it misses any updates that occurred while it was offline. It must call `GetFlag` or `ListFlags` on reconnect to synchronize state. `StreamHistory` has the same behavior.
- **No horizontal scaling** — each service is a single instance. The Flag Store and Audit Logger use SQLite, which does not support concurrent writers across processes.
- **No flag namespacing or multi-tenancy** — all flags share a single namespace. There is no concept of environments, projects, or owners.
- **No UI or dashboard** — operational interaction is via gRPC clients (the provided Python snippets, grpcurl, or custom clients).
- **No REST or HTTP API** — gRPC only. This is not a limitation to work around; it is a design constraint.
- **Not a replacement for LaunchDarkly, Flagsmith, or similar platforms** — those tools are designed for product experimentation, gradual rollouts, and user targeting. Kill Switch Relay is designed for binary operational control between infrastructure services.

---

## 4. Prerequisites

- Python 3.10 or later (tested on 3.14)
- `grpcio` and `grpcio-tools` — installed automatically by `generate_protos.sh`, or manually:

```bash
pip install grpcio grpcio-tools protobuf
```

- No external database. SQLite is used via the Python standard library.
- No Docker, no message broker, no additional infrastructure.

> **Python 3.14 note:** Daemon subscriber threads holding open gRPC stream iterators at interpreter shutdown will produce a `Fatal Python error: _enter_buffered_busy` abort message. All test assertions pass before shutdown; this is a Python 3.14 finalization quirk and does not affect correctness.

---

## 5. Getting Started

**1. Clone and enter the project:**
```bash
git clone <repo-url>
cd gRPC-Kill-Switch-Relay
```

**2. Generate protobuf stubs** (also installs grpcio dependencies):
```bash
bash scripts/generate_protos.sh
```

Expected output:
```
==> Installing gRPC dependencies...
==> Generating Python stubs from killswitch.proto...
==> Verifying output...
    OK  .../generated/killswitch_pb2.py
    OK  .../generated/killswitch_pb2_grpc.py
Proto generation complete.
```

**3. Start all services:**
```bash
bash scripts/run_all.sh
```

All four services start in dependency order (Policy Evaluator and Audit Logger first, then Broadcaster, then Flag Store). PIDs are written to `run_all.pids`. Logs go to `logs/`.

**4. Verify services are running:**
```bash
# Check ports are bound
ss -tlnp | grep -E '5005[1-4]'

# Tail all service logs
tail -f logs/50051-Flag_Store.log \
         logs/50052-Policy_Evaluator.log \
         logs/50053-Broadcaster.log \
         logs/50054-Audit_Logger.log
```

**5. Stop all services:**

Press `Ctrl+C` in the terminal running `run_all.sh`. All four services are killed cleanly via the EXIT trap.

---

## 6. Manual Evaluation Guide

### Setup

**Terminal 1 — start services:**
```bash
bash scripts/run_all.sh
```

**Terminal 2 — open a Python REPL:**
```bash
python
```

Paste this setup block once per session:
```python
import sys, time, threading
sys.path.insert(0, 'generated')
import grpc, killswitch_pb2, killswitch_pb2_grpc

fs  = killswitch_pb2_grpc.FlagStoreStub(grpc.insecure_channel('localhost:50051'))
pe  = killswitch_pb2_grpc.PolicyEvaluatorStub(grpc.insecure_channel('localhost:50052'))
bc  = killswitch_pb2_grpc.BroadcasterStub(grpc.insecure_channel('localhost:50053'))
al  = killswitch_pb2_grpc.AuditLoggerStub(grpc.insecure_channel('localhost:50054'))

def flag(name, enabled, desc=''):
    return killswitch_pb2.Flag(name=name, enabled=enabled, description=desc)
```

> **Maintenance window:** The Policy Evaluator blocks all changes between 02:00–04:00 **UTC+7** (Asia/Jakarta). If you are in that window, `SetFlag` calls will be denied. To bypass it temporarily, change `MAINTENANCE_WINDOW_UTC = (2, 4)` to any window that excludes the current Jakarta hour in `policy_evaluator/engine.py` and restart the services.

---

### Policy Evaluator in isolation (port 50052)

Call `ValidateChange` directly — no other services required.

**Rule 1 — protected flag cannot be disabled:**
```python
pe.ValidateChange(killswitch_pb2.PolicyRequest(
    current_flag=flag('payment-fallback', True),
    proposed_change=flag('payment-fallback', False),
    changed_by='test',
))
# approved: false  denial_reason: "'payment-fallback' is a protected flag..."
```

**Rule 1 — enabling a protected flag is allowed:**
```python
pe.ValidateChange(killswitch_pb2.PolicyRequest(
    current_flag=flag('payment-fallback', False),
    proposed_change=flag('payment-fallback', True),
    changed_by='test',
))
# approved: true  (outside maintenance window)
```

**Rule 2 — mutex pair: both cannot be enabled simultaneously:**
```python
pe.ValidateChange(killswitch_pb2.PolicyRequest(
    current_flag=flag('cache-only-mode', False),
    proposed_change=flag('cache-only-mode', True),
    changed_by='test',
    context_flags=[flag('disable-cache-refresh', True)],  # already enabled
))
# approved: false  denial_reason: "mutually exclusive..."
```

**Rule 2 — enabling one when the other is off is allowed:**
```python
pe.ValidateChange(killswitch_pb2.PolicyRequest(
    current_flag=flag('cache-only-mode', False),
    proposed_change=flag('cache-only-mode', True),
    changed_by='test',
    context_flags=[flag('disable-cache-refresh', False)],
))
# approved: true
```

**Rule 3 — maintenance window (shift the window to the current Jakarta hour to test the denial path):**
```python
pe.ValidateChange(killswitch_pb2.PolicyRequest(
    current_flag=flag('disable-recommendations', False),
    proposed_change=flag('disable-recommendations', True),
    changed_by='test',
))
# approved: false  denial_reason: "...maintenance window...Current hour: XX (UTC+7)"
# approved: true   (outside the window)
```

---

### Audit Logger in isolation (port 50054)

**Write a record directly:**
```python
al.LogChange(killswitch_pb2.AuditRecord(
    flag_name='payment-fallback',
    old_value=True, new_value=False,
    changed_by='ops-manual',
    changed_at=int(time.time()),
    reason='manual eval test',
    policy_result='approved',
))
# Empty {}
```

**Query it back — filtered:**
```python
al.GetHistory(killswitch_pb2.AuditQuery(flag_name='payment-fallback', limit=5))
# AuditHistoryResponse with records
```

**Query all records:**
```python
al.GetHistory(killswitch_pb2.AuditQuery(limit=10))
```

**Live stream — open in a background thread, then write:**
```python
def watch():
    for rec in al.StreamHistory(killswitch_pb2.Empty()):
        print(f'[StreamHistory] {rec.flag_name} {rec.old_value}->{rec.new_value} by {rec.changed_by}')

threading.Thread(target=watch, daemon=True).start()
time.sleep(0.2)

al.LogChange(killswitch_pb2.AuditRecord(
    flag_name='cache-only-mode',
    old_value=False, new_value=True,
    changed_by='ops-manual',
    changed_at=int(time.time()),
    reason='testing stream',
    policy_result='approved',
))
# [StreamHistory] line prints immediately
```

---

### Broadcaster in isolation (port 50053)

**Subscribe, then push an update:**
```python
def watch():
    for upd in bc.SubscribeFlags(killswitch_pb2.Empty()):
        print(f'[SubscribeFlags] {upd.flag.name} enabled={upd.flag.enabled} type={upd.change_type}')

threading.Thread(target=watch, daemon=True).start()
time.sleep(0.2)

bc.NotifyChange(killswitch_pb2.FlagUpdate(
    flag=flag('disable-recommendations', True),
    changed_by='ops-manual',
    timestamp=int(time.time()),
    change_type='ENABLED',
))
# [SubscribeFlags] line prints immediately
```

**Multiple concurrent subscribers — paste the subscribe block again, then call NotifyChange:**
```python
threading.Thread(target=watch, daemon=True).start()

bc.NotifyChange(killswitch_pb2.FlagUpdate(
    flag=flag('cache-only-mode', False),
    changed_by='ops-manual',
    timestamp=int(time.time()),
    change_type='DISABLED',
))
# Both subscriber threads print the update
```

---

### Flag Store — full stack (port 50051, all services must be running)

**Create a flag:**
```python
fs.SetFlag(killswitch_pb2.FlagChangeRequest(
    flag=flag('payment-fallback', True, 'payment circuit breaker'),
    changed_by='sre-oncall',
    reason='initial setup',
))
# FlagChangeResponse  success: true  message: "ok"
```

**Read it back:**
```python
fs.GetFlag(killswitch_pb2.FlagQuery(name='payment-fallback'))
# Flag  name: "payment-fallback"  enabled: true  description: "payment circuit breaker"
```

**List all flags:**
```python
fs.ListFlags(killswitch_pb2.Empty())
```

**Policy denial — try to disable the protected flag:**
```python
fs.SetFlag(killswitch_pb2.FlagChangeRequest(
    flag=flag('payment-fallback', False),
    changed_by='sre-oncall',
    reason='should be denied',
))
# FlagChangeResponse  success: false  message: "'payment-fallback' is a protected flag..."
```

**Mutex denial — enable both flags in the pair:**
```python
fs.SetFlag(killswitch_pb2.FlagChangeRequest(
    flag=flag('cache-only-mode', True),
    changed_by='sre-oncall', reason='step 1',
))

fs.SetFlag(killswitch_pb2.FlagChangeRequest(
    flag=flag('disable-cache-refresh', True),
    changed_by='sre-oncall', reason='should fail',
))
# success: false  message: "mutually exclusive..."
```

**Live subscriber watching a SetFlag:**
```python
def watch_all():
    for upd in bc.SubscribeFlags(killswitch_pb2.Empty()):
        print(f'[live] {upd.flag.name} enabled={upd.flag.enabled} by={upd.changed_by}')

threading.Thread(target=watch_all, daemon=True).start()
time.sleep(0.2)

fs.SetFlag(killswitch_pb2.FlagChangeRequest(
    flag=flag('disable-recommendations', True, 'rec engine kill switch'),
    changed_by='sre-oncall',
    reason='reducing load',
))
# SetFlag returns success: true
# [live] line prints from the broadcaster stream

al.GetHistory(killswitch_pb2.AuditQuery(flag_name='disable-recommendations', limit=1))
# Confirms audit record was written
```

**NOT_FOUND error for an unknown flag:**
```python
try:
    fs.GetFlag(killswitch_pb2.FlagQuery(name='nonexistent'))
except grpc.RpcError as e:
    print(e.code(), e.details())
# StatusCode.NOT_FOUND  "Flag 'nonexistent' not found"
```

---

### Observing the full log cascade

For any successful `SetFlag`, tail all four logs simultaneously and watch the cascade:

```bash
tail -f logs/50051-Flag_Store.log \
         logs/50052-Policy_Evaluator.log \
         logs/50053-Broadcaster.log \
         logs/50054-Audit_Logger.log
```

Expected sequence per successful `SetFlag`:
1. `[flag_store]` — `SetFlag: flag='...' enabled=... by='...'`
2. `[policy_evaluator]` — `Decision: APPROVED flag='...'`
3. `[flag_store]` — `Persisted: flag='...'`
4. `[broadcaster]` — `Notified N subscriber(s): flag='...'`
5. `[audit_logger]` — `Logged change: flag='...'`

A denied change stops at step 2. Nothing appears in the Broadcaster or Audit Logger logs.

---

## 7. Project Structure

```
gRPC-Kill-Switch-Relay/
├── protos/
│   └── killswitch.proto          Single source of truth for all service contracts.
│                                  Defines all 4 services, 9 RPCs, and 12 message types.
│
├── generated/                     protoc output. Regenerate with scripts/generate_protos.sh.
│   ├── killswitch_pb2.py          Message classes (do not edit).
│   ├── killswitch_pb2_grpc.py     Stub and servicer classes (do not edit).
│   └── __init__.py
│
├── flag_store/
│   ├── server.py                  gRPC server. Wires the servicer to stubs for all 3
│   │                              downstream services. Listens on port 50051.
│   └── store.py                   SQLite read/write logic. Implements the full SetFlag
│                                  flow: validate → persist → notify → log.
│
├── policy_evaluator/
│   ├── server.py                  gRPC server. Listens on port 50052.
│   └── engine.py                  Rule evaluation logic. Defines PROTECTED_FLAGS,
│                                  MUTEX_PAIRS, and the maintenance window check.
│                                  No database access.
│
├── broadcaster/
│   ├── server.py                  gRPC server. Listens on port 50053.
│   └── subscriber_manager.py      Thread-safe subscriber queue list. Handles add,
│                                  remove, fan-out, and shutdown sentinel.
│
├── audit_logger/
│   ├── server.py                  gRPC server. Listens on port 50054.
│   └── logger.py                  SQLite persistence for audit records. Manages
│                                  live StreamHistory subscriber queues.
│
├── scripts/
│   ├── generate_protos.sh         Installs grpcio-tools, runs protoc, verifies output.
│   └── run_all.sh                 Starts all 4 services in dependency order with
│                                  port readiness checks and clean EXIT trap shutdown.
│
└── tests/
    └── integration_test.py        Starts all 4 services as subprocesses, runs 4
                                   end-to-end scenarios, asserts on every step,
                                   then shuts down. Includes maintenance window guard.
```

---

## 8. Configuration

All configuration is in source files. There is no config file format or environment variable system in v1.

### Policy rules — `policy_evaluator/engine.py`

**Protected flags** — flags that can never be disabled:
```python
PROTECTED_FLAGS = {
    "payment-fallback",   # must always remain active for downstream payment fallback path
}
```

**Mutex pairs** — pairs of flags that cannot both be enabled simultaneously:
```python
MUTEX_PAIRS = [
    ("cache-only-mode", "disable-cache-refresh"),
    # cache-only-mode=True + disable-cache-refresh=True → cache goes stale with no refresh path
]
```

**Maintenance window** — all changes blocked during this window:
```python
_TZ_JAKARTA         = datetime.timezone(datetime.timedelta(hours=7))
MAINTENANCE_WINDOW_UTC = (2, 4)   # 02:00–04:00 UTC+7 (Asia/Jakarta)
```

To add a new protected flag, add its name to `PROTECTED_FLAGS`. To add a mutex pair, append a tuple to `MUTEX_PAIRS`. To change the timezone, replace `_TZ_JAKARTA` with the appropriate `datetime.timezone(datetime.timedelta(hours=N))` and update the comment.

### Example flag names (used in tests and evaluation)

| Flag name | Represents |
|---|---|
| `payment-fallback` | Fallback path for the payment processor. Protected. |
| `cache-only-mode` | Service serves exclusively from cache, bypasses live data. |
| `disable-cache-refresh` | Stops background cache refresh jobs. Mutex with `cache-only-mode`. |
| `disable-recommendations` | Kill switch for the recommendation engine. |

### Port assignments

| Service | Port |
|---|---|
| Flag Store | 50051 |
| Policy Evaluator | 50052 |
| Broadcaster | 50053 |
| Audit Logger | 50054 |

Ports are hardcoded in each service's `server.py` and in the Flag Store's outbound channel configuration.

---

## 9. Limitations and Future Work

### v1 limitations

**Security:** There is no authentication, authorization, or TLS. Any process that can reach the service ports can read and modify any flag. This makes v1 suitable only for trusted internal networks or local development. For production use, mTLS with service identity certificates is the appropriate control.

**Persistence model:** SQLite supports only a single writer at a time. The Flag Store and Audit Logger each hold a single connection with a threading lock. This is sufficient for low-to-moderate write rates on a single machine but does not support horizontal scaling.

**Subscription reliability:** `SubscribeFlags` and `StreamHistory` are live feeds only. A client that disconnects misses updates and has no way to request a replay of what it missed. Reconnecting clients must call `GetFlag`/`ListFlags` to resynchronize. A persistent subscription model (where the server tracks each subscriber's last-seen offset) would require a more stateful broadcaster and is not implemented.

**Observability:** Logging is written to files and stdout. There is no metrics endpoint, no tracing, and no structured log format. Integration with Prometheus or OpenTelemetry would require adding instrumentation to each servicer method.

### What v2 might include

- **mTLS + service identity** — each service presents a certificate; the Flag Store only accepts policy and broadcast calls from authenticated peers.
- **Token-based authorization** — callers supply a token in gRPC metadata; the Flag Store validates it before processing `SetFlag`.
- **Persistent subscriptions with replay** — subscribers register with a client ID; the Broadcaster tracks the last update delivered to each and replays missed updates on reconnect.
- **Admin CLI** — a small Python client for `SetFlag`, `GetFlag`, `ListFlags`, and `GetHistory` via the command line, for use in incident response without writing a REPL session.
- **Flag namespacing** — a `namespace` field on `Flag` to support multi-team or multi-environment deployments on a shared relay.
- **Configurable rules** — load `PROTECTED_FLAGS`, `MUTEX_PAIRS`, and window settings from a YAML or TOML file instead of hardcoding them, enabling rule changes without a service restart.
