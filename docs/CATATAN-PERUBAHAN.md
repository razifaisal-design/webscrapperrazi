# Catatan Perubahan

Ringkasan semua yang dibangun dan diubah pada aplikasi pemantauan pengadaan (SiRUP, SPSE, perbandingan, Home, web publik, Supabase).
Disusun menurut tema, terbaru di bagian bawah tiap tema. Hal-hal yang masih tertunda ada di bagian **Belum dikerjakan** paling bawah.
Catatan teknis yang lebih rinci per topik: [revisi.md](revisi.md) dan [online.md](online.md).

Tanggal kerja: 8-9 Oktober 2026. Jumlah tes otomatis saat catatan ini ditulis: **384** (semua lulus).

---

## 1. Sumber data

### SiRUP
- Pengambilan daftar RUP (100 baris per halaman) dan detail paket (lokasi, volume, uraian, spesifikasi, MAK). Satu proses "Ambil Data + Detail" dengan pilihan koneksi (1-5) dan jeda, bilah kemajuan, perkiraan sisa waktu dan jam selesai.
- idSatker bisa berbeda tiap tahun; dicari otomatis menurut **nama satker** lewat direktori SiRUP (`scraper/sources/direktori.py`), lalu dicatat di config.
- **Foto harian** daftar RUP aktif (`sirup_foto`), satu foto per hari per satker dan tahun.
- **Revisi RUP lintas pengambilan**: RUP lama hilang di satu pengambilan, RUP baru bernama sama muncul dalam 14 hari -> dipasangkan (syarat: nama sama dan pagu selisih <= 10% atau 12 segmen MAK sama). Event BARU/HILANG diganti satu REVISI_RUP.
- **Periksa RUP langsung ke SiRUP** lewat kode (`sirup_luar_daftar`): ditemukan bahwa 112 RUP Perkim 2026 ada di SiRUP tetapi tidak tampil di daftar publik satker. Tabel ini dipakai Perbandingan dan Home.
- Pencocokan kode RUP didahulukan dari pencocokan nama (nama yang sama bisa dipakai dua RUP berbeda).

### SPSE (LPSE) Non-Tender
- Daftar paket (100 per halaman, diurutkan menurut kode paket karena urutan bawaan situs tidak stabil), lalu detail: Pengumuman (tanpa Syarat Kualifikasi), Pemenang (semua kolom), Pemenang Berkontrak (cek nilai kontrak diisi PPK), Jadwal dan riwayat perubahan tiap tahap.
- Detail diambil paralel (1-5 koneksi), hanya yang belum lengkap diambil lagi; pemeriksaan awal mencetak sebab tiap paket perlu diambil.
- Rincian lengkap (pemenang, kontrak, jadwal) bisa dibatasi: satker terpilih, semua satker, atau hanya Pengumuman.
- Perbaikan: paket batal tidak lagi dianggap "berubah" selamanya (perbandingan memakai tahapan di daftar saat detail diambil).
- Nama paket dibersihkan dari sisa HTML (mis. badge "Pengadaan Langsung Ulang"); 2.082 nama lama dibersihkan di database. Teks asli tetap di kolom `raw`.
- Nama satker dinormalkan (tanda baca dibuang, PEMUKIMAN = PERMUKIMAN) sehingga satu satker tidak terpecah dua di filter.
- Tahun "Tender" belum diambil.

### Satker dikenali lewat NAMA (bukan ID)
- Tambah satker dari panel "Tambah satker / dinas" di dashboard SiRUP (tulis sebagian nama, pilih dari hasil). Satker baru memakai rekap umum; aturan Jalan/Saluran Perkim tidak diterapkan.
- Satker kembar nama dalam satu tahun: dipakai yang paketnya terbanyak.

---

## 2. Dashboard lokal

