import json
import tempfile
import unittest
from pathlib import Path

import httpx

from scraper import tugas
from scraper.core import banding, db
from scraper.core.http import DiblokirError
from scraper.sources import sirup_detail

FIX = Path(__file__).parent / "fixtures"
SATKER = "DINAS PERUMAHAN RAKYAT DAN KAWASAN PERMUKIMAN"
HTML = (FIX / "sirup_publik_penyedia.html").read_text(encoding="utf-8")        # RUP 64482894 (satker Perkim, 2026, pagu 200 juta)


class Klien:
    def __init__(self, blokir=None):
        self.url, self.blokir = [], blokir

    def get_text(self, url, params=None):
        kode = url.rsplit("/", 1)[-1].split("=")[-1]
        self.url.append(kode)
        if kode == self.blokir:
            raise DiblokirError("HTTP 429")
        if kode == "64482894":
            return HTML
        if kode == "555":                                       # RUP milik satker lain
            return HTML.replace("64482894", "555").replace(SATKER, "DINAS LAIN")
        if kode == "666":
            raise RuntimeError("jaringan putus")
        raise httpx.HTTPStatusError("galat", request=httpx.Request("GET", url), response=httpx.Response(500))

    def close(self):
        pass


class TestParse(unittest.TestCase):
    def test_halaman_detail_publik(self):
        d = sirup_detail.ambil_detail(Klien(), "penyedia", "64482894")
        self.assertEqual((d["nama_paket"], d["satuan_kerja"], d["total_pagu"], d["tahun_anggaran"]),
                         ("Belanja Modal Jalan Kota (Jl. Petani, Gg. Green Sentarum, Kec. Pontianak Kota)", SATKER, 200000000, "2026"))
        self.assertEqual(d["extra"]["metode_pemilihan"], "Pengadaan Langsung")


class TestRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = db.buka(str(Path(self.tmp.name) / "t.db"))

    def jalan(self, kodes, klien=None, **kw):
        klien = klien or Klien()
        logs = []
        kode = tugas.run_periksa_rup(self.conn, kodes, buat_klien=lambda jeda: klien, log=logs.append, **kw)
        return kode, klien, logs

    def baris(self, kode):
        return self.conn.execute("SELECT ditemukan, satker_nama, pagu, error FROM sirup_luar_daftar WHERE kode_rup=?", (kode,)).fetchone()

    def test_ada_dan_tidak_ada_disimpan_dan_tidak_diulang(self):
        kode, klien, _ = self.jalan(["64482894", "1"])
        self.assertEqual(kode, 0)
        self.assertEqual(tuple(self.baris("64482894")), (1, SATKER, 200000000, None))
        self.assertEqual(tuple(self.baris("1")), (0, None, None, None))
        kode, klien2, logs = self.jalan(["64482894", "1"])
        self.assertEqual(klien2.url, [])                                     # sudah dicek: tidak dibuka lagi
        kode, klien3, _ = self.jalan(["64482894"], ulang=True)
        self.assertEqual(klien3.url, ["64482894"])

    def test_galat_jaringan_dicatat_dan_diulang_kemudian(self):
        kode, _, _ = self.jalan(["666"])
        self.assertEqual(kode, 4)
        self.assertIsNone(self.baris("666")["ditemukan"])
        self.assertIn("jaringan putus", self.baris("666")["error"])
        _, klien, _ = self.jalan(["666"])
        self.assertEqual(klien.url, ["666"])                                 # galat belum dianggap hasil: dicoba lagi

    def test_diblokir_berhenti_dan_paralel(self):
        kode, _, _ = self.jalan(["64482894", "1", "2", "3"], Klien(blokir="2"), koneksi=2)
        self.assertEqual(kode, 2)
        kode, klien, _ = self.jalan(["64482894", "1", "2", "3", "555"], koneksi=3)
        self.assertEqual(kode, 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sirup_luar_daftar WHERE error IS NULL").fetchone()[0], 5)


class TestBandingLuarDaftar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = db.buka(str(Path(self.tmp.name) / "t.db"))
        self.c.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,jenis,nama_paket,pagu,metode_pemilihan,is_active,link) VALUES('1',2026,1,'penyedia','Lain',10,'Pengadaan Langsung',1,'l')")
        for kode in ("64482894", "555", "777", "888"):
            self.spse(kode)

    def spse(self, kode):
        self.c.execute("INSERT INTO spse_paket(lpse,jenis,kode_paket,tahun,nama_paket,tahapan,is_active,link) VALUES('p','nontender',?,2026,?,'Evaluasi Penawaran',1,'l')", (f"9{kode}", f"Paket {kode}"))
        self.c.execute("INSERT INTO spse_detail(lpse,jenis,kode_paket,kode_rup,rup_json,satker,pagu,hps,lengkap) VALUES('p','nontender',?,?,?,?,200000000,199000000,1)",
                       (f"9{kode}", kode, json.dumps([{"kode_rup": kode, "nama_paket": f"Paket {kode}", "sumber_dana": "APBD"}]), SATKER))
        self.c.execute("INSERT INTO spse_jadwal(lpse,jenis,kode_paket,no,tahap,mulai,sampai,jumlah_perubahan,riwayat_json) VALUES('p','nontender',?,1,'Upload Dokumen Penawaran','2026-03-01T08:00','2026-03-05T08:00',0,'[]')", (f"9{kode}",))

    def luar(self, kode, ditemukan, satker=SATKER, pagu=200000000, nama="Nama di SiRUP"):
        self.c.execute("INSERT INTO sirup_luar_daftar(kode_rup,ditemukan,nama_paket,satker_nama,pagu,metode_pemilihan,link) VALUES(?,?,?,?,?,'Pengadaan Langsung','http://s/'||?)",
                       (kode, ditemukan, nama if ditemukan else None, satker if ditemukan else None, pagu if ditemukan else None, kode))

    def hitung(self):
        h = banding.hitung(self.c, "p", "nontender", [2026], {SATKER: [1]}, sekarang="2026-06-01T00:00")
        return {b["kode_nontender"]: b for b in h["baris"] if b.get("kode_nontender")}

    def test_empat_kemungkinan_untuk_rup_di_luar_daftar(self):
        self.luar("64482894", 1, nama="Paket 64482894")
        self.luar("555", 1, satker="DINAS LAIN")
        self.luar("777", 0)
        b = self.hitung()
        ok = b["964482894"]
        self.assertEqual((ok["status"], ok["kode_rup"], ok["di_daftar"], ok["pagu_sama"], ok["link_sirup"]),
                         ("Sudah tayang", "64482894", False, True, "http://s/64482894"))
        self.assertIn("tidak tampil di daftar", ok["kecocokan"])
        self.assertEqual(b["9555"]["status"], "RUP di SiRUP milik satker lain")
        self.assertEqual(b["9777"]["status"], "RUP tidak ada di SiRUP")
        self.assertEqual(b["9888"]["status"], "Tidak ada di daftar SiRUP")                    # belum dicek langsung

    def test_nama_sama_tapi_kode_rup_beda_didahulukan_kode(self):
        # SPSE menyebut RUP 64482894 (di luar daftar, pagu 200 jt); di daftar ada RUP lain 'N' dengan nama persis sama tetapi pagu 50 jt
        self.c.execute("INSERT INTO sirup_paket(kode_rup,tahun,id_satker,jenis,nama_paket,pagu,metode_pemilihan,is_active,link) VALUES('N',2026,1,'penyedia','Paket 64482894',50000000,'Pengadaan Langsung',1,'l')")
        b = self.hitung()["964482894"]
        self.assertEqual(b["kecocokan"], "Nama paket + instansi (RUP berubah)")             # sebelum dicek: hanya bisa lewat nama
        self.luar("64482894", 1, nama="Paket 64482894")
        b = self.hitung()["964482894"]
        self.assertEqual((b["kode_rup"], b["di_daftar"], b["pagu_sama"]), ("64482894", False, True))   # setelah dicek: RUP aslinya yang dipakai
        h = banding.hitung(self.c, "p", "nontender", [2026], {SATKER: [1]}, sekarang="2026-06-01T00:00")
        self.assertEqual({b["kode_rup"]: b["status"] for b in h["baris"] if b["kode_rup"] == "N"}, {"N": "Belum ada di SPSE"})   # RUP 'N' tidak lagi salah dipasangkan

    def test_pagu_beda_terlihat_pada_rup_di_luar_daftar(self):
        self.luar("64482894", 1, pagu=150000000)
        b = self.hitung()["964482894"]
        self.assertEqual((b["pagu_sama"], b["selisih_pagu"]), (False, 50000000))



if __name__ == "__main__":
    unittest.main()
