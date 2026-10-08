import csv
import json
import tempfile
import unittest
from pathlib import Path

from scraper.core import database, db, rekap

J = "1.04.05.2.01.0012.5.2.04.01.001.00004"
S = "1.04.05.2.01.0011.5.2.04.02.002.00004"
TARGET = json.loads((Path(__file__).parents[1] / "config" / "targets.json").read_text(encoding="utf-8"))["targets"]["perkim-pontianak"]
TARGET = dict(TARGET, id_satker=1, tahun=2026)


def paket(kode, nama, pagu):
    return {"kode_rup": kode, "tahun": 2026, "klpd_nama": "K", "id_satker": 1, "jenis": "penyedia", "nama_paket": nama,
            "penyelenggara": None, "pagu": pagu, "metode_pemilihan": "Pengadaan Langsung", "sumber_dana": "APBD",
            "waktu_pemilihan": "Maret 2026", "link": f"http://x/{kode}"}


def detail(mak, pagu, uraian, volume="62 M1"):
    return {"lokasi": [{"provinsi": "Kalbar", "kabupaten_kota": "Pontianak (Kota)", "detail": "Kota Pontianak"}],
            "lokasi_ringkas": "Kalbar / Pontianak (Kota) / Kota Pontianak", "volume": volume, "uraian": uraian,
            "spesifikasi": "Sheet Pile", "sumber_dana": [{"sumber_dana": "APBD", "tahun": "2026", "klpd": "K", "mak": mak, "pagu": pagu}],
            "mak": mak, "total_pagu": pagu, "extra": {"jenis_pengadaan": "Pekerjaan Konstruksi", "kontrak_mulai": "Maret 2026"}}


class TestDatabaseLengkap(unittest.TestCase):
    def setUp(self):
        self.conn = db.buka(":memory:")
        self.addCleanup(self.conn.close)
        data = [("1", "Belanja Modal Jalan Kota (Jl. Flora, Gg. Flora 4, Kec. Pontianak Utara)", 100, J + ".8.1.02", "Pekerjaan Jalan"),
                ("2", "Belanja Modal Saluran Pembuang Pasang Surut (Jl. Flora, Gg. Flora 5, Kec. Pontianak Utara)", 50, J, "Pekerjaan Saluran"),
                ("3", "Belanja Modal Saluran Pembuang Pasang Surut (Jl. Ampera, Kec. Pontianak Kota)", 70, S, "Pekerjaan Saluran"),
                ("4", "Fotocopy", 10, "X.1", "Fotocopy")]
        rid = db.mulai_run(self.conn, 1, 2026)
        db.finalisasi(self.conn, rid, [paket(k, n, p) for k, n, p, _, _ in data], 1, 2026)
        rd = db.mulai_run(self.conn, 1, 2026, "SIRUP_DETAIL")
        for k, n, p, m, u in data:
            db.simpan_detail(self.conn, rd, k, n, p, detail(m, p, u))
        self.data = rekap.lengkap(self.conn, TARGET)
        self.rows = {r["kode_rup"]: r for r in database.baris(self.conn, TARGET, self.data)}

    def test_semua_paket_masuk_dengan_kolom_turunan(self):
        self.assertEqual(sorted(self.rows), ["1", "2", "3", "4"])
        r1, r2 = self.rows["1"], self.rows["2"]
        self.assertEqual((r1["jenis_kegiatan"], r1["status_mak"], r1["jalan"], r1["gang"], r1["kecamatan"]),
                         ("Jalan", "Sesuai", "Flora", ["Flora 4"], "Pontianak Utara"))
        self.assertEqual(r1["mak"], [J])                                  # buntut MAK dipotong
        self.assertEqual((r2["jenis_kegiatan"], r2["jenis_perbaikan"], r2["status_mak"]), ("Jalan", "Saluran", "Salah MAK"))
        self.assertEqual((r2["mak_perbaikan"], r2["mak_akhir"]), ([S], [S]))
        self.assertIn("MAK tidak sesuai kategori", r2["temuan"])

    def test_kolom_detail_ikut(self):
        r = self.rows["1"]
        self.assertEqual((r["spesifikasi"], r["jenis_pengadaan"], r["kontrak_mulai"]), ("Sheet Pile", "Pekerjaan Konstruksi", "Maret 2026"))
        self.assertEqual(r["sumber_dana_rincian"][0]["mak"], J + ".8.1.02")  # MAK lengkap asli tetap tersedia
        self.assertTrue(r["ada_detail"] and r["aktif"])

    def test_paket_tanpa_detail_tetap_tampil(self):
        db.finalisasi(self.conn, db.mulai_run(self.conn, 1, 2026), [paket("5", "Baru", 5)] + [
            paket(k, v["nama_paket"], v["pagu"]) for k, v in self.data["paket"].items()], 1, 2026)
        baris = {r["kode_rup"]: r for r in database.baris(self.conn, TARGET, rekap.lengkap(self.conn, TARGET))}
        self.assertFalse(baris["5"]["ada_detail"])
        self.assertIsNone(baris["5"]["kategori"])

    def test_ekspor_csv_semua_kolom(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.csv"
            n = database.ekspor_csv(list(self.rows.values()), p)
            baca = list(csv.DictReader(open(p, encoding="utf-8-sig")))
        self.assertEqual(n, 4)
        self.assertEqual(list(baca[0].keys()), [j for _, j in database.KOLOM])
        r2 = next(x for x in baca if x["Kode RUP"] == "2")
        self.assertEqual((r2["Jenis Kegiatan"], r2["Jenis Perbaikan"], r2["MAK Perbaikan"], r2["Nama Gang"]), ("Jalan", "Saluran", S, "Flora 5"))


class TestTabelLokasi(unittest.TestCase):
    def test_simpan_lokasi(self):
        t = TestDatabaseLengkap("test_semua_paket_masuk_dengan_kolom_turunan")
        t.setUp(); self.addCleanup(t.conn.close)
        nj, ng = database.simpan_lokasi(t.conn, TARGET, t.data)
        self.assertEqual((nj, ng), (2, 2))                          # jalan: Flora, Ampera | gang: Flora 4, Flora 5 (Ampera tanpa gang)
        self.assertEqual(t.conn.execute("SELECT jumlah_paket, jumlah_gang FROM ref_jalan WHERE nama='Jl. Flora'").fetchone()[:], (2, 2))
        self.assertEqual(t.conn.execute("SELECT COUNT(*) FROM ref_gang WHERE nama='Gg. Flora 4'").fetchone()[0], 1)
        salah = t.conn.execute("SELECT jenis_kegiatan, jenis_perbaikan, mak_perbaikan FROM paket_lokasi WHERE kode_rup='2'").fetchone()
        self.assertEqual(tuple(salah), ("Jalan", "Saluran", S))
        database.simpan_lokasi(t.conn, TARGET, t.data)               # dibangun ulang -> tidak dobel
        self.assertEqual(t.conn.execute("SELECT COUNT(*) FROM ref_jalan").fetchone()[0], 2)
        self.assertEqual(t.conn.execute("SELECT COUNT(*) FROM paket_lokasi").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
