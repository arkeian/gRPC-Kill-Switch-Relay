# Grus dan Surg: Kill Switch Relay

## Anggota

| Nama | NRP |
|------|-----|
| Ahmad Wildan Fawwaz | 5027241001 |
| Muhammad Rakha Hananditya R. | 5027241015 |

---

## Apa Ini?

**Grus** adalah engine feature flag real-time berbasis gRPC dan bertindak sebagai manajemen untuk seluruh status flag di sistem Anda, mulai dari kill switch darurat, circuit breaker, hingga mode eksperimen yang dapat diaktifkan dan dimatikan tanpa deploy ulang.

**Surg** adalah UI wrapper berbasis web dan berkomunikasi dengan Grus melewati WebSocket. Buka browser, lihat seluruh flag sistem secara live, mengubah status dalam satu klik, dan pantau setiap perubahan yang terjadi secara real-time.

---

## Mengapa Grus?

Mayoritas sistem manajemen flag bekerja dengan cara yang sama: klien melakukan polling ke server secara berkala untuk mengecek apakah ada perubahan. Artinya ada *jeda* antara perubahan dibuat dan efeknya dirasakan, kemungkinan bisa 30 detik, bisa 5 menit, tergantung interval polling.

Grus bekerja secara berbeda.

### Propagasi Sub-Detik via gRPC Streaming

Setiap perubahan flag dikirimkan ke seluruh subscriber secara langsung menggunakan server-streaming gRPC, bukan polling. Saat Anda mengubah flag di Surg, seluruh sistem yang berlangganan menerima perubahan tersebut dalam hitungan milidetik.

### Validasi Kebijakan Sebelum Perubahan Tersimpan

Setiap mutasi melewati lapisan `PolicyEvaluator` sebelum data apa pun ditulis. Flag dapat dikonfigurasi sebagai:

- **Protected**: tidak dapat dinonaktifkan, bahkan oleh operator. Cocok untuk flag yang menjaga ketersediaan sistem kritis.
- **Mutex**: dua flag tidak dapat aktif bersamaan. Jika flag A dinyalakan, flag B dimatikan secara otomatis, dan sebaliknya.

Penolakan dikembalikan sebelum SQLite disentuh. Tidak ada setengah-perubahan, tidak ada state yang tidak konsisten.

### Audit Trail yang Tidak Dapat Dihilangkan

Setiap perubahan, siapa, apa, kapan, mengapa, dan apakah disetujui oleh kebijakan akan dicatat ke SQLite melalui `AuditLogger` yang berjalan sebagai layanan terpisah. Ini bukan log aplikasi biasa yang bisa terhapus saat container di-restart. Audit berjalan independen dari engine utama.

### Arsitektur Microservices, Bukan Monolith Tersembunyi

Grus terdiri dari empat layanan gRPC yang terpisah dengan tanggung jawab yang jelas:

| Layanan | Port | Tanggung Jawab |
|---------|------|----------------|
| FlagStore | 50051 | Sumber kebenaran. Mengorkestrasi seluruh alur perubahan. |
| PolicyEvaluator | 50052 | Gatekeeper stateless. Memvalidasi setiap perubahan terhadap aturan. |
| Broadcaster | 50053 | Fan-out pub/sub. Mendistribusikan update ke seluruh subscriber secara real-time. |
| AuditLogger | 50054 | Pencatatan persisten. Merekam setiap perubahan ke SQLite. |

Setiap layanan dapat dimonitor, di-scale, dan di-restart secara independen.

### Self-Hosted, Data Tidak Keluar

Grus dan Surg berjalan sepenuhnya di infrastruktur Anda. Tidak ada data flag, tidak ada audit history, tidak ada konfigurasi kebijakan yang dikirim ke server eksternal.

---

## Alur Perubahan Flag

```
Operator (via Surg)
       │
       ▼
  FlagStore ──► PolicyEvaluator (validasi)
       │              │
       │         DITOLAK → kembalikan error, tidak ada tulis
       │
   DISETUJUI
       │
       ├──► SQLite (simpan)
       ├──► Broadcaster ──► semua subscriber (sub-detik)
       └──► AuditLogger ──► SQLite audit (persisten)
```

