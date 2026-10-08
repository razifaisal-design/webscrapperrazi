"""Baris 'database lengkap' per paket (daftar + detail + hasil olahan) dan penyimpanan tabel Jalan/Gang."""
import html
import json

EXTRA_KUNCI = [
    "jenis_pengadaan", "produk_dalam_negeri", "usaha_kecil", "pra_dipa", "spp_ekonomi", "spp_sosial", "spp_lingkungan",
    "pemanfaatan_mulai", "pemanfaatan_akhir", "kontrak_mulai", "kontrak_akhir", "pemilihan_mulai", "pemilihan_akhir",
    "tanggal_umumkan", "tipe_swakelola", "penyelenggara_swakelola", "pelaksanaan_mulai", "pelaksanaan_akhir"]

# (kunci, judul kolom) - urutan = urutan kolom CSV
KOLOM = [
    ("tahun", "Tahun"), ("kode_rup", "Kode RUP"), ("link", "Tautan SiRUP"), ("jenis", "Penyedia/Swakelola"), ("nama_paket", "Nama Paket"),
    ("penyelenggara", "Penyelenggara"), ("pagu", "Pagu"), ("metode_pemilihan", "Metode Pemilihan"),
    ("sumber_dana", "Sumber Dana"), ("waktu_pemilihan", "Waktu Pemilihan"), ("uraian", "Uraian"),
    ("spesifikasi", "Spesifikasi"), ("volume", "Volume"), ("lokasi_pekerjaan", "Lokasi Pekerjaan"),
    ("mak", "MAK (tercatat)"), ("kategori", "Kategori"), ("jenis_pekerjaan", "Fisik/Konsultan"),
    ("jenis_kegiatan", "Jenis Kegiatan"), ("status_mak", "Status MAK"), ("jenis_perbaikan", "Jenis Perbaikan"),
    ("mak_perbaikan", "MAK Perbaikan"), ("mak_akhir", "MAK Seharusnya"), ("jalan", "Nama Jalan"), ("gang", "Nama Gang"),
    ("komplek", "Komplek"), ("kecamatan", "Kecamatan"), ("kelurahan", "Kelurahan"), ("kecamatan_asli", "Kecamatan (tertulis)"),
    ("kelurahan_asli", "Kelurahan (tertulis)"), ("temuan", "Temuan Pemeriksaan"),
] + [(k, k.replace("_", " ").capitalize()) for k in EXTRA_KUNCI] + [
    ("kode_rup_sebelumnya", "RUP sebelumnya (revisi)"), ("kode_rup_pengganti", "RUP pengganti (revisi)"),
    ("aktif", "Aktif"), ("first_seen", "Pertama terlihat"), ("last_seen", "Terakhir terlihat"),
    ("diambil_pada", "Detail diambil"), ("ada_detail", "Ada detail")]


def _gabung(v):
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    return v


