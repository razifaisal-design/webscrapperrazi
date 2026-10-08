# PRD — Sistem Monitoring Pengadaan Pemda Kota Pontianak (per KLPD)

| | |
|---|---|
| **Status** | Draft v1.1 (Revisi 2: cakupan berbasis KLPD) |
| **Tanggal** | 8 Oktober 2026 |
| **Target awal** | 1 KLPD yang ditentukan user — awal: Dinas Perumahan Rakyat dan Kawasan Permukiman (Perkim) Kota Pontianak (nama & kode diverifikasi saat discovery). Ke depan: beberapa KLPD, atau **semua KLPD satu kota**. |
| **Stack** | Python (scraper & parser) · Supabase/PostgreSQL · Next.js (dashboard) |
| **Menggantikan** | PRD "Desktop Application Suite & Document Generator" → dipindah ke [PRD-docgen-backlog.md](PRD-docgen-backlog.md) |

---

## 1. Ringkasan & Tujuan

Sistem ini mengambil data **publik** pengadaan Kota Pontianak, per **KLPD** (awal: Dinas Perkim), dari tiga sumber, menyimpannya di Supabase lengkap dengan riwayat perubahan, lalu menampilkannya di dashboard web yang memperbarui diri setiap 5 menit.

| Lapisan | Sumber | Pertanyaan yang dijawab |
|---|---|---|
| Anggaran | PDF SIPD (DPA/RKA) | Berapa anggaran per sub kegiatan/rekening? |
| Perencanaan | SiRUP | Berapa paket & total pagu? Paket mana yang berubah (pagu, metode, nama, kode RUP)? |
| Pelaksanaan | LPSE (SPSE) | Paket mana sudah tayang, sudah ada pemenang, sudah berkontrak? |

Dikerjakan dalam **3 bagian berurutan**, masing-masing utuh dari pengambilan data sampai tampil di dashboard:

1. **Bagian 1 — SiRUP** (pertama)
2. **Bagian 2 — LPSE** + perbandingan SiRUP ↔ LPSE
3. **Bagian 3 — SIPD (PDF)** + perbandingan anggaran ↔ RUP

## 2. Lingkup

**Cakupan target (dua mode):**
- `klpd` — satu atau beberapa KLPD yang ditentukan user (**v1 memakai mode ini dengan 1 KLPD**).
- `kota` — semua KLPD di satu kota; daftar KLPD dicacah otomatis dari SiRUP lalu dijalankan satu per satu.
- Multi-kota (lebih dari satu kota sekaligus) tetap di luar v1; skemanya tidak menghalangi.

> Catatan istilah: di SiRUP, KLPD = Kementerian/Lembaga/Perangkat Daerah pemilik RUP; di bawahnya ada satuan kerja. Hierarki sebenarnya (Pemda → KLPD → satker, atau tiap OPD = satu KLPD) dipastikan di Discovery 1a. Desain bekerja di kedua kemungkinan.

**Dalam lingkup**
- Scraper SiRUP & LPSE — data publik, tanpa login.
- Parser PDF SIPD — file diunggah manual.
- Supabase: skema & migrasi SQL, change log, view agregat.
- Dashboard Next.js read-only.

**Di luar lingkup (v1)**
- Generator dokumen docx/PDF (lihat backlog).
- Notifikasi Telegram/email, AI agent.
- Multi-kota aktif (skema siap; v1 hanya satu KLPD di Kota Pontianak).
- Detail transaksi e-Katalog.
- Login ke sistem pemerintah mana pun.

## 3. Arsitektur

```
 [SiRUP]      [LPSE/SPSE]      [PDF SIPD]
     \             |             /
      \            |            /
   Python scraper / parser  (jalan di Mac: manual atau launchd 2x sehari)
     - endpoint JSON publik dulu (httpx); Playwright hanya bila halaman wajib dirender
     - menulis ke tabel STAGING per run  (service_role key, hanya di .env lokal)
                   |
                   v
   Supabase Postgres
     finalize_run(run_id): validasi → diff → paket_events → upsert → tandai hilang
                   |
                   v
   SQL Views  (dibaca anon key, RLS read-only)
                   |
                   v
   Dashboard Next.js  (polling 5 menit, hosting Vercel)
```

