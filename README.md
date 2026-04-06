# Grus: Kill Switch Relay

## Anggota

| Nama | NRP |
|------|-----|
| Ahmad Wildan Fawwaz | 5027241001 |
| Muhammad Rakha Hananditya R. | 5027241015 |

## Gambaran Umum

Grus adalah sistem flag operasional real-time berbasis gRPC untuk komunikasi antar layanan infrastruktur. Sistem ini menyediakan kill switch, circuit breaker, dan mode switch yang dapat diubah saat runtime. Setiap perubahan flag divalidasi oleh kebijakan, disiarkan ke subscriber secara real-time, dan dicatat dalam audit trail.

Grus dilengkapi TUI (Terminal User Interface) interaktif yang menjalankan seluruh sistem dalam satu perintah.

## Arsitektur

| Layanan | Port | Peran |
|---------|------|-------|
| Flag Store | 50051 | Sumber kebenaran untuk seluruh status flag. Mengorkestrasi alur perubahan. |
| Policy Evaluator | 50052 | Gatekeeper stateless. Memvalidasi perubahan terhadap aturan sebelum disimpan. |
| Broadcaster | 50053 | Mengelola stream subscriber dan mendistribusikan perubahan flag secara real-time. |
| Audit Logger | 50054 | Mencatat setiap perubahan flag ke SQLite dan menyediakan query serta stream langsung. |

### Tabel RPC

| RPC | Layanan | Tipe | Deskripsi |
|-----|---------|------|-----------|
| `SetFlag` | Flag Store | Unary | Mengubah flag. Memicu alur: validasi → simpan → broadcast → audit. |
| `GetFlag` | Flag Store | Unary | Membaca status satu flag. |
| `ListFlags` | Flag Store | Unary | Mengembalikan semua flag. |
| `ValidateChange` | Policy Evaluator | Unary | Mengevaluasi perubahan terhadap aturan kebijakan. |
| `SubscribeFlags` | Broadcaster | Server-streaming | Menerima update flag secara real-time. |
| `NotifyChange` | Broadcaster | Unary | Dipanggil Flag Store untuk mendistribusikan update. |
| `LogChange` | Audit Logger | Unary | Menyimpan catatan perubahan. |
| `GetHistory` | Audit Logger | Unary | Mengambil riwayat audit. |
| `StreamHistory` | Audit Logger | Server-streaming | Menerima catatan audit secara real-time. |

### Alur Kerja

1. Pengguna mengirim `SetFlag` ke Flag Store.
2. Flag Store membaca status flag saat ini dan seluruh flag dari SQLite.
3. Flag Store memanggil `PolicyEvaluator.ValidateChange` dengan konteks seluruh flag.
4. Jika ditolak: langsung mengembalikan error. Tidak ada data yang ditulis.
5. Jika disetujui: Flag Store menulis ke SQLite (upsert).
6. Flag Store memanggil `Broadcaster.NotifyChange` untuk distribusi ke subscriber.
7. Flag Store memanggil `AuditLogger.LogChange` untuk pencatatan.
8. Flag Store mengembalikan respons sukses.

## Prasyarat

- Python 3.10+
- pip

## Cara Menjalankan

### Opsi 1: Grus TUI (Direkomendasikan)

Grus TUI menjalankan seluruh sistem dalam satu perintah — otomatis memulai keempat layanan, menyediakan antarmuka interaktif, dan menangani shutdown.

**1. Clone dan masuk ke proyek:**
```bash
git clone <repo-url>
cd gRPC-Kill-Switch-Relay
```

**2. Install dependensi dan Grus:**
```bash
pip install -e .
```

**3. Jalankan Grus:**
```bash
grus
```

Saat pertama kali dijalankan, Grus akan:
- Memeriksa dan me-regenerasi file protobuf jika diperlukan
- Memulai keempat layanan gRPC
- Menanyakan apakah ingin memuat data demo (5 flag contoh)
- Meluncurkan TUI interaktif

**Pilihan environment:**
```bash
grus --env=dev    # default, logging INFO
grus --env=demo   # logging DEBUG, timeout lebih panjang
grus --env=prod   # logging WARNING, tanpa prompt seed data
```

### Opsi 2: Manual (Tanpa TUI)

**1. Generate protobuf:**
```bash
bash scripts/generate_protos.sh
```

**2. Jalankan semua layanan:**
```bash
bash scripts/run_all.sh
```

**3. Hentikan layanan:** Tekan `Ctrl+C`.

## Panduan TUI

### Navigasi Tab