def baris(conn, target, data):
    """List dict datar (list tetap list agar UI bisa memakainya). `data` = hasil rekap.lengkap()."""
    turunan = data["paket"]
    temuan, temuan_rinci = {}, {}
    for t in data["periksa"]["temuan"]:
        temuan.setdefault(t["kode_rup"], []).append(t["judul"])
        temuan_rinci.setdefault(t["kode_rup"], []).append([t["tingkat"], t["judul"], t["pesan"]])
    rows = conn.execute(
        "SELECT p.*, d.lokasi_ringkas, d.volume, d.uraian AS d_uraian, d.spesifikasi, d.sumber_dana_json, "
        "d.extra_json, d.diambil_pada, d.kode_rup AS ada_detail FROM sirup_paket p "
        "LEFT JOIN sirup_detail d ON d.kode_rup=p.kode_rup AND d.error IS NULL "
        "WHERE p.id_satker=? AND p.tahun=? ORDER BY p.kode_rup", (target["id_satker"], target["tahun"])).fetchall()
    hasil = []
    for r in rows:
        t = turunan.get(r["kode_rup"], {})
        extra = json.loads(r["extra_json"]) if r["extra_json"] else {}
        b = {
            "tahun": r["tahun"], "kode_rup": r["kode_rup"], "link": r["link"], "jenis": r["jenis"],
            "nama_paket": html.unescape(r["nama_paket"] or ""), "penyelenggara": r["penyelenggara"],
            "pagu": r["pagu"], "metode_pemilihan": r["metode_pemilihan"],
            "sumber_dana": t.get("sumber_dana") or r["sumber_dana"],
            "waktu_pemilihan": r["waktu_pemilihan"], "uraian": t.get("uraian") or r["d_uraian"],
            "spesifikasi": r["spesifikasi"], "volume": r["volume"], "lokasi_pekerjaan": r["lokasi_ringkas"],
            "mak": [e["mak"] for e in t.get("mak_entri", [])],
            "kategori": t.get("kategori"), "jenis_pekerjaan": t.get("jenis_pekerjaan"),
            "jenis_kegiatan": t.get("jenis_kegiatan"), "status_mak": t.get("status_mak"),
            "jenis_perbaikan": t.get("jenis_perbaikan"), "mak_perbaikan": t.get("mak_perbaikan", []),
            "mak_akhir": t.get("mak_akhir", []), "jalan": t.get("jalan"), "gang": t.get("gang", []),
            "komplek": t.get("komplek", []), "kecamatan": t.get("kecamatan"), "kelurahan": t.get("kelurahan"),
            "kecamatan_asli": t.get("kecamatan_asli"), "kelurahan_asli": t.get("kelurahan_asli"),
            "temuan": temuan.get(r["kode_rup"], []), "temuan_rinci": temuan_rinci.get(r["kode_rup"], []),
            "kode_rup_sebelumnya": r["kode_rup_sebelumnya"], "kode_rup_pengganti": r["kode_rup_pengganti"],
            "aktif": bool(r["is_active"]), "first_seen": r["first_seen"], "last_seen": r["last_seen"],
            "diambil_pada": r["diambil_pada"], "ada_detail": r["ada_detail"] is not None,
            "mak_entri": t.get("mak_entri", []),
            "sumber_dana_rincian": json.loads(r["sumber_dana_json"]) if r["sumber_dana_json"] else [],
        }
        for k in EXTRA_KUNCI:
            b[k] = extra.get(k)
        hasil.append(b)
    return hasil


def perubahan(conn, target, batas=3000):
    """Riwayat perubahan paket (terbaru dulu). REVISI_RUP = nama paket sama, kode RUP berganti."""
    sat, th = target["id_satker"], target["tahun"]
    info = {r["kode_rup"]: r for r in conn.execute(
        "SELECT kode_rup, pagu, link, nama_paket, is_active FROM sirup_paket WHERE id_satker=? AND tahun=?", (sat, th))}
    rows = conn.execute(
        "SELECT e.id,e.waktu,e.sumber,e.jenis_event,e.kunci,e.nama_paket,e.field,e.nilai_lama,e.nilai_baru,e.selisih "
        "FROM paket_events e JOIN sirup_paket p ON p.kode_rup=e.kunci WHERE p.id_satker=? AND p.tahun=? "
        "ORDER BY e.id DESC LIMIT ?", (sat, th, batas)).fetchall()
    hasil = []
    for r in rows:
        x = dict(r)
        x["tahun"] = th
        x["link"] = info[r["kunci"]]["link"]
        x["pagu"] = info[r["kunci"]]["pagu"]
        if r["jenis_event"] == "REVISI_RUP":
            lama = info.get(r["nilai_lama"])
            x["link_lama"] = lama["link"] if lama else None
            x["pagu_lama"] = lama["pagu"] if lama else None
        hasil.append(x)
    return hasil


def ekspor_csv(rows, path):
    import csv
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([j for _, j in KOLOM])
        for r in rows:
            w.writerow([("Ya" if r[k] else "Tidak") if k in ("aktif", "ada_detail") else _gabung(r.get(k)) for k, _ in KOLOM])
    return len(rows)


# ---------- tabel Jalan / Gang di SQLite ----------
SKEMA_LOKASI = """
CREATE TABLE IF NOT EXISTS ref_jalan (
  id INTEGER PRIMARY KEY AUTOINCREMENT, id_satker INTEGER, tahun INTEGER, nama TEXT, kecamatan TEXT,
  jumlah_paket INTEGER, jumlah_gang INTEGER, total_pagu NUMERIC, variasi TEXT);
CREATE TABLE IF NOT EXISTS ref_gang (
  id INTEGER PRIMARY KEY AUTOINCREMENT, id_satker INTEGER, tahun INTEGER, jalan_id INTEGER, nama TEXT,
  tipe TEXT, kecamatan TEXT, jumlah_paket INTEGER, total_pagu NUMERIC, variasi TEXT);
CREATE TABLE IF NOT EXISTS paket_lokasi (
  kode_rup TEXT PRIMARY KEY, id_satker INTEGER, tahun INTEGER, jalan_id INTEGER, jalan TEXT, gang TEXT, komplek TEXT,
  kecamatan TEXT, kelurahan TEXT, jenis_kegiatan TEXT, status_mak TEXT, mak_tercatat TEXT,
  jenis_perbaikan TEXT, mak_perbaikan TEXT);
"""


