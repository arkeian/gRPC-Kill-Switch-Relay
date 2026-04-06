# Estafet v1: Codename Mannheim

## Anggota

| Nama | NRP|
|-------------------------------|---------------|
| Ahmad Wildan Fawwaz| 5027241001 |
| Muhammad Rakha Hananditya R.| 5027241015 |

## 1. Gambaran Umum

<p align="justify">
    Estafet merupakan sistem flag operasional ringan dan real-time berbasis Python yang dibangun untuk komunikasi antar layanan dalam suatu infrastrukutur melalui kerangka kerja gRPC. Sistem ini menyediakan cara terstruktur bagi layanan infrastruktur untuk mengubah perilaku operasional saat runtime, layaknya kill switch yang dapat menonaktifkan suatu subsistem yang mengalami degradasi, flag circuit breaker untuk mengalihkan traffic ke fallback, serta mode switch untuk menyesuaikan perilaku layanan saat terjadi insiden.
</p>

**Who it's for:** Platform engineering teams, SREs, and infrastructure engineers who need a programmable control plane for operational flags between internal services. It is designed to be forked and embedded into an existing system, not run as managed SaaS.

**Core philosophy:** Flags represent operational state, not product decisions. Every flag change is validated by policy before it is accepted, broadcast to all subscribers in real time, and written to an immutable audit trail. The system is intentionally minimal — no web UI, no REST API, no external dependencies beyond grpcio and SQLite.

**Why gRPC and not REST:** gRPC's server-streaming RPC type maps directly onto the push-notification pattern that flag distribution requires. A subscriber opens a single long-lived stream and receives flag updates as they happen, with no polling. Proto contracts enforce the message schema at both ends, catching integration errors at compile time rather than at runtime. For low-latency internal M2M communication, gRPC's binary framing also outperforms JSON/HTTP in both throughput and payload size.

## 2. Arsitektur

### Layanan

| Layanan | Port | Peran |
|---|---|---|
| Flag Store | 50051 | Sumber kebenaran (source of truth) untuk seluruh status flag. Menangani operasi baca, tulis, dan mengorkestrasi alur perubahan. |
| Policy Evaluator | 50052 | Gatekeeper stateless. Memvalidasi setiap perubahan yang diajukan terhadap aturan yang dikonfigurasi sebelum disimpan. |
| Broadcaster | 50053 | Mengelola stream subscriber. Menerima notifikasi perubahan dari `Flag Store` dan mendistribusikannya ke semua klien yang terhubung. |
| Audit Logger | 50054 | Lapisan persistensi untuk riwayat perubahan. Mencatat setiap perubahan yang telah disimpan dan menyediakannya melalui query dan stream langsung. |

### Tabel RPC

| RPC | Layanan | Tipe gRPC | Deskripsi |
|---|---|---|---|
| `SetFlag` | Flag Store | Unary | Mengirim perubahan flag. Memicu alur lengkap: validasi → simpan → notifikasi → pencatatan. |
| `GetFlag` | Flag Store | Unary | Membaca status terkini dari satu flag berdasarkan nama. |
| `ListFlags` | Flag Store | Unary | Mengembalikan semua flag. |
| `ValidateChange` | Policy Evaluator | Unary | Mengevaluasi perubahan yang diajukan terhadap semua aturan. Mengembalikan hasil disetujui/ditolak beserta alasannya. |
| `SubscribeFlags` | Broadcaster | Server-streaming | Membuka stream langsung. Menerima pesan `FlagUpdate` setiap kali ada perubahan flag. |
| `NotifyChange` | Broadcaster | Unary | Dipanggil oleh Flag Store untuk mendorong update ke semua subscriber aktif. |
| `LogChange` | Audit Logger | Unary | Menyimpan satu catatan perubahan. |
| `GetHistory` | Audit Logger | Unary | Mengambil audit log, opsional difilter berdasarkan nama flag dan dibatasi jumlahnya. |
| `StreamHistory` | Audit Logger | Server-streaming | Menerima catatan audit baru secara real-time saat ditulis. |

### Alur Kerja Sistem

<ol style="text-align: justify;">
  <li>
    Pengguna mengirim <code>SetFlag(FlagChangeRequest)</code> ke Flag Store (50051).
  </li>
  <li>
    Flag Store membaca status saat ini dari flag target dari SQLite. Selain itu, Flag Store juga membaca semua flag untuk membangun konteks kebijakan.
  </li>
  <li>
    Flag Store memanggil <code>PolicyEvaluator.ValidateChange</code> (50052), dengan mengirimkan status flag saat ini, status baru yang diusulkan, serta seluruh flag sebagai konteks. Hal ini memungkinkan Policy Evaluator menegakkan aturan yang bergantung pada flag lain (misalnya pasangan mutual exclusion) tanpa perlu mengakses database secara langsung.
  </li>
  <li>
    Jika Policy Evaluator mengembalikan <code>approved: false</code>, maka Flag Store langsung mengembalikan <code>FlagChangeResponse(success: false)</code>. Tidak ada data yang ditulis. Langkah selanjutnya tidak dijalankan.
  </li>
  <li>
    Jika disetujui atau <code>approved: true</code>, Flag Store menulis status flag baru ke SQLite menggunakan mekanisme upsert.
  </li>
  <li>
    Flag Store memanggil <code>Broadcaster.NotifyChange</code> (50053) dengan <code>FlagUpdate</code>. Broadcaster kemudian mendistribusikan perubahan tersebut ke semua stream <code>SubscribeFlags</code> yang aktif.
  </li>
  <li>
    Flag Store memanggil <code>AuditLogger.LogChange</code> (50054) dengan <code>AuditRecord</code> yang berisi nilai lama, nilai baru, siapa yang melakukan perubahan, alasan perubahan, serta hasil evaluasi kebijakan.
  </li>
  <li>
    Flag Store mengembalikan <code>FlagChangeResponse(success: true)</code> kepada pengguna.
  </li>
