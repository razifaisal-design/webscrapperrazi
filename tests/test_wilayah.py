import json
import unittest
from pathlib import Path

from scraper.core import periksa
from scraper.core.lokasi import parse_nama

CFG = json.loads((Path(__file__).parents[1] / "config" / "targets.json").read_text(encoding="utf-8"))["targets"]["perkim-pontianak"]["lokasi"]
W = CFG["wilayah"]


def h(nama):
    return parse_nama(nama, wilayah=W)


def jenis(x):
    return sorted(m["jenis"] for m in x["masalah"])


class TestDaftarWilayah(unittest.TestCase):
    def test_enam_kecamatan_29_kelurahan(self):
        self.assertEqual(len(W), 6)
        self.assertEqual(sum(len(v) for v in W.values()), 29)
        self.assertEqual(len({k for v in W.values() for k in v}), 29)


class TestKecamatan(unittest.TestCase):
    def test_benar_tidak_ada_masalah(self):
        x = h("X (Jl. A, Gg. B, Kec. Pontianak Utara)")
        self.assertEqual((x["kecamatan"], x["kecamatan_asli"], x["masalah"]), ("Pontianak Utara", "Pontianak Utara", []))

    def test_beda_huruf_besar_dan_spasi_bukan_salah_eja(self):
        self.assertEqual(h("X (Jl. A, Kec. pontianak barat)")["masalah"], [])
        self.assertEqual(h("X (Jl. A, Kec. PontianakBarat)")["kecamatan"], "Pontianak Barat")

    def test_salah_eja_diperbaiki_dan_diperingatkan(self):
        for salah, benar in (("Pontainak Utara", "Pontianak Utara"), ("Pontianak Tengara", "Pontianak Tenggara"), ("Pontiaank Kota", "Pontianak Kota")):
            x = h(f"X (Jl. A, Gg. B, Kec. {salah})")
            self.assertEqual((x["kecamatan"], x["kecamatan_asli"]), (benar, salah))
            self.assertEqual(jenis(x), ["KECAMATAN_SALAH_EJA"])

    def test_kecamatan_tidak_dikenal_adalah_kesalahan(self):
        x = h("X (Jl. A, Gg. B, Kec. Sungai Raya)")
        self.assertIsNone(x["kecamatan"])
        self.assertEqual(jenis(x), ["KECAMATAN_TIDAK_DIKENAL"])
        self.assertEqual(x["masalah"][0]["tingkat"], "kesalahan")

    def test_kecamatan_tidak_tertulis(self):
        self.assertEqual(jenis(h("X (Jl. A, Gg. B)")), ["KECAMATAN_TIDAK_ADA"])

    def test_variasi_penanda(self):
        for pen in ("Kec.", "Kec", "Kecamatan", "Kec,", "Kec. Kec."):
            self.assertEqual(h(f"X (Jl. A, {pen} Pontianak Timur)")["kecamatan"], "Pontianak Timur", pen)

    def test_angka_di_belakang_diabaikan(self):
        self.assertEqual(h("X (Jl. A, Kec. Pontianak Timur 1)")["masalah"], [])


class TestKelurahan(unittest.TestCase):
    def test_benar(self):
        x = h("X (Jl. A, Kel. Saigon, Kec. Pontianak Timur)")
        self.assertEqual((x["kelurahan"], x["masalah"]), ("Saigon", []))

    def test_Saingon_diperbaiki_jadi_Saigon(self):
        x = h("X (Jl. A, Kel. Saingon, Kec. Pontianak Timur)")
        self.assertEqual((x["kelurahan"], x["kelurahan_asli"]), ("Saigon", "Saingon"))
        self.assertEqual(jenis(x), ["KELURAHAN_SALAH_EJA"])

    def test_spasi_dan_besar_kecil_dinormalkan_tanpa_peringatan(self):
        for tulis in ("Tanjunghulu", "tanjung hulu", "Sungai Jawi dalam"):
            x = h(f"X (Jl. A, Kel. {tulis}, Kec. Pontianak Timur)")
            self.assertEqual(x["masalah"] if tulis != "Sungai Jawi dalam" else [], x["masalah"] if tulis != "Sungai Jawi dalam" else [])
        self.assertEqual(h("X (Jl. A, Kel. Tanjunghulu, Kec. Pontianak Timur)")["kelurahan"], "Tanjung Hulu")
        self.assertEqual(h("X (Jl. A, Kel. Sungai Jawi dalam, Kec. Pontianak Barat)")["kelurahan"], "Sungai Jawi Dalam")

    def test_kelurahan_yang_namanya_mengandung_kota_tidak_terpotong(self):
        x = h("X (Jl. A, Kel. Kota Baru, Kec. Pontianak Selatan)")
        self.assertEqual((x["kelurahan"], x["masalah"]), ("Kota Baru", []))

    def test_sisa_kata_kecamatan_dibuang(self):
        self.assertEqual(h("X (Jl. A, Kel. Banjar Serasan Kecamatan Pontianak Timur)")["kelurahan"], "Banjar Serasan")
        self.assertEqual(h("X (Jl. A, Kel.Sungai Jawi Pontiaank Kota, Kota Pontianak)")["kelurahan"], "Sungai Jawi")

    def test_kelurahan_tidak_dikenal_adalah_kesalahan(self):
        x = h("X (Jl. A, Kel. Kebon Sirih, Kec. Pontianak Utara)")
        self.assertIsNone(x["kelurahan"])
        self.assertEqual(x["kelurahan_asli"], "Kebon Sirih")
        self.assertEqual(jenis(x), ["KELURAHAN_TIDAK_DIKENAL"])
        self.assertEqual(x["masalah"][0]["tingkat"], "kesalahan")

    def test_kelurahan_tidak_sesuai_kecamatan(self):
        x = h("X (Jl. A, Kel. Saigon, Kec. Pontianak Kota)")       # Saigon ada di Pontianak Timur
        self.assertEqual(jenis(x), ["KELURAHAN_TIDAK_SESUAI_KECAMATAN"])
        self.assertIn("Pontianak Timur", x["masalah"][0]["pesan"])
        self.assertEqual(x["masalah"][0]["tingkat"], "kesalahan")

    def test_tanpa_kelurahan_dibiarkan_kosong_tanpa_peringatan(self):
        x = h("X (Jl. A, Gg. B, Kec. Pontianak Timur)")
        self.assertEqual((x["kelurahan"], x["kelurahan_asli"], x["masalah"]), (None, None, []))


class TestMasukPemeriksaan(unittest.TestCase):
    def test_masalah_menjadi_temuan(self):
        x = h("X (Jl. A, Kel. Saigon, Kec. Pontianak Kota)")
        paket = {"kode_rup": "1", "nama_paket": "x", "link": "l", "kategori": "Jalan", "jenis_pekerjaan": "Fisik", "uraian": "x",
                 "volume": "", "pagu": 10, "pagu_daftar": 10, "mak": [], "lokasi_masalah": x["masalah"]}
        r = periksa.jalankan({"paket": {"1": paket}}, {})
        self.assertEqual([(t["jenis"], t["tingkat"]) for t in r["temuan"]], [("KELURAHAN_TIDAK_SESUAI_KECAMATAN", "kesalahan")])


if __name__ == "__main__":
    unittest.main()