def simpan_lokasi(conn, target, data):
    """Bangun ulang tabel Jalan/Gang/Paket-Lokasi untuk satu satker+tahun (data turunan, aman dibangun ulang)."""
    sat, th = target["id_satker"], target["tahun"]
    conn.executescript(SKEMA_LOKASI)
    paket = data["paket"]
    with conn:
        for tb in ("ref_gang", "ref_jalan", "paket_lokasi"):
            conn.execute(f"DELETE FROM {tb} WHERE id_satker=? AND tahun=?", (sat, th))
        id_jalan = {}
        for j in data["lokasi"]["jalan"]:
            cur = conn.execute(
                "INSERT INTO ref_jalan(id_satker,tahun,nama,kecamatan,jumlah_paket,jumlah_gang,total_pagu,variasi) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (sat, th, j["nama"], "; ".join(j["kecamatan"]), j["jumlah_paket"], j["jumlah_gang"], j["total_pagu"],
                 "; ".join(j["variasi"])))
            id_jalan[j["nama"]] = cur.lastrowid
            for k in j["paket"]:
                id_jalan.setdefault(("paket", k), cur.lastrowid)
        for g in data["lokasi"]["gang"]:
            conn.execute(
                "INSERT INTO ref_gang(id_satker,tahun,jalan_id,nama,tipe,kecamatan,jumlah_paket,total_pagu,variasi) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (sat, th, id_jalan.get(g["jalan"]), g["nama"], g["tipe"], "; ".join(g["kecamatan"]),
                 g["jumlah_paket"], g["total_pagu"], "; ".join(g["variasi"])))
        for kode, p in paket.items():
            if p["kategori"] not in ("Jalan", "Saluran"):
                continue
            conn.execute(
                "INSERT INTO paket_lokasi VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (kode, sat, th, id_jalan.get(("paket", kode)), p.get("jalan"), "; ".join(p.get("gang") or []),
                 "; ".join(p.get("komplek") or []), p.get("kecamatan"), p.get("kelurahan"), p["jenis_kegiatan"],
                 p["status_mak"], "; ".join(e["mak"] for e in p["mak_entri"]), p["jenis_perbaikan"],
                 "; ".join(p["mak_perbaikan"])))
    return len(data["lokasi"]["jalan"]), len(data["lokasi"]["gang"])


KOLOM_SPSE = [("tahun", "Tahun"), ("kode_paket", "Kode paket"), ("nama_paket", "Nama paket"), ("instansi", "K/L/PD"),
              ("tahapan", "Tahapan"), ("metode", "Metode"), ("kategori", "Jenis pengadaan"), ("tahun_anggaran", "Tahun anggaran"),
              ("hps_teks", "HPS (ringkas di daftar)"), ("hps_perkiraan", "HPS perkiraan (Rp)"), ("nilai_kontrak_teks", "Nilai kontrak"),
              ("versi_spse", "Versi SPSE"), ("konsolidasi", "Konsolidasi"), ("oap", "Khusus OAP"), ("link", "Tautan"),
              ("is_active", "Aktif"), ("first_seen", "Pertama terlihat"), ("last_seen", "Terakhir terlihat")]


def baris_spse(conn, lpse, jenis, tahun=None, aktif_saja=False):
    sql = "SELECT * FROM spse_paket WHERE lpse=? AND jenis=?"
    par = [lpse, jenis]
    if tahun not in (None, "semua"):
        sql += " AND tahun=?"
        par.append(int(tahun))
    if aktif_saja:
        sql += " AND is_active=1"
    return [dict(r) for r in conn.execute(sql + " ORDER BY tahun DESC, kode_paket DESC", par)]


def ekspor_spse_csv(conn, lpse, jenis, path, tahun=None):
    import csv
    from pathlib import Path
    rows = baris_spse(conn, lpse, jenis, tahun)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([j for _, j in KOLOM_SPSE])
        for r in rows:
            w.writerow([("Ya" if r[k] else "Tidak") if k in ("is_active", "konsolidasi", "oap") else r.get(k) for k, _ in KOLOM_SPSE])
    return len(rows)
