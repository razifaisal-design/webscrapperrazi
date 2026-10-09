"""Daftar perintah yang bisa dijalankan dari halaman 'Pusat Perintah' di dashboard lokal, beserta penjelasan fungsinya.

Perintah yang SUDAH punya tugas sendiri di dashboard (ambil SiRUP, ambil SPSE, periksa RUP) hanya dijelaskan di sini dan dijalankan
lewat jenis tugasnya masing-masing; sisanya dijalankan lewat `jalankan()` di bawah, satu pada satu waktu (dikelola PengelolaTugas)."""
import threading
from pathlib import Path

from . import konfig

# jenis: nama jenis tugas di PengelolaTugas; 'perintah' = lewat jalankan() di modul ini
DAFTAR = [
    {"id": "perbarui", "jenis": "perintah", "nama": "Perbarui semuanya", "kelompok": "Satu klik",
     "fungsi": "Mengerjakan seluruh alur berurutan: ambil data SiRUP (semua satker terdaftar) -> ambil data SPSE -> periksa RUP ke SiRUP -> cadangkan ke Supabase -> terbitkan ke web publik (-> opsional unggah halaman ke Cloudflare).",
     "kapan": "Rutin (mis. sehari dua kali) atau setelah lama tidak diperbarui.",
     "waktu": "10 menit - 1 jam+ (bergantung jumlah data baru)", "mengubah": ["Lokal", "Supabase", "Web publik"],
     "param": [{"k": "tahun", "label": "Tahun anggaran", "tipe": "tahun"}, {"k": "koneksi", "label": "Koneksi", "tipe": "pilih", "opsi": [1, 2, 3, 4, 5], "bawaan": 2},
               {"k": "jeda", "label": "Jeda (detik)", "tipe": "pilih", "opsi": [1, 1.5, 2, 3], "bawaan": 1.5},
               {"k": "unggah", "label": "Unggah halaman ke Cloudflare juga", "tipe": "cek", "bawaan": False}]},
    {"id": "sirup", "jenis": "semua", "nama": "Ambil data SiRUP", "kelompok": "Ambil data",
     "fungsi": "Mengambil daftar RUP satker (100 baris per halaman), lalu detail tiap paket (lokasi, volume, uraian, spesifikasi, MAK), lalu membangun database Jalan/Gang. Mencatat perubahan (baru, berubah, hilang, revisi RUP) dan membuat foto harian.",
     "kapan": "Untuk memperbarui rekap SiRUP.", "waktu": "±1 menit (daftar) + ±menit-jam (detail baru)", "mengubah": ["Lokal"],
     "param": [{"k": "tahun", "label": "Tahun anggaran", "tipe": "tahun"}, {"k": "koneksi", "label": "Koneksi (detail)", "tipe": "pilih", "opsi": [1, 2, 3, 5], "bawaan": 1},
               {"k": "jeda", "label": "Jeda (detik)", "tipe": "pilih", "opsi": [0.5, 1, 1.5, 2, 3], "bawaan": 1.5},
               {"k": "semua", "label": "Paksa ambil ulang semua detail", "tipe": "cek", "bawaan": False}]},
    {"id": "spse", "jenis": "spse_semua", "nama": "Ambil data SPSE Non-Tender", "kelompok": "Ambil data",
     "fungsi": "Mengambil daftar paket Non-Tender dari LPSE, lalu detail tiap paket: Pengumuman (satker, kode RUP, pagu, HPS), Pemenang, Pemenang Berkontrak, Jadwal beserta riwayat perubahan tahap. Hanya paket yang belum lengkap yang diambil.",
     "kapan": "Untuk memperbarui halaman SPSE dan Perbandingan.", "waktu": "±1 menit (daftar) + ±menit-jam (detail)", "mengubah": ["Lokal"],
     "param": [{"k": "tahun", "label": "Tahun anggaran", "tipe": "tahun", "semua": True}, {"k": "koneksi", "label": "Koneksi (detail)", "tipe": "pilih", "opsi": [1, 2, 3, 4, 5], "bawaan": 1},
               {"k": "jeda", "label": "Jeda (detik)", "tipe": "pilih", "opsi": [1, 1.5, 2, 3], "bawaan": 1.5},
               {"k": "semua", "label": "Paksa ambil ulang semua detail", "tipe": "cek", "bawaan": False}]},
    {"id": "periksa_rup", "jenis": "banding_periksa", "nama": "Periksa RUP ke SiRUP", "kelompok": "Ambil data",
     "fungsi": "Untuk kode RUP yang disebut SPSE tetapi tidak ada di daftar SiRUP satker, membuka halaman detail RUP-nya langsung lewat kode untuk memastikan ada/tidaknya, satkernya, dan paginya. Hasilnya dipakai halaman Perbandingan.",
     "kapan": "Setelah mengambil data SPSE, bila halaman Perbandingan menunjukkan paket yang 'belum dicek'.", "waktu": "±1 detik per kode RUP", "mengubah": ["Lokal"],
     "param": [{"k": "tahun", "label": "Tahun anggaran", "tipe": "tahun", "semua": True}, {"k": "koneksi", "label": "Koneksi", "tipe": "pilih", "opsi": [1, 2, 3, 4, 5], "bawaan": 2},
               {"k": "jeda", "label": "Jeda (detik)", "tipe": "pilih", "opsi": [1, 1.5, 2, 3], "bawaan": 1.5}]},
    {"id": "lokasi", "jenis": "perintah", "nama": "Bangun database Jalan & Gang", "kelompok": "Olah data lokal",
     "fungsi": "Membaca nama paket fisik, menguraikannya menjadi jalan, gang, komplek, kecamatan, kelurahan, lalu menyimpan tabel Daftar Jalan/Daftar Gang tanpa duplikat dan CSV lengkap. Aman dijalankan ulang.",
     "kapan": "Setelah detail SiRUP bertambah atau aturan nama diubah (sudah otomatis di Ambil data SiRUP).", "waktu": "beberapa detik", "mengubah": ["Lokal"],
     "param": [{"k": "tahun", "label": "Tahun anggaran", "tipe": "tahun"}]},
    {"id": "sinkron", "jenis": "perintah", "nama": "Cadangkan ke Supabase", "kelompok": "Supabase & publikasi", "perlu": "supabase",
     "fungsi": "Mencerminkan seluruh database lokal ke Supabase dalam satu transaksi (isi lama diganti isi lokal; gagal = Supabase tidak berubah). Tabelnya tertutup untuk publik; ini cadangan dan pusat data.",
     "kapan": "Setelah mengambil data, bila tidak memakai 'Perbarui semuanya'.", "waktu": "±30 detik", "mengubah": ["Supabase"], "param": []},
    {"id": "terbitkan", "jenis": "perintah", "nama": "Terbitkan ke web publik", "kelompok": "Supabase & publikasi", "perlu": "terbitkan",
     "fungsi": "Membuat berkas data untuk web publik (rekap, database, SPSE, perbandingan, Excel) lalu menaruhnya di Supabase (tabel publik_berkas yang boleh dibaca publik), dan membuat halaman kecil di folder publik/. Halaman Cloudflare tidak perlu diunggah ulang untuk pembaruan data.",
     "kapan": "Setelah data lokal diperbarui dan Anda ingin web publik ikut berubah.", "waktu": "±2-3 menit", "mengubah": ["Supabase", "Web publik"],
     "param": [{"k": "excel", "label": "Sertakan berkas Excel", "tipe": "cek", "bawaan": True}]},
    {"id": "unggah", "jenis": "perintah", "nama": "Unggah halaman ke Cloudflare", "kelompok": "Supabase & publikasi", "perlu": "cloudflare",
     "fungsi": "Mengunggah isi folder publik/ (halaman HTML kecil, bukan data) ke Cloudflare dengan Wrangler. Hanya perlu bila tampilan/kode halaman berubah; data tidak ikut.",
     "kapan": "Setelah halaman berubah, atau pertama kali.", "waktu": "±30 detik", "mengubah": ["Cloudflare"], "param": []},
    {"id": "ekspor_statis", "jenis": "perintah", "nama": "Ekspor salinan statis lengkap", "kelompok": "Supabase & publikasi",
     "fungsi": "Membuat folder publik/ yang memuat SEMUA data di dalamnya (±100 MB), untuk dihosting tanpa Supabase atau dicoba lokal. Menimpa isi publik/.",
     "kapan": "Bila ingin situs statis mandiri; biasanya tidak perlu (pakai 'Terbitkan').", "waktu": "±2 menit", "mengubah": ["Lokal (folder publik/)"], "param": []},
    {"id": "tarik", "jenis": "perintah", "nama": "Pulihkan database dari Supabase", "kelompok": "Supabase & publikasi", "perlu": "supabase", "bahaya": True,
     "fungsi": "Mengganti database lokal dengan isi cermin di Supabase (yang lama disimpan sebagai pantau.db.sebelum-tarik). Dipakai di komputer baru atau bila database lokal rusak.",
     "kapan": "Hanya bila yakin isi Supabase lebih baru/lengkap daripada lokal.", "waktu": "±30 detik", "mengubah": ["Lokal (menimpa)"],
     "param": [{"k": "konfirmasi", "label": "Saya mengerti database lokal akan DIGANTI", "tipe": "cek", "bawaan": False}]},
]
PER_ID = {p["id"]: p for p in DAFTAR}
ID_PERINTAH = {p["id"] for p in DAFTAR if p["jenis"] == "perintah"}


