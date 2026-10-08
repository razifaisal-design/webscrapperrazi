import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from scraper import web
from scraper.cli import muat_target
from scraper.core import db, rekap, semua_tahun

SAT = muat_target(None, None)[1]["id_satker"]
KLAS = {"kategori": [{"nama": "Jalan", "cocok": {"nama_paket": "(?i)^Belanja Modal Jalan Kota"}},
                     {"nama": "Saluran", "cocok": {"nama_paket": "(?i)^Belanja Modal Saluran Pembuang"}}],
        "konsultan": "(?i)\\b(perencanaan|pengawasan)\\b"}
J25, S25 = "1.04.05.2.01.0012.5.2.04.01.001.00004", "1.04.05.2.01.0011.5.2.04.02.002.00004"      # kode MAK tahun 2025
J26, S26 = "9.99.99.2.01.0012.5.2.04.01.001.00004", "9.99.99.2.01.0011.5.2.04.02.002.00004"      # kode MAK tahun 2026 (beda!)


def target(th):
    j, s = (J25, S25) if th == 2025 else (J26, S26)
    return {"id_satker": SAT, "tahun": th, "klasifikasi": KLAS, "satker_nama": "S", "klpd_nama": "K",
            "periksa": {"mak_kategori": [{"awalan": j[:17], "kategori": "Jalan", "mak_baku": j},
                                         {"awalan": s[:17], "kategori": "Saluran", "mak_baku": s}]}}


def paket(kode, nama, pagu, th):
    return {"kode_rup": kode, "tahun": th, "klpd_nama": "K", "id_satker": SAT, "jenis": "penyedia", "nama_paket": nama,
            "penyelenggara": None, "pagu": pagu, "metode_pemilihan": "Tender", "sumber_dana": "APBD",
            "waktu_pemilihan": "Jan", "link": f"http://x/{kode}"}


def isi(conn, th, daftar):
    """daftar = [(kode, nama, pagu, mak)] -> daftar + detail."""
    rid = db.mulai_run(conn, SAT, th)
    db.finalisasi(conn, rid, [paket(k, n, p, th) for k, n, p, _ in daftar], SAT, th)
    rd = db.mulai_run(conn, SAT, th, "SIRUP_DETAIL")
    for k, n, p, m in daftar:
        db.simpan_detail(conn, rd, k, n, p, {"lokasi": [], "lokasi_ringkas": "", "volume": "1", "uraian": "Pekerjaan",
                                              "spesifikasi": "", "sumber_dana": [{"mak": m, "pagu": p}], "mak": m,
                                              "total_pagu": p, "extra": {}})


DATA = {2025: [("1", "Belanja Modal Jalan Kota (Jl. A, Gg. X, Kec. Pontianak Utara)", 100, J25),
               ("2", "Belanja Modal Saluran Pembuang Pasang Surut (Jl. A, Gg. X, Kec. Pontianak Utara)", 40, J25)],   # salah MAK
        2026: [("3", "Belanja Modal Jalan Kota (Jl. B, Gg. Y, Kec. Pontianak Barat)", 200, J26),
               ("4", "Belanja Modal Saluran Pembuang Pasang Surut (Jl. B, Kec. Pontianak Kota)", 60, S26),
               ("5", "Belanja Modal Jalan Kota (Jl. A, Gg. X, Kec. Pontianak Utara)", 25, J26)]}


