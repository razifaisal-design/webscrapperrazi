"""Referensi MAK / sub kegiatan (nomenklatur SIPD) dan pemecahan kode MAK.

Kode MAK lengkap (format 2026), contoh `1.04.05.2.01.0012.5.2.04.01.001.00004`:
  [0..5]  1.04.05.2.01.0012  = sub kegiatan (urusan.bidang.program . jenis . kegiatan . sub kegiatan)
  [6..11] 5.2.04.01.001.00004 = kode rekening (di sini: Belanja Modal Jalan Kota); segmen ke-13 dst. diabaikan
Referensi diimpor dari database MAK (kode_mak.db) buatan pengguna; nama yang belum diketahui TIDAK ditebak."""
import sqlite3

TABEL_REF = """
CREATE TABLE IF NOT EXISTS ref_sub_kegiatan (
  kode_sub_kegiatan TEXT PRIMARY KEY, nama_sub_kegiatan TEXT,
  kode_kegiatan TEXT, nama_kegiatan TEXT, kode_program TEXT, nama_program TEXT, kode_bidang TEXT, nama_bidang TEXT,
  kode_unit TEXT, nama_unit TEXT, sumber TEXT);
CREATE TABLE IF NOT EXISTS ref_mak (
  kode_mak_full TEXT PRIMARY KEY, kode_sub_kegiatan TEXT, kode_rekening TEXT, nama_rekening TEXT, kategori_belanja TEXT);
"""


def kode_sub_kegiatan(mak):
    """'1.04.05.2.01.0012.5.2.04.01.001.00004' -> '1.04.05.2.01.0012' (6 segmen pertama); kosong -> None."""
    seg = (mak or "").strip().rstrip(".").split(".")
    return ".".join(seg[:6]) if len(seg) >= 6 and seg[0] else None


def kode_rekening(mak):
    """'1.04.05.2.01.0012.5.2.04.01.001.00004' -> '5.2.04.01.001.00004'; MAK yang tak punya bagian rekening -> None."""
    seg = (mak or "").strip().rstrip(".").split(".")
    return ".".join(seg[6:12]) if len(seg) > 6 else None            # 6 segmen rekening; segmen setelah ke-12 (mis. kode sumber pendanaan) diabaikan, seperti di seluruh aplikasi


def daftar_mak(teks):
    """Kolom detail.mak bisa memuat beberapa MAK dipisah ';' -> daftar MAK bersih."""
    return [m.strip().rstrip(".") for m in (teks or "").split(";") if m.strip()]


def impor(conn, path_mak, log=print):
    """Baca database MAK pengguna (hanya-baca) -> ref_sub_kegiatan & ref_mak di database proyek (idempoten: ganti isi dengan isi sumber).
    -> {'sub_kegiatan': n, 'mak': n}"""
    conn.executescript(TABEL_REF)
    src = sqlite3.connect(f"file:{path_mak}?mode=ro", uri=True)
    try:
        sub = src.execute("""SELECT s.kode_sub_kegiatan, s.nama_sub_kegiatan, k.kode_kegiatan, k.nama_kegiatan, p.kode_program, p.nama_program,
                                    b.kode_bidang, b.nama_bidang, s.kode_unit, u.nama_unit
                             FROM sub_kegiatan s JOIN kegiatan k ON k.kode_kegiatan=s.kode_kegiatan JOIN program p ON p.kode_program=k.kode_program
                             LEFT JOIN bidang_urusan b ON b.kode_bidang=p.kode_bidang LEFT JOIN unit_organisasi u ON u.kode_unit=s.kode_unit""").fetchall()
        mak = src.execute("""SELECT m.kode_mak_full, m.kode_sub_kegiatan, m.kode_rekening, r.nama_rekening, r.kategori
                             FROM mak m LEFT JOIN rekening r ON r.kode_rekening=m.kode_rekening""").fetchall()
    finally:
        src.close()
    with conn:
        conn.execute("DELETE FROM ref_sub_kegiatan")
        conn.execute("DELETE FROM ref_mak")
        conn.executemany("INSERT INTO ref_sub_kegiatan VALUES(?,?,?,?,?,?,?,?,?,?,?)", [tuple(r) + (str(path_mak),) for r in sub])
        conn.executemany("INSERT INTO ref_mak VALUES(?,?,?,?,?)", [tuple(r) for r in mak])
    log(f"Referensi MAK diimpor: {len(sub)} sub kegiatan, {len(mak)} MAK.")
    return {"sub_kegiatan": len(sub), "mak": len(mak)}


def isi_sub_kegiatan(conn, kode_rup=None):
    """Isi field sirup_detail.sub_kegiatan_kode / sub_kegiatan_nama dari MAK pertama tiap paket. Nama diisi HANYA bila ada di referensi
    (selain itu NULL = 'belum diketahui'). `kode_rup` None = semua paket. -> jumlah baris yang diperbarui."""
    n = 0
    sql = "SELECT kode_rup, mak FROM sirup_detail WHERE mak IS NOT NULL" + (" AND kode_rup=?" if kode_rup else "")
    rows = conn.execute(sql, (kode_rup,) if kode_rup else ()).fetchall()
    nama = {k: v for k, v in conn.execute("SELECT kode_sub_kegiatan, nama_sub_kegiatan FROM ref_sub_kegiatan")}
    pembaruan = []
    for r in rows:
        mk = daftar_mak(r[1])
        kode = kode_sub_kegiatan(mk[0]) if mk else None
        pembaruan.append((kode, nama.get(kode), r[0]))
    with conn:
        conn.executemany("UPDATE sirup_detail SET sub_kegiatan_kode=?, sub_kegiatan_nama=? WHERE kode_rup=?", pembaruan)
    return len(pembaruan)
