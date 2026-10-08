import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scraper import konfig, tugas
from scraper.core import db, semua_tahun, statistik

TAHUN = 2021
DEFAULT, LAMA = 173394, 69427


class KlienPalsu:
    """Meniru endpoint DataTables SiRUP: {(idSatker, tahun, jenis): [baris...]}; selain itu 0 paket (seperti SiRUP asli)."""
    data = {}
    permintaan = []

    def __init__(self, jeda=0):
        pass

    def close(self):
        pass

    def get_json(self, url, params=None):
        jenis = "penyedia" if "penyedia" in url else "swakelola"
        KlienPalsu.permintaan.append((params["idSatker"], params["tahun"], jenis))
        baris = KlienPalsu.data.get((params["idSatker"], params["tahun"], jenis), [])
        a = params["iDisplayStart"]
        return {"aaData": baris[a:a + params["iDisplayLength"]], "iTotalDisplayRecords": len(baris), "sEcho": 1}


def baris_penyedia(n, mulai=1000):
    return [[str(mulai + i), f"Paket {mulai + i}", "1000", "Tender", "APBD, APBD", str(mulai + i), "Jan"] for i in range(n)]


def target(id_satker=DEFAULT, tahun=TAHUN):
    return {"id_satker": id_satker, "tahun": tahun, "satker_nama": "S", "klpd_nama": "K", "id_satker_semua": sorted({LAMA, DEFAULT})}


class Dasar(unittest.TestCase):
    def setUp(self):
        KlienPalsu.data, KlienPalsu.permintaan = {}, []
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)
        self.log = []
        p = mock.patch.object(konfig, "simpan_id_satker", mock.Mock(return_value=True))
        self.simpan = p.start()
        self.addCleanup(p.stop)

    def jalankan(self, tgt, **kw):
        return tugas.run_daftar(self.conn, tgt, jeda=0.2, ekspor=False, log=self.log.append, buat_klien=KlienPalsu, **kw)


class TestTentukan(Dasar):
    def test_data_yang_sudah_ada_dipercaya_tanpa_permintaan_jaringan(self):
        self.conn.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,is_active) VALUES('1',?,?,1)", (TAHUN, DEFAULT))
        self.assertEqual(tugas.tentukan_id_satker(self.conn, target(), KlienPalsu(), self.log.append), (DEFAULT, False))
        self.assertEqual(KlienPalsu.permintaan, [])

    def test_id_dari_config_benar(self):
        KlienPalsu.data = {(DEFAULT, TAHUN, "penyedia"): baris_penyedia(3)}
        self.assertEqual(tugas.tentukan_id_satker(self.conn, target(), KlienPalsu(), self.log.append), (DEFAULT, False))

    def test_id_salah_lalu_ditemukan_id_lain_yang_dikenal(self):
        KlienPalsu.data = {(LAMA, TAHUN, "penyedia"): baris_penyedia(5)}           # 2021: hanya 69427 yang punya data
        hasil = tugas.tentukan_id_satker(self.conn, target(DEFAULT), KlienPalsu(), self.log.append)
        self.assertEqual(hasil, (LAMA, True))
        self.assertTrue(any("memakai 69427" in x for x in self.log))

    def test_tidak_ada_yang_cocok(self):
        self.assertEqual(tugas.tentukan_id_satker(self.conn, target(), KlienPalsu(), self.log.append), (None, False))