def kesiapan():
    """Apa saja yang sudah terpasang/terisi, agar tombol bisa dinonaktifkan dengan alasan yang jelas."""
    import shutil
    from . import ekspor_publik, sinkron
    return {"supabase": bool(sinkron.url_db()), "terbitkan": bool(sinkron.url_db() and ekspor_publik.muat_konfig_publik()),
            "cloudflare": bool(shutil.which("npx")) and (konfig.ROOT / "wrangler.jsonc").exists()}


def metadata():
    siap = kesiapan()
    alasan = {"supabase": "SUPABASE_DB_URL belum diisi di .env", "terbitkan": "SUPABASE_DB_URL di .env atau config/publik.json belum lengkap",
              "cloudflare": "Node.js (npx) belum terpasang"}
    hasil = []
    for p in DAFTAR:
        x = dict(p)
        butuh = p.get("perlu")
        x["siap"] = siap.get(butuh, True) if butuh else True
        x["alasan_belum_siap"] = None if x["siap"] else alasan[butuh]
        hasil.append(x)
    return hasil


def validasi(id_, opsi):
    """Opsi yang boleh dikirim browser, dibersihkan menurut definisi di DAFTAR. ValueError bila tidak sah."""
    if id_ not in ID_PERINTAH:
        raise ValueError("perintah tidak dikenal")
    opsi = opsi or {}
    bersih = {}
    for par in PER_ID[id_]["param"]:
        k, nilai = par["k"], opsi.get(par["k"], par.get("bawaan"))
        if par["tipe"] == "cek":
            bersih[k] = bool(nilai)
        elif par["tipe"] == "pilih":
            if float(nilai) not in [float(o) for o in par["opsi"]]:
                raise ValueError(f"nilai {k} tidak sah")
            bersih[k] = float(nilai) if k == "jeda" else int(nilai)
        elif par["tipe"] == "tahun":
            bersih[k] = int(nilai) if nilai not in (None, "") else None
            if bersih[k] is not None and not 2000 <= bersih[k] <= 2100:
                raise ValueError("tahun di luar jangkauan")
    if id_ == "tarik" and not bersih.get("konfirmasi"):
        raise ValueError("pulihkan dari Supabase menimpa database lokal: centang konfirmasi dulu")
    return bersih


