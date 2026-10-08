import tempfile
import unittest
from pathlib import Path

from scraper import tugas
from scraper.core import db
from scraper.core.http import DiblokirError
from scraper.sources import spse

FIX = Path(__file__).parent / "fixtures" / "spse"


def baca(nama):
    return (FIX / nama).read_text(encoding="utf-8")


class TestParseDetail(unittest.TestCase):
    def test_pengumuman_tanpa_syarat_kualifikasi(self):
        a = spse.parse_pengumuman(baca("pengumuman.html"))
        self.assertEqual(a["kode_paket"], "10748199000")
        self.assertEqual(a["rup"], [{"kode_rup": "62728864", "nama_paket": "Perencanaan PSU Saluran Tahun 2026 Kecamatan Pontianak Barat", "sumber_dana": "APBD"}])
        self.assertEqual((a["pagu"], a["hps"]), (100000000, 99920000))
        self.assertEqual(a["satker"], "DINAS PERUMAHAN RAKYAT DAN KAWASAN PERMUKIMAN")
        self.assertEqual(a["lokasi"], ["Kota Pontianak - Pontianak (Kota)"])
        self.assertEqual((a["metode"], a["jenis_kontrak"], a["sumber_dana"], a["tahun_anggaran"], a["oap"]),
                         ("Pengadaan Langsung", "Lumsum", "APBD", 2026, "Tidak"))
        self.assertEqual(spse.pisah_tahun_anggaran("APBD-P 2026"), ("APBD-P", 2026))
        self.assertEqual(spse.pisah_tahun_anggaran("APBN"), ("APBN", None))
        self.assertNotIn("Izin Usaha", repr(a))                                # Syarat Kualifikasi tidak ikut

    def test_pemenang_semua_kolom(self):
        p = spse.parse_pemenang(baca("pemenang.html"))["pemenang"]
        self.assertEqual(len(p), 1)
        self.assertEqual(list(p[0]), ["Nama Pemenang", "Alamat", "NPWP", "Harga Penawaran", "Harga Terkoreksi", "Hasil Negosiasi"])
        self.assertEqual(p[0]["Nama Pemenang"], "CV DW KREASI KONSULTAN")
        self.assertTrue(p[0]["Alamat"].startswith("Jl HM SUWIGNYO"))

    def test_kontrak_kosong_dan_terisi(self):
        a = spse.parse_pengumuman(baca("pengumuman.html"))
        pm = spse.parse_pemenang(baca("pemenang.html"))
        kosong = spse.ringkas_detail(a, pm, spse.parse_pemenang(baca("kontrak_kosong.html")))
        self.assertEqual((kosong["pemenang_terisi"], kosong["kontrak_terisi"], kosong["nilai_kontrak"]), (1, 0, None))
        self.assertEqual((kosong["harga_penawaran"], kosong["hasil_negosiasi"]), (99808536, 99800000))
        isi = spse.ringkas_detail(a, pm, spse.parse_pemenang(baca("kontrak_terisi.html")))
        self.assertEqual((isi["kontrak_terisi"], isi["nilai_kontrak"]), (1, 71509752))

    def test_halaman_asing_ditolak(self):
        with self.assertRaises(spse.SpseError):
            spse.parse_pengumuman("<html>404</html>")
        with self.assertRaises(spse.SpseError):
            spse.parse_pengumuman('<div class="content"><table></table></div>')

    def test_url_tab(self):
        self.assertEqual(spse.url_tab("pontianak", "nontender", "1", "pengumuman"), "https://spse.inaproc.id/pontianak/nontender/1/pengumumanpl")
        self.assertEqual(spse.url_tab("pontianak", "nontender", "1", "kontrak"), "https://spse.inaproc.id/pontianak/evaluasinontender/1/pemenangberkontrak")


class TestJadwal(unittest.TestCase):
    def test_tanggal_indonesia(self):
        self.assertEqual(spse.tanggal_id("19 Agustus 2026 20:00"), "2026-08-19T20:00")
        self.assertEqual(spse.tanggal_id("1 September 2026 15:45"), "2026-09-01T15:45")
        self.assertEqual(spse.tanggal_id("2 Januari 2026"), "2026-01-02T00:00")
        self.assertIsNone(spse.tanggal_id("kapan-kapan"))
        self.assertIsNone(spse.tanggal_id(None))

    def test_jadwal_tanpa_dan_dengan_perubahan(self):
        biasa = spse.parse_jadwal(baca("jadwal_biasa.html"))
        self.assertEqual([t["tahap"] for t in biasa][:2], ["Upload Dokumen Penawaran", "Pembukaan Dokumen Penawaran"])
        self.assertEqual((biasa[0]["mulai"], biasa[0]["sampai"], biasa[0]["jumlah_perubahan"], biasa[0]["url_riwayat"]),
                         ("2026-08-19T20:00", "2026-08-24T11:59", 0, None))
        ubah = spse.parse_jadwal(baca("jadwal_berubah.html"))
        self.assertEqual(len(ubah), 5)
        self.assertEqual((ubah[0]["jumlah_perubahan"], ubah[0]["url_riwayat"]),
                         (1, "https://spse.inaproc.id/pontianak/jadwalnontender/13404325000/history"))

    def test_riwayat(self):
        r = spse.parse_riwayat_jadwal(baca("riwayat.html"))
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["tanggal_edit_iso"], r[0]["mulai_asli_iso"], r[0]["keterangan"]),
                         ("2026-02-11T14:50", "2026-02-06T16:05", "Pejabat Pengadaan memerlukan waktu untuk Evaluasi Penawaran"))


