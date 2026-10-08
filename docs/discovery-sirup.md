# Discovery SiRUP (Bagian 1a) — 8 Oktober 2026

Sumber: `https://sirup.inaproc.id/sirup/home/penyediaSatker?idSatker=173394`

## Hierarki (terkonfirmasi dari halaman detail paket)
- **KLPD = "Kota Pontianak"** (Pemda itu sendiri).
- **Satuan Kerja = Dinas Perumahan Rakyat dan Kawasan Permukiman**, `idSatker=173394`.
- Jadi "semua KLPD satu kota" = semua **satker** di bawah KLPD Kota Pontianak. Daftar `idSatker` lain belum dicacah.

## Endpoint JSON publik (DataTables server-side, tanpa login)
| Jenis | URL | Kolom `aaData` |
|---|---|---|
| Penyedia | `/sirup/datatablectr/dataruppenyediasatker?tahun=2026&idSatker=173394` | id, nama paket, pagu, metode, sumber dana, kode RUP, waktu pemilihan |
| Swakelola | `/sirup/datatablectr/datarupswakelolasatker?tahun=2026&idSatker=173394` | id, penyelenggara, nama paket, pagu, sumber dana, kode RUP, waktu pemilihan |

- Paging: `iDisplayStart`, `iDisplayLength` (100 = setara "Tampilkan 100 entri"). Total ada di `iTotalDisplayRecords`.
- Pagu dikirim sebagai angka polos (`"8915000"`).
- Hasil 8 Okt 2026: **976 penyedia + 3 swakelola = 979 paket**, total pagu Rp 166.322.739.888.
- Situs mencantumkan "Data rekap terakhir diperbaharui pada tanggal 08 Oktober 2026 01:47" → data tidak berubah tiap menit.

## Tautan detail paket (pola tetap, kode RUP = id)
- Penyedia: `/sirup/home/detailPaketPenyediaPublic2017/{kode_rup}`
- Swakelola: `/sirup/home/detailPaketSwakelolaPublic2017?idPaket={kode_rup}`
- Detail memuat lokasi, volume, uraian, spesifikasi, dll. (belum diambil — v1 hanya daftar + tautan).

## Catatan
- `robots.txt` tidak tersedia (mengembalikan halaman HTML, bukan aturan).
- Situs di belakang Cloudflare; akses Python dengan User-Agent jujur + jeda 1,5 dtk berjalan tanpa hambatan.
- Python macOS tanpa sertifikat SSL → memakai `httpx` (membawa `certifi`).
