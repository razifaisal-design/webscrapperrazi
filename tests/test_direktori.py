import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scraper import konfig, tugas
from scraper.sources import direktori

DAFTAR = [
    {"id": 173394, "nama": "DINAS PERUMAHAN RAKYAT DAN KAWASAN PERMUKIMAN", "paket": 976},
    {"id": 173393, "nama": "DINAS PEKERJAAN UMUM DAN PENATAAN RUANG", "paket": 698},
    {"id": 76518, "nama": "DINAS KESEHATAN", "paket": 639},
    {"id": 173391, "nama": "DINAS KESEHATAN", "paket": 188},
    {"id": 173412, "nama": "KECAMATAN PONTIANAK BARAT", "paket": 352},
]


class KlienDirektori:
    def __init__(self):
        self.url = []

    def close(self):
        pass

    def get_json(self, url, params=None):
        self.url.append((url.rsplit("/", 1)[-1], params))
        if url.endswith("datatablerupkldi2"):
            kat = {"KOTA": [["D199", "Kota Pontianak", "8993"]], "KABUPATEN": [["D1", "Kabupaten Kubu Raya", "10"]]}.get(params["jenisID"], [])
            return {"aaData": kat}
        if url.endswith("datatableruprekapkldi"):
            return {"aaData": [[str(s["id"]), s["nama"], "0", "0", "0", "0", "0", "0", str(s["paket"]), "0", "false", "0"] for s in DAFTAR]}
        raise AssertionError(url)


