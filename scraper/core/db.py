"""Penyimpanan lokal SQLite + finalisasi run (diff -> event -> upsert -> tandai hilang) dalam satu transaksi."""
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .mak import mak_inti, norm_mak

DB_DEFAULT = Path(__file__).resolve().parents[2] / "data" / "pantau.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS scrape_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sumber TEXT NOT NULL, id_satker INTEGER NOT NULL, tahun INTEGER NOT NULL,
  mulai TEXT NOT NULL, selesai TEXT,
  status TEXT NOT NULL,                 -- running | success | failed | invalid
  jumlah_baris INTEGER, jumlah_diharapkan INTEGER, catatan TEXT
);
CREATE TABLE IF NOT EXISTS sirup_paket (
  kode_rup TEXT PRIMARY KEY,
  tahun INTEGER, klpd_nama TEXT, id_satker INTEGER,
  jenis TEXT,                           -- penyedia | swakelola
  nama_paket TEXT, penyelenggara TEXT, pagu NUMERIC,
  metode_pemilihan TEXT, sumber_dana TEXT, waktu_pemilihan TEXT,
  link TEXT,
  first_seen TEXT, last_seen TEXT, is_active INTEGER DEFAULT 1, last_run_id INTEGER
);
CREATE TABLE IF NOT EXISTS paket_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER, sumber TEXT, kunci TEXT, nama_paket TEXT,
  jenis_event TEXT,                     -- BARU | BERUBAH | HILANG | MUNCUL_KEMBALI | KEMUNGKINAN_REVISI
  field TEXT, nilai_lama TEXT, nilai_baru TEXT, selisih NUMERIC, waktu TEXT
);
CREATE TABLE IF NOT EXISTS sirup_detail (
  kode_rup TEXT PRIMARY KEY,
  lokasi_ringkas TEXT, lokasi_json TEXT, volume TEXT, uraian TEXT, spesifikasi TEXT,
  mak TEXT, sumber_dana_json TEXT, total_pagu NUMERIC, extra_json TEXT,
  pagu_saat_diambil NUMERIC, nama_saat_diambil TEXT,
  diambil_pada TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS ix_paket_satker ON sirup_paket(id_satker, tahun, is_active);
CREATE INDEX IF NOT EXISTS ix_events_run ON paket_events(run_id);
"""

FIELD_DIPANTAU = ("jenis", "nama_paket", "pagu", "metode_pemilihan", "sumber_dana", "waktu_pemilihan")
PERSEN_TURUN_MAKS = 20


def buka(path=DB_DEFAULT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _now():
    return datetime.now().isoformat(timespec="seconds")


def mulai_run(conn, id_satker, tahun, sumber="SIRUP"):
    with conn:
        cur = conn.execute(
            "INSERT INTO scrape_runs(sumber,id_satker,tahun,mulai,status) VALUES(?,?,?,?, 'running')",
            (sumber, id_satker, tahun, _now()),
        )
    return cur.lastrowid


def tutup_run(conn, run_id, status, jumlah=None, diharapkan=None, catatan=None):
    with conn:
        conn.execute(
            "UPDATE scrape_runs SET selesai=?, status=?, jumlah_baris=?, jumlah_diharapkan=?, catatan=? WHERE id=?",
            (_now(), status, jumlah, diharapkan, catatan, run_id),
        )


def jumlah_run_valid_terakhir(conn, id_satker, tahun):
    row = conn.execute(
        "SELECT jumlah_baris FROM scrape_runs WHERE sumber='SIRUP' AND id_satker=? AND tahun=? "
        "AND status='success' ORDER BY id DESC LIMIT 1",
        (id_satker, tahun),
    ).fetchone()
    return row["jumlah_baris"] if row else None


def validasi(paket, totals, sebelumnya, force=False):
    """Kembalikan daftar alasan run TIDAK valid (kosong = valid)."""
    alasan = []
    for jenis, total in totals.items():
        n = sum(1 for p in paket if p["jenis"] == jenis)
        if n != total:
            alasan.append(f"{jenis}: terambil {n}, situs melaporkan {total}")
    kode = [p["kode_rup"] for p in paket]
    if len(set(kode)) != len(kode):
        alasan.append(f"ada kode RUP ganda ({len(kode) - len(set(kode))} duplikat)")
    if sebelumnya and not force:
        turun = (sebelumnya - len(paket)) * 100 / sebelumnya
        if turun > PERSEN_TURUN_MAKS:
            alasan.append(f"jumlah turun {turun:.0f}% dari run valid sebelumnya ({sebelumnya} -> {len(paket)}); gunakan --force bila memang benar")
    return alasan


def _norm(nama):
    return " ".join((nama or "").lower().split())


def finalisasi(conn, run_id, paket, id_satker, tahun):
    """Satu transaksi: diff vs data saat ini -> event -> upsert -> tandai hilang. Return ringkasan."""
    now = _now()
    ringkasan = {"baru": 0, "berubah": 0, "hilang": 0, "muncul_kembali": 0, "revisi": 0, "baseline": False}
    with conn:
        ada_sebelumnya = conn.execute(
            "SELECT 1 FROM scrape_runs WHERE sumber='SIRUP' AND id_satker=? AND tahun=? AND status='success' LIMIT 1",
            (id_satker, tahun),
        ).fetchone()
        baseline = ada_sebelumnya is None  # run pertama: tidak membanjiri event BARU
        ringkasan["baseline"] = baseline
        lama = {
            r["kode_rup"]: r
            for r in conn.execute("SELECT * FROM sirup_paket WHERE id_satker=? AND tahun=?", (id_satker, tahun))
        }

        def event(kunci, nama, jenis_event, field=None, lama_v=None, baru_v=None, selisih=None):
            if baseline:
                return
            conn.execute(
                "INSERT INTO paket_events(run_id,sumber,kunci,nama_paket,jenis_event,field,nilai_lama,nilai_baru,selisih,waktu) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (run_id, "SIRUP", kunci, nama, jenis_event, field,
                 None if lama_v is None else str(lama_v), None if baru_v is None else str(baru_v), selisih, now),
            )

        baru_kode, terlihat = [], set()
        for p in paket:
            k = p["kode_rup"]
            terlihat.add(k)
            o = lama.get(k)
            if o is None:
                event(k, p["nama_paket"], "BARU")
                ringkasan["baru"] += 1
                baru_kode.append(k)
                conn.execute(
                    "INSERT INTO sirup_paket(kode_rup,tahun,klpd_nama,id_satker,jenis,nama_paket,penyelenggara,pagu,"
                    "metode_pemilihan,sumber_dana,waktu_pemilihan,link,first_seen,last_seen,is_active,last_run_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                    (k, p["tahun"], p["klpd_nama"], p["id_satker"], p["jenis"], p["nama_paket"], p["penyelenggara"],
                     p["pagu"], p["metode_pemilihan"], p["sumber_dana"], p["waktu_pemilihan"], p["link"], now, now, run_id),
                )
                continue
            if not o["is_active"]:
                event(k, p["nama_paket"], "MUNCUL_KEMBALI")
                ringkasan["muncul_kembali"] += 1
            for f in FIELD_DIPANTAU:
                if str(o[f]) != str(p[f]):
                    selisih = (p[f] - o[f]) if f == "pagu" and o[f] is not None else None
                    event(k, p["nama_paket"], "BERUBAH", f, o[f], p[f], selisih)
                    ringkasan["berubah"] += 1
            conn.execute(
                "UPDATE sirup_paket SET jenis=?,nama_paket=?,penyelenggara=?,pagu=?,metode_pemilihan=?,sumber_dana=?,"
                "waktu_pemilihan=?,link=?,last_seen=?,is_active=1,last_run_id=? WHERE kode_rup=?",
                (p["jenis"], p["nama_paket"], p["penyelenggara"], p["pagu"], p["metode_pemilihan"], p["sumber_dana"],
                 p["waktu_pemilihan"], p["link"], now, run_id, k),
            )

        hilang = [k for k, o in lama.items() if o["is_active"] and k not in terlihat]
        for k in hilang:
            event(k, lama[k]["nama_paket"], "HILANG")
            ringkasan["hilang"] += 1
            conn.execute("UPDATE sirup_paket SET is_active=0, last_run_id=? WHERE kode_rup=?", (run_id, k))

        # Penanda 'kemungkinan revisi': paket hilang + paket baru dengan nama sama (kode RUP berganti)
        baru_by_nama = {}
        for p in paket:
            if p["kode_rup"] in baru_kode:
                baru_by_nama.setdefault(_norm(p["nama_paket"]), []).append(p["kode_rup"])
        for k in hilang:
            for kb in baru_by_nama.get(_norm(lama[k]["nama_paket"]), []):
                event(kb, lama[k]["nama_paket"], "KEMUNGKINAN_REVISI", "kode_rup", k, kb)
                ringkasan["revisi"] += 1
    return ringkasan


DETAIL_DIPANTAU = ("lokasi_ringkas", "volume", "uraian", "spesifikasi", "mak", "extra_json")


def paket_perlu_detail(conn, id_satker, tahun, semua=False):
    """Paket aktif yang detailnya belum ada / gagal / sudah basi (pagu atau nama di daftar berubah)."""
    sql = ("SELECT p.kode_rup,p.jenis,p.nama_paket,p.pagu FROM sirup_paket p "
           "LEFT JOIN sirup_detail d ON d.kode_rup=p.kode_rup "
           "WHERE p.id_satker=? AND p.tahun=? AND p.is_active=1 ")
    if not semua:
        sql += ("AND (d.kode_rup IS NULL OR d.error IS NOT NULL OR d.pagu_saat_diambil IS NOT p.pagu "
                "OR d.nama_saat_diambil IS NOT p.nama_paket) ")
    return conn.execute(sql + "ORDER BY p.kode_rup", (id_satker, tahun)).fetchall()


def simpan_detail(conn, run_id, kode, nama, pagu, d):
    """Simpan detail; bila sebelumnya sudah ada dan isinya berubah -> catat event."""
    now = _now()
    baru = {
        "lokasi_ringkas": d["lokasi_ringkas"], "volume": d["volume"], "uraian": d["uraian"],
        "spesifikasi": d["spesifikasi"], "mak": d["mak"],
        "extra_json": json.dumps(d["extra"], ensure_ascii=False, sort_keys=True),
    }
    with conn:
        lama = conn.execute("SELECT * FROM sirup_detail WHERE kode_rup=?", (kode,)).fetchone()
        if lama is not None and lama["error"] is None:
            for f in DETAIL_DIPANTAU:
                a, b = lama[f] or "", baru[f] or ""
                if f == "mak":                      # angka setelah segmen ke-12 diabaikan
                    a, b = mak_inti(a), mak_inti(b)
                if a != b:
                    conn.execute(
                        "INSERT INTO paket_events(run_id,sumber,kunci,nama_paket,jenis_event,field,nilai_lama,nilai_baru,waktu) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (run_id, "SIRUP_DETAIL", kode, nama, "BERUBAH", "detail." + f, lama[f], baru[f], now))
        conn.execute(
            "INSERT OR REPLACE INTO sirup_detail(kode_rup,lokasi_ringkas,lokasi_json,volume,uraian,spesifikasi,mak,"
            "sumber_dana_json,total_pagu,extra_json,pagu_saat_diambil,nama_saat_diambil,diambil_pada,error) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
            (kode, baru["lokasi_ringkas"], json.dumps(d["lokasi"], ensure_ascii=False), baru["volume"], baru["uraian"],
             baru["spesifikasi"], baru["mak"], json.dumps(d["sumber_dana"], ensure_ascii=False), d["total_pagu"],
             baru["extra_json"], pagu, nama, now))


def catat_gagal_detail(conn, kode, pesan):
    with conn:
        conn.execute(
            "INSERT INTO sirup_detail(kode_rup,diambil_pada,error) VALUES(?,?,?) "
            "ON CONFLICT(kode_rup) DO UPDATE SET error=excluded.error, diambil_pada=excluded.diambil_pada",
            (kode, _now(), pesan[:300]))


KOLOM_CSV = ["kode_rup", "jenis", "nama_paket", "penyelenggara", "pagu", "metode_pemilihan", "sumber_dana",
             "waktu_pemilihan", "jenis_pengadaan", "lokasi", "volume", "uraian", "spesifikasi", "mak",
             "produk_dalam_negeri", "usaha_kecil", "kontrak_mulai", "kontrak_akhir", "pemilihan_mulai",
             "tanggal_umumkan", "link", "first_seen", "last_seen"]


def ekspor_csv(conn, id_satker, tahun, path, mak_segmen=12):
    """CSV gabungan daftar + detail (kolom detail kosong bila belum diambil)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT p.*, d.lokasi_ringkas, d.volume, d.uraian, d.spesifikasi, d.mak, d.extra_json "
        "FROM sirup_paket p LEFT JOIN sirup_detail d ON d.kode_rup=p.kode_rup AND d.error IS NULL "
        "WHERE p.id_satker=? AND p.tahun=? AND p.is_active=1 ORDER BY p.jenis, p.kode_rup", (id_satker, tahun)).fetchall()
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(KOLOM_CSV)
        for r in rows:
            extra = json.loads(r["extra_json"]) if r["extra_json"] else {}
            if r["jenis"] == "swakelola":
                extra.setdefault("kontrak_mulai", extra.get("pelaksanaan_mulai"))
                extra.setdefault("kontrak_akhir", extra.get("pelaksanaan_akhir"))
            baris = dict(r)
            baris["lokasi"] = r["lokasi_ringkas"]
            baris["mak"] = mak_inti(r["mak"], mak_segmen)
            baris.update({k: extra.get(k) for k in ("jenis_pengadaan", "produk_dalam_negeri", "usaha_kecil",
                                                    "kontrak_mulai", "kontrak_akhir", "pemilihan_mulai", "tanggal_umumkan")})
            w.writerow([baris.get(k) for k in KOLOM_CSV])
    return len(rows)
