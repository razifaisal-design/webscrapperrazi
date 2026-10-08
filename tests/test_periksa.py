import unittest

from scraper.core import periksa

J = "1.04.05.2.01.0012.5.2.04.01.001.00004"
S = "1.04.05.2.01.0011.5.2.04.02.002.00004"
ATURAN = {"mak_kategori": [{"awalan": "1.04.05.2.01.0012", "kategori": "Jalan"},
                           {"awalan": "1.04.05.2.01.0011", "kategori": "Saluran"}],
          "satuan_salah": {"Jalan": ["M1"], "Saluran": ["M2"]}}


def p(kode, kategori, mak, nama=None, uraian=None, pagu=100, volume="1 Paket", pagu_daftar=None, jenis="Fisik"):
    nama = nama or f"Paket {kode}"
    return {"kode_rup": kode, "nama_paket": nama, "link": "x", "kategori": kategori, "jenis_pekerjaan": jenis,
            "uraian": uraian or nama, "volume": volume, "pagu": pagu,
            "pagu_daftar": pagu if pagu_daftar is None else pagu_daftar,
            "mak": [[m, v] for m, v in mak]}


def hitung(*paket, aturan=ATURAN):
    return periksa.jalankan({"paket": {x["kode_rup"]: x for x in paket}}, aturan)


def jenis(h):
    return sorted((t["jenis"], t["kode_rup"]) for t in h["temuan"])


class TestMakKategori(unittest.TestCase):
    def test_saluran_di_mak_jalan_adalah_kesalahan(self):
        h = hitung(p("1", "Saluran", [(J, 100)]))
        self.assertEqual(jenis(h), [("MAK_TIDAK_SESUAI", "1")])
        self.assertEqual(h["temuan"][0]["tingkat"], "kesalahan")
        self.assertEqual(h["jumlah_kesalahan"], 1)

    def test_jalan_di_mak_saluran_adalah_kesalahan(self):
        self.assertEqual(jenis(hitung(p("1", "Jalan", [(S, 100)]))), [("MAK_TIDAK_SESUAI", "1")])

    def test_yang_benar_tidak_ditandai(self):
        h = hitung(p("1", "Jalan", [(J, 100)]), p("2", "Saluran", [(S, 100)]))
        self.assertEqual(h["temuan"], [])

    def test_paket_dua_mak_hanya_mak_yang_salah_ditandai_dengan_nilainya(self):
        h = hitung(p("1", "Saluran", [(S, 60), (J, 40)]))
        self.assertEqual([(t["jenis"], t["pagu"]) for t in h["temuan"]], [("MAK_TIDAK_SESUAI", 40)])

    def test_awalan_harus_berhenti_di_batas_titik(self):
        # ...0012 tidak boleh cocok dengan sub kegiatan ...00120
        self.assertEqual(jenis(hitung(p("1", "Saluran", [("1.04.05.2.01.00120.5", 100)]))),
                         [("MAK_BELUM_DIPETAKAN", "1")])

    def test_mak_belum_dipetakan_adalah_peringatan_bukan_kesalahan(self):
        h = hitung(p("1", "Jalan", [("1.04.03.2.03.0013.5.2", 100)]))
        self.assertEqual((h["jumlah_kesalahan"], h["jumlah_peringatan"]), (0, 1))

    def test_kategori_lainnya_tidak_diperiksa_terhadap_mak(self):
        self.assertEqual(hitung(p("1", "Lainnya", [(J, 100)]))["temuan"], [])

    def test_tanpa_pemetaan_tidak_ada_temuan_mak_dan_tidak_ada_matriks(self):
        h = hitung(p("1", "Saluran", [(J, 100)]), aturan={})
        self.assertEqual(h["temuan"], [])
        self.assertIsNone(h["matriks"])

    def test_matriks_rekonsiliasi(self):
        h = hitung(p("1", "Jalan", [(J, 100)]), p("2", "Saluran", [(J, 40)]), p("3", "Saluran", [(S, 60)]))
        n = h["matriks"]["nilai"]
        self.assertEqual(n["Jalan"]["Jalan"], {"pagu": 100, "paket": 1})
        self.assertEqual(n["Saluran"]["Jalan"], {"pagu": 40, "paket": 1})   # Saluran tercatat di MAK Jalan
        self.assertEqual(n["Saluran"]["Saluran"], {"pagu": 60, "paket": 1})


class TestCekLain(unittest.TestCase):
    def test_nama_dan_uraian_bertentangan(self):
        h = hitung(p("1", "Jalan", [(J, 100)], nama="Pengawasan PSU Jalan Tahun 2026", uraian="Pengawasan Saluran"))
        self.assertEqual(jenis(h), [("NAMA_URAIAN_BERTENTANGAN", "1")])

    def test_nama_jalan_di_dalam_kurung_bukan_jenis_pekerjaan(self):
        # Saluran yang berada di (Jalan Berdikari) bukan 'bertentangan'
        h = hitung(p("1", "Saluran", [(S, 100)], nama="Belanja Modal Saluran Pembuang (Jalan Berdikari)", uraian="Pekerjaan Saluran"))
        self.assertEqual(h["temuan"], [])

    def test_satuan_bertentangan(self):
        self.assertEqual(jenis(hitung(p("1", "Jalan", [(J, 100)], volume="525,06 M1"))), [("SATUAN_BERTENTANGAN", "1")])
        self.assertEqual(jenis(hitung(p("2", "Saluran", [(S, 100)], volume="62,8 M2"))), [("SATUAN_BERTENTANGAN", "2")])

    def test_satuan_paket_atau_cocok_tidak_ditandai(self):
        h = hitung(p("1", "Jalan", [(J, 100)], volume="525,06 M2"), p("2", "Jalan", [(J, 100)], volume="1 Paket"))
        self.assertEqual(h["temuan"], [])

    def test_pagu_detail_beda_dengan_daftar(self):
        h = hitung(p("1", "Jalan", [(J, 90)], pagu=90, pagu_daftar=100))
        self.assertEqual(jenis(h), [("PAGU_TIDAK_SAMA", "1")])

    def test_tanpa_mak(self):
        self.assertEqual(jenis(hitung(p("1", "Lainnya", [("(tanpa MAK)", 100)]))), [("TANPA_MAK", "1")])

    def test_kemungkinan_ganda(self):
        a = p("1", "Jalan", [(J, 100)], nama="Pengawasan PSU Jalan Timur (Tahap 2)")
        b = p("2", "Jalan", [(J, 100)], nama="Pengawasan PSU Jalan Timur - (Tahap 2)")
        c = p("3", "Jalan", [(J, 100)], nama="Pengawasan PSU Jalan Barat (Tahap 2)")
        self.assertEqual(jenis(hitung(a, b, c)), [("KEMUNGKINAN_GANDA", "1"), ("KEMUNGKINAN_GANDA", "2")])

    def test_nama_sama_tapi_pagu_atau_mak_beda_bukan_ganda(self):
        a = p("1", "Lainnya", [("X", 100)], nama="Fotocopy")
        b = p("2", "Lainnya", [("Y", 100)], nama="Fotocopy")
        c = p("3", "Lainnya", [("X", 200)], nama="Fotocopy", pagu=200)
        self.assertEqual(hitung(a, b, c)["temuan"], [])


if __name__ == "__main__":
    unittest.main()
