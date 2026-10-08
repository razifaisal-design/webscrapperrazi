import unittest

from scraper.core import kegiatan

J = "1.04.05.2.01.0012.5.2.04.01.001.00004"
S = "1.04.05.2.01.0011.5.2.04.02.002.00004"
ATURAN = {"mak_kategori": [
    {"awalan": "1.04.05.2.01.0012", "kategori": "Jalan", "mak_baku": J},
    {"awalan": "1.04.05.2.01.0011", "kategori": "Saluran", "mak_baku": S}]}


def p(kode, kat, mak, jp="Fisik"):
    return {"kode_rup": kode, "kategori": kat, "jenis_pekerjaan": jp, "mak": [[m, v] for m, v in mak]}


def jalankan(*paket):
    data = {"paket": {x["kode_rup"]: x for x in paket}}
    kegiatan.tambahkan(data, ATURAN)
    return data


class TestJenisKegiatan(unittest.TestCase):
    def test_jalan_dengan_mak_jalan(self):
        x = jalankan(p("1", "Jalan", [(J, 100)]))["paket"]["1"]
        self.assertEqual((x["jenis_kegiatan"], x["status_mak"], x["jenis_perbaikan"], x["mak_perbaikan"]),
                         ("Jalan", "Sesuai", None, []))

    def test_saluran_dengan_mak_saluran(self):
        x = jalankan(p("1", "Saluran", [(S, 100)]))["paket"]["1"]
        self.assertEqual((x["jenis_kegiatan"], x["status_mak"]), ("Saluran", "Sesuai"))

    def test_saluran_di_mak_jalan_dibuatkan_perbaikan(self):
        x = jalankan(p("1", "Saluran", [(J, 100)]))["paket"]["1"]
        self.assertEqual(x["status_mak"], "Salah MAK")
        self.assertEqual(x["jenis_kegiatan"], "Jalan")           # sesuai MAK yang tercatat
        self.assertEqual(x["jenis_perbaikan"], "Saluran")        # yang seharusnya
        self.assertEqual(x["mak_perbaikan"], [S])
        self.assertEqual(x["mak_akhir"], [S])

    def test_jalan_di_mak_saluran_dibuatkan_perbaikan(self):
        x = jalankan(p("1", "Jalan", [(S, 100)]))["paket"]["1"]
        self.assertEqual((x["jenis_kegiatan"], x["jenis_perbaikan"], x["mak_perbaikan"]), ("Saluran", "Jalan", [J]))

    def test_paket_dua_mak_hanya_yang_salah_diperbaiki(self):
        x = jalankan(p("1", "Saluran", [(S, 60), (J, 40)]))["paket"]["1"]
        self.assertEqual(x["mak_perbaikan"], [S])
        self.assertEqual(x["mak_akhir"], [S])                     # dua-duanya jadi MAK Saluran
        self.assertEqual([e["status"] for e in x["mak_entri"]], ["Sesuai", "Salah MAK"])

    def test_konsultan_diberi_awalan(self):
        d = jalankan(p("1", "Jalan", [(J, 100)], "Konsultan"), p("2", "Saluran", [(J, 50)], "Konsultan"))["paket"]
        self.assertEqual(d["1"]["jenis_kegiatan"], "Konsultan Jalan")
        self.assertEqual((d["2"]["jenis_kegiatan"], d["2"]["jenis_perbaikan"]), ("Konsultan Jalan", "Konsultan Saluran"))

    def test_lainnya_tidak_dinilai(self):
        x = jalankan(p("1", "Lainnya", [(J, 100)]))["paket"]["1"]
        self.assertEqual((x["status_mak"], x["jenis_kegiatan"], x["mak_perbaikan"]), ("Tidak dinilai", "Lainnya", []))

    def test_mak_belum_dipetakan_tidak_diperbaiki(self):
        x = jalankan(p("1", "Jalan", [("1.04.03.2.03.0013.5.2", 100)]))["paket"]["1"]
        self.assertEqual((x["status_mak"], x["mak_perbaikan"]), ("MAK belum dipetakan", []))


class TestTanpaPemetaan(unittest.TestCase):
    def test_tanpa_pemetaan_semua_dianggap_tidak_dinilai_dan_tidak_diperbaiki(self):
        data = {"paket": {"1": p("1", "Saluran", [(J, 100)])}}
        kegiatan.tambahkan(data, {})
        x = data["paket"]["1"]
        self.assertEqual((x["status_mak"], x["jenis_kegiatan"], x["mak_perbaikan"], x["mak_akhir"]), ("Tidak dinilai", "Saluran", [], [J]))


class TestRekapPerbaikan(unittest.TestCase):
    def test_tercatat_vs_seharusnya_dan_total_tetap(self):
        d = jalankan(p("1", "Jalan", [(J, 100)]), p("2", "Saluran", [(J, 40)]), p("3", "Saluran", [(S, 60)]))
        r = {b["mak"]: b for b in d["perbaikan"]["Semua"]["mak"]}
        self.assertEqual((r[J]["tercatat_pagu"], r[J]["seharusnya_pagu"], r[J]["selisih_pagu"]), (140, 100, -40))
        self.assertEqual((r[S]["tercatat_pagu"], r[S]["seharusnya_pagu"], r[S]["selisih_pagu"]), (60, 100, 40))
        self.assertEqual(d["perbaikan"]["Semua"]["total_tercatat"], d["perbaikan"]["Semua"]["total_seharusnya"])
        self.assertTrue(d["perbaikan"]["Semua"]["ada_perbaikan"])

    def test_filter_fisik_dan_konsultan_terpisah(self):
        d = jalankan(p("1", "Jalan", [(J, 100)]), p("2", "Jalan", [(J, 30)], "Konsultan"))
        self.assertEqual(d["perbaikan"]["Fisik"]["total_tercatat"], 100)
        self.assertEqual(d["perbaikan"]["Konsultan"]["total_tercatat"], 30)
        self.assertEqual(d["perbaikan"]["Semua"]["total_tercatat"], 130)
        self.assertFalse(d["perbaikan"]["Konsultan"]["ada_perbaikan"])


if __name__ == "__main__":
    unittest.main()
