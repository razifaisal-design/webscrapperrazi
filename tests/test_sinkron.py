import sqlite3
import tempfile
import unittest
from pathlib import Path

from scraper import sinkron
from scraper.core import db


class FakeCopy:
    def __init__(self, pg, tabel):
        self.pg, self.tabel = pg, tabel

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def write_row(self, baris):
        self.pg.rows.setdefault(self.tabel, []).append(list(baris))


class FakeCursor:
    def __init__(self, pg):
        self.pg, self._hasil = pg, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, par=None):
        self.pg.sql.append((sql, par))
        if sql.startswith("TRUNCATE"):
            self.pg.rows = {}
        if sql.startswith("SELECT count(*)"):
            tabel = sql.split("public.")[1].strip('"')
            self._hasil = (len(self.pg.rows.get(tabel, [])) + self.pg.selisih.get(tabel, 0),)

    def copy(self, sql):
        tabel = sql.split("public.")[1].split(" ")[0].strip('"')
        self.pg.copy_sql.append(sql)
        return FakeCopy(self.pg, tabel)

    def fetchone(self):
        return self._hasil


class FakePg:
    def __init__(self, selisih=None):
        self.sql, self.copy_sql, self.rows, self.selisih, self.selesai, self.batal = [], [], {}, selisih or {}, False, False

    def __enter__(self):
        return self

    def __exit__(self, tipe, *a):
        self.batal = tipe is not None
        self.selesai = tipe is None
        return False

    def cursor(self):
        return FakeCursor(self)


class TestSinkron(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "t.db")
        c = db.buka(self.path)
        c.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,jenis,nama_paket,pagu,is_active) VALUES('1',2026,5,'penyedia',?,100.5,1)", ("Paket\x00NUL",))
        c.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,jenis,nama_paket,pagu,is_active) VALUES('2',2026,5,'penyedia','B',200,1)")
        c.execute("INSERT INTO spse_jadwal(lpse,jenis,kode_paket,no,tahap) VALUES('p','nontender','9',1,'Upload')")
        c.commit()
        c.close()

    def test_skema_ddl_idempoten_aman_dan_lengkap(self):
        c = sqlite3.connect(self.path)
        sk = sinkron.skema_lokal(c)
        # tabel lokasi (paket_lokasi, ref_jalan, ref_gang) baru ada setelah database Jalan/Gang dibangun; yang belum ada dilewati
        self.assertEqual(set(sk), set(sinkron.TABEL) - {"paket_lokasi", "ref_jalan", "ref_gang"})
        sql = sinkron.ddl(sk)
        self.assertTrue(all(("IF NOT EXISTS" in s) or ("IF NOT EXISTS" in s) or s.startswith(("ALTER TABLE", "REVOKE")) for s in sql))
        for t in sk:
            self.assertIn(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY', sql)           # tidak ada tabel terbuka ke publik
            self.assertIn(f'REVOKE ALL ON TABLE public."{t}" FROM anon, authenticated', sql)
        self.assertTrue(any('PRIMARY KEY ("lpse", "jenis", "kode_paket", "no")' in s for s in sql))
        self.assertTrue(any('"pagu" numeric' in s for s in sql))

    def test_sinkron_cerminkan_dalam_satu_transaksi_dan_bersihkan_nul(self):
        pg = FakePg()
        jumlah = sinkron.sinkron(self.path, url="postgresql://x", log=lambda *a: None, connect=lambda url, **kw: pg)
        self.assertEqual((jumlah["sirup_paket"], jumlah["spse_jadwal"], jumlah["spse_detail"]), (2, 1, 0))
        self.assertTrue(pg.selesai)
        urutan = [s for s, _ in pg.sql]
        self.assertTrue(urutan[0].startswith("CREATE TABLE"))
        self.assertLess([i for i, s in enumerate(urutan) if s.startswith("TRUNCATE")][0], len(urutan))
        self.assertTrue(any(s.startswith("INSERT INTO public.sinkron_riwayat") for s in urutan))
        self.assertEqual(pg.rows["sirup_paket"][0][5], "PaketNUL")                      # karakter NUL dibuang (Postgres menolaknya)
        self.assertEqual(pg.rows["sirup_paket"][0][7], 100.5)

    def test_jumlah_tidak_sama_membatalkan_semuanya(self):
        pg = FakePg(selisih={"sirup_paket": 1})
        with self.assertRaises(sinkron.SinkronError) as e:
            sinkron.sinkron(self.path, url="postgresql://x", log=lambda *a: None, connect=lambda url, **kw: pg)
        self.assertIn("Supabase tidak berubah", str(e.exception))
        self.assertTrue(pg.batal)                                                       # keluar transaksi lewat galat = rollback

    def test_url_default_tidak_dibaca_dari_env_asli_saat_diuji(self):
        # sinkron(url=...) eksplisit tidak pernah memakai .env; jaminan agar uji tidak menyentuh Supabase milik pengguna
        pg = FakePg()
        sinkron.sinkron(self.path, url="postgresql://uji", log=lambda *a: None, connect=lambda url, **kw: pg)
        self.assertTrue(pg.selesai)

    def test_tanpa_url_atau_gagal_konek_pesan_jelas_tanpa_membocorkan_url(self):
        with self.assertRaises(sinkron.SinkronError) as e:
            sinkron.sinkron(self.path, url=None, log=print, connect=lambda *a, **k: None) if sinkron.url_db() is None else self.skipTest("url ada di lingkungan")
        self.assertIn("SUPABASE_DB_URL", str(e.exception))

        def gagal(url, **kw):
            raise OSError("password authentication failed for postgres:RAHASIA")
        with self.assertRaises(sinkron.SinkronError) as e:
            sinkron.sinkron(self.path, url="postgresql://postgres:RAHASIA@h/db", log=print, connect=gagal)
        self.assertNotIn("RAHASIA", str(e.exception))

    def test_url_masih_berisi_placeholder_ditolak_sebelum_konek(self):
        dipanggil = []
        with self.assertRaises(sinkron.SinkronError) as e:
            sinkron.sinkron(self.path, url="postgresql://u:[YOUR-PASSWORD]@h/db", log=print, connect=lambda *a, **k: dipanggil.append(1))
        self.assertIn("YOUR-PASSWORD", str(e.exception))
        self.assertEqual(dipanggil, [])

    def test_muat_env(self):
        env = Path(self.tmp.name) / ".env"
        env.write_text('# komentar\nSUPABASE_DB_URL="postgresql://u:p@h/db"\nLAIN=1\n', encoding="utf-8")
        self.assertEqual(sinkron.muat_env(env)["SUPABASE_DB_URL"], "postgresql://u:p@h/db")


if __name__ == "__main__":
    unittest.main()


class FakeCursorTarik:
    def __init__(self, pg):
        self.pg, self.hasil = pg, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, par=None):
        if "information_schema" in sql:
            self.hasil = [(k,) for k in self.pg.kolom.get(par[0], [])]
        else:
            tabel = sql.split('public."')[1].rstrip('"')
            diminta = [x.strip().strip('"') for x in sql[len("SELECT "):sql.index(" FROM ")].split(",")]
            urut = self.pg.kolom.get(tabel, [])
            self.hasil = [tuple(baris[urut.index(k)] for k in diminta) for baris in self.pg.data.get(tabel, [])]

    def fetchall(self):
        return self.hasil


