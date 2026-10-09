import json
import tempfile
import unittest
from pathlib import Path

from scraper.core import db, home

PERKIM = "DINAS PERUMAHAN RAKYAT DAN KAWASAN PERMUKIMAN"
JALAN = "1.04.05.2.01.0012.5.2.04.01.001.00004"
SALURAN = "1.04.05.2.01.0011.5.2.04.02.002.00004"
LAIN = "1.04.01.2.01.0001.5.1.02.01.001.00024"
ATURAN = {"tahun_berlaku": [2026], "tampil_di_home": ["Jalan PSU", "Saluran PSU"], "kategori": [
    {"nama": "Jalan PSU", "sub_kegiatan": ["1.04.05.2.01.0012"], "rekening": ["5.2.04.01.001.00004"]},
    {"nama": "Saluran PSU", "sub_kegiatan": ["1.04.05.2.01.0011"], "rekening": ["5.2.04.02.002.00004"]}]}
TAHAP = ["Upload Dokumen Penawaran", "Pembukaan Dokumen Penawaran", "Evaluasi Penawaran", "Klarifikasi Teknis dan Negosiasi", "Penandatanganan Kontrak"]


class TestTahap(unittest.TestCase):
    def jadwal(self, *mulai):
        return [{"no": i + 1, "tahap": TAHAP[i], "mulai": m} for i, m in enumerate(mulai)]

    def test_tahap_terakhir_yang_tanggal_mulainya_tiba(self):
        j = self.jadwal("2026-10-01T08:00", "2026-10-05T08:00", "2026-10-07T08:00", "2026-10-08T08:00", "2026-10-09T15:00")
        self.assertEqual(home.tahap_saat_ini(j, "2026-10-09"), "Penandatanganan Kontrak")      # contoh pengguna: tahanggal sama = tahap itu (jam diabaikan)
        self.assertEqual(home.tahap_saat_ini(j, "2026-10-08"), "Klarifikasi Teknis dan Negosiasi")
        self.assertEqual(home.tahap_saat_ini(j, "2026-10-02"), "Upload Dokumen Penawaran")
        self.assertIsNone(home.tahap_saat_ini(j, "2026-09-30"))
        self.assertEqual(home.tahap_saat_ini(j, "2027-01-01"), "Penandatanganan Kontrak")      # sudah lewat semua: tetap tahap terakhir

    def test_nilai_gabungan(self):
        self.assertEqual(home.nilai_gabungan({"hasil_negosiasi": 90, "hps": 100}), (90, True))
        self.assertEqual(home.nilai_gabungan({"hasil_negosiasi": None, "hps": 100}), (100, False))
        self.assertEqual(home.nilai_gabungan({"hasil_negosiasi": 0, "hps": 100}), (0, True))        # negosiasi 0 tetap dianggap ada
        self.assertEqual(home.nilai_gabungan({}), (0, False))