---

## Prasyarat

- Python 3.10 atau lebih baru
- pip

---

## Instalasi

**1. Clone repositori:**
```bash
git clone <repo-url>
cd gRPC-Kill-Switch-Relay
```

**2. Buat virtual environment:**
```bash
python -m venv .venv
source .venv/bin/activate   # (Linux/macOS)
# atau: .venv\Scripts\activate  (Windows)
```

**3. Install Grus dan Surg:**
```bash
pip install -e grus/
pip install -e surg/
```

---

## Cara Menjalankan

### Menjalankan dengan Surg (Direkomendasikan)

Surg secara otomatis mendeteksi apakah Grus sudah berjalan. Jika belum, ia akan memulai Grus terlebih dahulu, lalu membuka UI di browser.

```bash
surg
```

Buka `http://localhost:8080` di browser. Saat pertama kali dijalankan, Anda akan diminta memasukkan nama operator.

### Menjalankan Grus Saja (Tanpa UI)

```bash
grus
```

Grus akan menjalankan keempat layanan gRPC secara headless dan menunggu hingga Ctrl+C.

### Opsi Environment

```bash
grus --env=dev    # default, logging INFO
grus --env=prod   # logging WARNING, tanpa prompt seed data
```

**Catatan**: Surg hanya berjalan pada Grus versi prod.
---

## Konfigurasi

### Surg (`surg/surg.toml`)

```toml
[server]
host = "localhost"
port = 8080

[operator]
name = "[NAMA USER]"          # diisi otomatis saat pertama kali dijalankan

[grus]
executable = "grus"         # path ke binary grus

[behavior]
idle_timeout_minutes = 60   # Surg dan Grus berhenti otomatis setelah idle; 0 = nonaktif
```

### Aturan Kebijakan (`grus/config/policy_rules.toml`)

```toml
# Flag yang tidak dapat dinonaktifkan
protected_flags = ["payment-fallback"]

# Pasangan flag yang tidak dapat aktif bersamaan
[[mutual_exclusion]]
flags = ["cache-only-mode", "disable-cache-refresh"]

# Semua perubahan diblokir dalam jendela waktu ini
[maintenance_window]
start_hour = 2
end_hour = 4
timezone_offset = 7
```

---

## Menjalankan Test Integrasi

```bash
source .venv/bin/activate
PYTHONPATH="$(pwd)" python grus/tests/integration_test.py
```

Test ini memulai keempat layanan sebagai subprocess, menguji propagasi flag, penolakan kebijakan, pencatatan audit, dan multi-flag streaming, lalu mematikan semua layanan.

---

## Struktur Proyek

```
gRPC-Kill-Switch-Relay/
├── grus/                    ← Engine gRPC
│   ├── flag_store/          ← FlagStore service (port 50051)
│   ├── policy_evaluator/    ← PolicyEvaluator service (port 50052)
│   ├── broadcaster/         ← Broadcaster service (port 50053)
│   ├── audit_logger/        ← AuditLogger service (port 50054)
│   ├── tui/                 ← TUI (dipertahankan, tidak aktif)
│   ├── config/              ← TOML configs (policy_rules, env)
│   ├── data/                ← SQLite databases
│   ├── logs/
│   ├── tests/
│   └── setup.py
├── surg/                    ← UI Wrapper
│   ├── main.py              ← Entry point, lifecycle Grus
│   ├── socket_server.py     ← Socket.io handlers, gRPC bridge
│   ├── streams.py           ← Background streams + idle timer
│   ├── grpc_client.py       ← Async gRPC client
│   ├── config.py            ← Loader surg.toml
│   ├── surg.toml            ← Konfigurasi Surg
│   ├── frontend/            ← Source React (TypeScript + Vite + Tailwind)
│   ├── dist/                ← Build React siap pakai
│   └── setup.py
├── protos/
│   └── killswitch.proto     ← Definisi seluruh RPC dan message
├── generated/
│   ├── killswitch_pb2.py
│   └── killswitch_pb2_grpc.py
└── assets/                  ← Logo dan brand assets
```
