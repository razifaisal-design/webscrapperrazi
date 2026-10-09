import json
import tempfile
import unittest
from pathlib import Path

from scraper import ekspor_publik
from scraper.core import db


class TestEksporPublik(unittest.TestCase):
    def test_ekspor_membuat_situs_statis_tanpa_tautan_mutlak_dan_tanpa_kontrol_pengambilan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "t.db")
            conn = db.buka(path)
            conn.execute("INSERT INTO spse_paket(lpse,jenis,kode_paket,tahun,nama_paket,tahapan,is_active,link) VALUES('pontianak','nontender','900',2026,'Paket Uji','Selesai',1,'http://x/900')")
            conn.execute("INSERT INTO spse_detail(lpse,jenis,kode_paket,kode_rup,rup_json,satker,pagu,hps,lengkap) VALUES('pontianak','nontender','900','55','[]','DINAS UJI',10,9,1)")
            conn.execute("INSERT INTO spse_jadwal(lpse,jenis,kode_paket,no,tahap,mulai,sampai,jumlah_perubahan,riwayat_json) VALUES('pontianak','nontender','900',1,'Upload Dokumen Penawaran','2026-01-01T08:00','2026-01-02T08:00',0,'[]')")
            conn.commit()
            conn.close()
            keluar = Path(tmp) / "publik"
            r = ekspor_publik.ekspor(path, keluar, log=lambda *a: None, dengan_excel=True)
            self.assertGreater(r["berkas"], 5)
            meta = json.loads((keluar / "data" / "meta.json").read_text())
            self.assertEqual(meta["tahun_spse"], [2026])
            spse = json.loads((keluar / "data" / "spse_2026.json").read_text())
            self.assertEqual([b["kode_paket"] for b in spse["baris"]], ["900"])
            self.assertEqual(json.loads((keluar / "data" / "jadwal_spse.json").read_text())["900"][0]["tahap"], "Upload Dokumen Penawaran")
            self.assertTrue((keluar / "data" / "spse_2026.xlsx").read_bytes().startswith(b"PK"))
            for nama in ("index.html", "spse.html", "banding.html", "grafik.html"):
                h = (keluar / nama).read_text(encoding="utf-8")
                self.assertIn('<script src="statis.js"></script>', h, nama)
                self.assertNotIn('"/gaya.css"', h, nama)                          # tautan relatif: bisa di-hosting di sub-folder
                self.assertNotIn('"/bersama.js"', h, nama)
                self.assertNotIn('href="/spse"', h, nama)
            for nama in ("gaya.css", "bersama.js", "statis.js", ".nojekyll"):
                self.assertTrue((keluar / nama).exists(), nama)
            self.assertNotIn("password", (keluar / "statis.js").read_text().lower())


if __name__ == "__main__":
    unittest.main()