**Struktur repo (usulan)**

```
docs/                      PRD, hasil discovery
scraper/                   paket Python
  core/                    http client "sopan", parser rupiah, run manager, repo Supabase
  sources/                 sirup.py, lpse.py, sipd_pdf.py
  cli.py                   python -m scraper run <sumber> ...
supabase/migrations/       *.sql (tabel, fungsi finalize_run, view, RLS)
dashboard/                 Next.js
tests/                     unit test + fixtures/ (sampel JSON/HTML/PDF asli)
```

## 4. Prinsip Data (berlaku untuk ketiga bagian)

1. **Run terakhir yang VALID adalah kebenaran.**
   Setiap eksekusi = satu baris `scrape_runs` **per (sumber, KLPD)**. Mode `kota` = N run terpisah; kegagalan satu KLPD tidak membatalkan atau merusak data KLPD lain. Sebuah run valid hanya jika:
   - selesai tanpa error, **dan**
   - jumlah baris = total yang dilaporkan situs sumber, atau (bila situs tidak melaporkan total) tidak turun > 20% dari run valid sebelumnya — kalau turun lebih, run ditandai `invalid` dan menunggu konfirmasi manual.

   Run gagal/parsial **tidak pernah** mengubah data yang tampil di dashboard.

2. **Finalisasi atomik di database.**
   Scraper hanya menulis ke tabel staging. Fungsi SQL `finalize_run(run_id)` dalam **satu transaksi**:
   membandingkan staging vs data aktif → menulis `paket_events` → upsert data → menandai paket yang tidak muncul lagi `is_active = false` (tidak dihapus).

3. **Kunci = ID resmi dari sumber** (kode RUP, kode tender).
   Tidak ada ID buatan dari hash, tidak ada deduplikasi berdasarkan nama paket. Nama yang mirip hanya menghasilkan penanda **"kemungkinan revisi"** untuk diperiksa manusia.

4. **Uang disimpan `NUMERIC` dalam rupiah penuh.**
   Satu fungsi parser rupiah Indonesia yang teruji: titik = pemisah ribuan, koma = desimal.
   `Rp 150.000.000,00` → `150000000`. Angka negatif/dalam kurung ditangani.

5. **Simpan data mentah.**
   Respons JSON/HTML ringkas per paket disimpan di staging agar parsing bisa diulang tanpa scraping ulang.

## 5. Model Data Bersama

| Tabel | Kolom utama | Keterangan |
|---|---|---|
| `target_scope` | id, nama, kota, mode (`klpd`/`kota`), tahun, aktif | Apa yang sedang dipantau |
| `klpd` | kode_klpd, nama, kota/pemda, jenis, URL sumber SiRUP/LPSE, target_scope_id | Satu baris per KLPD (diisi manual atau dari pencacahan kota) |
| `scrape_runs` | id, sumber (`SIRUP`/`LPSE`/`SIPD`), kode_klpd, tahun, mulai, selesai, status (`running`/`success`/`failed`/`invalid`), jumlah_baris, jumlah_diharapkan, catatan_error | Satu baris per eksekusi |
| `paket_events` | id, run_id, sumber, kunci, jenis (`BARU`/`BERUBAH`/`HILANG`/`MUNCUL_KEMBALI`), field, nilai_lama, nilai_baru, selisih_numeric, waktu | Satu tabel log untuk semua sumber. Jenis tambahan: `KLPD_BARU`/`KLPD_HILANG` dari pencacahan kota |