class TestHitung(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = db.buka(str(Path(self.tmp.name) / "t.db"))

    def rup(self, kode, nama, pagu, mak, metode="Pengadaan Langsung"):
        self.c.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,jenis,nama_paket,pagu,metode_pemilihan,is_active,link) VALUES(?,2026,1,'penyedia',?,?,?,1,'l')", (kode, nama, pagu, metode))
        self.c.execute("INSERT INTO sirup_detail(kode_rup,mak) VALUES(?,?)", (kode, mak))

    def spse(self, kode, rup, tahapan, hps, nego, jadwal, pagu=100):
        self.c.execute("INSERT INTO spse_paket(lpse,jenis,kode_paket,tahun,nama_paket,tahapan,is_active,link) VALUES('pontianak','nontender',?,2026,'x',?,1,'l')", (kode, tahapan))
        self.c.execute("INSERT INTO spse_detail(lpse,jenis,kode_paket,kode_rup,rup_json,satker,pagu,hps,hasil_negosiasi,lengkap) VALUES('pontianak','nontender',?,?,?,?,?,?,?,1)",
                       (kode, rup, json.dumps([{"kode_rup": rup, "nama_paket": "x", "sumber_dana": "APBD"}]), PERKIM, pagu, hps, nego))
        for i, m in enumerate(jadwal):
            self.c.execute("INSERT INTO spse_jadwal(lpse,jenis,kode_paket,no,tahap,mulai,sampai,jumlah_perubahan,riwayat_json) VALUES('pontianak','nontender',?,?,?,?,?,0,'[]')",
                           (kode, i + 1, TAHAP[i], m, m))

    def hitung(self, tahun=(2026,), hari="2026-10-09"):
        self.c.commit()
        return home.hitung(self.c, "pontianak", list(tahun), {PERKIM: [1]}, None, hari_ini=hari, aturan=ATURAN)

    def test_jalan_saluran_belum_tayang_batal_dan_lainnya(self):
        self.rup("1", "Belanja Modal Jalan Kota (Jl. A)", 200, JALAN)
        self.rup("2", "Belanja Modal Jalan Kota (Jl. B)", 200, JALAN)
        self.rup("3", "Pengawasan PSU Saluran Tahun 2026", 50, SALURAN)
        self.rup("4", "Belanja Modal Jalan Kota (Jl. C)", 300, JALAN)                  # belum ada di SPSE
        self.rup("5", "Belanja Modal Jalan Kota (Jl. D)", 150, JALAN)                  # SPSE batal
        self.rup("6", "Fotocopy", 10, LAIN)                                            # Lainnya: tidak masuk
        self.spse("11", "1", "Paket Sudah Selesai", 190, 180, ["2026-02-01T08:00", "2026-02-02T08:00", "2026-02-03T08:00", "2026-02-04T08:00", "2026-02-05T08:00"])
        self.spse("12", "2", "Evaluasi Penawaran", 195, None, ["2026-10-01T08:00", "2026-10-02T08:00", "2026-10-08T08:00", "2026-10-20T08:00", "2026-10-25T08:00"])
        self.spse("13", "3", "Paket Sudah Selesai", 48, 47, ["2026-03-01T08:00", "2026-03-02T08:00", "2026-03-03T08:00", "2026-03-04T08:00", "2026-03-05T08:00"])
        self.spse("15", "5", "Paket Dibatalkan", 140, None, ["2026-04-01T08:00"] * 5)
        h = self.hitung()
        self.assertFalse(h["kosong"])
        j, s, a = (h["kelompok"][k] for k in ("Jalan PSU", "Saluran PSU", "Semua"))
        self.assertEqual((j["total_paket"], s["total_paket"], a["total_paket"]), (4, 1, 5))        # 'Lainnya' tidak terhitung
        b = {x["kunci"]: x for x in j["bucket"]}
        self.assertEqual((b["tahap:Penandatanganan Kontrak"]["paket"], b["tahap:Penandatanganan Kontrak"]["nilai"]), (1, 180))         # negosiasi dipakai
        self.assertEqual((b["tahap:Evaluasi Penawaran"]["paket"], b["tahap:Evaluasi Penawaran"]["nilai"]), (1, 195))                    # belum negosiasi: HPS
        self.assertEqual((b["belum_tayang"]["paket"], b["belum_tayang"]["nilai"]), (1, 300))                                            # pagu SiRUP
        self.assertEqual((b["batal"]["paket"], b["batal"]["nilai"]), (1, 140))
        self.assertAlmostEqual(sum(x["persen"] for x in j["bucket"]), 100)
        self.assertEqual((j["paket_tayang"], j["nilai_tayang"], j["paket_negosiasi"]), (2, 375, 1))                                    # batal tidak tayang
        self.assertEqual((j["fisik"], j["konsultan"], s["konsultan"]), (4, 0, 1))
        self.assertEqual(a["total_nilai"], j["total_nilai"] + s["total_nilai"])

    def test_tahun_di_luar_aturan_kosong_dengan_pesan(self):
        h = self.hitung(tahun=(2025,))
        self.assertTrue(h["kosong"])
        self.assertIn("2026", h["pesan"])
        self.assertEqual(h["kelompok"], {})

    def test_rup_di_luar_daftar_ikut_dikategorikan_lewat_mak_hasil_periksa(self):
        self.c.execute("INSERT INTO sirup_luar_daftar(kode_rup,ditemukan,nama_paket,satker_nama,pagu,metode_pemilihan,mak,link) VALUES('9',1,'Belanja Modal Jalan Kota (Jl. X)',?,200,'Pengadaan Langsung',?,'http://s/9')", (PERKIM, JALAN))
        self.spse("19", "9", "Paket Sudah Selesai", 190, 185, ["2026-02-01T08:00"] * 5)
        h = self.hitung()
        self.assertEqual(h["kelompok"]["Jalan PSU"]["total_paket"], 1)
        self.assertEqual(h["kelompok"]["Jalan PSU"]["nilai_tayang"], 185)


if __name__ == "__main__":
    unittest.main()
