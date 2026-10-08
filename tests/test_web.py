import http.client
import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from scraper import tugas, web
from scraper.core import db


class TestWebTugas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "t.db")
        db.buka(self.path).close()
        self.panggilan = []
        selesai = threading.Event()
        self.selesai = selesai

        def run_detail_palsu(conn, target, **kw):
            self.panggilan.append(("detail", target["tahun"], kw["koneksi"], kw["jeda"], kw["usia_hari"], kw["semua"]))
            kw["progres"](3, 10, 3, 0)
            kw["log"]("halo dari tugas")
            while not kw["berhenti"].is_set() and not selesai.is_set():
                time.sleep(0.01)
            return 130 if kw["berhenti"].is_set() else 0

        def run_daftar_palsu(conn, target, **kw):
            self.panggilan.append(("daftar", target["tahun"], kw["jeda"]))
            return 0

        def run_semua_palsu(conn, target, **kw):
            self.panggilan.append(("semua", target["tahun"], kw["koneksi"], kw["jeda"]))
            kw["tahap"](1, 2, "Daftar RUP")
            kw["log"]("tahap satu")
            kw["tahap"](2, 2, "Detail paket")
            kw["progres"](5, 20, 5, 0)
            return 0

        for nama, fn in (("run_detail", run_detail_palsu), ("run_daftar", run_daftar_palsu), ("run_semua", run_semua_palsu)):
            p = mock.patch.object(tugas, nama, fn)
            p.start()
            self.addCleanup(p.stop)
        self.peng = web.PengelolaTugas(self.path)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), web.buat_handler(self.path, None, self.peng))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self.selesai.set)

    def minta(self, metode, jalur, body=None, **header):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": f"127.0.0.1:{self.port}", **header}
        data = None
        if body is not None:
            data = json.dumps(body)
            h["Content-Type"] = "application/json"
        c.request(metode, jalur, data, h)
        r = c.getresponse()
        isi = r.read()
        c.close()
        try:
            return r.status, json.loads(isi)
        except ValueError:
            return r.status, isi

    def mulai(self, **kw):
        return self.minta("POST", "/api/tugas/mulai", {"jenis": "detail", "tahun": 2026, "koneksi": 3, "jeda": 1, **kw}, **{"X-Pantau": "1"})

    # ---- keamanan ----
    def test_post_tanpa_header_dashboard_ditolak(self):
        self.assertEqual(self.minta("POST", "/api/tugas/mulai", {"jenis": "detail", "tahun": 2026})[0], 403)
        self.assertEqual(self.panggilan, [])

    def test_post_dari_situs_lain_ditolak(self):
        s, _ = self.minta("POST", "/api/tugas/mulai", {"jenis": "detail", "tahun": 2026}, **{"X-Pantau": "1", "Origin": "https://jahat.example"})
        self.assertEqual(s, 403)

    def test_host_palsu_ditolak(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/api/tugas", headers={"Host": "jahat.example"})
        self.assertEqual(c.getresponse().status, 403)
        c.close()

    def test_get_status_boleh(self):
        s, j = self.minta("GET", "/api/tugas")
        self.assertEqual((s, j["status"]), (200, "idle"))

    # ---- parameter ----
    def test_parameter_tidak_valid(self):
        for bad in ({"koneksi": 0}, {"koneksi": 11}, {"jeda": 0.05}, {"tahun": 1999}, {"usia_hari": -1}, {"jenis": "hapus"}):
            s, j = self.mulai(**bad)
            self.assertEqual(s, 400, bad)
        self.assertEqual(self.panggilan, [])

    # ---- alur ----
    def test_mulai_progres_henti(self):
        s, j = self.mulai(koneksi=3, jeda=0.7, usia_hari=3, semua=True)
        self.assertEqual((s, j["status"], j["koneksi"], j["jeda"]), (200, "berjalan", 3, 0.7))
        for _ in range(100):
            st = self.minta("GET", "/api/tugas")[1]
            if st["selesai"] == 3:
                break
            time.sleep(0.02)
        self.assertEqual((st["selesai"], st["total"], st["ok"]), (3, 10, 3))
        self.assertIn("halo dari tugas", st["log"])
        self.assertEqual(self.panggilan, [("detail", 2026, 3, 0.7, 3, True)])
        self.assertEqual(self.mulai()[0], 409)                          # tidak boleh dua tugas sekaligus
        self.minta("POST", "/api/tugas/henti", {}, **{"X-Pantau": "1"})
        for _ in range(100):
            st = self.minta("GET", "/api/tugas")[1]
            if st["status"] != "berjalan":
                break
            time.sleep(0.02)
        self.assertEqual((st["status"], st["kode"]), ("dihentikan", 130))

    def test_peringatan_laju_tinggi_dikirim_ke_ui(self):
        s, j = self.mulai(koneksi=10, jeda=0.2)
        self.assertIn("TINGGI", j["peringatan"])

    def test_satu_proses_semua_melaporkan_tahap(self):
        s, j = self.minta("POST", "/api/tugas/mulai", {"jenis": "semua", "tahun": 2025, "koneksi": 3, "jeda": 1.5}, **{"X-Pantau": "1"})
        self.assertEqual((s, j["jenis"], j["koneksi"]), (200, "semua", 3))
        for _ in range(100):
            st = self.minta("GET", "/api/tugas")[1]
            if st["status"] != "berjalan":
                break
            time.sleep(0.02)
        self.assertEqual((st["status"], st["tahap_ke"], st["tahap_total"], st["tahap_nama"]), ("selesai", 2, 2, "Detail paket"))
        self.assertEqual((st["selesai"], st["total"]), (5, 20))
        self.assertEqual(self.panggilan, [("semua", 2025, 3, 1.5)])

    def test_tugas_daftar_memakai_satu_koneksi(self):
        s, j = self.minta("POST", "/api/tugas/mulai", {"jenis": "daftar", "tahun": 2025, "koneksi": 5, "jeda": 2}, **{"X-Pantau": "1"})
        self.assertEqual((s, j["koneksi"]), (200, 1))
        for _ in range(100):
            if self.minta("GET", "/api/tugas")[1]["status"] != "berjalan":
                break
            time.sleep(0.02)
        self.assertEqual(self.panggilan, [("daftar", 2025, 2.0)])


class TestPerkiraanWaktu(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = web.PengelolaTugas(str(Path(self.tmp.name) / "x.db"))

    def progres(self, waktu, selesai, total=100):
        with mock.patch.object(web.time, "monotonic", return_value=waktu):
            self.p._progres(selesai, total, selesai, 0)
        return self.p.status()

    def test_kecepatan_dari_jendela_30_detik_dan_sisa_waktu(self):
        self.p._tahap_mulai = 0
        self.progres(10, 10)                                  # 1/detik sejak awal
        st = self.progres(20, 20)
        self.assertAlmostEqual(st["laju"], 1.0)
        self.assertEqual(st["sisa_detik"], 80)               # 80 tersisa / 1 per detik

    def test_laju_mengikuti_kecepatan_terbaru_bukan_rata_rata_seumur_hidup(self):
        self.p._tahap_mulai = 0
        self.progres(10, 1)                                   # awalnya lambat
        for t, n in ((100, 10), (110, 30)):                   # lalu 2 paket/detik di jendela terakhir
            st = self.progres(t, n)
        self.assertAlmostEqual(st["laju"], 2.0)
        self.assertEqual(st["sisa_detik"], 35)                # 70 / 2

    def test_selesai_sisa_nol_dan_belum_ada_data_kosong(self):
        self.p._tahap_mulai = 0
        self.assertIsNone(self.progres(5, 0)["sisa_detik"])
        self.assertEqual(self.progres(50, 100)["sisa_detik"], 0)

    def test_ganti_tahap_mereset_perkiraan(self):
        self.p._tahap_mulai = 0
        self.progres(10, 50)
        self.p._tahap(2, 2, "Detail paket")
        st = self.p.status()
        self.assertEqual((st["laju"], st["sisa_detik"], st["selesai"]), (None, None, 0))


if __name__ == "__main__":
    unittest.main()