Semua tabel data (`sirup_paket`, `lpse_paket`, `sipd_*`, `scrape_runs`, `paket_events`) memuat `kode_klpd` (dan `kode_satker` bila ada), sehingga laporan bisa difilter per KLPD maupun diagregasi per kota.

---

## 6. BAGIAN 1 — SiRUP

**Tujuan:** daftar lengkap RUP untuk KLPD terpilih (awal: Dinas Perkim; penyedia + swakelola) tahun berjalan — akurat dan terlacak perubahannya.

### 1a. Discovery (tanpa kode produksi)
- Buka SiRUP untuk Kota Pontianak; **cacah semua KLPD** yang tersedia (kode, nama, jumlah paket) dan konfirmasi hierarki KLPD ↔ satker.
- User menetapkan KLPD awal dari daftar itu (atau memberi nama/kode langsung).
- Petakan endpoint JSON (DataTables) publik: URL, parameter paging/filter, total yang dilaporkan.
- Bandingkan field yang ada di daftar vs halaman detail paket.
- Cek `robots.txt` dan ketentuan penggunaan situs.
- Simpan sampel respons ke `tests/fixtures/sirup/`.
- **Hasil:** `docs/discovery-sirup.md`.

### 1b. Data — `sirup_paket`
`kode_rup` (PK), tahun, kode_klpd, kode_satker, nama_paket, jenis (penyedia/swakelola), jenis_pengadaan, metode_pemilihan, pagu, sumber_dana, waktu_pemilihan, lokasi, first_seen, last_seen, is_active, last_run_id, raw.

### 1c. Scraper
- Ambil **semua halaman** (paging penuh).
- Jeda ≥ 1–2 detik per request, satu koneksi, User-Agent jujur, timeout, retry dengan backoff.
- Berhenti dan lapor bila mendapat 403/429.
- CLI:
  - `python -m scraper run sirup --klpd <kode> [--klpd <kode> ...] --tahun 2026`
  - `python -m scraper run sirup --kota pontianak --tahun 2026` (mencacah semua KLPD, lalu menjalankan satu per satu secara berurutan)
  - Target default dibaca dari `config/targets.yaml`.
- Mode `kota`: perkiraan waktu total ditampilkan sebelum mulai; ada batas waktu per KLPD.

### 1d. Deteksi perubahan
- Field dipantau: pagu, metode pemilihan, nama paket, jenis pengadaan, sumber dana, waktu pemilihan.
- Paket `HILANG` + paket `BARU` dengan nama/pagu mirip di KLPD yang sama → penanda **"kemungkinan revisi RUP"**.

### 1e. Dashboard v1
- KPI: jumlah paket, total pagu, rincian per metode pemilihan dan penyedia/swakelola.
- Tabel paket: cari, filter, urut.
- Feed perubahan terbaru, contoh: *Pagu Rp150.000.000 → Rp200.000.000 (+Rp50.000.000)*.
- **Filter KLPD** (default: KLPD aktif) dan tampilan agregat "Seluruh Kota"; KPI dan tabel mengikuti filter.
- Keterangan "Data per run terakhir: tanggal/jam" + status run terakhir.

### Kriteria selesai Bagian 1
- [ ] Jumlah paket & total pagu di dashboard **sama persis** dengan angka di situs SiRUP untuk KLPD tersebut.
- [ ] Run ulang tanpa perubahan di situs → 0 event, 0 duplikat.
- [ ] Fixture dimodifikasi (pagu berubah, paket hilang, paket baru) → event yang tepat tercatat.
- [ ] Run dihentikan di tengah → dashboard tetap menampilkan run valid sebelumnya.
- [ ] Unit test parser rupiah & pemetaan field lulus.
- [ ] Menjalankan KLPD kedua tidak mengubah data KLPD pertama.
- [ ] Mode `kota` pada fixture multi-KLPD: total kota = jumlah total tiap KLPD; satu KLPD yang gagal tidak mengubah total KLPD lain.

---

## 7. BAGIAN 2 — LPSE