class TestDirektori(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(direktori.norm(" Dinas  Perumahan, Rakyat & Kawasan-Permukiman "), "DINAS PERUMAHAN RAKYAT KAWASAN PERMUKIMAN")

    def test_cari_nama_persis_mengandung_mirip(self):
        h = direktori.cari_nama(DAFTAR, "dinas perumahan rakyat dan kawasan permukiman")
        self.assertEqual((h[0]["id"], h[0]["cocok"]), (173394, "persis"))
        self.assertEqual(direktori.cari_nama(DAFTAR, "perumahan")[0]["id"], 173394)             # kata kunci cukup
        self.assertEqual(direktori.cari_nama(DAFTAR, "perumahan")[0]["cocok"], "mengandung")
        self.assertEqual(direktori.cari_nama(DAFTAR, "DINAS PERUMAHAN RAKYAT DAN KAWASAN PEMUKIMAN")[0]["cocok"], "mirip")   # salah ketik tahun lama
        self.assertEqual(direktori.cari_nama(DAFTAR, "nama yang tidak ada sama sekali"), [])
        self.assertEqual(direktori.cari_nama(DAFTAR, ""), [])

    def test_id_untuk_tahun_satker_kembar_pilih_paket_terbanyak(self):
        self.assertEqual(direktori.id_untuk_tahun(DAFTAR, "DINAS KESEHATAN"), (76518, [173391]))
        self.assertEqual(direktori.id_untuk_tahun(DAFTAR, "Dinas Antah Berantah"), (None, []))

    def test_cari_klpd_dan_daftar_satker(self):
        k = KlienDirektori()
        self.assertEqual(direktori.cari_klpd(k, "kota pontianak", 2026)["id"], "D199")
        self.assertIsNone(direktori.cari_klpd(k, "Kota Tidak Ada", 2026))
        self.assertEqual([s["id"] for s in direktori.daftar_satker(k, "D199", 2026)][:2], [173394, 173393])


class TestKonfigTambah(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        asal = json.loads(konfig.TARGETS.read_text(encoding="utf-8"))
        self.path = Path(self.tmp.name) / "targets.json"
        self.path.write_text(json.dumps(asal), encoding="utf-8")
        p = mock.patch.object(konfig, "TARGETS", self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_tambah_satker_baru_mewarisi_wilayah_dan_terdaftar(self):
        kunci = konfig.tambah_target("DINAS PEKERJAAN UMUM DAN PENATAAN RUANG", "Kota Pontianak", "D199", 173393, {"2021": 70859, "2022": 173393})
        _, t = konfig.muat_target(kunci, 2021)
        self.assertEqual((t["satker_nama"], t["id_satker"], t["id_satker_semua"]), ("DINAS PEKERJAAN UMUM DAN PENATAAN RUANG", 70859, [70859, 173393]))
        self.assertTrue(t["umum"])
        self.assertNotIn("klasifikasi", t)                                  # aturan Jalan/Saluran khusus Perkim tidak ikut
        self.assertIn("wilayah", t["lokasi"])
        self.assertEqual({d["satker_nama"] for d in konfig.daftar_target()}, {"DINAS PERUMAHAN RAKYAT DAN KAWASAN PERMUKIMAN", "DINAS PEKERJAAN UMUM DAN PENATAAN RUANG"})
        self.assertIn("DINAS PEKERJAAN UMUM DAN PENATAAN RUANG", konfig.satker_sirup())
        self.assertEqual(konfig.muat_target("perkim-pontianak")[1]["satker_nama"], "DINAS PERUMAHAN RAKYAT DAN KAWASAN PERMUKIMAN")   # target lama utuh

    def test_tambah_dua_kali_tidak_menggandakan(self):
        a = konfig.tambah_target("DINAS KESEHATAN", "Kota Pontianak", "D199", 173391)
        b = konfig.tambah_target("Dinas  Kesehatan", "kota pontianak", "D199", 173391, {"2021": 76518})
        self.assertEqual(a, b)
        self.assertEqual(len(konfig.daftar_target()), 2)
        self.assertEqual(konfig.muat_target(a, 2021)[1]["id_satker"], 76518)

    def test_nama_target_ikut_di_hasil_muat(self):
        self.assertEqual(konfig.muat_target("perkim-pontianak")[1]["nama"], "perkim-pontianak")


class TestCariTambahSatker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "targets.json"
        self.path.write_text(konfig.TARGETS.read_text(encoding="utf-8"), encoding="utf-8")
        p = mock.patch.object(konfig, "TARGETS", self.path)
        p.start()
        self.addCleanup(p.stop)
        self.k = KlienDirektori()

    def buat(self, jeda=1.0):
        return self.k

    def test_cari_tanpa_id_untuk_pengguna(self):
        h = tugas.cari_satker_nama("pekerjaan umum", buat_klien=self.buat)
        self.assertEqual((h["klpd"], h["kandidat"][0]["nama"]), ("Kota Pontianak", "DINAS PEKERJAAN UMUM DAN PENATAAN RUANG"))
        self.assertNotIn("id", h["kandidat"][0])
        self.assertFalse(any(u[0] == "datatablerupkldi2" for u in self.k.url))        # klpd_id sudah ada di config: tidak perlu mencari lagi

    def test_tambah_nama_persis_dan_sebagian_unik(self):
        kunci, resmi = tugas.tambah_satker_nama("dinas pekerjaan umum dan penataan ruang", buat_klien=self.buat)
        self.assertEqual(resmi, "DINAS PEKERJAAN UMUM DAN PENATAAN RUANG")
        self.assertEqual(konfig.muat_target(kunci)[1]["id_satker"], 173393)
        kunci2, _ = tugas.tambah_satker_nama("pontianak barat", buat_klien=self.buat)             # hanya satu kandidat
        self.assertNotEqual(kunci, kunci2)

    def test_tambah_nama_ambigu_atau_tidak_ada_ditolak(self):
        with self.assertRaises(ValueError) as e:
            tugas.tambah_satker_nama("dinas", buat_klien=self.buat)
        self.assertIn("cocok dengan", str(e.exception))
        with self.assertRaises(ValueError):
            tugas.tambah_satker_nama("zzzz tidak ada", buat_klien=self.buat)
        self.assertEqual(len(konfig.daftar_target()), 1)                                           # gagal = config tidak berubah

    def test_satker_kembar_nama_pilih_paket_terbanyak(self):
        kunci, _ = tugas.tambah_satker_nama("DINAS KESEHATAN", buat_klien=self.buat)
        self.assertEqual(konfig.muat_target(kunci)[1]["id_satker"], 76518)


class TestTentukanIdDariDirektori(unittest.TestCase):
    def test_id_tahun_ini_diambil_dari_direktori_menurut_nama(self):
        import sqlite3
        from scraper.core import db
        conn = db.buka(":memory:")
        target = {"id_satker": 173394, "id_satker_semua": [173394], "tahun": 2021, "satker_nama": "DINAS PERUMAHAN RAKYAT DAN KAWASAN PEMUKIMAN",
                  "klpd_id": "D199"}
        sirup_total = []

        def total(client, jenis, t):
            sirup_total.append(t["id_satker"])
            return 5 if t["id_satker"] == 69427 else 0

        class K(KlienDirektori):
            def get_json(self, url, params=None):
                if url.endswith("datatableruprekapkldi"):
                    return {"aaData": [["69427", "DINAS PERUMAHAN RAKYAT DAN KAWASAN PEMUKIMAN", "0", "0", "0", "0", "0", "0", "1233", "0", "false", "0"]]}
                return super().get_json(url, params)

        with mock.patch.object(tugas.sirup, "total_paket", total):
            sat, diganti = tugas.tentukan_id_satker(conn, target, K(), log=lambda *a: None)
        self.assertEqual((sat, diganti), (69427, True))
        self.assertEqual(sirup_total[0], 69427)                              # id dari direktori diuji lebih dulu, tanpa menebak


if __name__ == "__main__":
    unittest.main()
