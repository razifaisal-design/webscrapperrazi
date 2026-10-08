import threading
import unittest

from scraper import tugas
from scraper.core import db
from scraper.core.http import DiblokirError
from scraper.sources import spse

HALAMAN = """<html><select name="tahun" id="tahun">{opsi}</select>
<script>var table = $("#tbllelang").DataTable({{ajax: {{url: "/pontianak/dt/pl?tahun=2026", type: 'POST', data: function (d) {{
 d.authenticityToken = '{token}'; }}}}}});</script></html>"""


def baris(kode, nama="Paket", tahapan="Evaluasi Penawaran", hps="19,9 Jt", metode="Pengadaan Langsung",
          kategori="Pekerjaan Konstruksi - TA 2026", nilai="Nilai Kontrak belum dibuat", konsol="0", oap="0"):
    return [str(kode), nama, "Kota Pontianak", tahapan, hps, metode, kategori, "5", nilai, None, konsol, oap]


class ServerSpse:
    """Meniru SPSE: GET halaman (token + pilihan tahun) dan POST DataTables (paging, urutan menurut kode)."""
    def __init__(self, data, tahun=(2026, 2025), gangguan=None):
        self.data, self.tahun, self.gangguan = data, list(tahun), gangguan or {}
        self.token, self.permintaan, self.versi_token = "a000", [], 0

    def get_text(self, url, params=None):
        self.versi_token += 1
        self.token = f"a{self.versi_token:03x}"
        return HALAMAN.format(opsi="".join(f'<option value="{t}">{t}</option>' for t in self.tahun), token=self.token)

    def post_json(self, url, data=None, params=None, headers=None):
        th, mulai, arah = int(params["tahun"]), int(data["start"]), data["order[0][dir]"]
        self.permintaan.append((th, mulai, arah))
        if data["authenticityToken"] != self.token or self.gangguan.get("token_basi", 0) > 0:
            self.gangguan["token_basi"] = max(0, self.gangguan.get("token_basi", 0) - 1)
            raise ValueError("bukan JSON")                       # SPSE membalas halaman HTML bila token salah
        rows = sorted(self.data.get(th, []), key=lambda r: int(r[0]), reverse=(arah == "desc"))
        if self.gangguan.get("geser", 0) > 0 and arah == "asc" and mulai == 100:
            self.gangguan["geser"] -= 1
            mulai -= 3                                           # data bergeser: 3 baris halaman sebelumnya muncul lagi
        if self.gangguan.get("ekor_hilang", 0) > 0 and arah == "asc" and mulai + 100 >= len(rows):
            self.gangguan["ekor_hilang"] -= 1
            rows = rows[:-1]                                     # paket terakhir tidak ikut
        if self.gangguan.get("blokir") and mulai >= 100:
            raise DiblokirError("HTTP 429")
        return {"draw": "1", "recordsTotal": 2147483647, "recordsFiltered": 2147483647, "data": rows[mulai:mulai + 100]}

    def close(self):
        pass


def sesi(server):
    return spse.Sesi(server, "pontianak", "nontender").buka()


class TestParse(unittest.TestCase):
    def test_token_dan_tahun(self):
        token, tahun = spse.parse_halaman(HALAMAN.format(opsi='<option value="2026">2026</option><option value="2019">2019</option><option value="">Semua</option>', token="abc123"))
        self.assertEqual((token, tahun), ("abc123", [2026, 2019]))
        with self.assertRaises(spse.SpseError):
            spse.parse_halaman("<html>tidak ada token</html>")

    def test_hps_ringkas(self):
        for teks, harap in (("19,9 Jt", 19_900_000), ("1,2 M", 1_200_000_000), ("950 Rb", 950_000), ("Rp 1.500.000", 1_500_000), ("abc", None), ("", None)):
            self.assertEqual(spse.hps_perkiraan(teks), harap, teks)

    def test_baris(self):
        p = spse.parse_baris(baris(11048278000, "  Belanja  X ", konsol="1", oap="1"), "pontianak", "nontender", 2026)
        self.assertEqual((p["kode_paket"], p["nama_paket"], p["kategori"], p["tahun_anggaran"], p["metode"]),
                         ("11048278000", "Belanja X", "Pekerjaan Konstruksi", 2026, "Pengadaan Langsung"))
        self.assertEqual((p["hps_perkiraan"], p["konsolidasi"], p["oap"]), (19_900_000, 1, 1))
        self.assertEqual(p["link"], "https://spse.inaproc.id/pontianak/nontender/11048278000/pengumumanpl")

    def test_baris_tidak_valid(self):
        for rusak in ([], ["abc"] * 12, ["x1"] + [""] * 11):
            with self.assertRaises(spse.SpseError):
                spse.parse_baris(rusak, "pontianak", "nontender", 2026)


