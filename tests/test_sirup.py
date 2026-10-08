import unittest

from scraper.sources import sirup

T = {"tahun": 2026, "klpd_nama": "Kota Pontianak", "id_satker": 173394}


class TestParse(unittest.TestCase):
    def test_penyedia(self):
        p = sirup.parse_baris("penyedia", ["62728266", "Fotocopy", "8915000", "E-Purchasing", "APBD", "62728266", "January 2026"], T)
        self.assertEqual(p["kode_rup"], "62728266")
        self.assertEqual(p["pagu"], 8915000)
        self.assertEqual(p["metode_pemilihan"], "E-Purchasing")
        self.assertEqual(p["link"], "https://sirup.inaproc.id/sirup/home/detailPaketPenyediaPublic2017/62728266")

    def test_swakelola(self):
        p = sirup.parse_baris("swakelola", ["42529798", "Administrasi Umum", "Belanja Perjalanan  Dinas", "60000000", "APBD", "42529798", "February 2026"], T)
        self.assertEqual(p["nama_paket"], "Belanja Perjalanan Dinas")
        self.assertEqual(p["penyelenggara"], "Administrasi Umum")
        self.assertEqual(p["metode_pemilihan"], "Swakelola")
        self.assertTrue(p["link"].endswith("detailPaketSwakelolaPublic2017?idPaket=42529798"))

    def test_kode_tidak_valid(self):
        with self.assertRaises(ValueError):
            sirup.parse_baris("penyedia", ["abc", "x", "1", "m", "APBD", "abc", "Jan"], T)


if __name__ == "__main__":
    unittest.main()