</ol>

## 3. Fitur

### Apa yang Bisa Dilakukan Sistem

<ul style="text-align: justify;">
  <li>
    <b>Propagasi flag real-time</b>: Klien cukup berlangganan sekali dan akan menerima pembaruan melalui RPC server-streaming yang persisten. Tanpa polling.
  </li>
  <li>
    <b>Penegakan kebijakan</b>: Setiap perubahan divalidasi sebelum disimpan. Tiga jenis aturan didukung: protected flags (tidak dapat dinonaktifkan), mutex pairs (dua flag yang tidak dapat aktif bersamaan), dan maintenance window berbasis waktu.
  </li>
  <li>
    <b>Evaluasi kebijakan berbasis konteks</b>: Flag Store mengirimkan status seluruh flag saat ini ke Policy Evaluator pada setiap pemanggilan, memungkinkan aturan lintas-flag tanpa memberikan akses database ke Policy Evaluator.
  </li>
  <li>
    <b>Audit trail lengkap</b>: Setiap perubahan yang disimpan dicatat di SQLite dengan nilai lama, nilai baru, siapa yang mengubah, alasan perubahan, serta hasil evaluasi kebijakan. Dapat di-query berdasarkan nama flag dengan batas jumlah opsional.
  </li>
  <li>
    <b>Streaming audit langsung</b>: <code>StreamHistory</code> mengirimkan catatan audit baru secara real-time saat ditulis, yang dapat digunakan untuk kebutuhan monitoring langsung.
  </li>
  <li>
    <b>Graceful Degradation</b>: Gangguan pada Broadcaster dan Audit Logger tidak menghambat perubahan flag. Jalur inti baca/tulis (Flag Store + Policy Evaluator) adalah sistem minimal yang tetap berjalan.
  </li>
  <li>
    <b>Deployment dan pengujian layanan independen</b>: Policy Evaluator dan Audit Logger tidak memiliki dependensi terhadap layanan lain dan dapat dijalankan serta diuji secara terpisah.
  </li>
</ul>

### Apa yang Tidak Bisa Dilakukan Sistem

<ul style="text-align: justify;">
  <li>
    <b>Tidak ada autentikasi atau otorisasi</b>: Siapapun dapat mengirim perubahan flag.
  </li>
  <li>
    <b>Tidak ada TLS atau enkripsi</b>: Semua channel gRPC tidak aman. Jangan mengekspos port ini selain ke jaringan yang terpercaya.
  </li>
  <li>
    <b>Tidak ada subscription persisten</b>: Jika <code>SubscribeFlags</code> pengguna terputus, maka pembaruan yang terjadi selama offline akan terlewat. Pengguna harus memanggil <code>GetFlag</code> atau <code>ListFlags</code> saat tersambung kembali untuk sinkronisasi. <code>StreamHistory</code> memiliki perilaku yang sama.
  </li>
  <li>
    <b>Tidak ada horizontal scaling</b>: Setiap layanan berjalan sebagai satu instance. Flag Store dan Audit Logger menggunakan SQLite yang tidak mendukung penulisan paralel lintas proses.
  </li>
  <li>
    <b>Tidak ada namespacing flag atau multi-tenancy</b>: Semua flag berada dalam satu namespace. Tidak ada konsep environment atau kepemilikan flag.
  </li>
  <li>
    <b>Tidak ada UI atau dashboard</b>: Interaksi operasional dilakukan melalui klien gRPC (snippet Python yang disediakan, grpcurl, atau CLI yang telah disediakan).
  </li>
  <li>
    <b>Tidak ada REST atau HTTP API</b>: Sistem hanya berupa gRPC. Ini bukan keterbatasan yang harus dihindari, melainkan bagian dari desain.
  </li>
  <li>
    <b>Bukan pengganti LaunchDarkly, Flagsmith, atau platform serupa</b>: Alat-alat tersebut dirancang untuk eksperimen produk, rollout bertahap, dan targeting pengguna. Estafet dirancang untuk kontrol operasional biner antar layanan infrastruktur.
  </li>
</ul>

## 4. Prasyarat

- Python 3.10 atau versi lebih baru.
- `grpcio` and `grpcio-tools`.

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
