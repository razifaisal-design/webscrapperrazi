# Panduan untuk AI Pelaksana (OpenCode): Parser PDF SIPD

Dokumen ini ditujukan kepada AI lain (OpenCode) yang akan membuat fitur **pembacaan PDF SIPD** di proyek ini.
Baca seluruhnya sebelum menulis kode. Proyek sudah berjalan dan memiliki banyak konvensi; fitur baru harus terasa seperti bagian dari proyek, bukan tempelan.

---

## 0. Aturan kerja (wajib)

1. **Pelajari dulu, tanya dulu, baru koding.** Pengguna tidak mau asumsi. Jika format PDF, arti kolom, atau aturan bisnis tidak jelas, **tanyakan**; jangan menebak.
2. **Jangan menulis kode sebelum pengguna mengirim contoh PDF** dan Anda sudah melaporkan temuan struktur PDF serta daftar pertanyaan.
3. **Jangan mengubah perilaku fitur yang sudah ada** (SiRUP, SPSE, Perbandingan, Home, sinkron, publik). Fitur ini bersifat menambah.
4. **Jangan mengunggah, mem-push, atau menerbitkan apa pun** (GitHub, Supabase, Cloudflare) tanpa diminta. Menjalankan `sinkron`/`terbitkan`/`unggah` hanya atas perintah pengguna.
5. **Jangan menyalin isi `.env`, kata sandi, URL database, atau kunci ke chat, log, kode, maupun berkas yang ikut ke git.**
6. **PDF SIPD adalah data milik pengguna/pemerintah daerah.** Folder data pengguna (`data/`) tidak masuk GitHub dan tidak boleh dipindah ke `config/`, `tests/fixtures/` publik, atau repo tanpa persetujuan.
7. Semua teks yang tampil ke pengguna (pesan CLI, label UI, komentar, dokumentasi) berbahasa **Indonesia**. Nama fungsi/variabel mengikuti gaya yang sudah ada (campuran Indonesia, lihat bagian 3).
8. Setelah selesai, jalankan seluruh tes (`.venv/bin/python -m unittest discover -s tests`) dan laporkan hasilnya apa adanya, termasuk yang gagal atau dilewati.

---

## 1. Tentang proyek

Memantau pengadaan Dinas Perumahan Rakyat dan Kawasan Permukiman (Perkim) Kota Pontianak, tetapi dirancang **umum untuk satker/dinas mana pun** (satker dikenali lewat **nama**, bukan ID).

Alur data yang sudah ada:

```
SiRUP (perencanaan)  ->  SPSE/LPSE Non-Tender (pelaksanaan)  ->  [SIPD: anggaran, BELUM ADA]
        \                         |
         ->  SQLite lokal data/pantau.db  ->  dashboard lokal (Python stdlib, scraper/web.py)
                                         ->  cermin Supabase (sinkron)  ->  web publik statis (Cloudflare)
```

Fitur SIPD adalah **Bagian 3** pada [PRD.md](PRD.md) (bagian 8): membandingkan **anggaran (DPA/RKA dari SIPD)** dengan **RUP di SiRUP**. Baca juga:

- [PRD.md](PRD.md): prinsip data dan kriteria selesai Bagian 3
- [CATATAN-PERUBAHAN.md](CATATAN-PERUBAHAN.md): ringkasan apa yang sudah dibangun
- [revisi.md](revisi.md) dan [online.md](online.md): catatan teknis

### Mengapa SIPD penting
Kode **MAK** (Mata Anggaran Kegiatan) tiap paket RUP di SiRUP, misalnya `1.04.05.2.01.0012.5.2.04.01.001.00004`, harus cocok dengan baris anggaran di SIPD:

- 6 segmen pertama `1.04.05.2.01.0012` = **sub kegiatan**
- 6 segmen berikutnya `5.2.04.01.001.00004` = **kode rekening** (segmen ke-13 dan seterusnya diabaikan di seluruh aplikasi)

Pertanyaan yang ingin dijawab: berapa anggaran per sub kegiatan/rekening menurut SIPD, berapa total pagu RUP untuk MAK yang sama, adakah anggaran yang belum punya RUP, adakah RUP yang melebihi anggaran.

---

## 2. Lingkungan dan cara menjalankan

