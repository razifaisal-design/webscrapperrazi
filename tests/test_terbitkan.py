import json
import tempfile
import unittest
from pathlib import Path

from scraper import ekspor_publik
from scraper.core import db


class Kursor:
    def __init__(self, pg):
        self.pg = pg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, par=None):
        self.pg.sql.append((sql, par))


class Pg:
    def __init__(self):
        self.sql, self.selesai, self.batal, self.tutup = [], False, False, False

    def __enter__(self):
        return self

    def __exit__(self, tipe, *a):
        self.batal, self.selesai = tipe is not None, tipe is None
        return False

    def cursor(self):
        return Kursor(self)

    def close(self):
        self.tutup = True


class TestTerbitkan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_unggah_berkas_satu_transaksi_json_jadi_jsonb_xlsx_jadi_bytea_dan_hapus_yang_usang(self):
        d = Path(self.tmp.name)
        (d / "a.json").write_text('{"x": 1}')
        (d / "b.xlsx").write_bytes(b"PK\x03\x04data")
        (d / "abaikan.txt").write_text("x")
        pg = Pg()
        n = ekspor_publik.unggah_berkas(pg, d, log=lambda *a: None)
        self.assertEqual(n, 2)
        self.assertTrue(pg.selesai)
        sql = pg.sql
        self.assertIn("::jsonb", sql[0][0])
        self.assertEqual(sql[0][1][:2], ("a.json", "json"))
        self.assertEqual(sql[1][1][:2], ("b.xlsx", "xlsx"))
        import base64
        self.assertEqual(base64.b64decode(json.loads(sql[1][1][2])["base64"]), b"PK\x03\x04data")      # xlsx utuh setelah decode
        self.assertIn("DELETE FROM public.publik_berkas", sql[-1][0])
        self.assertEqual(sql[-1][1], (["a.json", "b.xlsx"],))                      # selain berkas ini dihapus

    def test_terbitkan_menaruh_data_di_supabase_dan_halaman_kecil_tanpa_data(self):
        path = str(Path(self.tmp.name) / "t.db")
        conn = db.buka(path)
        conn.execute("INSERT INTO spse_paket(lpse,jenis,kode_paket,tahun,nama_paket,tahapan,is_active,link) VALUES('pontianak','nontender','900',2026,'Uji','x',1,'l')")
        conn.commit()
        conn.close()
        keluar = Path(self.tmp.name) / "publik"
        pg = Pg()
        kfg = {"supabase_url": "https://abc.supabase.co", "kunci_publikasi": "sb_publishable_uji"}
        r = ekspor_publik.terbitkan(path, keluar, "postgresql://uji", kfg, log=lambda *a: None, dengan_excel=False, connect=lambda url, **kw: pg)
        self.assertGreater(r["berkas"], 3)
        self.assertTrue(pg.tutup and pg.selesai)
        self.assertFalse((keluar / "data").exists())                                  # data tidak ikut diunggah ke hosting halaman
        h = (keluar / "index.html").read_text(encoding="utf-8")
        self.assertIn('window.PANTAU_SUPABASE={"url": "https://abc.supabase.co", "kunci": "sb_publishable_uji"}', h)
        self.assertLess(h.index("PANTAU_SUPABASE"), h.index('<script src="statis.js">'))     # konfigurasi dimuat sebelum shim
        self.assertLess(r["ukuran_mb"], 1.0)
        nama = {p[1][0] for p in pg.sql if p[1] and isinstance(p[1][0], str) and p[1][0].endswith(".json")}
        self.assertIn("spse_2026.json", nama)
        self.assertIn("meta.json", nama)

    def test_penerbitan_gagal_tidak_mengubah_folder_publik_lama(self):
        path = str(Path(self.tmp.name) / "t.db")
        db.buka(path).close()
        keluar = Path(self.tmp.name) / "publik"
        keluar.mkdir()
        (keluar / "index.html").write_text("LAMA")

        def gagal(url, **kw):
            raise OSError("tidak bisa konek")
        with self.assertRaises(OSError):
            ekspor_publik.terbitkan(path, keluar, "postgresql://uji", {"supabase_url": "u", "kunci_publikasi": "k"}, log=lambda *a: None,
                                    dengan_excel=False, connect=gagal)
        self.assertEqual((keluar / "index.html").read_text(), "LAMA")

    def test_muat_konfig_publik(self):
        p = Path(self.tmp.name) / "publik.json"
        p.write_text(json.dumps({"supabase_url": "u", "kunci_publikasi": "k"}))
        self.assertEqual(ekspor_publik.muat_konfig_publik(p)["kunci_publikasi"], "k")
        p.write_text(json.dumps({"supabase_url": "u"}))
        self.assertIsNone(ekspor_publik.muat_konfig_publik(p))
        self.assertIsNone(ekspor_publik.muat_konfig_publik(Path(self.tmp.name) / "tidak-ada.json"))


if __name__ == "__main__":
    unittest.main()
