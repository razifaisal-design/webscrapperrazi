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