class TestRunDaftar(Dasar):
    def test_nol_paket_BUKAN_sukses_dan_menjelaskan_penyebabnya(self):
        kode = self.jalankan(target())
        self.assertEqual(kode, 3)
        run = self.conn.execute("SELECT status, catatan FROM scrape_runs ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(run["status"], "invalid")
        self.assertIn("idSatker", run["catatan"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sirup_paket").fetchone()[0], 0)
        self.assertTrue(any("TIDAK ADA DATA" in x for x in self.log))
        self.simpan.assert_not_called()

    def test_id_otomatis_berganti_data_tersimpan_dengan_id_yang_benar_dan_dicatat_ke_config(self):
        KlienPalsu.data = {(LAMA, TAHUN, "penyedia"): baris_penyedia(120)}         # 120 paket -> 2 halaman
        kode = self.jalankan(target(DEFAULT))
        self.assertEqual(kode, 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*), MIN(id_satker), MAX(id_satker) FROM sirup_paket").fetchone()[:], (120, LAMA, LAMA))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sirup_paket WHERE sumber_dana LIKE '%,%'").fetchone()[0], 0)   # sumber dana rapi
        self.simpan.assert_called_once_with(TAHUN, LAMA)

    def test_run_kedua_tidak_menguji_ulang_idsatker(self):
        KlienPalsu.data = {(DEFAULT, TAHUN, "penyedia"): baris_penyedia(4)}
        self.assertEqual(self.jalankan(target(DEFAULT)), 0)
        KlienPalsu.permintaan.clear()
        self.assertEqual(self.jalankan(target(DEFAULT)), 0)
        self.assertEqual(len(KlienPalsu.permintaan), 2)                           # hanya 1 halaman penyedia + 1 swakelola, tanpa probe tambahan

    def test_run_semua_memakai_id_hasil_penentuan_di_tahap_detail(self):
        KlienPalsu.data = {(LAMA, TAHUN, "penyedia"): baris_penyedia(3)}
        dipakai = {}

        def detail(conn, tgt, **k):
            dipakai["id"] = tgt["id_satker"]
            return 0
        with mock.patch.object(tugas, "run_detail", detail):
            kode = tugas.run_semua(self.conn, target(DEFAULT), koneksi=1, jeda=0.2, log=self.log.append, buat_klien=KlienPalsu)
        self.assertEqual((kode, dipakai["id"]), (0, LAMA))

    def test_run_semua_berhenti_bila_tidak_ada_data(self):
        detail = mock.Mock(return_value=0)
        with mock.patch.object(tugas, "run_detail", detail):
            kode = tugas.run_semua(self.conn, target(), koneksi=1, jeda=0.2, log=self.log.append, buat_klien=KlienPalsu)
        self.assertEqual(kode, 3)
        detail.assert_not_called()


class TestKonfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "t.json"
        self.path.write_text(json.dumps({"default": "a", "targets": {"a": {"id_satker": DEFAULT, "tahun": 2026,
                                         "id_satker_per_tahun": {"2021": LAMA}, "satker_nama": "Dinas Ä"}}}))
        p = mock.patch.object(konfig, "TARGETS", self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_id_per_tahun_dan_daftar_semua_id(self):
        for th, harap in ((2021, LAMA), (2022, DEFAULT), (2026, DEFAULT), (None, DEFAULT)):
            t = konfig.muat_target(None, th)[1]
            self.assertEqual(t["id_satker"], harap, th)
            self.assertEqual(t["id_satker_semua"], sorted({LAMA, DEFAULT}))

    def test_penimpa_id_dari_pengguna(self):
        t = konfig.muat_target(None, 2019, id_satker=555)[1]
        self.assertEqual((t["id_satker"], 555 in t["id_satker_semua"]), (555, True))

    def test_simpan_id_satker_menulis_config_dan_tidak_merusak_isi_lain(self):
        self.assertTrue(konfig.simpan_id_satker(2020, LAMA))
        self.assertEqual(konfig.muat_target(None, 2020)[1]["id_satker"], LAMA)
        cfg = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(cfg["targets"]["a"]["id_satker_per_tahun"], {"2020": LAMA, "2021": LAMA})   # terurut
        self.assertEqual(cfg["targets"]["a"]["satker_nama"], "Dinas Ä")                              # isi lain utuh (Unicode)
        self.assertFalse(konfig.simpan_id_satker(2020, LAMA))                                        # tidak berubah -> tidak ditulis ulang
        self.assertTrue(konfig.simpan_id_satker(2020, DEFAULT))                                      # kembali ke bawaan -> entri dihapus
        self.assertNotIn("2020", json.loads(self.path.read_text())["targets"]["a"]["id_satker_per_tahun"])
        self.assertFalse(list(Path(self.tmp.name).glob("*.tmp")))                                    # tidak meninggalkan berkas sementara


class TestDataLintasId(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)
        for kode, th, sat in (("1", 2021, LAMA), ("2", 2021, LAMA), ("3", 2022, DEFAULT), ("4", 2026, DEFAULT)):
            self.conn.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,jenis,nama_paket,pagu,is_active,sumber_dana) "
                              "VALUES(?,?,?,?,?,?,1,'APBD')", (kode, th, sat, "penyedia", f"P{kode}", 10))

    def test_tahun_dipetakan_ke_id_menurut_data(self):
        self.assertEqual(db.id_satker_per_tahun(self.conn, [DEFAULT, LAMA]), {2021: LAMA, 2022: DEFAULT, 2026: DEFAULT})
        self.assertEqual(db.id_satker_per_tahun(self.conn, DEFAULT), {2022: DEFAULT, 2026: DEFAULT})    # id lain tidak ikut

    def test_semua_tahun_dan_statistik_menyertakan_tahun_dengan_id_berbeda(self):
        ambil = lambda th: {"id_satker": DEFAULT, "tahun": th, "klasifikasi": None, "satker_nama": "S", "klpd_nama": "K"}
        st = statistik.statistik_semua(self.conn, ambil, [DEFAULT, LAMA])
        self.assertEqual(st["tahun"], [2021, 2022, 2026])
        self.assertEqual(st["per_tahun"]["2021"]["paket"], 2)                                            # 2021 (id 69427) terbaca

    def test_run_kosong_lama_yang_dicatat_sukses_ditandai_tidak_valid(self):
        import tempfile as tf
        f = os.path.join(tf.mkdtemp(), "m.db")
        c = db.buka(f)
        c.execute("INSERT INTO scrape_runs(sumber,id_satker,tahun,mulai,status,jumlah_baris) VALUES('SIRUP',1,2021,'x','success',0)")
        c.execute("INSERT INTO scrape_runs(sumber,id_satker,tahun,mulai,status,jumlah_baris) VALUES('SIRUP',1,2026,'x','success',979)")
        c.commit(); c.close()
        c = db.buka(f)
        self.addCleanup(c.close)
        self.assertEqual([r[0] for r in c.execute("SELECT status FROM scrape_runs ORDER BY id")], ["invalid", "success"])


if __name__ == "__main__":
    unittest.main()
