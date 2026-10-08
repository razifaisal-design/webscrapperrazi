import unittest

from scraper.core import db

T = {"tahun": 2026, "klpd_nama": "Kota Pontianak", "id_satker": 1}


def pk(kode, nama="Paket", pagu=100, jenis="penyedia", metode="Tender"):
    return {"kode_rup": kode, "tahun": 2026, "klpd_nama": "Kota Pontianak", "id_satker": 1, "jenis": jenis,
            "nama_paket": nama, "penyelenggara": None, "pagu": pagu, "metode_pemilihan": metode,
            "sumber_dana": "APBD", "waktu_pemilihan": "January 2026", "link": f"http://x/{kode}"}


def jalankan(conn, paket):
    rid = db.mulai_run(conn, 1, 2026)
    r = db.finalisasi(conn, rid, paket, 1, 2026)
    db.tutup_run(conn, rid, "success", len(paket), len(paket))
    return rid, r


class TestFinalisasi(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)

    def events(self):
        return [tuple(r) for r in self.conn.execute("SELECT jenis_event,kunci,field,nilai_lama,nilai_baru,selisih FROM paket_events ORDER BY id")]

    def test_run_pertama_baseline_tanpa_event(self):
        _, r = jalankan(self.conn, [pk("1"), pk("2")])
        self.assertTrue(r["baseline"])
        self.assertEqual(self.events(), [])

    def test_run_ulang_sama_tanpa_event_dan_tanpa_duplikat(self):
        jalankan(self.conn, [pk("1"), pk("2")])
        jalankan(self.conn, [pk("1"), pk("2")])
        self.assertEqual(self.events(), [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sirup_paket").fetchone()[0], 2)

    def test_pagu_berubah_150_ke_200(self):
        jalankan(self.conn, [pk("1", pagu=150)])
        jalankan(self.conn, [pk("1", pagu=200)])
        self.assertEqual(self.events(), [("BERUBAH", "1", "pagu", "150", "200", 50)])

    def test_baru_dan_hilang(self):
        jalankan(self.conn, [pk("1", "A"), pk("2", "B")])
        jalankan(self.conn, [pk("2", "B"), pk("3", "C")])
        jenis = sorted(e[0] for e in self.events())
        self.assertEqual(jenis, ["BARU", "HILANG"])
        self.assertEqual(self.conn.execute("SELECT is_active FROM sirup_paket WHERE kode_rup='1'").fetchone()[0], 0)

    def test_muncul_kembali(self):
        jalankan(self.conn, [pk("1"), pk("2")])
        jalankan(self.conn, [pk("2")])
        jalankan(self.conn, [pk("1"), pk("2")])
        self.assertIn("MUNCUL_KEMBALI", [e[0] for e in self.events()])

    def test_revisi_rup_nama_sama_kode_berganti(self):
        jalankan(self.conn, [pk("1", "Jalan A", 100), pk("9", "Lain")])
        jalankan(self.conn, [pk("2", "Jalan  A", 120), pk("9", "Lain")])        # spasi beda tidak masalah
        self.assertEqual(self.events(), [("REVISI_RUP", "2", "kode_rup", "1", "2", 20)])   # satu event, bukan BARU+HILANG
        baris = {r["kode_rup"]: r for r in self.conn.execute("SELECT * FROM sirup_paket")}
        self.assertEqual((baris["2"]["kode_rup_sebelumnya"], baris["1"]["kode_rup_pengganti"]), ("1", "2"))
        self.assertEqual(baris["1"]["is_active"], 0)

    def test_beberapa_nama_sama_dipasangkan_menurut_pagu_terdekat(self):
        jalankan(self.conn, [pk("1", "Fotocopy", 10), pk("2", "Fotocopy", 500)])
        jalankan(self.conn, [pk("3", "Fotocopy", 505), pk("4", "Fotocopy", 11)])
        pasang = {(e[3], e[4]) for e in self.events() if e[0] == "REVISI_RUP"}
        self.assertEqual(pasang, {("2", "3"), ("1", "4")})

    def test_nama_beda_tetap_baru_dan_hilang(self):
        jalankan(self.conn, [pk("1", "A"), pk("2", "B")])
        jalankan(self.conn, [pk("2", "B"), pk("3", "C")])
        self.assertEqual(sorted(e[0] for e in self.events()), ["BARU", "HILANG"])

    def test_kelebihan_baru_atau_hilang_tidak_dipaksa_berpasangan(self):
        jalankan(self.conn, [pk("1", "X")])
        jalankan(self.conn, [pk("2", "X"), pk("3", "X")])                       # 1 hilang, 2 baru dengan nama sama
        jenis = sorted(e[0] for e in self.events())
        self.assertEqual(jenis, ["BARU", "REVISI_RUP"])

    def test_view_gabungan_memuat_tahun_dan_status_detail(self):
        jalankan(self.conn, [pk("1"), pk("2")])
        self.conn.execute("INSERT INTO sirup_detail(kode_rup,volume,diambil_pada) VALUES('1','5 M2','x')")
        baris = {r["kode_rup"]: tuple(r) for r in self.conn.execute("SELECT kode_rup, tahun, volume, ada_detail FROM v_paket_detail")}
        self.assertEqual(baris, {"1": ("1", 2026, "5 M2", 1), "2": ("2", 2026, None, 0)})

    def test_migrasi_database_lama_tanpa_kolom_tautan(self):
        import sqlite3, tempfile, os
        d = tempfile.mkdtemp(); f = os.path.join(d, "lama.db")
        c = sqlite3.connect(f)
        c.execute("CREATE TABLE sirup_paket (kode_rup TEXT PRIMARY KEY, tahun INTEGER, klpd_nama TEXT, id_satker INTEGER, jenis TEXT, nama_paket TEXT, penyelenggara TEXT, pagu NUMERIC, metode_pemilihan TEXT, sumber_dana TEXT, waktu_pemilihan TEXT, link TEXT, first_seen TEXT, last_seen TEXT, is_active INTEGER DEFAULT 1, last_run_id INTEGER)")
        c.commit(); c.close()
        conn = db.buka(f)
        self.addCleanup(conn.close)
        self.assertIn("kode_rup_sebelumnya", {r[1] for r in conn.execute("PRAGMA table_info(sirup_paket)")})


class TestValidasi(unittest.TestCase):
    def test_jumlah_tidak_sama_dengan_situs(self):
        self.assertTrue(db.validasi([pk("1")], {"penyedia": 5}, None))

    def test_kode_ganda(self):
        self.assertTrue(db.validasi([pk("1"), pk("1")], {"penyedia": 2}, None))

    def test_penurunan_drastis_ditolak_kecuali_force(self):
        paket = [pk(str(i)) for i in range(5)]
        self.assertTrue(db.validasi(paket, {"penyedia": 5}, 100))
        self.assertFalse(db.validasi(paket, {"penyedia": 5}, 100, force=True))

    def test_valid(self):
        self.assertEqual(db.validasi([pk("1"), pk("2")], {"penyedia": 2}, 2), [])


if __name__ == "__main__":
    unittest.main()
