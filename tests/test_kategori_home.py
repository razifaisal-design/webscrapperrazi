import sqlite3
import tempfile
import unittest
from pathlib import Path

from scraper.core import db, kategori_home as kh, mak_ref

A = {"tahun_berlaku": [2026], "kategori": [
    {"nama": "Jalan PSU", "sub_kegiatan": ["1.04.05.2.01.0012"], "rekening": ["5.2.04.01.001.00004"]},
    {"nama": "Saluran PSU", "sub_kegiatan": ["1.04.05.2.01.0011"], "rekening": ["5.2.04.02.002.00004"]},
    {"nama": "Jalan Kawasan Permukiman", "sub_kegiatan": ["1.04.03.2.03.0013"], "rekening": ["5.2.04.01.001.00004"]}]}


class TestMak(unittest.TestCase):
    def test_pemecahan(self):
        m = "1.04.05.2.01.0012.5.2.04.01.001.00004"
        self.assertEqual(mak_ref.kode_sub_kegiatan(m), "1.04.05.2.01.0012")
        self.assertEqual(mak_ref.kode_rekening(m), "5.2.04.01.001.00004")
        self.assertEqual(mak_ref.kode_rekening(m + ".1.3.04.01.01.0004.00299"), "5.2.04.01.001.00004")        # segmen setelah ke-12 diabaikan
        self.assertEqual(mak_ref.kode_rekening(m + "."), "5.2.04.01.001.00004")                                  # titik di ujung
        self.assertIsNone(mak_ref.kode_sub_kegiatan(""))
        self.assertIsNone(mak_ref.kode_rekening("1.04.05.2.01.02"))
        self.assertEqual(mak_ref.daftar_mak("A.1; B.2 ;; "), ["A.1", "B.2"])


class TestKategori(unittest.TestCase):
    def test_tiga_kategori_dan_lainnya(self):
        k = lambda m, t=2026: kh.kategori(m, t, A)                                      # noqa: E731
        self.assertEqual(k("1.04.05.2.01.0012.5.2.04.01.001.00004"), "Jalan PSU")
        self.assertEqual(k("1.04.05.2.01.0011.5.2.04.02.002.00004"), "Saluran PSU")
        self.assertEqual(k("1.04.03.2.03.0013.5.2.04.01.001.00004.1.3.04.01.01.0004.00299"), "Jalan Kawasan Permukiman")   # ekor MAK tidak mengganggu
        self.assertIsNone(k("1.04.05.2.01.0012.5.1.02.01.001.00024"))                 # sub kegiatan PSU tetapi bukan belanja jalan: Lainnya
        self.assertIsNone(k("1.04.03.2.03.0013.5.2.04.02.002.00004"))                 # rekening saluran di sub kegiatan kawasan: tidak ada aturannya
        self.assertIsNone(k("1.04.05.2.01.0002.5.2.04.01.001.00004"))                 # format 2024-2025 tidak dikenal
        self.assertIsNone(k("1.04.05.2.01.0012.5.2.04.01.001.00004", 2025))           # di luar tahun berlaku
        self.assertEqual(k("1.04.01.2.01.0001.5.1.02.01.001.00024; 1.04.05.2.01.0011.5.2.04.02.002.00004"), "Saluran PSU")   # MAK ganda: yang cocok dipakai

    def test_fisik_atau_konsultan_dari_nama(self):
        self.assertEqual(kh.jenis_pekerjaan("Pengawasan PSU Jalan Tahun 2026 Kecamatan Pontianak Utara"), "Konsultan")
        self.assertEqual(kh.jenis_pekerjaan("Belanja Modal Jalan Kota (Jl. Flora, Gg. Flora 4)"), "Fisik")


class TestImpor(unittest.TestCase):
    def test_impor_idempoten_dan_field_sub_kegiatan_tidak_menebak_nama(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "mak.db"
            s = sqlite3.connect(src)
            s.executescript("""
              CREATE TABLE bidang_urusan(kode_bidang TEXT, nama_bidang TEXT, kode_urusan TEXT);
              CREATE TABLE program(kode_program TEXT, nama_program TEXT, kode_bidang TEXT);
              CREATE TABLE kegiatan(kode_kegiatan TEXT, nama_kegiatan TEXT, kode_program TEXT);
              CREATE TABLE unit_organisasi(kode_unit TEXT, nama_unit TEXT, kode_bidang TEXT);
              CREATE TABLE sub_kegiatan(kode_sub_kegiatan TEXT, nama_sub_kegiatan TEXT, kode_kegiatan TEXT, kode_unit TEXT, kode_sub_unit TEXT, spm TEXT, jenis_layanan TEXT, sumber_dana_header TEXT);
              CREATE TABLE rekening(kode_rekening TEXT, nama_rekening TEXT, akun TEXT, kelompok TEXT, jenis TEXT, objek TEXT, rincian TEXT, sub_rincian TEXT, kategori TEXT);
              CREATE TABLE mak(kode_mak_full TEXT, kode_sub_kegiatan TEXT, kode_rekening TEXT, file_sumber TEXT);
              INSERT INTO bidang_urusan VALUES('1.04','BIDANG PERKIM','1');
              INSERT INTO program VALUES('1.04.05','PROGRAM PSU','1.04');
              INSERT INTO kegiatan VALUES('1.04.05.2.01','Urusan PSU','1.04.05');
              INSERT INTO unit_organisasi VALUES('U1','DINAS PERKIM','1.04');
              INSERT INTO sub_kegiatan VALUES('1.04.05.2.01.0012','Penyediaan PSU di Perumahan','1.04.05.2.01','U1','-','','','');
              INSERT INTO rekening VALUES('5.2.04.01.001.00004','Belanja Modal Jalan Kota','5','2','04','01','001','00004','BELANJA MODAL');
              INSERT INTO mak VALUES('1.04.05.2.01.0012.5.2.04.01.001.00004','1.04.05.2.01.0012','5.2.04.01.001.00004','f');""")
            s.commit(); s.close()
            c = db.buka(str(Path(tmp) / "t.db"))
            for kode, mak in (("1", "1.04.05.2.01.0012.5.2.04.01.001.00004"), ("2", "1.04.05.2.01.0002.5.2.04.01.001.00004"), ("3", None)):
                c.execute("INSERT INTO sirup_detail(kode_rup,mak) VALUES(?,?)", (kode, mak))
            c.commit()
            self.assertEqual(mak_ref.impor(c, src, log=lambda *a: None), {"sub_kegiatan": 1, "mak": 1})
            mak_ref.impor(c, src, log=lambda *a: None)                                               # ulang: tidak menggandakan
            self.assertEqual(c.execute("SELECT COUNT(*) FROM ref_sub_kegiatan").fetchone()[0], 1)
            mak_ref.isi_sub_kegiatan(c)
            hasil = {r[0]: (r[1], r[2]) for r in c.execute("SELECT kode_rup, sub_kegiatan_kode, sub_kegiatan_nama FROM sirup_detail")}
            self.assertEqual(hasil["1"], ("1.04.05.2.01.0012", "Penyediaan PSU di Perumahan"))
            self.assertEqual(hasil["2"], ("1.04.05.2.01.0002", None))                                 # kode ada, nama belum diketahui: tidak ditebak
            self.assertEqual(hasil["3"], (None, None))
            self.assertEqual(c.execute("SELECT nama_bidang, nama_program, nama_unit FROM ref_sub_kegiatan").fetchone()[:], ("BIDANG PERKIM", "PROGRAM PSU", "DINAS PERKIM"))


if __name__ == "__main__":
    unittest.main()