- **Halaman:** Home (`/`), SiRUP (`/sirup`), SPSE (`/spse`), Perbandingan (`/banding`), Pusat Perintah (`/perintah`), Grafik (`/grafik`).
- **SPSE:** tab Paket Terinci, Penyedia, Perubahan Jadwal, Semua Paket SPSE; filter satker/tahun di bagian atas; Excel dan CSV.
- **Tab Penyedia:** pemenang dikelompokkan per perusahaan (variasi nama disatukan), bentuk usaha CV/PT/Lainnya, total pagu, HPS, **negosiasi**, **nilai kontrak**, daftar paket (nama paket, satker, tahun) saat baris dibuka, baris jumlah, CSV.
- **Perbandingan SiRUP dan SPSE:** pasangan RUP-paket lewat kode RUP, lalu RUP pengganti, lalu nama + satker; status Sudah tayang / Belum tayang / Belum ada di SPSE / dll; pagu, HPS, penawaran, negosiasi, kontrak, jadwal beserta perubahan; Excel.
  - **Sudah tayang** = tahap pertama jadwal (Upload) sudah dimulai dibanding sekarang. Paket batal ikut terhitung sebagai tayang di halaman ini (14 dari 666 untuk Perkim 2026); di Home paket batal dipisah.
- **Filter yang bisa diketik** di setiap tabel (`scraper/filter_ketik.js`): klik untuk daftar, ketik untuk mencari; teks tidak cocok diabaikan.
- **Pusat Perintah:** 10 perintah dengan penjelasan fungsi, kapan dipakai, perkiraan waktu, dan apa yang diubahnya; satu perintah pada satu waktu dengan log dan tombol Hentikan.
- **Tema hijau modern** seragam di seluruh aplikasi (`scraper/gaya.css`), mode gelap ikut.
- Sidebar peringatan "kode aplikasi sudah diperbarui" bila server berjalan dengan kode lama.

### Home (baru)
- Tiga diagram lingkaran: **Jalan PSU**, **Saluran PSU**, **Semua**, plus empat kartu ringkas. Keterangan rinci di bawah tiap diagram: tahap, jumlah paket, nilai (Rp), persen dari nilai.
- Aturan: tahap = tahap terakhir yang tanggal mulainya sudah tiba (jam diabaikan); nilai = hasil negosiasi bila ada, HPS bila belum; paket belum tayang memakai pagu SiRUP; paket batal dipisah; persen dari total nilai paket yang terinput di SiRUP. Logika: `scraper/core/home.py`.
- Mengikuti filter satker dan tahun (termasuk semua tahun), juga di web publik.

### Kategori dari MAK (`config/kategori_home.json`)
| Kategori | Sub kegiatan | Rekening |
|---|---|---|
| Jalan PSU | 1.04.05.2.01.0012 | 5.2.04.01.001.00004 (Belanja Modal Jalan Kota) |
| Saluran PSU | 1.04.05.2.01.0011 | 5.2.04.02.002.00004 (Belanja Modal Saluran Pembuang Pasang Surut) |
| Jalan Kawasan Permukiman | 1.04.03.2.03.0013 | 5.2.04.01.001.00004 |

- Hanya MAK 2026. MAK lain ("Lainnya") tidak dimasukkan. Fisik atau Konsultan ditentukan dari nama paket (konsultan memakai MAK yang sama dengan fisiknya).
- Rekening dibaca dari 6 segmen setelah sub kegiatan; ekor MAK sesudah segmen ke-12 diabaikan.
- Referensi dari `kode_mak.db`: tabel `ref_sub_kegiatan` dan `ref_mak`, field `sirup_detail.sub_kegiatan_kode/nama`. Nama yang tidak ada di referensi dibiarkan kosong ("belum diketahui"), tidak ditebak. Impor: `python -m scraper impor-mak <path>`.
- Hasil 2026 Perkim: Jalan PSU 693 paket, Saluran PSU 124, Jalan Kawasan Permukiman 8, Lainnya 154 (paket di daftar SiRUP).

---

## 3. Online: Supabase, web publik, Cloudflare