SATKER = "DINAS PERUMAHAN RAKYAT DAN KAWASAN PERMUKIMAN"


class KlienPalsu:
    """Meniru SPSE: 5 jenis halaman per paket. `lain` = kode paket yang satkernya instansi lain."""
    def __init__(self, gagal=(), blokir=None, lain=()):
        self.gagal, self.blokir, self.lain, self.url = set(gagal), blokir, set(lain), []

    def get_text(self, url, params=None):
        self.url.append(url)
        if url.endswith("/history"):
            return baca("riwayat.html")
        kode = url.split("/")[-2]
        if kode == self.blokir:
            raise DiblokirError("HTTP 429")
        if kode in self.gagal:
            return "<html>rusak</html>"
        if url.endswith("pengumumanpl"):
            h = baca("pengumuman.html").replace("10748199000", kode)
            return h.replace(SATKER, "DINAS LAIN") if kode in self.lain else h
        if url.endswith("/pemenang"):
            return baca("pemenang.html")
        if url.endswith("/jadwal"):
            return baca("jadwal_berubah.html")
        return baca("kontrak_kosong.html")

    def close(self):
        pass


class TestRunDetail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = db.buka(str(Path(self.tmp.name) / "t.db"))
        for kode in ("111", "222", "333"):
            self.conn.execute("INSERT INTO spse_paket(lpse,jenis,kode_paket,tahun,nama_paket,tahapan,is_active) VALUES('pontianak','nontender',?,2026,'x','Paket Sudah Selesai',1)", (kode,))
        self.conn.commit()

    def jalan(self, klien, **kw):
        logs = []
        kw.setdefault("satker", SATKER)
        kode = tugas.run_spse_detail(self.conn, tahun=2026, buat_klien=lambda jeda: klien, log=logs.append, **kw)
        return kode, logs

    def kode_diminta(self, klien):
        return {u.split("/")[-2] for u in klien.url if not u.endswith("/history")}

    def test_satker_target_diambil_lengkap_dengan_jadwal_dan_riwayat(self):
        klien = KlienPalsu()
        self.assertEqual(self.jalan(klien, limit=1)[0], 0)
        self.assertEqual(len(klien.url), 9)         # pengumuman, pemenang, kontrak, jadwal + 5 riwayat tahap
        self.assertEqual(self.conn.execute("SELECT lengkap FROM spse_detail WHERE kode_paket='111'").fetchone()[0], 1)
        t = self.conn.execute("SELECT tahap, mulai, sampai, jumlah_perubahan, riwayat_json FROM spse_jadwal WHERE kode_paket='111' ORDER BY no").fetchall()
        self.assertEqual(len(t), 5)
        self.assertEqual((t[0][0], t[0][1], t[0][3]), ("Upload Dokumen Penawaran", "2026-02-06T16:05", 1))
        self.assertIn("memerlukan waktu", t[0][4])

    def test_instansi_lain_hanya_pengumuman_dan_tidak_diulang(self):
        klien = KlienPalsu(lain={"222"})
        self.jalan(klien)
        lain = [u for u in klien.url if "/222/" in u]
        self.assertEqual(len(lain), 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM spse_jadwal WHERE kode_paket='222'").fetchone()[0], 0)
        klien = KlienPalsu(lain={"222"})
        self.jalan(klien)
        self.assertEqual(klien.url, [])                               # semua sudah ada; instansi lain tidak diambil ulang

    def test_tanpa_satker_semua_dirinci(self):
        klien = KlienPalsu(lain={"222"})
        self.jalan(klien, satker=None)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM spse_jadwal WHERE kode_paket='222'").fetchone()[0], 5)

    def test_tahapan_berubah_diambil_ulang(self):
        self.jalan(KlienPalsu())
        self.conn.execute("UPDATE spse_paket SET tahapan='Penandatanganan Kontrak' WHERE kode_paket='111'")
        klien = KlienPalsu()
        self.jalan(klien)
        self.assertEqual(self.kode_diminta(klien), {"111"})

    def test_satu_gagal_tidak_menghentikan_dan_diulang_kemudian(self):
        kode, _ = self.jalan(KlienPalsu(gagal={"222"}))
        self.assertEqual(kode, 4)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM spse_detail WHERE error IS NULL").fetchone()[0], 2)
        klien = KlienPalsu()
        self.assertEqual(self.jalan(klien)[0], 0)
        self.assertEqual(self.kode_diminta(klien), {"222"})

    def test_diblokir_berhenti_kode_2(self):
        kode, _ = self.jalan(KlienPalsu(blokir="222"))
        self.assertEqual(kode, 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM spse_detail").fetchone()[0], 1)

    def test_gagal_tidak_menimpa_detail_lama_yang_baik(self):
        self.jalan(KlienPalsu(), limit=1)
        db.simpan_detail_spse(self.conn, "pontianak", "nontender", "111", None, "boom")
        row = self.conn.execute("SELECT satker, error, lengkap FROM spse_detail WHERE kode_paket='111'").fetchone()
        self.assertEqual((row[0], row[1], row[2]), (SATKER, "boom", 1))


if __name__ == "__main__":
    unittest.main()
