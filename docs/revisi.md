# Revisi (untuk di-update nanti)

> Status: **belum dikerjakan** — dicatat 8 Oktober 2026, ditunda atas permintaan.
> Topik: pendeteksian **Revisi RUP** (nama paket sama, kode RUP berganti).

## Definisi yang dipakai sekarang
Menurut Anda: *perubahan = nama paket sama, kode RUP berganti.*
Saat ini dideteksi di `finalisasi()` ([scraper/core/db.py](../scraper/core/db.py)):
satu paket **hilang** dan satu paket **baru** muncul **dalam pengambilan daftar yang sama** dengan **nama sama**
(nama dibandingkan setelah huruf dikecilkan dan spasi dirapikan; tanda baca tetap dibedakan). Bila ada beberapa nama
kembar, dipasangkan menurut **pagu terdekat**. Hasilnya satu event `REVISI_RUP` (menggantikan event Baru + Hilang) dan
kedua paket saling ditautkan (`kode_rup_sebelumnya` / `kode_rup_pengganti`).

## Pilihan perbaikan (yang akan dikerjakan)
- Pasangkan revisi **lintas pengambilan**: RUP lama hilang di pengambilan N, RUP baru bernama sama muncul dalam beberapa hari berikutnya.
- **Perketat kecocokan**: nama sama **dan** MAK sama **atau** pagu mirip, supaya nama umum tidak salah pasang.
- **Pengambilan terjadwal otomatis** (misalnya tiap hari), supaya riwayatnya rapat.

## Kelemahan yang mendasari perbaikan di atas
1. Pengambilan pertama tiap tahun hanya menjadi **data dasar**; perubahan sebelum itu tidak diketahui.
2. Hanya melihat **selisih antar-pengambilan**: bila RUP berubah dua kali di antaranya, yang tercatat hanya hasil akhir.
3. **"Hilang" tidak berarti dibatalkan** — bisa dihapus, dipindah satker/tahun, atau sedang dirombak.
4. **Salah pasang** mungkin terjadi untuk nama umum (mis. "Fotocopy"): paket yang dihapus dan paket baru lain yang kebetulan bernama sama dikira revisi.
5. Revisi yang **terpotong** (lama hilang di satu pengambilan, baru muncul di pengambilan berikutnya) dicatat sebagai Hilang dan Baru biasa, tanpa dipasangkan.
6. RUP lama yang **masih tampil bersama** RUP barunya tidak dihitung revisi; hanya masuk peringatan "Kemungkinan paket ganda" di tab Pemeriksaan.

## Fakta saat dicatat
- Tabel `paket_events` masih **kosong (0 catatan)**: pengambilan daftar yang berhasil hanya berjarak menit/jam dan tidak ada paket yang berubah.
- Artinya logika Revisi RUP **belum pernah diuji pada perilaku SiRUP yang sebenarnya**, hanya pada skenario buatan di tes
  ([tests/test_db.py](../tests/test_db.py)).

## Bahan untuk saat dikerjakan
- Butuh **contoh nyata** revisi RUP di SiRUP (nama tetap sama? sedikit berubah? kode lama masih tampil?) untuk menyesuaikan aturan.
- Keputusan: berapa hari jendela pemasangan lintas pengambilan? (usulan: 7–14 hari)
- Keputusan: syarat "MAK sama atau pagu mirip" — seberapa mirip pagu? (usulan: selisih ≤ 10%)
- Penjadwalan otomatis: `launchd` (Mac) atau jalankan lewat tombol di dashboard secara berkala.

---

# Catatan SPSE / LPSE (Bagian 2) — dicatat 8 Oktober 2026

Sumber: `https://spse.inaproc.id/pontianak/nontender`. Yang sudah dikerjakan: **daftar Non-Tender saja** (tahun 2026 sebagai bawaan).

## Ditunda (untuk nanti)
- **Tender** (`/pontianak/lelang`): belum diambil.
- **Detail paket** (halaman `pengumumanpl`): belum diambil. Isi yang dibutuhkan dari detail: satker/OPD pemilik, HPS pasti, kode RUP (untuk menautkan ke SiRUP), pemenang, nilai kontrak, jadwal.
- Penautan paket SPSE → RUP SiRUP (lewat kode RUP di detail) dan status per RUP (Belum Diumumkan / Proses / Pemenang / Berkontrak / Batal).
- Pemisahan **hanya Dinas Perkim**: daftar SPSE memuat semua K/L/PD di LPSE ini (kolom instansi hanya "Kota Pontianak"); satker baru terlihat di halaman detail.

## Temuan teknis
- `recordsTotal` selalu 2147483647 → tidak bisa dipakai sebagai total pembanding. Validasi memakai: tanpa duplikat, kode urut naik, dan cek ujung (halaman pertama urutan turun).
- Urutan bawaan (tanggal pengumuman) **tidak stabil** antar halaman (7 duplikat/terlewat dari 1155 paket). Solusi: urutkan kolom 0 (kode paket) naik; hasilnya stabil (1155 unik).
- HPS di daftar hanya ringkas ("19,9 Jt") → `hps_perkiraan` hanya perkiraan; nilai pasti di detail.
- Pilihan tahun di situs: 2026, 2025, 2024, 2023, 2022, 2021, 2019 (tidak ada 2020).
- Token `authenticityToken` + cookie sesi diperlukan untuk POST DataTables; diperbarui sekali bila kedaluwarsa.

## Catatan pengambilan
- Sempat terambil semua tahun (2019, 2021–2026) sebelum diminta 2026 saja; data tahun lain masih di `data/pantau.db` (tabel `spse_paket`). Bisa dihapus bila tidak diperlukan.

