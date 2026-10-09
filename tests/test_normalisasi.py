import json
import tempfile
import unittest
from pathlib import Path

from scraper.core import banding, db
from scraper.sources import spse

PERKIM = "DINAS PERUMAHAN RAKYAT DAN KAWASAN PERMUKIMAN"


class TestBersihkanNama(unittest.TestCase):
    def test_badge_ulang_dibuang(self):
        self.assertEqual(spse.bersihkan_nama('Perencanaan Toilet di RPH Babi <span class="badge badge-warning">Pengadaan Langsung Ulang</span>'),
                         "Perencanaan Toilet di RPH Babi")
        self.assertEqual(spse.bersihkan_nama("Jalan A &amp; B  <b>x</b> sisa <br> tag"), "Jalan A & B sisa tag")
        self.assertEqual(spse.bersihkan_nama(None), "")
        self.assertEqual(spse.bersihkan_nama("Paket biasa tanpa HTML"), "Paket biasa tanpa HTML")

    def test_parse_baris_memakai_nama_bersih_dan_raw_tetap(self):
        baris = ["10500423000", 'Perencanaan Kandang <span class="badge">Pengadaan Langsung Ulang</span>', "Kota Pontianak", "Paket Sudah Selesai",
                 "10 Jt", "Pengadaan Langsung", "Jasa Konsultansi - TA 2025", "5", "Rp. 1", None, "0", "0"]
        p = spse.parse_baris(baris, "pontianak", "nontender", 2025)
        self.assertEqual(p["nama_paket"], "Perencanaan Kandang")
        self.assertIn("badge", json.dumps(p["raw"]))                                    # info mentah tidak hilang


class TestNormSatker(unittest.TestCase):
    def test_tanda_baca_dan_ejaan_disatukan(self):
        n = db.norm_satker
        self.assertEqual(n("DINAS PANGAN. PERTANIAN DAN PERIKANAN"), n("Dinas Pangan, Pertanian  dan Perikanan"))
        self.assertEqual(n("DINAS PERUMAHAN RAKYAT DAN KAWASAN PEMUKIMAN"), n(PERKIM))
        self.assertNotEqual(n("DINAS KESEHATAN"), n("DINAS PENDIDIKAN"))
        self.assertEqual(n(None), "")

    def test_nama_kanonik_pilih_yang_paling_sering(self):
        k = db.nama_kanonik(["DINAS X, Y", "DINAS X. Y", "DINAS X. Y", "LAIN"])
        self.assertEqual(k[db.norm_satker("DINAS X Y")], "DINAS X. Y")
        self.assertEqual(len(k), 2)


class TestMigrasiNamaKotor(unittest.TestCase):
    def test_nama_lama_berisi_html_dibersihkan_saat_database_dibuka(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "t.db")
            c = db.buka(path)
            c.execute("INSERT INTO spse_paket(lpse,jenis,kode_paket,tahun,nama_paket) VALUES('p','nontender','1',2025,?)", ('Toilet <span class="badge">Pengadaan Langsung Ulang</span>',))
            c.execute("INSERT INTO spse_paket(lpse,jenis,kode_paket,tahun,nama_paket) VALUES('p','nontender','2',2025,'Bersih')")
            c.commit()
            c.close()
            c = db.buka(path)
            self.assertEqual([r[0] for r in c.execute("SELECT nama_paket FROM spse_paket ORDER BY kode_paket")], ["Toilet", "Bersih"])
            c.close()


class TestBandingSatkerSatu(unittest.TestCase):
    def test_dua_ejaan_satker_menjadi_satu_dan_cocok_dengan_sirup(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = db.buka(str(Path(tmp) / "t.db"))
            c.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,jenis,nama_paket,pagu,metode_pemilihan,is_active,link) VALUES('1',2021,1,'penyedia','Jalan A',100,'Pengadaan Langsung',1,'l')")
            for kode, rup, sat in (("11", "1", "DINAS PERUMAHAN RAKYAT DAN KAWASAN PEMUKIMAN"), ("12", "2", PERKIM)):
                c.execute("INSERT INTO spse_paket(lpse,jenis,kode_paket,tahun,nama_paket,tahapan,is_active,link) VALUES('p','nontender',?,2021,?,'x',1,'l')", (kode, f"Jalan {rup}"))
                c.execute("INSERT INTO spse_detail(lpse,jenis,kode_paket,kode_rup,rup_json,satker,pagu,lengkap) VALUES('p','nontender',?,?,?,?,100,1)",
                          (kode, rup, json.dumps([{"kode_rup": rup, "nama_paket": "x", "sumber_dana": "APBD"}]), sat))
            h = banding.hitung(c, "p", "nontender", [2021], {PERKIM: [1]}, sekarang="2021-06-01T00:00")
            self.assertEqual({b["satker"] for b in h["baris"]}, {PERKIM})                      # satu satker, bukan dua
            satu = [b for b in h["baris"] if b.get("kode_rup") == "1"][0]
            self.assertEqual(satu["kode_nontender"], "11")                                    # paket ber-ejaan lama ikut dicocokkan ke SiRUP
            self.assertEqual([d["nama"] for d in h["satker_daftar"]], [PERKIM])


if __name__ == "__main__":
    unittest.main()