class TestRayap(unittest.TestCase):
    def data(self, n, th=2026):
        return {th: [baris(1000 + i * 10) for i in range(n)]}

    def test_semua_halaman_100_per_halaman_lalu_berikutnya(self):
        sv = ServerSpse(self.data(250))
        hasil = spse.rayap_tahun(sesi(sv), 2026, log=lambda *_: None)
        self.assertEqual(len(hasil), 250)
        awal = [(m, a) for th, m, a in sv.permintaan if a == "asc"]
        self.assertEqual(awal, [(0, "asc"), (100, "asc"), (200, "asc")])      # halaman 1, 2, 3 (yang ke-3 berisi 50)

    def test_tepat_kelipatan_100_diakhiri_halaman_kosong(self):
        sv = ServerSpse(self.data(200))
        self.assertEqual(len(spse.rayap_tahun(sesi(sv), 2026, log=lambda *_: None)), 200)

    def test_tahun_kosong(self):
        self.assertEqual(spse.rayap_tahun(sesi(ServerSpse({})), 2026, log=lambda *_: None), [])

    def test_data_bergeser_antar_halaman_terdeteksi_lalu_diulang(self):
        sv = ServerSpse(self.data(250), gangguan={"geser": 1})
        log = []
        hasil = spse.rayap_tahun(sesi(sv), 2026, log=log.append)
        self.assertEqual(len(hasil), 250)
        self.assertEqual(len({r[0] for r in hasil}), 250)                  # tanpa ganda
        self.assertTrue(any("PERINGATAN" in x and "ganda" in x for x in log))

    def test_paket_ujung_yang_terlewat_terdeteksi_lewat_urutan_terbalik(self):
        sv = ServerSpse(self.data(120), gangguan={"ekor_hilang": 1})
        log = []
        self.assertEqual(len(spse.rayap_tahun(sesi(sv), 2026, log=log.append)), 120)
        self.assertTrue(any("ujung urutan terbalik" in x for x in log))

    def test_gagal_terus_menerus_menimbulkan_error_bukan_data_setengah(self):
        sv = ServerSpse(self.data(250), gangguan={"geser": 99})
        with self.assertRaises(spse.SpseError):
            spse.rayap_tahun(sesi(sv), 2026, log=lambda *_: None, ulang=1)

    def test_token_kedaluwarsa_diminta_ulang(self):
        sv = ServerSpse(self.data(30), gangguan={"token_basi": 1})
        self.assertEqual(len(spse.rayap_tahun(sesi(sv), 2026, log=lambda *_: None)), 30)

    def test_dihentikan(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(spse.Dihentikan):
            spse.rayap_tahun(sesi(ServerSpse(self.data(10))), 2026, log=lambda *_: None, berhenti=stop)


class TestRunSpse(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)
        self.log = []

    def jalan(self, server, **kw):
        return tugas.run_spse(self.conn, "nontender", "pontianak", ekspor=False, log=self.log.append, jeda=0.2,
                              buat_klien=lambda jeda=0: server, **kw)

    def n(self, sql="", *a):
        return self.conn.execute("SELECT COUNT(*) FROM spse_paket " + sql, a).fetchone()[0]

    def test_semua_tahun_tersimpan_dan_pengambilan_pertama_adalah_data_dasar(self):
        sv = ServerSpse({2026: [baris(1000 + i) for i in range(130)], 2025: [baris(500 + i, kategori="Jasa Lainnya - TA 2025") for i in range(40)]})
        self.assertEqual(self.jalan(sv), 0)
        self.assertEqual((self.n("WHERE tahun=2026"), self.n("WHERE tahun=2025")), (130, 40))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM paket_events").fetchone()[0], 0)
        r = self.conn.execute("SELECT * FROM spse_paket WHERE kode_paket='1000'").fetchone()
        self.assertEqual((r["hps_teks"], r["hps_perkiraan"], r["kategori"], r["is_active"]), ("19,9 Jt", 19_900_000, "Pekerjaan Konstruksi", 1))

    def test_satu_tahun_saja(self):
        sv = ServerSpse({2026: [baris(1)], 2025: [baris(2)]})
        self.assertEqual(self.jalan(sv, tahun=2025), 0)
        self.assertEqual((self.n("WHERE tahun=2025"), self.n("WHERE tahun=2026")), (1, 0))

    def test_tahun_yang_tidak_ada_di_pilihan_ditolak_dengan_pesan(self):
        self.assertEqual(self.jalan(ServerSpse({}), tahun=2020), 3)
        self.assertTrue(any("2020" in x and "tersedia" in x for x in self.log))

    def test_pengambilan_kedua_mencatat_baru_berubah_hilang(self):
        sv = ServerSpse({2026: [baris(1, "A"), baris(2, "B"), baris(3, "C")]}, tahun=(2026,))
        self.jalan(sv)
        sv.data[2026] = [baris(1, "A", tahapan="Penandatanganan Kontrak"), baris(3, "C"), baris(4, "D")]       # 2 hilang, 4 baru, 1 berubah
        self.jalan(sv)
        ev = sorted((e["jenis_event"], e["kunci"], e["field"]) for e in self.conn.execute("SELECT * FROM paket_events"))
        self.assertEqual(ev, [("BARU", "4", None), ("BERUBAH", "1", "tahapan"), ("HILANG", "2", None)])
        self.assertEqual(self.conn.execute("SELECT is_active FROM spse_paket WHERE kode_paket='2'").fetchone()[0], 0)
        sv.data[2026].append(baris(2, "B"))
        self.jalan(sv)
        self.assertIn("MUNCUL_KEMBALI", [e[0] for e in self.conn.execute("SELECT jenis_event FROM paket_events")])

    def test_nol_paket_pada_pengambilan_pertama_bukan_sukses(self):
        sv = ServerSpse({}, tahun=(2026,))
        self.assertEqual(self.jalan(sv), 1)
        self.assertEqual(self.conn.execute("SELECT status FROM scrape_runs ORDER BY id DESC LIMIT 1").fetchone()[0], "invalid")
        self.assertEqual(self.n(), 0)

    def test_penurunan_drastis_ditolak_kecuali_force(self):
        sv = ServerSpse({2026: [baris(i) for i in range(1, 51)]}, tahun=(2026,))
        self.jalan(sv)
        sv.data[2026] = [baris(i) for i in range(1, 6)]
        self.assertEqual(self.jalan(sv), 1)
        self.assertEqual(self.n("WHERE is_active=1"), 50)                       # data lama utuh
        self.assertEqual(self.jalan(sv, force=True), 0)
        self.assertEqual(self.n("WHERE is_active=1"), 5)

    def test_diblokir_berhenti_dan_data_lama_aman(self):
        sv = ServerSpse({2026: [baris(i) for i in range(1, 51)], 2025: [baris(900 + i) for i in range(250)]})
        self.jalan(sv, tahun=2026)
        sv.gangguan["blokir"] = True
        self.assertEqual(self.jalan(sv, tahun=2025), 2)
        self.assertEqual(self.n("WHERE tahun=2025"), 0)
        self.assertEqual(self.n("WHERE tahun=2026"), 50)

    def test_satu_tahun_gagal_tidak_membatalkan_tahun_lain(self):
        sv = ServerSpse({2026: [baris(i) for i in range(1, 11)], 2025: [baris(900 + i) for i in range(250)]}, gangguan={"geser": 99})
        # 2025 (250 baris, 3 halaman) selalu bergeser -> gagal; 2026 (10 baris, 1 halaman) tidak terpengaruh
        self.assertEqual(self.jalan(sv), 1)
        self.assertEqual((self.n("WHERE tahun=2026"), self.n("WHERE tahun=2025")), (10, 0))

    def test_tombol_hentikan(self):
        stop = threading.Event()
        stop.set()
        self.assertEqual(self.jalan(ServerSpse({2026: [baris(1)]}), berhenti=stop), 130)


if __name__ == "__main__":
    unittest.main()
