import unittest

from scraper.core import db, rekap
from scraper.core.mak import TANPA_MAK, mak_inti, norm_mak

INTI = "1.04.03.2.03.0013.5.2.04.01.001.00004"


class TestNormMak(unittest.TestCase):
    def test_segmen_setelah_ke_12_diabaikan(self):
        self.assertEqual(norm_mak(INTI + ".8.1.02.02.09.0009.00002"), INTI)
        self.assertEqual(norm_mak(INTI + ".1.3.04.01.01.0004.00299"), INTI)

    def test_titik_di_ujung_dan_spasi(self):
        self.assertEqual(norm_mak(" " + INTI + ". "), INTI)

    def test_yang_sudah_12_segmen_atau_lebih_pendek_tidak_berubah(self):
        self.assertEqual(norm_mak(INTI), INTI)
        self.assertEqual(norm_mak("1.04.02.2.05.0002.5.1.02.02.001.00051"), "1.04.02.2.05.0002.5.1.02.02.001.00051")
        self.assertEqual(norm_mak("A.1"), "A.1")

    def test_kosong(self):
        self.assertEqual(norm_mak(""), TANPA_MAK)
        self.assertEqual(norm_mak(None), TANPA_MAK)

    def test_jumlah_segmen_bisa_diatur(self):
        self.assertEqual(norm_mak("1.2.3.4.5", 3), "1.2.3")

    def test_mak_inti_menggabungkan_beberapa_mak(self):
        self.assertEqual(mak_inti(f"{INTI}.8.1; {INTI}.9.9; X.1"), f"{INTI}; X.1")


def paket(kode, pagu):
    return {"kode_rup": kode, "tahun": 2026, "klpd_nama": "K", "id_satker": 1, "jenis": "penyedia",
            "nama_paket": f"P{kode}", "penyelenggara": None, "pagu": pagu, "metode_pemilihan": "Tender",
            "sumber_dana": "APBD", "waktu_pemilihan": "Jan", "link": "x"}


def detail(rincian, mak=""):
    return {"lokasi": [], "lokasi_ringkas": "", "volume": "", "uraian": "U", "spesifikasi": "", "sumber_dana": rincian,
            "mak": mak, "total_pagu": sum(r["pagu"] for r in rincian), "extra": {}}


class TestRekapDenganMakDipotong(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)
        rid = db.mulai_run(self.conn, 1, 2026)
        db.finalisasi(self.conn, rid, [paket("1", 100), paket("2", 50), paket("3", 70)], 1, 2026)
        self.rid = db.mulai_run(self.conn, 1, 2026, "SIRUP_DETAIL")

    def test_mak_beda_suffix_digabung(self):
        db.simpan_detail(self.conn, self.rid, "1", "P1", 100, detail([{"mak": INTI + ".8.1.02.02.09.0009.00002", "pagu": 100}]))
        db.simpan_detail(self.conn, self.rid, "2", "P2", 50, detail([{"mak": INTI + ".1.3.04.01.01.0004.00299", "pagu": 50}]))
        db.simpan_detail(self.conn, self.rid, "3", "P3", 70, detail([{"mak": INTI, "pagu": 70}]))
        r = rekap.rekap_mak(self.conn, 1, 2026)
        self.assertEqual(r["jumlah_mak"], 1)
        self.assertEqual((r["per_mak"][0]["mak"], r["per_mak"][0]["jumlah_paket"], r["per_mak"][0]["total_pagu"]), (INTI, 3, 220))
        self.assertEqual(r["selisih"], 0)

    def test_paket_dengan_dua_mak_yang_sama_setelah_dipotong_dihitung_sekali_dan_dijumlah(self):
        db.simpan_detail(self.conn, self.rid, "1", "P1", 100,
                         detail([{"mak": INTI + ".8.1", "pagu": 60}, {"mak": INTI + ".9.9", "pagu": 40}]))
        r = rekap.rekap_mak(self.conn, 1, 2026)
        g = r["per_mak"][0]
        self.assertEqual((g["jumlah_paket"], g["total_pagu"]), (1, 100))
        self.assertEqual(r["paket"]["1"]["mak"], [[INTI, 100]])

    def test_perubahan_hanya_di_buntut_mak_bukan_event(self):
        d1 = detail([{"mak": INTI + ".8.1", "pagu": 100}], mak=INTI + ".8.1")
        d2 = detail([{"mak": INTI + ".9.9", "pagu": 100}], mak=INTI + ".9.9")
        db.simpan_detail(self.conn, self.rid, "1", "P1", 100, d1)
        db.simpan_detail(self.conn, self.rid, "1", "P1", 100, d2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM paket_events WHERE field='detail.mak'").fetchone()[0], 0)
        d3 = detail([{"mak": "LAIN.1", "pagu": 100}], mak="LAIN.1")
        db.simpan_detail(self.conn, self.rid, "1", "P1", 100, d3)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM paket_events WHERE field='detail.mak'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
