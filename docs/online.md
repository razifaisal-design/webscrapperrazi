# Berjalan penuh online (gratis)

Alur: **GitHub Actions** (penjadwal + komputer gratis) -> mengambil data dari SiRUP/SPSE -> **Supabase** (database + sumber data web publik) -> **Cloudflare** (halaman statis kecil).

## Jadwal
`.github/workflows/perbarui.yml` berjalan tiap hari **00:00 WIB** dan **13:00 WIB** (cron UTC `0 17` dan `0 6`), dan bisa dijalankan manual (tab Actions > Perbarui data > Run workflow, bisa mengatur koneksi dan jeda). GitHub dapat menunda jadwal beberapa menit saat sibuk.

## Persiapan sekali
1. Kirim kode ke GitHub (Kirim ke GitHub.command). Folder `data/`, `.env`, `publik/` tidak ikut.
2. Di repo GitHub: Settings > Secrets and variables > Actions > New repository secret: nama `SUPABASE_DB_URL`, nilai = string Session pooler (sama dengan di `.env`).
3. Tab Actions > Perbarui data > Run workflow. Lihat langkah "Cek akses ke SiRUP dan SPSE": harus 200 untuk keduanya.

## Sumber kebenaran
Setelah online, **Supabase** (cermin) adalah sumber kebenaran. Jangan menjalankan pengambilan lokal lalu `sinkron` tanpa lebih dulu `python -m scraper tarik --paksa`, supaya tidak menimpa hasil jalan online. Satu jalan online pada satu waktu (concurrency).

## Batas gratis
- GitHub Actions: repo privat 2.000 menit/bulan, repo publik tidak dibatasi. 2 jalan/hari x 30 hari = 60 jalan; aman bila tiap jalan rata-rata < 30 menit (jalan pertama untuk tahun yang belum terambil bisa jauh lebih lama).
- Supabase gratis: database 500 MB (terpakai ±116 MB), transfer 5 GB/bulan, proyek ditidurkan bila tidak ada aktivitas 1 minggu (jalan harian mencegahnya).

## Bila SiRUP/SPSE memblokir server GitHub
Server GitHub berada di luar negeri; situs pemerintah kadang menolak IP luar negeri. Bila langkah cek akses gagal: pakai VM gratis yang bisa dipilih wilayahnya (mis. Oracle Cloud Always Free, wilayah Singapura/Jakarta bila tersedia) dan jalankan `python -m scraper perbarui` dengan cron di sana, atau tetap jalankan dari komputer sendiri (`Perbarui dan Ekspor Publik.command`).
