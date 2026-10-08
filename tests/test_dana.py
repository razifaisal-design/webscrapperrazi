import unittest

from scraper.core import dana, db
from scraper.sources import sirup

T = {"tahun": 2026, "klpd_nama": "K", "id_satker": 1}


class TestKanon(unittest.TestCase):
    def test_pengulangan_jadi_satu(self):
        for mentah, hasil in (("APBD", "APBD"), ("APBD, APBD", "APBD"), ("APBD,APBD,APBD,", "APBD"), ("APBDP, APBDP", "APBDP"),
                              ("APBD, APBD, APBD, APBD, APBD, APBD, APBD, APBD, APBD, APBD, APBD", "APBD"), ("", ""), (None, "")):
            self.assertEqual(dana.kanon(mentah), hasil, mentah)

    def test_tidak_pernah_berkoma(self):
        for mentah in ("APBD, APBDP", "APBD,APBD,APBDP,", "APBDP, APBD, APBD", "APBD,APBD,APBD,APBD,APBDP,APBDP,APBDP,APBDP,"):
            self.assertNotIn(",", dana.kanon(mentah))
            self.assertIn(dana.kanon(mentah), ("APBD", "APBDP"))

    def test_campuran_dipilih_yang_terbanyak_seri_yang_pertama(self):
        self.assertEqual(dana.kanon("APBD, APBD, APBDP"), "APBD")
        self.assertEqual(dana.kanon("APBDP, APBDP, APBD"), "APBDP")
        self.assertEqual(dana.kanon("APBDP, APBD"), "APBDP")

    def test_himpunan_dan_dominan_dari_rincian_menurut_pagu(self):
        self.assertEqual(dana.himpunan("APBD, APBDP, APBD"), ["APBD", "APBDP"])
        rincian = [{"sumber_dana": "APBD", "pagu": 10}, {"sumber_dana": "APBDP", "pagu": 90}, {"sumber_dana": "APBD", "pagu": 20}]
        self.assertEqual(dana.dominan(rincian), ("APBDP", ["APBD", "APBDP"]))          # menurut PAGU, bukan jumlah baris
        self.assertEqual(dana.dominan([]), ("", []))


class TestScraperDanMigrasi(unittest.TestCase):
    def test_baris_baru_langsung_rapi(self):
        p = sirup.parse_baris("penyedia", ["1", "X", "100", "Tender", "APBD, APBD, APBD", "1", "Jan"], T)
        self.assertEqual(p["sumber_dana"], "APBD")
        s = sirup.parse_baris("swakelola", ["2", "Peny", "Y", "50", "APBDP,APBDP,", "2", "Feb"], T)
        self.assertEqual(s["sumber_dana"], "APBDP")

    def test_data_lama_berkoma_dirapikan_saat_database_dibuka(self):
        import os, sqlite3, tempfile
        f = os.path.join(tempfile.mkdtemp(), "lama.db")
        conn = db.buka(f)
        conn.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,sumber_dana,pagu,is_active) VALUES('1',2025,1,'APBD, APBD, APBD',5,1)")
        conn.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,sumber_dana,pagu,is_active) VALUES('2',2025,1,'APBDP,APBDP,',5,1)")
        conn.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,sumber_dana,pagu,is_active) VALUES('3',2025,1,'APBD',5,1)")
        conn.commit(); conn.close()
        conn = db.buka(f)
        self.addCleanup(conn.close)
        self.assertEqual([r[0] for r in conn.execute("SELECT sumber_dana FROM sirup_paket ORDER BY kode_rup")], ["APBD", "APBDP", "APBD"])

    def test_pengambilan_ulang_tidak_dianggap_perubahan_setelah_dirapikan(self):
        conn = db.buka(":memory:")
        self.addCleanup(conn.close)
        def p(dana_mentah):
            x = sirup.parse_baris("penyedia", ["1", "X", "100", "Tender", dana_mentah, "1", "Jan"], T)
            return x
        rid = db.mulai_run(conn, 1, 2026); db.finalisasi(conn, rid, [p("APBD, APBD")], 1, 2026); db.tutup_run(conn, rid, "success", 1, 1)
        rid = db.mulai_run(conn, 1, 2026); db.finalisasi(conn, rid, [p("APBD,APBD,APBD")], 1, 2026)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM paket_events").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
