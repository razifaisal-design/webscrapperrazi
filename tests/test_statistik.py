import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from scraper import web
from scraper.cli import muat_target
from scraper.core import db, statistik

SATKER = muat_target(None, None)[1]["id_satker"]          # satker di config (web memakai config yang sama)


def paket(kode, nama, pagu, tahun=2026, metode="Pengadaan Langsung", dana="APBD", jenis="penyedia"):
    return {"kode_rup": kode, "tahun": tahun, "klpd_nama": "K", "id_satker": SATKER, "jenis": jenis, "nama_paket": nama,
            "penyelenggara": None, "pagu": pagu, "metode_pemilihan": metode, "sumber_dana": dana,
            "waktu_pemilihan": "Jan", "link": "x"}


def isi(conn, tahun, daftar):
    rid = db.mulai_run(conn, SATKER, tahun)
    db.finalisasi(conn, rid, [paket(*d[:3], tahun=tahun, **(d[3] if len(d) > 3 else {})) for d in daftar], SATKER, tahun)
    db.tutup_run(conn, rid, "success", len(daftar), len(daftar))


DATA = {
    2025: [("1", "Belanja Modal Jalan Kota (Jl. A, Gg. X, Kec. Pontianak Utara)", 100),
           ("2", "Belanja Modal Saluran Pembuang Pasang Surut (Jl. A, Gg. X, Kec. Pontianak Utara)", 40),
           ("3", "Fotocopy", 10, {"metode": "E-Purchasing"})],
    2026: [("4", "Belanja Modal Jalan Kota (Jl. B, Gg. Y, Kec. Pontianak Barat)", 200),
           ("5", "Pengawasan PSU Jalan Tahun 2026 Kecamatan Pontianak Barat", 30),
           ("6", "Belanja Modal Saluran Pembuang Pasang Surut (Jl. B, Kec. Pontianak Kota)", 60),
           ("7", "Belanja Modal Jalan Kota (Jl. C, lokasi tanpa kecamatan)", 5),
           ("8", "Materai", 5)],
}


class TestStatistik(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)
        for th, d in DATA.items():
            isi(self.conn, th, d)
        self.hasil = statistik.statistik_semua(self.conn, lambda th: muat_target(None, th)[1], SATKER)

    def test_pagu_per_tahun_dan_kategori(self):
        a, b = self.hasil["per_tahun"]["2025"], self.hasil["per_tahun"]["2026"]
        self.assertEqual((a["pagu_dinas"], a["jalan"]["total"], a["saluran"]["total"], a["lainnya"]["total"]), (150, 100, 40, 10))
        self.assertEqual((b["pagu_dinas"], b["jalan"]["total"], b["saluran"]["total"], b["jalan_saluran"]), (300, 235, 60, 295))
        self.assertEqual((b["jalan"]["fisik"], b["jalan"]["konsultan"]), (205, 30))        # konsultan dipisah dari fisik
        self.assertEqual(a["jalan"]["total"] + a["saluran"]["total"] + a["lainnya"]["total"], a["pagu_dinas"])

    def test_per_kecamatan_termasuk_yang_tanpa_kecamatan_dan_cocok_dengan_total(self):
        b = self.hasil["per_tahun"]["2026"]["kecamatan"]
        self.assertEqual((b["Pontianak Barat"]["jalan"], b["Pontianak Barat"]["total"]), (230, 230))   # fisik + konsultan (nama berisi 'Kecamatan ...')
        self.assertEqual(b["Pontianak Kota"]["saluran"], 60)
        self.assertEqual(b["(tanpa kecamatan)"]["jalan"], 5)
        self.assertEqual(sum(v["total"] for v in b.values()), self.hasil["per_tahun"]["2026"]["jalan_saluran"])   # tidak ada yang hilang
        self.assertEqual(self.hasil["kecamatan"][-1], "(tanpa kecamatan)")                                       # selalu paling akhir

    def test_metode_dan_jumlah_unik(self):
        a = self.hasil["per_tahun"]["2025"]
        self.assertEqual(a["metode"], {"Pengadaan Langsung": 140, "E-Purchasing": 10})
        self.assertEqual((a["jalan_unik"], a["gang_unik"]), (1, 1))                        # Jl. A + Gg. X dihitung sekali
        self.assertEqual(self.hasil["per_tahun"]["2026"]["jalan_unik"], 2)               # Jl. B (di paket Jalan dan Saluran) + Jl. C

    def test_tahun_info_menandai_detail_belum_lengkap(self):
        self.assertTrue(all(not i["lengkap"] for i in self.hasil["tahun_info"]))           # belum ada detail sama sekali
        self.assertEqual([i["tahun"] for i in self.hasil["tahun_info"]], [2025, 2026])

    def test_top_jalan_lintas_tahun(self):
        top = self.hasil["top_jalan"]
        self.assertEqual(top[0]["nama"], "Jl. B")                                           # 200 + 60 = 260 terbesar
        self.assertEqual(top[0]["total_pagu"], 260)


class TestRuteGrafik(unittest.TestCase):
    def test_halaman_dan_api(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = str(Path(tmp.name) / "g.db")
        conn = db.buka(path)
        for th, d in DATA.items():
            isi(conn, th, d)
        conn.close()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web.buat_handler(path, None))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)

        def get(jalur):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.request("GET", jalur, headers={"Host": f"127.0.0.1:{srv.server_address[1]}"})
            r = c.getresponse()
            return r.status, r.read()

        s, isi_html = get("/grafik")
        self.assertEqual(s, 200)
        self.assertIn(b"Grafik Pagu", isi_html)
        s, isi_json = get("/api/statistik")
        d = json.loads(isi_json)
        self.assertEqual((s, d["tahun"]), (200, [2025, 2026]))
        self.assertEqual(d["per_tahun"]["2026"]["jalan"]["total"], 235)
        self.assertIn("satker_nama", d["target"])


if __name__ == "__main__":
    unittest.main()