| Tombol | Fungsi |
|--------|--------|
| `1` | Tab Flag Management |
| `2` | Tab Live Stream |
| `3` | Tab Audit History |
| `4` | Tab Policy Testing |
| `5` | Tab System Logs |
| `Q` | Keluar (shutdown semua layanan) |
| `?` | Tampilkan bantuan shortcut |

### Tab 1: Flag Management

Menampilkan seluruh flag beserta status (ON/OFF), badge protected, dan indikator mutex.

| Tombol | Fungsi |
|--------|--------|
| `T` | Toggle flag (enable/disable) |
| `A` | Tambah flag baru |
| `D` | Nonaktifkan flag |
| `I` | Lihat detail flag |
| `R` | Refresh daftar |
| `X` | Ekspor ke JSON |

### Tab 2: Live Stream Monitor

Menampilkan output real-time dari `SubscribeFlags` — setiap perubahan flag muncul langsung.

| Tombol | Fungsi |
|--------|--------|
| `P` | Pause/Resume |
| `C` | Bersihkan log |
| `F` | Filter berdasarkan nama flag |
| `S` | Cari teks |

### Tab 3: Audit History

Tabel riwayat audit dengan paginasi.

| Tombol | Fungsi |
|--------|--------|
| `R` | Refresh |
| `F` | Filter berdasarkan nama flag |
| `N` / `P` | Halaman berikutnya / sebelumnya |
| `X` | Ekspor ke CSV |

### Tab 4: Policy Testing

Form untuk menguji validasi kebijakan secara dry-run (tidak mengubah flag).

Pilih flag, pilih state yang diajukan, isi `changed_by`, lalu tekan tombol Validate. Hasil ditampilkan langsung: APPROVED (hijau) atau DENIED (merah) beserta alasan.

### Tab 5: System Logs

Menampilkan log gabungan dari seluruh layanan dengan warna berbeda per layanan:
- Flag Store: Biru
- Policy Evaluator: Hijau
- Broadcaster: Kuning
- Audit Logger: Magenta
- Grus: Cyan

| Tombol | Fungsi |
|--------|--------|
| `P` | Pause/Resume |
| `C` | Bersihkan log |
| `S` | Cari teks |

## Konfigurasi

### File Konfigurasi

| File | Fungsi |
|------|--------|
| `config/dev.toml` | Konfigurasi environment development |
| `config/demo.toml` | Konfigurasi environment demo |
| `config/prod.toml` | Konfigurasi environment production |
| `config/policy_rules.toml` | Aturan kebijakan (protected flags, mutex, maintenance window) |
| `config/seed_flags.toml` | Data flag demo untuk first-run |

### Aturan Kebijakan (`config/policy_rules.toml`)

**Protected flags** - Flag yang tidak dapat dinonaktifkan:
```toml
protected_flags = ["payment-fallback"]
```

**Mutual exclusion** - Pasangan flag yang tidak dapat aktif bersamaan:
```toml
[[mutual_exclusion]]
flags = ["cache-only-mode", "disable-cache-refresh"]
```

**Maintenance window** - Semua perubahan diblokir dalam jendela waktu:
```toml
[maintenance_window]
start_hour = 2
end_hour = 4
timezone_offset = 7
```

## Menjalankan Test

```bash
PYTHONPATH="$(pwd)" python tests/integration_test.py
```

Test ini menjalankan keempat layanan sebagai subprocess, menguji 4 skenario (propagasi, policy denial, audit, multi-flag stream), lalu mematikan layanan.

## Struktur Proyek

```
gRPC-Kill-Switch-Relay/
├── protos/
│   └── killswitch.proto
├── generated/
│   ├── killswitch_pb2.py
│   └── killswitch_pb2_grpc.py
├── flag_store/
│   ├── server.py
│   └── store.py
├── policy_evaluator/
│   ├── server.py
│   └── engine.py
├── broadcaster/
│   ├── server.py
│   └── subscriber_manager.py
├── audit_logger/
│   ├── server.py
│   └── logger.py
├── grus/
│   ├── main.py
│   ├── app.py
│   ├── config.py
│   ├── grpc_client.py
│   ├── process_manager.py
│   ├── proto_check.py
│   ├── seed.py
│   └── tabs/
│       ├── flag_management.py
│       ├── live_stream.py
│       ├── audit_history.py
│       ├── policy_testing.py
│       └── system_logs.py
├── config/
│   ├── dev.toml
│   ├── demo.toml
│   ├── prod.toml
│   ├── policy_rules.toml
│   └── seed_flags.toml
├── data/
├── scripts/
│   ├── generate_protos.sh
│   └── run_all.sh
├── tests/
│   └── integration_test.py
└── setup.py
```
