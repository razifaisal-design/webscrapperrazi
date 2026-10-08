import threading
import unittest

from scraper import tugas
from scraper.core import db
from scraper.core.http import DiblokirError
from scraper.sources.sirup_detail import DetailError

TARGET = {"id_satker": 1, "tahun": 2026, "satker_nama": "S", "klpd_nama": "K"}


def paket(kode, pagu=100):
    return {"kode_rup": kode, "tahun": 2026, "klpd_nama": "K", "id_satker": 1, "jenis": "penyedia",
            "nama_paket": f"Belanja Modal Jalan Kota (Jl. A{kode}, Gg. B, Kec. Pontianak Utara)", "penyelenggara": None,
            "pagu": pagu, "metode_pemilihan": "Tender", "sumber_dana": "APBD", "waktu_pemilihan": "Jan", "link": "x"}


def detail_palsu(kode):
    return {"lokasi": [], "lokasi_ringkas": "", "volume": "1 Paket", "uraian": "Pekerjaan Jalan", "spesifikasi": "",
            "sumber_dana": [{"mak": "M", "pagu": 100}], "mak": "M", "total_pagu": 100, "extra": {}}


class KlienPalsu:
    dibuat = []

    def __init__(self, jeda=0):
        self.jeda = jeda
        KlienPalsu.dibuat.append(self)

    def close(self):
        pass


class TestParam(unittest.TestCase):
    def test_laju_dan_peringatan(self):
        self.assertAlmostEqual(tugas.laju(1, 1.5), 1 / 1.65)
        self.assertIsNone(tugas.peringatan_laju(1, 1.5))
        self.assertIn("TINGGI", tugas.peringatan_laju(10, 0.3))
        self.assertIn("Sedang", tugas.peringatan_laju(3, 1.5))

    def test_batas(self):
        with self.assertRaises(ValueError):
            tugas.cek_param(0, 1)
        with self.assertRaises(ValueError):
            tugas.cek_param(11, 1)
        with self.assertRaises(ValueError):
            tugas.cek_param(2, 0.05)
        tugas.cek_param(10, 0.2)


class TestRunDetail(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)
        rid = db.mulai_run(self.conn, 1, 2026)
        db.finalisasi(self.conn, rid, [paket(str(i)) for i in range(1, 21)], 1, 2026)
        self.log = []
        KlienPalsu.dibuat = []
        self.pakai = {"buat_klien": KlienPalsu, "log": self.log.append, "db_path": ":memory:"}
        p = unittest.mock.patch.object(tugas, "bangun_lokasi", lambda *a, **k: self.log.append("lokasi dibangun"))
        p.start()
        self.addCleanup(p.stop)

    def jumlah_detail(self):
        return self.conn.execute("SELECT COUNT(*) FROM sirup_detail WHERE error IS NULL").fetchone()[0]

    def test_semua_terambil_dengan_banyak_koneksi_dan_jeda_diteruskan(self):
        kode = tugas.run_detail(self.conn, TARGET, koneksi=4, jeda=0.7, ambil=lambda c, j, k: detail_palsu(k), **self.pakai)
        self.assertEqual(kode, 0)
        self.assertEqual(self.jumlah_detail(), 20)
        self.assertLessEqual(len(KlienPalsu.dibuat), 4)               # satu klien per thread, maksimal = koneksi
        self.assertTrue(all(k.jeda == 0.7 for k in KlienPalsu.dibuat))
        self.assertIn("lokasi dibangun", self.log)

    def test_hasil_sama_untuk_1_dan_5_koneksi(self):
        tugas.run_detail(self.conn, TARGET, koneksi=5, jeda=0.2, ambil=lambda c, j, k: detail_palsu(k), **self.pakai)
        self.assertEqual(self.jumlah_detail(), 20)
        self.assertEqual(self.conn.execute("SELECT COUNT(DISTINCT kode_rup) FROM sirup_detail").fetchone()[0], 20)

    def test_diblokir_menghentikan_semua_dan_menyimpan_yang_sudah(self):
        hitung = {"n": 0}
        kunci = threading.Lock()

        def ambil(c, j, k):
            with kunci:
                hitung["n"] += 1
                n = hitung["n"]
            if n >= 6:
                raise DiblokirError("HTTP 429")
            return detail_palsu(k)

        kode = tugas.run_detail(self.conn, TARGET, koneksi=1, jeda=0.2, ambil=ambil, **self.pakai)
        self.assertEqual(kode, 2)
        self.assertEqual(self.jumlah_detail(), 5)                      # 5 tersimpan, sisanya tidak dicoba lagi
        self.assertLess(hitung["n"], 20)
        self.assertEqual(self.conn.execute("SELECT status FROM scrape_runs ORDER BY id DESC LIMIT 1").fetchone()[0], "failed")
        self.assertIn("lokasi dibangun", self.log)                     # yang sudah terambil tetap dimasukkan ke tabel Jalan/Gang

    def test_diblokir_dengan_banyak_koneksi_berhenti_total(self):
        def ambil(c, j, k):
            raise DiblokirError("HTTP 403")
        self.assertEqual(tugas.run_detail(self.conn, TARGET, koneksi=5, jeda=0.2, ambil=ambil, **self.pakai), 2)
        self.assertEqual(self.jumlah_detail(), 0)
        self.assertNotIn("lokasi dibangun", self.log)                  # tidak ada detail sama sekali -> tidak ada yang dibangun

    def test_gagal_satu_paket_tidak_menghentikan_yang_lain(self):
        def ambil(c, j, k):
            if k == "7":
                raise DetailError("halaman rusak")
            return detail_palsu(k)
        kode = tugas.run_detail(self.conn, TARGET, koneksi=3, jeda=0.2, ambil=ambil, **self.pakai)
        self.assertEqual(kode, 4)
        self.assertEqual(self.jumlah_detail(), 19)
        self.assertEqual(self.conn.execute("SELECT error FROM sirup_detail WHERE kode_rup='7'").fetchone()[0], "halaman rusak")

    def test_tombol_hentikan(self):
        stop = threading.Event()
        n = {"i": 0}

        def ambil(c, j, k):
            n["i"] += 1
            if n["i"] == 4:
                stop.set()
            return detail_palsu(k)
        kode = tugas.run_detail(self.conn, TARGET, koneksi=1, jeda=0.2, ambil=ambil, berhenti=stop, **self.pakai)
        self.assertEqual(kode, 130)
        self.assertLess(self.jumlah_detail(), 20)
        self.assertGreaterEqual(self.jumlah_detail(), 3)
        self.assertIn("lokasi dibangun", self.log)

    def test_progres_dilaporkan(self):
        p = []
        tugas.run_detail(self.conn, TARGET, koneksi=2, jeda=0.2, ambil=lambda c, j, k: detail_palsu(k),
                         progres=lambda *a: p.append(a), **self.pakai)
        self.assertEqual(p[-1], (20, 20, 20, 0))

    def test_total_dilaporkan_sejak_awal_sebelum_ada_yang_selesai(self):
        p = []
        tugas.run_detail(self.conn, TARGET, koneksi=2, jeda=0.2, ambil=lambda c, j, k: detail_palsu(k),
                         progres=lambda *a: p.append(a), **self.pakai)
        self.assertEqual(p[0], (0, 20, 0, 0))

    def test_param_salah_ditolak(self):
        with self.assertRaises(ValueError):
            tugas.run_detail(self.conn, TARGET, koneksi=50, jeda=1, ambil=lambda *a: None, **self.pakai)


