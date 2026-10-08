"""Penyimpanan lokal SQLite + finalisasi run (diff -> event -> upsert -> tandai hilang) dalam satu transaksi."""
import csv
import sqlite3
from datetime import datetime
from pathlib import Path

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


def mulai_run(conn, id_satker, tahun):
    with conn:
        cur = conn.execute(
            "INSERT INTO scrape_runs(sumber,id_satker,tahun,mulai,status) VALUES('SIRUP',?,?,?, 'running')",
            (id_satker, tahun, _now()),
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


def ekspor_csv(conn, id_satker, tahun, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT kode_rup,jenis,nama_paket,penyelenggara,pagu,metode_pemilihan,sumber_dana,waktu_pemilihan,link,"
        "first_seen,last_seen FROM sirup_paket WHERE id_satker=? AND tahun=? AND is_active=1 ORDER BY jenis, kode_rup",
        (id_satker, tahun),
    ).fetchall()
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(rows[0].keys() if rows else ["kode_rup"])
        w.writerows([tuple(r) for r in rows])
    return len(rows)