**Tujuan:** status pelaksanaan setiap RUP — tayang, pemenang, kontrak.

### Discovery
- Tentukan situs SPSE yang melayani Kota Pontianak (domain diverifikasi, mengingat migrasi ke INAPROC).
- Petakan endpoint daftar **tender** dan **non-tender**, serta halaman detail: pengumuman, jadwal, pemenang, pemenang berkontrak.
- Pastikan letak field kode RUP di detail paket.
- **Hasil:** `docs/discovery-lpse.md` + fixtures.

### Data
- `lpse_paket`: `kode_tender` (PK), jenis (tender/non-tender), nama, kode_klpd, kode_satker, pagu, HPS, tahap saat ini, pemenang, nilai penawaran/terkoreksi, nilai kontrak, tanggal jadwal kontrak, status batal/gagal, raw.
- `lpse_paket_rup`: (`kode_tender`, `kode_rup`) — relasi **many-to-many**, karena satu tender bisa memuat beberapa RUP.

### Status per RUP (view), memperhitungkan metode pemilihan

| Metode di SiRUP | Status yang mungkin |
|---|---|
| Swakelola | Swakelola (tidak melalui LPSE) |
| E-Purchasing | E-Katalog (tidak dipantau v1) |
| Tender, Seleksi, Pengadaan Langsung, Penunjukan Langsung | Belum Diumumkan → Sedang Proses → Ada Pemenang → Terjadwal Kontrak → Berkontrak · atau Gagal/Batal |

### Event
Perubahan tahap, pemenang ditetapkan, nilai kontrak muncul, HPS berubah.

### Dashboard v2
- Kolom status, HPS, dan nilai kontrak di tabel RUP.
- Funnel status paket.
- Selisih pagu → HPS → kontrak.
- Daftar anomali: tender tanpa kode RUP yang cocok.

### Kriteria selesai Bagian 2
- [ ] Setiap tender/non-tender KLPD terpilih tahun berjalan terhubung ke RUP-nya, atau masuk daftar anomali.
- [ ] Status dicek manual pada ≥ 10 sampel paket dan cocok dengan situs.
- [ ] Paket swakelola/e-purchasing tidak pernah berstatus "Belum Diumumkan".

---

## 8. BAGIAN 3 — SIPD (PDF)

**Tujuan:** membandingkan anggaran (DPA/RKA) dengan RUP.

### Input
- PDF SIPD diunggah manual (CLI dulu).
- Harus PDF teks (bukan hasil scan) — diverifikasi dengan sampel nyata.

### Parser
- `pdfplumber` dengan pengaturan disetel per jenis laporan.
- Bersihkan newline/tab/spasi ganda di dalam sel; gabungkan baris yang terpotong (word-wrap).
- Buang header berulang berdasarkan **posisi/pola**, bukan kata kunci isi (baris "Jumlah" dan uraian yang sah tidak boleh ikut terbuang).
- Bangun hierarki: program → kegiatan → sub kegiatan → akun/rekening → rincian.

### Data
- `sipd_dokumen`: file, hash, jenis laporan, versi, tanggal unggah.
- `sipd_anggaran`: kunci gabungan (tahun, kode_klpd, dokumen, kode sub kegiatan, kode rekening, urutan baris) — **bukan** kode rekening saja, karena kode rekening yang sama muncul di banyak sub kegiatan.
- Unggah versi baru → diff → `paket_events`.

### Validasi wajib
Jumlah per sub kegiatan hasil parse = baris "Jumlah" yang tercetak di PDF. Jika tidak sama, dokumen ditolak dengan laporan selisih.

### Dashboard v3
- Anggaran vs total pagu RUP per sub kegiatan.
- Anggaran yang belum punya RUP.

### Kriteria selesai Bagian 3
- [ ] Total hasil parse = total di PDF untuk semua sub kegiatan pada dokumen sampel.
- [ ] Unggah ulang dokumen yang sama → 0 event.

