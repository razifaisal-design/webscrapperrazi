import unittest

from scraper.core import db

T = {"tahun": 2026, "klpd_nama": "Kota Pontianak", "id_satker": 1}


def pk(kode, nama="Paket", pagu=100, jenis="penyedia", metode="Tender"):
    return {"kode_rup": kode, "tahun": 2026, "klpd_nama": "Kota Pontianak", "id_satker": 1, "jenis": jenis,
            "nama_paket": nama, "penyelenggara": None, "pagu": pagu, "metode_pemilihan": metode,
            "sumber_dana": "APBD", "waktu_pemilihan": "January 2026", "link": f"http://x/{kode}"}


def jalankan(conn, paket):
    rid = db.mulai_run(conn, 1, 2026)
    r = db.finalisasi(conn, rid, paket, 1, 2026)
    db.tutup_run(conn, rid, "success", len(paket), len(paket))
    return rid, r


class TestFinalisasi(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")

    def events(self):
        return [tuple(r) for r in self.conn.execute("SELECT jenis_event,kunci,field,nilai_lama,nilai_baru,selisih FROM paket_events ORDER BY id")]

    def test_run_pertama_baseline_tanpa_event(self):
        _, r = jalankan(self.conn, [pk("1"), pk("2")])
        self.assertTrue(r["baseline"])
        self.assertEqual(self.events(), [])

    def test_run_ulang_sama_tanpa_event_dan_tanpa_duplikat(self):
        jalankan(self.conn, [pk("1"), pk("2")])
        jalankan(self.conn, [pk("1"), pk("2")])
        self.assertEqual(self.events(), [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sirup_paket").fetchone()[0], 2)

    def test_pagu_berubah_150_ke_200(self):
        jalankan(self.conn, [pk("1", pagu=150)])
        jalankan(self.conn, [pk("1", pagu=200)])
        self.assertEqual(self.events(), [("BERUBAH", "1", "pagu", "150", "200", 50)])

    def test_baru_dan_hilang(self):
        jalankan(self.conn, [pk("1", "A"), pk("2", "B")])
        jalankan(self.conn, [pk("2", "B"), pk("3", "C")])
        jenis = sorted(e[0] for e in self.events())
        self.assertEqual(jenis, ["BARU", "HILANG"])
        self.assertEqual(self.conn.execute("SELECT is_active FROM sirup_paket WHERE kode_rup='1'").fetchone()[0], 0)

    def test_muncul_kembali(self):
        jalankan(self.conn, [pk("1"), pk("2")])
        jalankan(self.conn, [pk("2")])
        jalankan(self.conn, [pk("1"), pk("2")])
        self.assertIn("MUNCUL_KEMBALI", [e[0] for e in self.events()])

    def test_kemungkinan_revisi_kode_rup_berganti(self):
        jalankan(self.conn, [pk("1", "Jalan A"), pk("9", "Lain")])
        jalankan(self.conn, [pk("2", "Jalan  A"), pk("9", "Lain")])
        revisi = [e for e in self.events() if e[0] == "KEMUNGKINAN_REVISI"]
        self.assertEqual(revisi, [("KEMUNGKINAN_REVISI", "2", "kode_rup", "1", "2", None)])


class TestValidasi(unittest.TestCase):
    def test_jumlah_tidak_sama_dengan_situs(self):
        self.assertTrue(db.validasi([pk("1")], {"penyedia": 5}, None))

    def test_kode_ganda(self):
        self.assertTrue(db.validasi([pk("1"), pk("1")], {"penyedia": 2}, None))

    def test_penurunan_drastis_ditolak_kecuali_force(self):
        paket = [pk(str(i)) for i in range(5)]
        self.assertTrue(db.validasi(paket, {"penyedia": 5}, 100))
        self.assertFalse(db.validasi(paket, {"penyedia": 5}, 100, force=True))

    def test_valid(self):
        self.assertEqual(db.validasi([pk("1"), pk("2")], {"penyedia": 2}, 2), [])


if __name__ == "__main__":
    unittest.main()
