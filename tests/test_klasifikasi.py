import json
import unittest
from pathlib import Path

from scraper.core.klasifikasi import AturanError, Pengklasifikasi
from scraper.core.rekap import norm_uraian

ATURAN = json.loads((Path(__file__).parents[1] / "config" / "targets.json").read_text(encoding="utf-8")
                    )["targets"]["perkim-pontianak"]["klasifikasi"]
K = Pengklasifikasi(ATURAN)


class TestKlasifikasiPerkim(unittest.TestCase):
    def cek(self, nama, uraian, kategori, jenis):
        self.assertEqual(K(nama, uraian), (kategori, jenis), nama)

    def test_belanja_modal_jalan_kota_adalah_jalan(self):
        self.cek("Belanja Modal Jalan Kota (Jl. Flora, Gg. Flora 4)", "Pekerjaan Jalan", "Jalan", "Fisik")

    def test_belanja_modal_saluran_pembuang_adalah_saluran(self):
        self.cek("Belanja Modal Saluran Pembuang Pasang Beton Pracetak", "Pekerjaan Saluran", "Saluran", "Fisik")

    def test_belanja_modal_jalan_kota_pengawasan_adalah_jalan_konsultan(self):
        self.cek("Belanja Modal Jalan Kota-Pengawasan di Kecamatan Pontianak Timur",
                 "Belanja Jasa Konsultansi Pengawasan Rekayasa; Belanja Modal Jalan Kota - Pengawasan", "Jalan", "Konsultan")

    def test_konsultan_terbagi_ke_jalan_dan_saluran(self):
        self.cek("Pengawasan PSU Jalan Tahun 2026 Kecamatan Pontianak Barat", "Pengawasan Jalan", "Jalan", "Konsultan")
        self.cek("Perencanaan PSU Saluran Tahun 2026 Kecamatan Pontianak Barat",
                 "Pekerjaan Konsultan Perencanaan Saluran", "Saluran", "Konsultan")
        self.cek("Pengawasan PSU Jalan Tahun 2026 Timur - (Tahap 2)",
                 "Belanja Jasa Konsultansi Pengawasan Rekayasa-Jasa Pengawas Pekerjaan Konstruksi Teknik Sipil Transportasi",
                 "Jalan", "Konsultan")

    def test_yang_bukan_jalan_atau_saluran_masuk_lainnya(self):
        self.cek("Fotocopy", "Fotocopy", "Lainnya", "Fisik")
        self.cek("Belanja Perjalanan Dinas Biasa Sub Kegiatan Rapat", "72 Perjalanan Dinas Biasa", "Lainnya", "Fisik")  # 'Perjalanan' != 'jalan'
        self.cek("Belanja Makanan dan Minuman (Perencanaan Penyediaan PSU Perumahan)", "Belanja Makanan dan Minuman", "Lainnya", "Konsultan")
        self.cek("Belanja Jasa Konsultansi Perencanaan Penataan Ruang", "Belanja Jasa Konsultansi Perencanaan Penataan Ruang", "Lainnya", "Konsultan")

    def test_ambigu_jalan_dan_saluran_sekaligus_tidak_dipaksa(self):
        self.cek("Perencanaan Jalan dan Saluran", "Perencanaan Jalan dan Saluran", "Lainnya", "Konsultan")


class TestAturanSalah(unittest.TestCase):
    def test_regex_rusak(self):
        with self.assertRaises(AturanError):
            Pengklasifikasi({"kategori": [{"nama": "X", "cocok": {"nama_paket": "("}}]})

    def test_field_tidak_dikenal(self):
        with self.assertRaises(AturanError):
            Pengklasifikasi({"kategori": [{"nama": "X", "cocok": {"warna": "a"}}]})


class TestNormUraian(unittest.TestCase):
    def test_rapikan(self):
        self.assertEqual(norm_uraian("Pekerjaan Jalan;"), "Pekerjaan Jalan")
        self.assertEqual(norm_uraian("Tinta Printer; Tinta Printer;  tinta printer"), "Tinta Printer")
        self.assertEqual(norm_uraian("A;  B ; A"), "A; B")
        self.assertEqual(norm_uraian(""), "(tanpa uraian)")
        self.assertEqual(norm_uraian(None), "(tanpa uraian)")


if __name__ == "__main__":
    unittest.main()


class TestPenamaanLama(unittest.TestCase):
    """Sebelum 2021 nama paket berbeda (2020 dan sebelumnya)."""

    def test_pengadaan_jalan_kabupaten_kota_adalah_jalan(self):
        for nama in ("Belanja modal Pengadaan Jalan Kabupaten/Kota (Jl. Kom Yos Sudarso, Gang Karya 1)",
                     "Belanja Modal Pengadaan Jalan Kabupaten / Kota (Peningkatan Kualitas Lingkungan Permukiman)",
                     "Belanja  modal  Pengadaan  Jalan  Kabupaten/Kota ( Jl. Flora)"):
            self.assertEqual(K(nama, nama)[0], "Jalan", nama)

    def test_pengadaan_bangunan_pembuang_pengaman_sungai_adalah_saluran(self):
        for nama in ("Belanja modal Pengadaan Bangunan Pembuang Pengaman Sungai (Jl. Parit Tengah)",
                     "Belanja modal Pengadaan Bangunan Pembuang Pengaman Sungai (Belanja modal Pengadaan Bangunan Pembuang Pengaman Sungai)"):
            self.assertEqual(K(nama, nama)[0], "Saluran", nama)

    def test_perencanaan_pada_nama_lama_tetap_konsultan(self):
        nama = "Belanja modal Pengadaan Bangunan Pembuang Pengaman Sungai (- Perencanaan Penataan Drainase Lingkungan (Kec. Pontianak Barat))"
        self.assertEqual(K(nama, nama), ("Saluran", "Konsultan"))

    def test_aturan_baru_tidak_mengubah_nama_2021_ke_atas(self):
        self.assertEqual(K("Belanja Modal Jalan Kota (Jl. A)", "Pekerjaan Jalan"), ("Jalan", "Fisik"))
        self.assertEqual(K("Belanja Modal Saluran Pembuang Pasang Surut (Jl. A)", "Pekerjaan Saluran"), ("Saluran", "Fisik"))
        self.assertEqual(K("Belanja Alat/Bahan untuk Kegiatan Kantor", "ATK")[0], "Lainnya")