---

## 9. Kebutuhan Non-Fungsional

| Aspek | Ketentuan |
|---|---|
| **Etika & legal** | Hanya data publik tanpa login. Rate limit. Tidak menyamarkan bot dan tidak menembus captcha/proteksi. Bila diblokir: berhenti dan lapor. Jadwal scraping default **2x sehari**; dashboard boleh refresh tiap 5 menit karena hanya membaca Supabase. |
| **Keamanan** | `service_role` key hanya di `.env` lokal — tidak di-commit, tidak pernah di dashboard. Dashboard memakai anon key + RLS read-only pada view. Repo menyertakan `.env.example`. |
| **Keandalan** | Log ke file per run. Run gagal tidak merusak data. Semua proses idempoten. |
| **Kinerja** | Satu run SiRUP satu KLPD < 5 menit; mode `kota` berurutan (satu koneksi, jeda tetap), dijadwalkan 1x sehari. Dashboard termuat < 2 detik (agregasi di view SQL). |
| **Maintainability** | Logika parsing berupa fungsi murni dengan test berbasis fixture asli. Scraper, DB, dan dashboard terpisah. |

## 10. Risiko & Mitigasi

| Risiko | Mitigasi |
|---|---|
| Struktur/endpoint situs berubah (mis. migrasi ke INAPROC) | Discovery per bagian, fixture + test, run ditandai `invalid` bila field wajib kosong |
| Diblokir / rate-limited | Jadwal jarang, jeda antar request, berhenti saat 403/429 |
| Satu tender memuat banyak RUP; RUP direvisi dengan kode baru | Relasi many-to-many; penanda "kemungkinan revisi" |
| Format PDF SIPD berbeda per jenis laporan | Parser per jenis + validasi total |
| Mac mati saat jadwal | Run manual tetap tersedia; opsi pindah ke VPS di fase lanjut |

## 11. Pertanyaan Terbuka

1. Kode/nama KLPD awal yang dituju (bila sudah tahu); dan apakah "semua KLPD satu kota" berarti semua Dinas/OPD Pemkot Pontianak (asumsi saat ini) atau juga lembaga vertikal yang berlokasi di kota tsb.
2. Tahun anggaran yang dipantau: 2026 saja, atau juga 2025 / APBD Perubahan?
3. Siapa yang mengakses dashboard: publik, atau perlu login (Supabase Auth)?
4. Jenis laporan SIPD yang akan diunggah (DPA, RKA, atau lainnya) — mohon contoh file.

---

## Lampiran A — Kesalahan desain dari draf sebelumnya yang dicegah PRD ini

| Masalah di draf Gemini | Aturan pencegah |
|---|---|
| `re.sub(r'[^0-9]','')` membuang koma desimal → nilai ×100 | §4.4 parser rupiah tunggal + unit test |
| ID fallback `hash(nama_paket)` berubah tiap run → duplikat | §4.3 hanya ID resmi sumber |
| Hanya halaman pertama tabel yang diambil | §6 1c paging penuh + validasi jumlah (§4.1) |
| Upsert SIPD berdasarkan kode rekening saja → saling menimpa | §8 kunci gabungan |
| Filter header membuang baris berisi "jumlah"/"uraian" | §8 buang header berdasarkan posisi/pola |
| Batch terakhir dipakai walau scraping gagal di tengah | §4.1 run valid + §4.2 finalisasi atomik |
| `DISTINCT ON (nama_paket, instansi)` membuang paket sah | §4.3 tanpa dedup nama, hanya penanda |
| Satu kolom `kode_rup` di tabel LPSE | §7 relasi many-to-many |
| Swakelola/e-katalog dianggap "belum tayang" | §7 status memperhitungkan metode |
| Scraper menulis dengan anon key | §9 service_role lokal, dashboard read-only |
| Scraping tiap 5 menit, plugin stealth | §9 2x sehari, tanpa penyamaran/bypass |