class TestGabung(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)
        for th, d in DATA.items():
            isi(self.conn, th, d)
        self.daftar = semua_tahun.hitung_per_tahun(self.conn, target, SAT)
        self.g = semua_tahun.gabung(self.daftar)

    def test_total_dan_jumlah_paket_adalah_jumlah_semua_tahun(self):
        self.assertEqual((self.g["paket_aktif"], self.g["paket_dengan_detail"]), (5, 5))
        self.assertEqual(self.g["total_pagu_mak"], 425)
        self.assertEqual(self.g["total_pagu_mak"], sum(d["total_pagu_mak"] for _, d in self.daftar))
        self.assertEqual(self.g["selisih"], 0)
        self.assertEqual(len(self.g["paket"]), 5)

    def test_mak_yang_sama_di_dua_tahun_digabung(self):
        mak = {g["mak"]: g for g in self.g["per_mak"]}
        self.assertEqual(mak[J25]["total_pagu"], 140)          # hanya 2025
        self.assertEqual(mak[J26]["jumlah_paket"], 2)           # paket 3 dan 5 (2026)
        self.assertEqual(sum(g["total_pagu"] for g in self.g["per_mak"]), 425)

    def test_klasifikasi_dan_perbaikan_dijumlahkan(self):
        k = self.g["klasifikasi"]
        self.assertEqual((k["Jalan"]["total_pagu"], k["Saluran"]["total_pagu"]), (325, 100))
        self.assertEqual(sum(v["total_pagu"] for v in k.values()), 425)
        r = self.g["perbaikan"]["Semua"]
        self.assertEqual(r["total_tercatat"], r["total_seharusnya"])
        self.assertTrue(r["ada_perbaikan"])

    def test_aturan_mak_dihormati_per_tahun(self):
        # 2025: paket 2 (Saluran) memakai MAK Jalan -> salah. 2026 memakai kode MAK lain; semuanya benar.
        salah = [t for t in self.g["periksa"]["temuan"] if t["jenis"] == "MAK_TIDAK_SESUAI"]
        self.assertEqual([t["kode_rup"] for t in salah], ["2"])
        self.assertEqual(self.g["periksa"]["jumlah_kesalahan"], 1)
        self.assertNotIn("MAK_BELUM_DIPETAKAN", self.g["periksa"]["ringkas"])   # kalau pakai satu aturan saja, 2026 akan penuh peringatan
        n = self.g["periksa"]["matriks"]["nilai"]
        self.assertEqual(n["Saluran"]["Jalan"], {"pagu": 40, "paket": 1})

    def test_aturan_mak_hanya_pada_tahun_berlaku(self):
        from scraper.core import rekap as rk
        t = target(2025); t["periksa"]["berlaku_tahun"] = [2026]
        self.assertNotIn("mak_kategori", rk.aturan_periksa_tahun(t))             # 2025 di luar tahun berlaku -> dimatikan
        t["tahun"] = 2026
        self.assertIn("mak_kategori", rk.aturan_periksa_tahun(t))
        t["periksa"].pop("berlaku_tahun"); t["tahun"] = 2025
        self.assertIn("mak_kategori", rk.aturan_periksa_tahun(t))                # tanpa berlaku_tahun: berlaku semua tahun (perilaku lama)

    def test_jalan_dan_gang_unik_lintas_tahun(self):
        self.assertEqual(sorted(j["nama"] for j in self.g["lokasi"]["jalan"]), ["Jl. A", "Jl. B"])   # Jl. A ada di 2025 & 2026
        jl_a = next(j for j in self.g["lokasi"]["jalan"] if j["nama"] == "Jl. A")
        self.assertEqual(jl_a["jumlah_paket"], 3)

    def test_kosong(self):
        self.assertIsNone(semua_tahun.gabung([]))


class TestApiSemuaTahun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "s.db")
        conn = db.buka(self.path)
        for th, d in DATA.items():
            isi(conn, th, d)
        conn.close()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), web.buat_handler(self.path, None))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def get(self, jalur):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=20)
        c.request("GET", jalur, headers={"Host": f"127.0.0.1:{self.srv.server_address[1]}"})
        r = c.getresponse()
        return r.status, json.loads(r.read())

    def test_rekap_database_perubahan_semua_tahun(self):
        s, d = self.get("/api/rekap?tahun=semua")
        self.assertEqual(s, 200)
        self.assertEqual((d["target"]["semua"], d["target"]["tahun"], d["target"]["tahun_daftar"][-2:]), (True, "semua", [2025, 2026][-2:]))
        s, b = self.get("/api/database?tahun=semua")
        self.assertEqual(s, 200)
        self.assertEqual(sorted({r["tahun"] for r in b["baris"]}), sorted(set(DATA) | {r["tahun"] for r in b["baris"]}))
        self.assertGreaterEqual(len(b["baris"]), 5)
        self.assertEqual(self.get("/api/perubahan?tahun=semua")[0], 200)
        one = self.get("/api/rekap?tahun=2026")[1]
        self.assertEqual(one["target"]["tahun"], 2026)
        self.assertLess(one["paket_aktif"], d["paket_aktif"])                              # satu tahun < semua tahun

    def test_cache_dipakai_ulang_dan_dibatalkan_saat_data_berubah(self):
        asli = web.semua_tahun.hitung_per_tahun
        n = {"i": 0}

        def hitung(*a, **k):
            n["i"] += 1
            return asli(*a, **k)
        with mock.patch.object(web.semua_tahun, "hitung_per_tahun", hitung):
            a = self.get("/api/rekap?tahun=semua")[1]
            b = self.get("/api/rekap?tahun=semua")[1]
            self.assertEqual(n["i"], 1)                                                   # jawaban kedua dari cache
            self.assertEqual(a, b)
            conn = db.buka(self.path)
            isi(conn, 2026, DATA[2026] + [("9", "Belanja Modal Jalan Kota (Jl. Z, Kec. Pontianak Kota)", 7, J26)])   # pengambilan daftar lengkap berikutnya
            conn.close()
            c = self.get("/api/rekap?tahun=semua")[1]
            self.assertEqual(n["i"], 2)                                                   # data berubah -> dihitung ulang
            self.assertEqual(c["paket_aktif"], a["paket_aktif"] + 1)


if __name__ == "__main__":
    unittest.main()
