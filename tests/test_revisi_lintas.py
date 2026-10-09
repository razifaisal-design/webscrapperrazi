import unittest
from unittest import mock

from scraper.core import db
from tests.test_db import pk


class Jam:
    """Jam palsu agar tiap pengambilan punya waktu berbeda (first_seen/last_seen/selesai)."""
    def __init__(self, awal="2026-10-01T08:00:00"):
        self.t = awal

    def set(self, t):
        self.t = t

    def __call__(self):
        return self.t


class TestRevisiLintasRun(unittest.TestCase):
    def setUp(self):
        self.jam = Jam()
        p = mock.patch.object(db, "_now", self.jam)
        p.start()
        self.addCleanup(p.stop)
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)

    def run_(self, waktu, paket):
        self.jam.set(waktu)
        rid = db.mulai_run(self.conn, 1, 2026)
        r = db.finalisasi(self.conn, rid, paket, 1, 2026)
        self.jam.set(waktu)
        db.tutup_run(self.conn, rid, "success", len(paket), len(paket))
        return r

    def events(self):
        return [tuple(r) for r in self.conn.execute("SELECT jenis_event,kunci,nilai_lama,nilai_baru,selisih FROM paket_events ORDER BY id")]

    def test_revisi_terpotong_antar_pengambilan_dipasangkan(self):
        self.run_("2026-10-01T08:00:00", [pk("1", "Jalan A", 100), pk("9", "Lain")])                 # data dasar
        r = self.run_("2026-10-02T08:00:00", [pk("9", "Lain")])                                       # RUP 1 hilang
        self.assertEqual((r["hilang"], r["revisi"], r["revisi_lintas"]), (1, 0, 0))
        r = self.run_("2026-10-04T08:00:00", [pk("9", "Lain"), pk("2", "Jalan  A", 105)])             # dua hari kemudian RUP baru bernama sama, pagu +5%
        self.assertEqual(r["revisi_lintas"], 1)
        self.assertEqual(self.events(), [("REVISI_RUP", "2", "1", "2", 5)])                           # BARU + HILANG diganti satu event revisi
        a, b = (self.conn.execute("SELECT kode_rup_pengganti, kode_rup_sebelumnya FROM sirup_paket WHERE kode_rup=?", (k,)).fetchone() for k in ("1", "2"))
        self.assertEqual((a[0], b[1]), ("2", "1"))

    def test_nama_sama_tapi_pagu_jauh_berbeda_tidak_dipasangkan(self):
        self.run_("2026-10-01T08:00:00", [pk("1", "Fotocopy", 100), pk("9", "Lain")])
        self.run_("2026-10-02T08:00:00", [pk("9", "Lain")])
        r = self.run_("2026-10-03T08:00:00", [pk("9", "Lain"), pk("2", "Fotocopy", 500)])
        self.assertEqual(r["revisi_lintas"], 0)
        self.assertEqual([e[0] for e in self.events()], ["HILANG", "BARU"])

    def test_di_luar_jendela_tidak_dipasangkan(self):
        self.run_("2026-09-01T08:00:00", [pk("1", "Jalan A", 100), pk("9", "Lain")])
        self.run_("2026-09-02T08:00:00", [pk("9", "Lain")])
        r = self.run_("2026-10-08T08:00:00", [pk("9", "Lain"), pk("2", "Jalan A", 100)])              # 36 hari kemudian
        self.assertEqual(r["revisi_lintas"], 0)

    def test_paket_data_dasar_tidak_dianggap_baru(self):
        self.run_("2026-10-01T08:00:00", [pk("9", "Lain")])
        r = self.run_("2026-10-02T08:00:00", [pk("9", "Lain")])
        self.assertEqual(r["revisi_lintas"], 0)

    def test_pasangan_satu_lawan_satu_dan_tidak_diulang(self):
        self.run_("2026-10-01T08:00:00", [pk("1", "Jalan A", 100), pk("9", "Lain")])
        self.run_("2026-10-02T08:00:00", [pk("9", "Lain")])
        self.run_("2026-10-03T08:00:00", [pk("9", "Lain"), pk("2", "Jalan A", 100), pk("3", "Jalan A", 100)])   # dua RUP baru, satu RUP lama
        revisi = [e for e in self.events() if e[0] == "REVISI_RUP"]
        self.assertEqual(len(revisi), 1)
        r = self.run_("2026-10-04T08:00:00", [pk("9", "Lain"), pk("2", "Jalan A", 100), pk("3", "Jalan A", 100)])
        self.assertEqual(r["revisi_lintas"], 0)
        self.assertEqual(len([e for e in self.events() if e[0] == "REVISI_RUP"]), 1)


class TestFotoHarian(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)

    def test_satu_foto_per_hari_diganti_dan_bertambah_tiap_hari(self):
        db.simpan_foto(self.conn, [pk("1", "A", 10), pk("2", "B", 20)], 1, 2026, "2026-10-01")
        db.simpan_foto(self.conn, [pk("1", "A", 15)], 1, 2026, "2026-10-01")                  # hari sama: mengganti foto hari itu
        db.simpan_foto(self.conn, [pk("1", "A", 15), pk("3", "C", 30)], 1, 2026, "2026-10-02")
        baris = [tuple(r) for r in self.conn.execute("SELECT tanggal, kode_rup, pagu FROM sirup_foto ORDER BY tanggal, kode_rup")]
        self.assertEqual(baris, [("2026-10-01", "1", 15), ("2026-10-02", "1", 15), ("2026-10-02", "3", 30)])

    def test_foto_dibuat_otomatis_saat_finalisasi_per_satker_dan_tahun(self):
        rid = db.mulai_run(self.conn, 1, 2026)
        db.finalisasi(self.conn, rid, [pk("1"), pk("2")], 1, 2026)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sirup_foto").fetchone()[0], 2)
        rid = db.mulai_run(self.conn, 7, 2025)
        db.finalisasi(self.conn, rid, [dict(pk("5"), id_satker=7, tahun=2025)], 7, 2025)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sirup_foto").fetchone()[0], 3)       # satker/tahun lain tidak menghapus foto ini


if __name__ == "__main__":
    unittest.main()