def jalankan(id_, opsi, db_path, log, berhenti=None):
    """Jalankan satu perintah. -> kode keluar (0 baik, 1 gagal, 2 diblokir, 130 dihentikan). Tidak melempar: galat dicatat ke log."""
    from . import ekspor_publik, sinkron, tugas, unggah
    from .core import db
    berhenti = berhenti or threading.Event()
    opsi = validasi(id_, opsi)
    try:
        if id_ == "perbarui":
            conn = db.buka(db_path)
            try:
                return tugas.run_perbarui(conn, db_path, tahun=opsi.get("tahun"), koneksi=opsi["koneksi"], jeda=opsi["jeda"], unggah=opsi["unggah"],
                                          log=log, berhenti=berhenti)
            finally:
                conn.close()
        if id_ == "lokasi":
            conn = db.buka(db_path)
            try:
                _, target = konfig.muat_target(None, opsi.get("tahun"))
                tugas.bangun_lokasi(conn, target, db_path, log)
                return 0
            finally:
                conn.close()
        if id_ == "sinkron":
            jumlah = sinkron.sinkron(db_path, log=log)
            log(f"Supabase dicerminkan: {sum(jumlah.values())} baris di {len(jumlah)} tabel.")
            return 0
        if id_ == "terbitkan":
            kfg, url = ekspor_publik.muat_konfig_publik(), sinkron.url_db()
            if not (kfg and url):
                log("[TIDAK BISA] config/publik.json atau SUPABASE_DB_URL belum lengkap.")
                return 1
            r = ekspor_publik.terbitkan(db_path, konfig.ROOT / "publik", url, kfg, log=log, dengan_excel=opsi.get("excel", True))
            log(f"Terbit: {r['berkas']} berkas data di Supabase; halaman publik {r['ukuran_mb']} MB di publik/.")
            return 0
        if id_ == "unggah":
            ok, pesan = unggah.unggah(None, log=log)
            log(("Terunggah: " if ok else "[TIDAK TERUNGGAH] ") + pesan)
            return 0 if ok else 1
        if id_ == "ekspor_statis":
            r = ekspor_publik.ekspor(db_path, konfig.ROOT / "publik", log=log)
            log(f"Salinan statis: {r['berkas']} berkas, {r['ukuran_mb']} MB di publik/.")
            return 0
        if id_ == "tarik":
            jumlah = sinkron.tarik(db_path, paksa=True, log=log)
            log(f"Database lokal dibangun dari Supabase: {sum(jumlah.values())} baris di {len(jumlah)} tabel.")
            return 0
    except sinkron.SinkronError as e:
        log(f"[GAGAL] {e}")
        return 1
    except Exception as e:
        log(f"[GAGAL] {type(e).__name__}: {str(e)[:300]}")
        return 1
    return 1