- Folder proyek: `/Users/razi/Desktop/Claude Code/Webscrapper`
- Python lewat virtualenv: `.venv/bin/python` (Python sistem **tidak** punya `httpx`).
- Dependensi di `requirements.txt` (`httpx`, `openpyxl`, `psycopg[binary]`). Menambah dependensi (mis. `pdfplumber`) **harus dikonfirmasi ke pengguna** dan dicatat di `requirements.txt`. Pilihan pustaka PDF: `pdfplumber` (disarankan PRD), alternatif `pymupdf`. Pilih berdasarkan contoh PDF nyata, jelaskan alasannya.
- Tes: `unittest` standar, `.venv/bin/python -m unittest discover -s tests`. Saat ini 384 tes lulus (1 dilewati). **Tidak boleh berkurang.**
- Database: SQLite `data/pantau.db` (pakai `--db` untuk jalur lain). **Tes tidak boleh menyentuh database nyata maupun `.env`**; gunakan database sementara. Pernah terjadi tes menimpa cermin Supabase dengan data uji; pengamannya sudah ada, jangan dilemahkan.
- Server lokal: `python -m scraper web`, port 8765 (milik pengguna, jangan dimatikan). Untuk menguji gunakan port lain, mis. 8766.
- Platform: macOS, shell zsh.

---

## 3. Struktur kode dan konvensi

```
scraper/
  cli.py            perintah CLI (argparse) -> memanggil tugas.*
  tugas.py          logika tugas (run_*), PengelolaTugas di web.py menjalankan tugas di thread
  perintah.py       katalog perintah untuk halaman Pusat Perintah (/perintah)
  web.py            server dashboard + semua endpoint /api/*
  sinkron.py        cermin SQLite -> Supabase; daftar tabel di konstanta TABEL
  ekspor_publik.py  data & halaman untuk web publik
  core/
    db.py           skema SQLite (CREATE TABLE IF NOT EXISTS + migrasi ringan), fungsi simpan_*
    mak_ref.py      pemecahan kode MAK, referensi sub kegiatan (ref_sub_kegiatan, ref_mak)
    banding.py      perbandingan SiRUP vs SPSE
    home.py, kategori_home.py, excel.py, money.py, http.py, ...
  sources/          pengambil/pengurai per sumber: sirup.py, sirup_detail.py, spse.py, direktori.py
  *.html, gaya.css, bersama.js, statis.js, filter_ketik.js   frontend (tanpa framework, tema hijau)
tests/              satu berkas test_*.py per modul; fixture di tests/fixtures/
config/             targets.json, kategori_home.json, publik.json
docs/               dokumentasi
```

Konvensi yang harus diikuti:

- **Parser = fungsi murni** (teks/struktur masuk -> dict/list keluar), tanpa I/O jaringan atau database, diuji dengan fixture. Contoh gaya: `scraper/sources/spse.py` (`parse_pengumuman`, `parse_jadwal`, ...). Tempatkan modul baru di `scraper/sources/sipd_pdf.py`.
- **Penyimpanan** lewat fungsi `simpan_*` di `core/db.py`, memakai `with conn:` (transaksi) dan pola `INSERT ... ON CONFLICT` atau ganti per dokumen. Skema ditambahkan ke konstanta skema di `db.py` dengan `CREATE TABLE IF NOT EXISTS`; perubahan kolom pada tabel lama lewat `ALTER TABLE` bersyarat seperti pola `PRAGMA table_info` yang sudah ada.
- **Uang** disimpan sebagai angka rupiah penuh. Gunakan/utamakan `core/money.py` untuk mengurai format Indonesia (`Rp 150.000.000,00`: titik = ribuan, koma = desimal). Jangan membuat parser rupiah baru; bug lama proyek Gemini justru dari parsing rupiah yang salah (hasil x100).
- **Kunci = ID resmi sumber**, bukan hash acak dan bukan nama. Untuk SIPD: kunci gabungan (lihat bagian 5).
- **Nama satker** selalu dinormalkan lewat `norm_satker`/`nama_kanonik` di `core/db.py`.
- **Simpan teks asli** (kolom `raw`) bila parsing mungkin perlu diulang.
- **Tidak ada framework web**; server memakai stdlib. UI baru mengikuti `gaya.css`, `bersama.js`, filter ketik (`select[data-f]`) dan pola halaman yang ada (lihat `spse.html`/`banding.html`).
- **Komentar** singkat, berbahasa Indonesia, hanya untuk "mengapa".

