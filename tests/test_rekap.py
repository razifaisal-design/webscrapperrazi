import json
import unittest

from scraper.core import db, rekap


def paket(kode, pagu, jenis="penyedia"):
    return {"kode_rup": kode, "tahun": 2026, "klpd_nama": "K", "id_satker": 1, "jenis": jenis,
            "nama_paket": f"Paket {kode}", "penyelenggara": None, "pagu": pagu, "metode_pemilihan": "Tender",
            "sumber_dana": "APBD", "waktu_pemilihan": "Jan", "link": f"http://x/{kode}"}


def detail(rincian, uraian=""):
    return {"lokasi": [], "lokasi_ringkas": "", "volume": "", "uraian": uraian, "spesifikasi": "",
            "sumber_dana": rincian, "mak": "", "total_pagu": sum(r["pagu"] for r in rincian), "extra": {}}


class TestRekap(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)
        rid = db.mulai_run(self.conn, 1, 2026)
        self.semua = [paket("1", 100), paket("2", 50), paket("3", 70), paket("4", 999), paket("5", 10)]
        db.finalisasi(self.conn, rid, self.semua, 1, 2026)
        self.rid = db.mulai_run(self.conn, 1, 2026, "SIRUP_DETAIL")

    def isi(self, kode, rincian, uraian=""):
        p = next(x for x in self.semua if x["kode_rup"] == kode)
        db.simpan_detail(self.conn, self.rid, kode, p["nama_paket"], p["pagu"], detail(rincian, uraian))

    def test_jumlah_pagu_per_mak_sama_dan_hanya_yang_ber_detail(self):
        self.isi("1", [{"mak": "A.1.", "pagu": 100}])
        self.isi("2", [{"mak": "A.1", "pagu": 50}])          # titik di ujung beda -> MAK yang sama
        self.isi("3", [{"mak": "B.2", "pagu": 70}])
        # paket 4 (pagu 999) tidak punya detail -> tidak boleh ikut dihitung
        r = rekap.rekap_mak(self.conn, 1, 2026)
        self.assertEqual(r["paket_aktif"], 5)
        self.assertEqual(r["paket_dengan_detail"], 3)
        self.assertEqual(r["jumlah_mak"], 2)
        mak = {g["mak"]: g for g in r["per_mak"]}
        self.assertEqual(mak["A.1"]["total_pagu"], 150)
        self.assertEqual(mak["A.1"]["jumlah_paket"], 2)
        self.assertEqual(mak["B.2"]["total_pagu"], 70)
        self.assertEqual(r["total_pagu_mak"], 220)
        self.assertEqual(r["selisih"], 0)
        self.assertEqual(r["per_mak"][0]["mak"], "A.1")      # urut pagu terbesar

    def test_paket_dengan_dua_mak_dipecah_per_mak(self):
        self.isi("1", [{"mak": "A.1", "pagu": 60}, {"mak": "B.2", "pagu": 40}])
        r = rekap.rekap_mak(self.conn, 1, 2026)
        mak = {g["mak"]: g for g in r["per_mak"]}
        self.assertEqual((mak["A.1"]["total_pagu"], mak["B.2"]["total_pagu"]), (60, 40))
        self.assertEqual(r["paket_dengan_detail"], 1)        # tetap 1 paket
        self.assertEqual(r["selisih"], 0)

    def test_detail_gagal_dan_paket_nonaktif_tidak_dihitung(self):
        self.isi("1", [{"mak": "A", "pagu": 100}])
        db.catat_gagal_detail(self.conn, "2", "rusak")
        self.isi("5", [{"mak": "Z", "pagu": 10}])
        rid = db.mulai_run(self.conn, 1, 2026)
        db.finalisasi(self.conn, rid, [x for x in self.semua if x["kode_rup"] != "5"], 1, 2026)  # 5 hilang
        r = rekap.rekap_mak(self.conn, 1, 2026)
        self.assertEqual(r["paket_dengan_detail"], 1)
        self.assertEqual([g["mak"] for g in r["per_mak"]], ["A"])

    def test_tanpa_mak(self):
        self.isi("1", [])
        r = rekap.rekap_mak(self.conn, 1, 2026)
        self.assertEqual(r["per_mak"][0]["mak"], rekap.TANPA_MAK)
        self.assertEqual(r["per_mak"][0]["total_pagu"], 100)

    def test_selisih_terdeteksi_bila_tidak_sejalan(self):
        self.isi("1", [{"mak": "A", "pagu": 90}])           # daftar 100, detail 90
        self.assertEqual(rekap.rekap_mak(self.conn, 1, 2026)["selisih"], -10)

    def test_rekap_per_uraian_dan_kategori(self):
        self.semua[0]["nama_paket"] = "Belanja Modal Jalan Kota (Jl. A)"          # kode 1, pagu 100
        self.semua[1]["nama_paket"] = "Belanja Modal Saluran Pembuang X"          # kode 2, pagu 50
        self.semua[2]["nama_paket"] = "Pengawasan PSU Jalan 2026"                 # kode 3, pagu 70
        rid = db.mulai_run(self.conn, 1, 2026)
        db.finalisasi(self.conn, rid, self.semua, 1, 2026)
        self.isi("1", [{"mak": "A", "pagu": 100}], "Pekerjaan Jalan;")
        self.isi("2", [{"mak": "B", "pagu": 50}], "Pekerjaan Saluran")
        self.isi("3", [{"mak": "C", "pagu": 70}], "Pengawasan Jalan")
        self.isi("5", [{"mak": "D", "pagu": 10}], "Fotocopy")
        aturan = {"kategori": [
            {"nama": "Jalan", "cocok": {"nama_paket": "(?i)^Belanja Modal Jalan Kota"}},
            {"nama": "Saluran", "cocok": {"nama_paket": "(?i)^Belanja Modal Saluran Pembuang"}},
            {"nama": "Jalan", "cocok": {"teks": "(?i)^(?=.*pengawasan)(?=.*\\bjalan\\b)(?!.*saluran)"}}],
            "konsultan": "(?i)pengawasan"}
        r = rekap.rekap_mak(self.conn, 1, 2026, aturan)
        self.assertEqual({g["uraian"]: g["total_pagu"] for g in r["per_uraian"]},
                         {"Pekerjaan Jalan": 100, "Pekerjaan Saluran": 50, "Pengawasan Jalan": 70, "Fotocopy": 10})
        k = r["klasifikasi"]
        self.assertEqual((k["Jalan"]["total_pagu"], k["Jalan"]["jumlah_paket"]), (170, 2))
        self.assertEqual((k["Jalan"]["Fisik"]["total_pagu"], k["Jalan"]["Konsultan"]["total_pagu"]), (100, 70))
        self.assertEqual(k["Saluran"]["total_pagu"], 50)
        self.assertEqual(k["Lainnya"]["total_pagu"], 10)
        self.assertEqual(sum(g["total_pagu"] for g in k.values()), r["total_pagu_mak"])  # tidak ada yang hilang/ganda
        self.assertEqual(r["selisih"], 0)

    def test_tanpa_aturan_tidak_ada_klasifikasi(self):
        self.isi("1", [{"mak": "A", "pagu": 100}])
        self.assertIsNone(rekap.rekap_mak(self.conn, 1, 2026)["klasifikasi"])


if __name__ == "__main__":
    unittest.main()
