import unittest
from pathlib import Path

from scraper.core import db
from scraper.sources import sirup_detail as sd

F = Path(__file__).parent / "fixtures" / "sirup"


def baca(nama):
    return (F / nama).read_text(encoding="utf-8")


class TestParseDetail(unittest.TestCase):
    def test_penyedia_konstruksi(self):
        d = sd.parse_penyedia(baca("detail_penyedia_62728546.html"))
        self.assertEqual(d["kode_rup"], "62728546")
        self.assertEqual(d["volume"], "3131.963024939374 M2")
        self.assertEqual(d["uraian"], "Pekerjaan Jalan")
        self.assertEqual(d["spesifikasi"], "K.225 Tebal Plat Beton 12 Cm")
        self.assertEqual(d["lokasi_ringkas"], "Kalimantan Barat / Pontianak (Kota) / Kota Pontianak")
        self.assertEqual(d["total_pagu"], 700000000)
        self.assertEqual(d["sumber_dana"][0]["pagu"], 700000000)
        self.assertTrue(d["mak"].startswith("1.04.05.2.01.0012"))
        self.assertEqual(d["extra"]["jenis_pengadaan"], "Pekerjaan Konstruksi")
        self.assertEqual(d["extra"]["kontrak_mulai"], "Januari 2026")
        self.assertEqual(d["extra"]["tanggal_umumkan"], "02 Januari 2026 20:19:27")

    def test_penyedia_barang(self):
        d = sd.parse_penyedia(baca("detail_penyedia_62728266.html"))
        self.assertEqual(d["uraian"], "Fotocopy;")
        self.assertEqual(d["spesifikasi"], "Hitam Putih A4;")
        self.assertEqual(d["extra"]["jenis_pengadaan"], "Barang")

    def test_swakelola(self):
        d = sd.parse_swakelola(baca("detail_swakelola_42529798.html"))
        self.assertEqual(d["kode_rup"], "42529798")
        self.assertEqual(d["volume"], "1 Paket")
        self.assertEqual(d["uraian"], "72 Perjalanan Dinas Biasa - Dalam Negeri;")
        self.assertEqual(d["total_pagu"], 60000000)
        self.assertEqual(d["extra"]["pelaksanaan_mulai"], "Februari 2026")
        self.assertEqual(d["lokasi"][0]["kabupaten_kota"], "Pontianak (Kota)")

    def test_halaman_rusak_menimbulkan_error(self):
        with self.assertRaises(sd.DetailError):
            sd.parse_penyedia("<html><body>Data tidak ditemukan</body></html>")
        with self.assertRaises(sd.DetailError):
            sd.parse_swakelola("<html><body>kosong</body></html>")


def paket(kode, pagu=100, nama="P"):
    return {"kode_rup": kode, "tahun": 2026, "klpd_nama": "K", "id_satker": 1, "jenis": "penyedia",
            "nama_paket": nama, "penyelenggara": None, "pagu": pagu, "metode_pemilihan": "Tender",
            "sumber_dana": "APBD", "waktu_pemilihan": "Jan", "link": "x"}


class TestDetailDb(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)
        rid = db.mulai_run(self.conn, 1, 2026)
        db.finalisasi(self.conn, rid, [paket("1"), paket("2")], 1, 2026)
        db.tutup_run(self.conn, rid, "success", 2, 2)
        self.d = sd.parse_penyedia(baca("detail_penyedia_62728266.html"))
        self.rid = db.mulai_run(self.conn, 1, 2026, "SIRUP_DETAIL")

    def antre(self, semua=False):
        return [r["kode_rup"] for r in db.paket_perlu_detail(self.conn, 1, 2026, semua)]

    def test_antrean_hanya_yang_belum_ada(self):
        self.assertEqual(self.antre(), ["1", "2"])
        db.simpan_detail(self.conn, self.rid, "1", "P", 100, self.d)
        self.assertEqual(self.antre(), ["2"])
        self.assertEqual(self.antre(semua=True), ["1", "2"])

    def test_detail_lama_diambil_ulang_walau_pagu_dan_nama_sama(self):
        from datetime import datetime, timedelta
        db.simpan_detail(self.conn, self.rid, "1", "P", 100, self.d)
        db.simpan_detail(self.conn, self.rid, "2", "P", 100, self.d)
        lama = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        self.conn.execute("UPDATE sirup_detail SET diambil_pada=? WHERE kode_rup='1'", (lama,))
        self.assertEqual([r["kode_rup"] for r in db.paket_perlu_detail(self.conn, 1, 2026, usia_hari=7)], ["1"])
        self.assertEqual(db.paket_perlu_detail(self.conn, 1, 2026), [])                       # tanpa batas umur: dianggap baru
        self.assertEqual([r["kode_rup"] for r in db.paket_perlu_detail(self.conn, 1, 2026, usia_hari=30)], [])

    def test_gagal_tetap_masuk_antrean(self):
        db.catat_gagal_detail(self.conn, "2", "halaman rusak")
        self.assertEqual(self.antre(), ["1", "2"])

    def test_pagu_di_daftar_berubah_membuat_detail_basi(self):
        db.simpan_detail(self.conn, self.rid, "1", "P", 100, self.d)
        rid2 = db.mulai_run(self.conn, 1, 2026)
        db.finalisasi(self.conn, rid2, [paket("1", pagu=250), paket("2")], 1, 2026)
        self.assertIn("1", self.antre())

    def test_perubahan_isi_detail_dicatat_sebagai_event(self):
        db.simpan_detail(self.conn, self.rid, "1", "P", 100, self.d)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM paket_events").fetchone()[0], 0)
        d2 = dict(self.d, volume="999 Lembar")
        db.simpan_detail(self.conn, self.rid, "1", "P", 100, d2)
        e = self.conn.execute("SELECT field,nilai_baru FROM paket_events").fetchall()
        self.assertEqual([tuple(x) for x in e], [("detail.volume", "999 Lembar")])


if __name__ == "__main__":
    unittest.main()