---

## 4. Yang harus dibangun

### Tahap A: Penemuan (tanpa koding produksi)
1. Pengguna akan mengirim contoh PDF SIPD. Buka dan periksa:
   - Apakah PDF **teks** atau hasil scan (scan di luar lingkup; laporkan).
   - **Jenis laporan** (DPA, RKA, DPPA, rincian belanja per sub kegiatan, dll.) dan judul/kop tiap halaman.
   - Susunan kolom, header yang berulang tiap halaman, baris yang terpotong (word-wrap), baris jumlah/subtotal, hierarki (program -> kegiatan -> sub kegiatan -> rekening -> rincian).
   - Cara angka dicetak (pemisah ribuan/desimal, kolom volume/satuan/harga).
   - Apakah ada beberapa dinas/satker dalam satu PDF atau satu PDF per dinas.
2. Tulis laporan temuan dan **daftar pertanyaan**; tunggu jawaban pengguna.
3. Simpan potongan kecil, **sudah dianonimkan bila perlu**, sebagai fixture di `tests/fixtures/sipd/` hanya jika pengguna mengizinkan.

### Tahap B: Parser (`scraper/sources/sipd_pdf.py`)
Aturan dari PRD:
- Atur ekstraksi per jenis laporan; bersihkan newline/tab/spasi ganda dalam sel; gabungkan baris terpotong.
- **Buang header berulang berdasarkan posisi/pola, bukan kata kunci isi.** Baris "Jumlah" dan uraian sah tidak boleh ikut terbuang.
- Bangun hierarki dan simpan kode setiap tingkat.
- Hasil parse berupa daftar baris terstruktur dengan nomor halaman dan urutan baris asli.

### Tahap C: Validasi wajib
- **Jumlah per sub kegiatan hasil parse harus sama dengan baris "Jumlah" yang tercetak di PDF.** Bila tidak sama: dokumen **ditolak** dan laporan selisih ditampilkan (kode, nilai PDF, nilai hasil parse, halaman). Jangan menyimpan sebagian.
- Total keseluruhan dokumen juga dicocokkan bila ada.
- Dokumen yang gagal tidak mengubah data yang sudah tersimpan.

### Tahap D: Penyimpanan, CLI, UI
Usulan skema (boleh disesuaikan setelah melihat PDF; setiap penyimpangan dijelaskan ke pengguna):

```sql
sipd_dokumen(
  id INTEGER PRIMARY KEY, nama_berkas TEXT, hash TEXT UNIQUE,   -- SHA-256 isi berkas
  jenis_laporan TEXT, tahun INTEGER, satker_nama TEXT,
  versi INTEGER, diunggah_pada TEXT, jumlah_baris INTEGER, total NUMERIC, status TEXT, catatan TEXT)

sipd_anggaran(
  dokumen_id INTEGER, urutan INTEGER,                           -- urutan baris asli di dokumen
  tahun INTEGER, satker_nama TEXT,
  kode_program TEXT, kode_kegiatan TEXT, kode_sub_kegiatan TEXT, kode_rekening TEXT,
  uraian TEXT, volume TEXT, satuan TEXT, harga_satuan NUMERIC, jumlah NUMERIC,
  halaman INTEGER, raw TEXT,
  PRIMARY KEY (dokumen_id, urutan))
```