- **Supabase** (proyek `pantau-pengadaan`): cermin database lokal (`python -m scraper sinkron`, TRUNCATE + COPY dalam satu transaksi), semua tabel tertutup untuk publik (RLS tanpa kebijakan, hak anon dicabut). `python -m scraper tarik` membangun database lokal dari cermin. Kredensial `SUPABASE_DB_URL` hanya di `.env`.
- **Web publik membaca langsung dari Supabase** (`python -m scraper terbitkan`): berkas data masuk tabel `publik_berkas` (satu-satunya tabel yang boleh dibaca anon, hanya SELECT). Halaman statis (+- 0,2 MB) tidak memuat data. Kunci publishable ada di `config/publik.json`.
- **Kesegaran data** di web publik: `meta.json` selalu diambil tanpa cache; alamat berkas data memuat penanda versi, jadi terbitan baru langsung terpakai, termasuk pada halaman yang dibiarkan terbuka.
- **Cloudflare**: situs `spring-flower-c5ae.razi-faisal.workers.dev`; unggah isi folder `publik/` (isi, bukan foldernya). `wrangler.jsonc` sudah disiapkan; Wrangler butuh Node.js dan login sekali.
- **GitHub Actions** (`.github/workflows/perbarui.yml`): uji pertama dari server GitHub -> SiRUP dan SPSE membalas **403**. Tidak disiasati; jadwal otomatis dimatikan. Pilihan yang sah ada di [online.md](online.md).

### Perintah (CLI dan klik dua kali)
| Tujuan | Perintah |
|---|---|
| Semuanya sekaligus (ambil data, periksa RUP, cadangkan, terbitkan) | `Perbarui dan Ekspor Publik.command` atau `python -m scraper perbarui` |
| Cadangan ke Supabase | `python -m scraper sinkron` |
| Terbitkan ke web publik | `python -m scraper terbitkan` |
| Pulihkan database dari Supabase | `python -m scraper tarik --paksa` |
| Unggah halaman ke Cloudflare | `Unggah ke Cloudflare.command` atau `python -m scraper unggah` |
| Jalankan pembaruan di server GitHub | `Jalankan Pembaruan Online.command` (saat ini tidak berguna: IP GitHub ditolak) |
| Impor referensi MAK | `python -m scraper impor-mak <path kode_mak.db>` |
| Ambil SPSE detail | `python -m scraper spse-detail nontender --satker ...` |

---

## 4. Perbaikan kekeliruan yang ditemukan

- Tautan Excel Perbandingan: kolom Kode RUP sempat berisi tautan SPSE; sekarang Kode RUP ke SiRUP dan Kode Non Tender ke SPSE.
- Excel gagal bila nama paket memuat karakter kontrol tersembunyi; karakter itu dibuang.
- Pencocokan lewat nama keliru memasangkan paket ke RUP lain (kasus Jl. Tanjung Raya 1): sekarang kode RUP yang terbukti ada didahulukan; pagu beda 2026 menjadi 0.
- Tes sempat menimpa cermin Supabase dengan database uji (cermin pulih dari data asli). Pengaman: sinkron otomatis hanya untuk database utama proyek, dan tes tidak boleh menyentuh `.env`.
- Pemeriksaan RUP sempat membuka ~1.430 RUP satker lain (tanpa diminta); dihentikan dan dibatasi hanya pada satker ber-SiRUP. Hasilnya tetap tersimpan.
- Halaman publik menampilkan data lama selama tab terbuka (cache memori); diperbaiki lewat pemeriksaan versi.
- Rekening MAK salah terbaca bila ada ekor setelah segmen ke-12; diperbaiki.

---

## 5. Belum dikerjakan / keputusan tertunda

- Aturan kategori Home untuk **2021-2025** (kode sub kegiatan berbeda: `0002` di 2024-2025, format lama sebelumnya). Perlu database MAK tahun-tahun itu.
- Halaman SiRUP lama (kartu Jalan/Saluran/Lainnya) masih memakai pengelompokan berdasarkan nama paket, belum selaras dengan kategori MAK baru.
- Home untuk satker selain Perkim.
- Tender/Seleksi (hanya Non-Tender yang diambil).
- Pengambilan terjadwal otomatis di komputer sendiri (launchd) atau self-hosted runner, karena server GitHub ditolak SiRUP/SPSE.
- Cakupan data publik (semua satker) belum diputuskan; saat ini semua satker yang detailnya sudah terambil ikut publik.
- Mengganti kata sandi database Supabase (potongan awalnya sempat tercetak di log GitHub yang sudah dihapus dan di percakapan).
- Kolom "pengadaan ulang" sebagai field tersendiri di halaman SPSE (penandanya hanya tersimpan di `raw`).
