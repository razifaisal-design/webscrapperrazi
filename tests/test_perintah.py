import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scraper import perintah, sinkron, tugas
import tests.test_web as _tw


class TestKatalog(unittest.TestCase):
    def test_semua_perintah_punya_penjelasan_lengkap(self):
        ids = [p["id"] for p in perintah.DAFTAR]
        self.assertEqual(len(ids), len(set(ids)))
        for p in perintah.DAFTAR:
            for k in ("nama", "fungsi", "kapan", "waktu", "mengubah", "kelompok", "jenis"):
                self.assertTrue(p.get(k), (p["id"], k))
            self.assertIn(p["jenis"], ("perintah", "semua", "spse_semua", "banding_periksa"))

    def test_validasi_menyaring_opsi(self):
        self.assertEqual(perintah.validasi("perbarui", {"tahun": "2025", "koneksi": 3, "jeda": 2, "unggah": 1, "asing": "x"}),
                         {"tahun": 2025, "koneksi": 3, "jeda": 2.0, "unggah": True})
        with self.assertRaises(ValueError):
            perintah.validasi("perbarui", {"koneksi": 99})                 # di luar pilihan
        with self.assertRaises(ValueError):
            perintah.validasi("rm -rf", {})                                # id tidak dikenal
        with self.assertRaises(ValueError):
            perintah.validasi("tarik", {})                                 # menimpa database: wajib konfirmasi
        self.assertTrue(perintah.validasi("tarik", {"konfirmasi": True})["konfirmasi"])
        with self.assertRaises(ValueError):
            perintah.validasi("lokasi", {"tahun": 1800})

    def test_kesiapan_menjelaskan_alasan(self):
        with mock.patch("scraper.sinkron.url_db", lambda *a, **k: None):
            m = {p["id"]: p for p in perintah.metadata()}
        self.assertFalse(m["sinkron"]["siap"])
        self.assertIn("SUPABASE_DB_URL", m["sinkron"]["alasan_belum_siap"])
        self.assertTrue(m["lokasi"]["siap"])


class TestJalankan(unittest.TestCase):
    def jalan(self, id_, opsi=None, **tambahan):
        logs = []
        kode = perintah.jalankan(id_, opsi or {}, "x.db", logs.append, **tambahan)
        return kode, logs

    def test_sinkron_sukses_dan_gagal_dilaporkan_tanpa_melempar(self):
        with mock.patch.object(sinkron, "sinkron", lambda db_path, log=print, **k: {"a": 2, "b": 3}):
            kode, logs = self.jalan("sinkron")
        self.assertEqual((kode, logs[-1]), (0, "Supabase dicerminkan: 5 baris di 2 tabel."))

        def gagal(*a, **k):
            raise sinkron.SinkronError("SUPABASE_DB_URL belum diisi")
        with mock.patch.object(sinkron, "sinkron", gagal):
            kode, logs = self.jalan("sinkron")
        self.assertEqual(kode, 1)
        self.assertIn("SUPABASE_DB_URL", logs[-1])

    def test_terbitkan_tanpa_konfigurasi_tidak_jalan(self):
        with mock.patch("scraper.sinkron.url_db", lambda *a, **k: None):
            kode, logs = self.jalan("terbitkan")
        self.assertEqual(kode, 1)
        self.assertIn("belum lengkap", logs[-1])

    def test_unggah_meneruskan_hasil(self):
        with mock.patch("scraper.unggah.unggah", lambda keluar=None, log=print: (False, "Node.js belum terpasang")):
            kode, logs = self.jalan("unggah")
        self.assertEqual((kode, "TIDAK TERUNGGAH" in logs[-1]), (1, True))

    def test_tarik_hanya_dengan_konfirmasi(self):
        with self.assertRaises(ValueError):
            self.jalan("tarik")
        with mock.patch.object(sinkron, "tarik", lambda p, paksa=False, log=print, **k: {"t": 1} if paksa else 1 / 0):
            kode, logs = self.jalan("tarik", {"konfirmasi": True})
        self.assertEqual(kode, 0)


class TestWebPerintah(unittest.TestCase):
    setUp = _tw.TestWebTugas.setUp                                            # server uji yang sama, tanpa menjalankan ulang tes induknya
    minta = _tw.TestWebTugas.minta

    def test_halaman_dan_katalog(self):
        s, isi = self.minta("GET", "/perintah")
        self.assertEqual(s, 200)
        self.assertIn(b"Pusat Perintah", isi)
        s, j = self.minta("GET", "/api/perintah")
        self.assertEqual(s, 200)
        self.assertEqual({p["id"] for p in j["perintah"]}, {p["id"] for p in perintah.DAFTAR})
        self.assertIn("fungsi", j["perintah"][0])

    def test_jalankan_perintah_lewat_pengelola_tugas(self):
        got = []

        def palsu(id_, opsi, db_path, log, berhenti=None):
            got.append((id_, opsi))
            log("halo dari perintah")
            return 0
        with mock.patch.object(perintah, "jalankan", palsu):
            s, j = self.minta("POST", "/api/tugas/mulai", {"jenis": "perintah", "opsi": {"id": "perbarui", "opsi": {"koneksi": 3, "jeda": 2}}}, **{"X-Pantau": "1"})
            self.assertEqual((s, j["jenis"]), (200, "perintah:perbarui"))
            self.assertIn(j["status"], ("berjalan", "selesai"))                 # perintah palsu bisa selesai sebelum balasan dikirim
            for _ in range(100):
                st = self.minta("GET", "/api/tugas")[1]
                if st["status"] != "berjalan":
                    break
                time.sleep(0.02)
        self.assertEqual((st["status"], st["kode"]), ("selesai", 0))
        self.assertIn("halo dari perintah", st["log"])
        self.assertEqual(got[0][0], "perbarui")
        self.assertEqual((got[0][1]["koneksi"], got[0][1]["jeda"]), (3, 2.0))

    def test_perintah_tidak_sah_ditolak_dan_tarik_perlu_konfirmasi(self):
        for opsi in ({"id": "hapus"}, {"id": "tarik", "opsi": {}}, {"id": "perbarui", "opsi": {"koneksi": 50}}):
            s, j = self.minta("POST", "/api/tugas/mulai", {"jenis": "perintah", "opsi": opsi}, **{"X-Pantau": "1"})
            self.assertEqual(s, 400, opsi)
        self.assertEqual(self.minta("POST", "/api/tugas/mulai", {"jenis": "perintah", "opsi": {"id": "sinkron"}})[0], 403)       # tanpa header dashboard


if __name__ == "__main__":
    unittest.main()