- Kunci gabungan: **(tahun, satker, dokumen, kode sub kegiatan, kode rekening, urutan baris)**; **jangan** memakai kode rekening saja, karena kode rekening yang sama muncul di banyak sub kegiatan dan akan saling menimpa.
- Mengunggah **versi baru** dokumen yang sama: bandingkan dengan versi sebelumnya dan catat perubahan (BARU/BERUBAH/HILANG) ke `paket_events` atau tabel sejenis, mengikuti pola di `core/db.py`. Mengunggah ulang berkas yang sama persis (hash sama) -> **0 perubahan**.
- Daftarkan tabel baru ke `TABEL` di `scraper/sinkron.py` agar ikut cermin Supabase (RLS tertutup untuk publik otomatis). Jangan membuka tabel baru ke akses anon.
- Pencocokan sub kegiatan dengan `ref_sub_kegiatan` (nama resmi) memakai fungsi di `core/mak_ref.py`; **nama yang tidak diketahui dibiarkan kosong, jangan ditebak.**
- CLI baru di `cli.py`, mis. `python -m scraper sipd <berkas.pdf> [--satker NAMA] [--tahun 2026] [--periksa-saja]`, dengan logika di `tugas.py`. `--periksa-saja` hanya mengurai dan memvalidasi tanpa menyimpan.
- Daftarkan di `scraper/perintah.py` agar muncul di halaman **Pusat Perintah** (nama, fungsi, kapan dipakai, perkiraan waktu, apa yang diubah) dan ikuti pola jenis tugas generik `perintah` serta daftar putih validasi.
- Dashboard: halaman/tab baru "Anggaran (SIPD)" dengan:
  - anggaran vs total pagu RUP per sub kegiatan (gabungkan lewat `sub_kegiatan_kode` pada `sirup_detail`, atau kode MAK dari SiRUP),
  - anggaran yang belum punya RUP,
  - RUP yang melebihi anggaran,
  - filter satker dan tahun yang bisa diketik, ekspor Excel via `core/excel.py`.
  Mengikuti gaya `spse.html`/`banding.html` dan endpoint `/api/...` di `web.py`.
- Web publik (opsional, **tanyakan dulu**): data anggaran bisa saja tidak ingin dipublikasikan. Jangan memasukkannya ke `ekspor_publik.py` tanpa persetujuan pengguna.

### Tahap E: Tes dan dokumentasi
- Tes parser dengan fixture (kasus: header berulang, baris terpotong, angka format Indonesia, baris jumlah, hierarki, kode rekening sama di dua sub kegiatan, dokumen yang selisihnya harus ditolak).
- Tes penyimpanan memakai database sementara; tes unggah ulang = 0 perubahan; tes versi baru = perubahan yang benar.
- Tes CLI dan endpoint seperti `tests/test_cli.py`, `tests/test_web.py`.
- Tambahkan bagian baru di [CATATAN-PERUBAHAN.md](CATATAN-PERUBAHAN.md) dan [revisi.md](revisi.md); perbarui README/PRD bila ada keputusan baru.

---

## 5. Kriteria selesai (dari PRD Bagian 3)

- [ ] Total hasil parse = total di PDF untuk **semua** sub kegiatan pada dokumen sampel.
- [ ] Dokumen dengan selisih ditolak disertai laporan selisih; data lama tidak berubah.
- [ ] Unggah ulang dokumen yang sama -> 0 event.
- [ ] Kode rekening yang sama di dua sub kegiatan tidak saling menimpa.
- [ ] Perbandingan anggaran vs pagu RUP per sub kegiatan tampil di dashboard dan cocok pada pemeriksaan manual minimal 5 sampel.
- [ ] Seluruh tes lama tetap lulus; tes baru ditambahkan.

---

## 6. Hal yang tidak boleh dilakukan

- Menebak arti kolom/kode ketika PDF ambigu.
- Memakai kata kunci isi untuk membuang header (risiko membuang baris sah).
- Menggunakan kode rekening saja sebagai kunci.
- Mengabaikan selisih validasi lalu tetap menyimpan.
- Mengubah `.env`, memindahkan data pengguna ke repo, atau mengirim data ke layanan luar.
- Menjalankan `sinkron`, `terbitkan`, `unggah`, atau push GitHub tanpa diminta.
- Mematikan atau menimpa server dashboard pengguna di port 8765.
- Menambah dependensi besar atau framework tanpa persetujuan.

---

## 7. Yang akan dikirim pengguna

Pengguna berencana memberikan, setelah panduan ini dibuat:
- Contoh PDF SIPD (beserta keterangan jenis laporannya: DPA/RKA/lainnya, tahun, satker).
- Kemungkinan: akses ke database MAK `kode_mak.db` (sudah diimpor ke `ref_sub_kegiatan` dan `ref_mak` untuk 2026).
- Jawaban atas pertanyaan Tahap A.

Langkah pertama Anda: baca dokumen-dokumen yang disebut di bagian 1, lalu tunggu contoh PDF. Setelah menerimanya, laporkan temuan dan pertanyaan, **belum koding**.