## Detail SPSE Non-Tender (uji coba 10 paket, 8 Oktober 2026)
- Perintah: `python -m scraper spse-detail nontender --tahun 2026 --limit 10` (tabel `spse_detail`, 3 halaman per paket).
- Halaman: Pengumuman (`/nontender/{kode}/pengumumanpl`, tanpa bagian Syarat Kualifikasi), Pemenang (`/evaluasinontender/{kode}/pemenang`, semua kolom), Pemenang Berkontrak (`.../pemenangberkontrak`, hanya untuk cek `nilai_kontrak` terisi = PPK sudah mengisi e-kontrak).
- Satker hanya ada di detail: 7 dari 10 paket pertama ternyata bukan milik Dinas Perkim → pemfilteran satker harus menunggu detail (atau ambil detail semua 1.155 paket ≈ 1,5 jam pada jeda 1,5 dtk).
- Belum dikerjakan: tombol/tab detail di dashboard; penautan kode RUP SPSE ↔ SiRUP (kode RUP sudah tersimpan di `spse_detail.kode_rup`); melewati halaman Pemenang untuk paket dibatalkan (hemat permintaan).

## Halaman SPSE & Perbandingan (8 Oktober 2026)
- Halaman terpisah: `/` (SiRUP), `/spse` (SPSE), `/banding` (Perbandingan SiRUP ↔ SPSE), `/grafik`. CSS bersama di `scraper/gaya.css`, JS bersama (tugas/progres) di `scraper/bersama.js`.
- Proses SPSE satu tombol "Ambil Data + Detail": tahap 1 daftar (100/halaman), tahap 2 detail. Pengumuman diambil untuk SEMUA paket (butuh instansi + kode RUP); Pemenang, Pemenang Berkontrak, Jadwal + riwayat perubahan hanya untuk paket satker target (opsi "semua instansi" tersedia).
- "Sudah tayang" = tahap *Upload Dokumen Penawaran* (tahap pertama jadwal) sudah mulai dibanding waktu sekarang (asumsi; ubah di `banding.TAHAP_TAYANG`).
- Pencocokan RUP ↔ paket SPSE: (1) kode RUP, (2) RUP lama → RUP pengganti (revisi), (3) nama paket + instansi sama bila RUP berubah setelah tayang.
- Belum dikerjakan: Tender/Seleksi (status "Tender/Seleksi (belum diambil)"), alias nama satker untuk tahun lama (config `spse.satker_alias`), pencocokan paket SPSE yang menggabungkan RUP lintas tahun.

## Satker dikenali lewat NAMA (9 Oktober 2026)
- Aplikasi tidak lagi terkunci pada satu dinas. Halaman SPSE dan Perbandingan punya filter utama **Satker / Dinas**; halaman SiRUP punya kotak Satker / Dinas + panel "Tambah satker / dinas" (tulis nama, bukan ID).
- Direktori SiRUP (publik): kategori (`datatablerupkldi2?jenisID=KOTA`) → K/L/PD (mis. Kota Pontianak = `D199`) → satker + idSatker per tahun (`datatableruprekapkldi?idKldi=D199&tahun=`). idSatker ditemukan otomatis menurut nama untuk tiap tahun (`tentukan_id_satker`), dan dicatat di config.
- Satker baru memakai **rekap umum** (per MAK, per uraian, database paket, perubahan). Aturan Jalan/Saluran/MAK Perbaikan/pemeriksaan wilayah khusus Perkim tidak diterapkan; tab itu otomatis tersembunyi. Aturan khusus bisa ditambahkan per satker di `config/targets.json`.
- Satker kembar nama dalam satu tahun (mis. DINAS KESEHATAN 2021: dua idSatker) → dipakai yang paketnya terbanyak; satker lainnya dicatat di log.
- Belum dikerjakan: rekap gabungan beberapa satker sekaligus ("Semua satker") di halaman SiRUP; filter satker di halaman Grafik hanya mengikuti satker yang dipilih.

## Supabase: cadangan, web publik live, foto harian (9 Oktober 2026)
- **Cadangan** (`python -m scraper sinkron`): database lokal dicerminkan ke Supabase (TRUNCATE + COPY dalam satu transaksi; gagal = tidak berubah). Tabel cermin tertutup untuk publik (RLS tanpa kebijakan, hak anon dicabut). Kredensial: `SUPABASE_DB_URL` di `.env`. Otomatis hanya untuk database utama proyek (database uji tidak boleh menimpa cermin).
- **Web publik membaca langsung dari Supabase** (`python -m scraper terbitkan`): berkas ekspor (JSON jadi jsonb, Excel jadi base64 dalam jsonb) masuk tabel `publik_berkas` yang SATU-SATUNYA tabel yang boleh dibaca anon (hanya SELECT). Halaman statis (±0,2 MB) membaca lewat REST dengan kunci publishable di `config/publik.json`. Data diperbarui tanpa unggah ulang halaman; halaman hanya perlu diunggah ke Cloudflare bila kode halaman berubah.
- Konsekuensi: kuota transfer Supabase (gratis ±5 GB/bulan) terpakai tiap pengunjung (rekap "semua tahun" ±beberapa MB terkompresi).
- **Foto harian** (`sirup_foto`): tiap pengambilan daftar RUP menyimpan daftar RUP aktif hari itu (satu foto per hari per satker & tahun).
- **Revisi RUP terpotong antar pengambilan** kini dipasangkan: RUP lama hilang di pengambilan N, RUP baru bernama sama muncul dalam 14 hari berikutnya, dengan syarat nama sama DAN (pagu selisih ≤ 10% ATAU 12 segmen MAK sama). Event BARU/HILANG diganti satu REVISI_RUP.
- Belum: pengambilan terjadwal otomatis (launchd). Foto dan pasangan revisi hanya selengkap seberapa sering pengambilan dijalankan.
