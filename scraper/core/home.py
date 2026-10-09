"""Data halaman Home: nilai paket per TAHAP untuk kategori Jalan PSU, Saluran PSU dan gabungannya, dibandingkan dengan total paket yang sudah
terinput di SiRUP.

Aturan (keputusan pengguna):
  * Kategori dari MAK (config/kategori_home.json); hanya MAK format 2026; yang 'Lainnya' tidak ikut.
  * Paket 'sudah tayang' = tahap pertama jadwal SPSE sudah dimulai; paket batal tidak dihitung sebagai tayang.
  * Tahap paket = tahap TERAKHIR yang tanggal mulainya sudah tiba (dibandingkan menurut tanggal, bukan jam).
  * Nilai satu paket = hasil negosiasi bila ada, bila belum HPS. Paket yang belum ada di SPSE memakai pagu SiRUP (satu-satunya nilai yang ada).
  * Persen = bagian dari total NILAI (Rp) seluruh paket kategori itu yang sudah terinput di SiRUP."""
from datetime import date

from . import banding, kategori_home

TAHAP = ["Upload Dokumen Penawaran", "Pembukaan Dokumen Penawaran", "Evaluasi Penawaran", "Klarifikasi Teknis dan Negosiasi", "Penandatanganan Kontrak"]
LAIN = [("belum_tayang", "Belum tayang di SPSE"), ("batal", "Dibatalkan (SPSE)"), ("tanpa_jadwal", "Jadwal SPSE belum diambil"), ("tidak_spse", "Tidak lewat SPSE")]


def nilai_gabungan(b):
    """(nilai, ada_negosiasi): hasil negosiasi bila ada, bila belum HPS."""
    if b.get("hasil_negosiasi") is not None:
        return b["hasil_negosiasi"], True
    return (b.get("hps") or 0), False


def tahap_saat_ini(jadwal, hari_ini):
    """Nama tahap terakhir yang tanggal mulainya <= hari_ini (YYYY-MM-DD); None bila belum ada yang dimulai."""
    sudah = [t for t in sorted(jadwal, key=lambda x: x["no"]) if t.get("mulai") and t["mulai"][:10] <= hari_ini]
    return sudah[-1]["tahap"] if sudah else None


def _taruh(b, hari_ini):
    """-> (kunci_bucket, nilai, ada_negosiasi) untuk satu baris perbandingan."""
    if not b.get("kode_nontender"):
        st = b.get("status") or ""
        return ("tidak_spse" if "tidak di SPSE" in st or st == "Dikecualikan" else "belum_tayang"), (b.get("pagu_sirup") or 0), False
    nilai, neg = nilai_gabungan(b)
    if "batal" in (b.get("tahapan") or "").lower():
        return "batal", nilai, neg
    if not b.get("jadwal"):
        return "tanpa_jadwal", nilai, neg
    tahap = tahap_saat_ini(b["jadwal"], hari_ini)
    return (("tahap:" + tahap) if tahap else "belum_tayang"), nilai, neg


def _ringkas(rows, hari_ini):
    isi, urut_tahap = {}, list(TAHAP)
    fisik = konsultan = 0
    total_pagu = 0
    for b in rows:
        kunci, nilai, neg = b["_bucket"]
        e = isi.setdefault(kunci, {"paket": 0, "nilai": 0, "negosiasi": 0})
        e["paket"] += 1; e["nilai"] += nilai; e["negosiasi"] += 1 if neg else 0
        total_pagu += b.get("pagu_sirup") or 0
        if b["_jenis"] == "Konsultan": konsultan += 1
        else: fisik += 1
        if kunci.startswith("tahap:") and kunci[6:] not in urut_tahap:
            urut_tahap.append(kunci[6:])
    total_nilai = sum(e["nilai"] for e in isi.values())
    daftar = [("tahap:" + t, t, "tahap") for t in urut_tahap] + [(k, n, k) for k, n in LAIN if k in isi]
    bucket = []
    for kunci, nama, tipe in daftar:
        e = isi.get(kunci, {"paket": 0, "nilai": 0, "negosiasi": 0})
        bucket.append({"kunci": kunci, "nama": nama, "tipe": tipe, "paket": e["paket"], "nilai": e["nilai"], "negosiasi": e["negosiasi"],
                       "persen": (e["nilai"] * 100 / total_nilai) if total_nilai else 0})
    tayang = [k for k in isi if k.startswith("tahap:")]
    return {"total_paket": len(rows), "total_nilai": total_nilai, "total_pagu_sirup": total_pagu, "fisik": fisik, "konsultan": konsultan,
            "paket_tayang": sum(isi[k]["paket"] for k in tayang), "nilai_tayang": sum(isi[k]["nilai"] for k in tayang),
            "paket_negosiasi": sum(isi[k]["negosiasi"] for k in tayang), "bucket": bucket}


def hitung(conn, lpse, tahun_list, peta_sirup, satker=None, hari_ini=None, aturan=None):
    """-> {'kelompok': {'Jalan PSU': ..., 'Saluran PSU': ..., 'Semua': ...}, 'hari_ini', 'tahun_berlaku', 'kosong', 'pesan'}"""
    hari_ini = hari_ini or date.today().isoformat()
    aturan = aturan or kategori_home.muat_aturan()
    berlaku = aturan.get("tahun_berlaku", [])
    tampil = aturan.get("tampil_di_home", [])
    tahun_pakai = [t for t in tahun_list if t in berlaku]
    hasil = {"hari_ini": hari_ini, "tahun_berlaku": berlaku, "tampil": tampil, "kelompok": {}, "kosong": True, "pesan": None}
    if not tahun_pakai:
        hasil["pesan"] = f"Kategori Home memakai MAK tahun {', '.join(map(str, berlaku))}; tahun yang dipilih belum punya aturan kategori."
        return hasil
    res = banding.hitung(conn, lpse, "nontender", tahun_pakai, peta_sirup, satker, sekarang=hari_ini + "T23:59")
    mak = {k: m for k, m in conn.execute("SELECT kode_rup, mak FROM sirup_detail WHERE mak IS NOT NULL")}
    for k, m in conn.execute("SELECT kode_rup, mak FROM sirup_luar_daftar WHERE mak IS NOT NULL") if _ada(conn, "sirup_luar_daftar") else []:
        mak.setdefault(k, m)
    per = {k: [] for k in tampil}
    for b in res["baris"]:
        if not b.get("kode_rup"):
            continue                                                    # paket SPSE tanpa RUP: tidak bisa dikategorikan lewat MAK
        kat = kategori_home.kategori(mak.get(b["kode_rup"]), b["tahun"], aturan)
        if kat not in per:
            continue
        b["_bucket"] = _taruh(b, hari_ini)
        b["_jenis"] = kategori_home.jenis_pekerjaan(b.get("nama_sirup") or "")
        per[kat].append(b)
    for kat in tampil:
        hasil["kelompok"][kat] = _ringkas(per[kat], hari_ini)
    gabung = [b for kat in tampil for b in per[kat]]
    hasil["kelompok"]["Semua"] = _ringkas(gabung, hari_ini)
    hasil["kosong"] = not gabung
    if hasil["kosong"]:
        hasil["pesan"] = "Belum ada paket Jalan/Saluran PSU untuk pilihan ini (cek tahun, satker, dan apakah detail MAK paket sudah diambil)."
    return hasil


def _ada(conn, tabel):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tabel,)).fetchone() is not None
