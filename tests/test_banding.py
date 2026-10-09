import json
import tempfile
import unittest
from pathlib import Path

from scraper.core import banding, db

SATKER = "DINAS PERUMAHAN RAKYAT DAN KAWASAN PERMUKIMAN"
SEKARANG = "2026-05-10T12:00"


class TestBanding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = db.buka(str(Path(self.tmp.name) / "t.db"))

    def rup(self, kode, nama, pagu=100, metode="Pengadaan Langsung", jenis="penyedia", aktif=1, pengganti=None, tahun=2026):
        self.c.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,jenis,nama_paket,pagu,metode_pemilihan,is_active,kode_rup_pengganti,link) "
                       "VALUES(?,?,1,?,?,?,?,?,?,'l')", (kode, tahun, jenis, nama, pagu, metode, aktif, pengganti))

    def spse(self, kode, nama, rups, satker=SATKER, pagu=100, hps=99, mulai="2026-04-01T08:00", tahapan="Evaluasi Penawaran",
             detail=True, perubahan=0, riwayat=None, tahun=2026):
        self.c.execute("INSERT INTO spse_paket(lpse,jenis,kode_paket,tahun,nama_paket,tahapan,is_active,link) VALUES('p','nontender',?,?,?,?,1,'l')",
                       (kode, tahun, nama, tahapan))
        if not detail:
            return
        self.c.execute("INSERT INTO spse_detail(lpse,jenis,kode_paket,kode_rup,rup_json,satker,pagu,hps,lengkap,harga_penawaran,hasil_negosiasi,pemenang_terisi,kontrak_terisi) "
                       "VALUES('p','nontender',?,?,?,?,?,?,?,?,?,1,0)",
                       (kode, ",".join(rups), json.dumps([{"kode_rup": r, "nama_paket": nama, "sumber_dana": "APBD"} for r in rups]), satker, pagu, hps,
                        1 if mulai else 0, 98, 97))
        if mulai:
            self.c.execute("INSERT INTO spse_jadwal(lpse,jenis,kode_paket,no,tahap,mulai,sampai,jumlah_perubahan,riwayat_json) VALUES('p','nontender',?,1,'Upload Dokumen Penawaran',?,?,?,?)",
                           (kode, mulai, "2026-04-05T08:00", perubahan, json.dumps(riwayat or [])))

    def hitung(self, **kw):
        return banding.hitung(self.c, "p", "nontender", [2026], {SATKER: [1]}, sekarang=SEKARANG, **kw)

    def per_rup(self, hasil):
        return {b["kode_rup"]: b for b in hasil["baris"] if b["kode_rup"]}

    def test_cocok_kode_rup_tayang_dan_belum_tayang(self):
        self.rup("1", "Jalan A"); self.rup("2", "Jalan B")
        self.spse("10", "Jalan A", ["1"], mulai="2026-04-01T08:00")
        self.spse("20", "Jalan B", ["2"], mulai="2026-06-01T08:00")
        b = self.per_rup(self.hitung())
        self.assertEqual((b["1"]["status"], b["1"]["kecocokan"], b["1"]["kode_nontender"]), ("Sudah tayang", "Kode RUP", "10"))
        self.assertEqual(b["2"]["status"], "Belum tayang")
        self.assertEqual((b["1"]["harga_penawaran"], b["1"]["hasil_negosiasi"], b["1"]["hps"]), (98, 97, 99))

    def test_rup_berubah_setelah_tayang_dicocokkan_lewat_nama_dan_instansi(self):
        self.rup("9", "Jalan C")                            # RUP baru; SPSE masih menyebut RUP lama "8"
        self.spse("30", "jalan  c", ["8"])
        b = self.per_rup(self.hitung())
        self.assertEqual((b["9"]["kode_nontender"], b["9"]["kecocokan"]), ("30", "Nama paket + instansi (RUP berubah)"))

    def test_rup_lama_diganti_dipetakan_ke_penggantinya(self):
        self.rup("8", "Jalan D", aktif=0, pengganti="9"); self.rup("9", "Jalan D (revisi)")
        self.spse("31", "Jalan D", ["8"])
        b = self.per_rup(self.hitung())
        self.assertEqual((b["9"]["kode_nontender"], b["9"]["kecocokan"]), ("31", "Kode RUP (RUP sudah direvisi)"))

    def test_nama_sama_tetapi_instansi_lain_tidak_dicocokkan(self):
        self.rup("5", "Pengadaan Meja")
        self.spse("40", "Pengadaan Meja", ["77"], satker="DINAS LAIN")
        h = self.hitung()
        self.assertEqual(self.per_rup(h)["5"]["status"], "Belum ada di SPSE")
        self.assertEqual(h["ringkas"]["per_status"].get("Tidak ada di daftar SiRUP"), None)      # tidak dicocokkan lintas satker
        lain = [b for b in h["baris"] if b["satker"] == "DINAS LAIN"]                   # tampil dari sisi SPSE, bukan "tidak ada di SiRUP"
        self.assertEqual([(b["kode_nontender"], b["status"]) for b in lain], [("40", "SiRUP satker ini belum diambil")])
        self.assertTrue(any("belum diambil" in x for x in h["peringatan"]))

    def test_pagu_beda_dan_gabungan_beberapa_rup(self):
        self.rup("1", "Paket X", pagu=60); self.rup("2", "Paket X lanjutan", pagu=40); self.rup("3", "Paket Y", pagu=100)
        self.spse("50", "Paket X gabungan", ["1", "2"], pagu=100)
        self.spse("60", "Paket Y", ["3"], pagu=90)
        b = self.per_rup(self.hitung())
        self.assertEqual((b["1"]["pagu_sama"], b["1"]["jumlah_rup_gabungan"], b["1"]["pagu_sirup_gabungan"]), (True, 2, 100))
        self.assertEqual((b["3"]["pagu_sama"], b["3"]["selisih_pagu"]), (False, -10))

    def test_perubahan_jadwal_dan_jadwal_awal(self):
        self.rup("1", "Jalan A")
        self.spse("10", "Jalan A", ["1"], perubahan=2, riwayat=[{"tanggal_edit_iso": "2026-03-25T10:00", "mulai_asli_iso": "2026-03-28T08:00", "sampai_asli_iso": "2026-04-02T08:00", "keterangan": "k2"},
                                                                  {"tanggal_edit_iso": "2026-03-21T10:00", "mulai_asli_iso": "2026-03-20T08:00", "sampai_asli_iso": "2026-03-24T08:00", "keterangan": "k1"}])
        b = self.per_rup(self.hitung())["1"]
        self.assertEqual((b["jadwal_diubah"], b["upload_mulai_awal"], b["upload_sampai_awal"], b["upload_mulai"]),
                         (2, "2026-03-20T08:00", "2026-03-24T08:00", "2026-04-01T08:00"))

    def test_kategori_non_spse(self):
        self.rup("1", "Katalog", metode="E-Purchasing"); self.rup("2", "Swa", metode="Swakelola", jenis="swakelola")
        self.rup("3", "Tender", metode="Tender"); self.rup("4", "Kecuali", metode="Dikecualikan")
        st = {k: v["status"] for k, v in self.per_rup(self.hitung()).items()}
        self.assertEqual(st, {"1": "E-Katalog (tidak di SPSE)", "2": "Swakelola (tidak di SPSE)", "3": "Tender/Seleksi (belum diambil)", "4": "Dikecualikan"})

    def test_spse_tanpa_pasangan_dan_detail_belum_lengkap(self):
        self.rup("1", "Jalan A")
        self.spse("70", "Paket Hantu", ["999"])
        self.spse("80", "Belum Diambil", [], detail=False)
        h = self.hitung()
        self.assertEqual(self.per_rup(h)["1"]["status"], "Belum dapat dipastikan (detail SPSE belum lengkap)")
        self.assertEqual([b["kode_nontender"] for b in h["baris"] if b["status"] == "Tidak ada di daftar SiRUP"], ["70"])
        self.assertEqual(len(h["peringatan"]), 1)

    def test_filter_satker_dan_daftar_satker(self):
        self.rup("1", "Jalan A")
        self.spse("10", "Jalan A", ["1"])
        self.spse("40", "Paket Lain", ["77"], satker="DINAS LAIN")
        h = self.hitung(satker="dinas  lain")                                         # nama dinormalkan
        self.assertEqual({b["satker"] for b in h["baris"]}, {"DINAS LAIN"})
        h = self.hitung(satker=SATKER)
        self.assertEqual({b["satker"] for b in h["baris"]}, {SATKER})
        self.assertEqual({d["nama"]: (d["paket_spse"], d["ada_sirup"]) for d in self.hitung()["satker_daftar"]},
                         {SATKER: (1, True), "DINAS LAIN": (1, False)})

    def test_dua_satker_dengan_sirup_dipisah(self):
        self.c.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,jenis,nama_paket,pagu,metode_pemilihan,is_active,link) VALUES('9',2026,2,'penyedia','Paket Z',50,'Pengadaan Langsung',1,'l')")
        self.rup("1", "Jalan A")
        self.spse("10", "Jalan A", ["1"])
        self.spse("90", "Paket Z", ["9"], satker="DINAS B", pagu=50)
        h = banding.hitung(self.c, "p", "nontender", [2026], {SATKER: [1], "DINAS B": [2]}, sekarang=SEKARANG)
        st = {b["kode_rup"]: (b["satker"], b["status"]) for b in h["baris"]}
        self.assertEqual(st, {"1": (SATKER, "Sudah tayang"), "9": ("DINAS B", "Sudah tayang")})

    def test_jadwal_belum_diambil(self):
        self.rup("1", "Jalan A")
        self.spse("10", "Jalan A", ["1"], mulai=None)
        self.assertEqual(self.per_rup(self.hitung())["1"]["status"], "Jadwal belum diambil")

    def test_paket_dibatalkan_dikalahkan_paket_aktif(self):
        self.rup("1", "Jalan A")
        self.spse("10", "Jalan A", ["1"], tahapan="Paket Dibatalkan")
        self.spse("20", "Jalan A", ["1"], tahapan="Evaluasi Penawaran")
        self.assertEqual(self.per_rup(self.hitung())["1"]["kode_nontender"], "20")


if __name__ == "__main__":
    unittest.main()