class TestRunSemua(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)
        self.urutan, self.tahap, self.log = [], [], []

    def jalankan(self, kode_daftar=0, hentikan_setelah_daftar=False, **kw):
        stop = threading.Event()

        def daftar(conn, target, **k):
            self.urutan.append(("daftar", k["jeda"], k["ekspor"]))
            if hentikan_setelah_daftar:
                stop.set()
            return kode_daftar

        def detail(conn, target, **k):
            self.urutan.append(("detail", k["koneksi"], k["jeda"], k["usia_hari"], k["semua"]))
            return 0

        with unittest.mock.patch.object(tugas, "run_daftar", daftar), unittest.mock.patch.object(tugas, "run_detail", detail):
            return tugas.run_semua(self.conn, TARGET, log=self.log.append, tahap=lambda *a: self.tahap.append(a),
                                   berhenti=stop, **kw)

    def test_daftar_lalu_detail_dengan_parameter_yang_sama(self):
        kode = self.jalankan(koneksi=3, jeda=0.7, usia_hari=2, semua=True)
        self.assertEqual(kode, 0)
        self.assertEqual(self.urutan, [("daftar", 0.7, False), ("detail", 3, 0.7, 2, True)])
        self.assertEqual(self.tahap, [(1, 2, "Daftar RUP"), (2, 2, "Detail paket")])

    def test_detail_tidak_jalan_bila_daftar_gagal_atau_tidak_valid(self):
        for kode_daftar in (1, 2, 3):
            self.urutan.clear(); self.log.clear()
            self.assertEqual(self.jalankan(kode_daftar=kode_daftar), kode_daftar)
            self.assertEqual([u[0] for u in self.urutan], ["daftar"])
            self.assertTrue(any("TIDAK dijalankan" in x for x in self.log))

    def test_dihentikan_setelah_daftar(self):
        self.assertEqual(self.jalankan(hentikan_setelah_daftar=True), 130)
        self.assertEqual([u[0] for u in self.urutan], ["daftar"])

    def test_param_salah_ditolak_sebelum_apa_pun(self):
        with self.assertRaises(ValueError):
            self.jalankan(koneksi=99)
        self.assertEqual(self.urutan, [])


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