class FakePgTarik:
    def __init__(self, kolom, data):
        self.kolom, self.data = kolom, data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return FakeCursorTarik(self)


class TestTarik(unittest.TestCase):
    def setUp(self):
        from decimal import Decimal
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "data" / "pantau.db"
        kol = ["kode_rup", "tahun", "id_satker", "nama_paket", "pagu", "is_active", "kolom_baru_di_supabase"]
        self.pg = FakePgTarik({"sirup_paket": kol}, {"sirup_paket": [("1", 2026, 5, "A", Decimal("100.50"), 1, "x"), ("2", 2026, 5, "B", Decimal("200"), 1, "y")]})

    def tarik(self, **kw):
        return sinkron.tarik(self.path, url="postgresql://uji", log=lambda *a: None, connect=lambda url, **k: self.pg, **kw)

    def test_bangun_database_dari_cermin_dengan_tipe_benar(self):
        jumlah = self.tarik()
        self.assertEqual(jumlah["sirup_paket"], 2)
        c = sqlite3.connect(self.path)
        self.assertEqual([tuple(r) for r in c.execute("SELECT kode_rup, pagu FROM sirup_paket ORDER BY kode_rup")], [("1", 100.5), ("2", 200)])
        self.assertIsInstance(c.execute("SELECT pagu FROM sirup_paket WHERE kode_rup='2'").fetchone()[0], int)      # Decimal bulat -> int
        self.assertTrue(c.execute("SELECT name FROM sqlite_master WHERE name='paket_lokasi'").fetchone())          # tabel lokasi ikut dibuat
        self.assertFalse(Path(str(self.path) + ".tarik").exists())

    def test_database_yang_sudah_ada_tidak_ditimpa_tanpa_paksa(self):
        self.tarik()
        with self.assertRaises(sinkron.SinkronError) as e:
            self.tarik()
        self.assertIn("--paksa", str(e.exception))
        self.tarik(paksa=True)
        self.assertTrue(Path(str(self.path) + ".sebelum-tarik").exists())                                          # yang lama disimpan

    def test_gagal_di_tengah_tidak_meninggalkan_berkas_setengah(self):
        def gagal(url, **kw):
            raise OSError("putus")
        with self.assertRaises(sinkron.SinkronError):
            sinkron.tarik(self.path, url="postgresql://uji", log=lambda *a: None, connect=gagal)
        self.assertFalse(self.path.exists())
        self.assertFalse(Path(str(self.path) + ".tarik").exists())
