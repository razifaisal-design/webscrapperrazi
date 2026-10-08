import unittest

from scraper.core.lokasi import bangun, kunci, parse_nama


def paket(kode, nama, kat="Jalan", pagu=100):
    return {"kode_rup": kode, "nama_paket": nama, "kategori": kat, "pagu": pagu}


class TestParseNama(unittest.TestCase):
    def test_bentuk_baku(self):
        h = parse_nama("Belanja Modal Jalan Kota (Jl. Imam Bonjol, Gg. Peniti Baru, Kec. Pontianak Tenggara)")
        self.assertEqual((h["jalan"], h["gang"], h["kecamatan"]), ("Imam Bonjol", ["Peniti Baru"], "Pontianak Tenggara"))

    def test_keterangan_dalam_kurung_di_akhir_tidak_mengganggu(self):
        h = parse_nama("Belanja Modal Jalan Kota (Jl. Flora, Gg. Flora 4, Kec. Pontianak Utara (Jalan Pendukung Sekolah Rakyat))")
        self.assertEqual((h["jalan"], h["gang"]), ("Flora", ["Flora 4"]))

    def test_jalan_ditulis_Jalan_tanpa_koma(self):
        h = parse_nama("Belanja Modal Jalan Kota (Jalan Danau Sentarum Gg.Kali Bening, Kel Sungai Bangkong Pontianak Kota)")
        self.assertEqual((h["jalan"], h["gang"], h["kecamatan"]), ("Danau Sentarum", ["Kali Bening"], "Pontianak Kota"))

    def test_JI_huruf_I_kapital_salah_ketik(self):
        h = parse_nama("Belanja Modal Saluran Pembuang Pasang Surut (JI. Purnama 1, Komp. Purnama Agung 7, Kec. Pontianak Selatan)")
        self.assertEqual((h["jalan"], h["komplek"], h["gang"]), ("Purnama 1", ["Purnama Agung 7"], []))

    def test_dua_gang_dipisah_dan(self):
        h = parse_nama("Belanja Modal Jalan Kota (Jl. H. M. Suwignyo, Gg. Arafah Dan Gg. Nur Asyikin, Kec. Pontianak Kota)")
        self.assertEqual(h["gang"], ["Arafah", "Nur Asyikin"])

    def test_gang_di_dalam_kurung_nama_lama_ikut_tercatat(self):
        h = parse_nama("Belanja Modal Jalan Kota (Jl. Khatulistiwa, (Gg. Barokah) Gg. Karya Usaha, Kec. Pontianak Utara)")
        self.assertEqual(h["gang"], ["Barokah", "Karya Usaha"])

    def test_keterangan_lanjutan_dibuang_dari_nama_gang(self):
        h = parse_nama("Belanja Modal Jalan Kota (Jl. Putri Daranante, Gg. Ambotin 1 (lanjutan) dan Gg. Ambotin 2, Kec. Pontianak Kota)")
        self.assertEqual(h["gang"], ["Ambotin 1", "Ambotin 2"])

    def test_gang_menempel_pada_jalan_tanpa_pemisah(self):
        h = parse_nama("Belanja Modal Jalan Kota (Jl. Karet Gg. Karet Permai Dalam, Kec. Pontianak barat)")
        self.assertEqual((h["jalan"], h["gang"], h["kecamatan"]), ("Karet", ["Karet Permai Dalam"], "Pontianak Barat"))

    def test_bentuk_Pekerjaan_Jl(self):
        h = parse_nama("Belanja Modal Jalan Kota-Pekerjaan Jl.Tanjung Harapan Gg.H.Ali Hasan Kec. Pontianak Timur")
        self.assertEqual((h["jalan"], h["gang"]), ("Tanjung Harapan", ["H.Ali Hasan"]))

    def test_apostrof_html(self):
        h = parse_nama("Belanja Modal Jalan Kota (Jl. Ya&#x27; M. Sabran, Gg. 86, Kec. Pontianak Timur)")
        self.assertEqual((h["jalan"], h["gang"]), ("Ya' M. Sabran", ["86"]))

    def test_kecamatan_salah_ketik_dikenali(self):
        self.assertEqual(parse_nama("X (Jl. A, Gg. B, Kec. Pontainak Utara)")["kecamatan"], "Pontianak Utara")
        self.assertEqual(parse_nama("X (Jl. A, Blok T, Kec. Pontianak Tengara)")["kecamatan"], "Pontianak Tenggara")

    def test_tanpa_kecamatan_dan_tanpa_gang(self):
        h = parse_nama("Belanja Modal Jalan Kota (JL. Harapan Jaya Blok A)")
        self.assertEqual((h["kecamatan"], h["gang"]), (None, []))

    def test_semua_penulisan_awalan(self):
        for jl in ("Jl.", "Jl", "JL.", "JI.", "Jalan", "jalan"):
            self.assertEqual(parse_nama(f"X ({jl} Flora, Gg. A, Kec. Pontianak Utara)")["jalan"], "Flora", jl)
        for gg in ("Gg.", "Gg", "GG.", "Gang"):
            self.assertEqual(parse_nama(f"X (Jl. Flora, {gg} Mawar, Kec. Pontianak Utara)")["gang"], ["Mawar"], gg)
        for kp in ("Komp.", "Komp", "Komplek", "Perumahan", "Perum."):
            self.assertEqual(parse_nama(f"X (Jl. Flora, {kp} Indah, Kec. Pontianak Utara)")["komplek"], ["Indah"], kp)
        for kc in ("Kec.", "Kec", "Kecamatan", "Kec,"):
            self.assertEqual(parse_nama(f"X (Jl. Flora, Gg. A, {kc} Pontianak Utara)")["kecamatan"], "Pontianak Utara", kc)

    def test_gang_dengan_koma_setelah_Gg(self):
        h = parse_nama("Belanja Modal Jalan Kota (Jl. Parit Tengah, Gg, Mekar Kurnia, Kec. Pontianak Barat)")
        self.assertEqual((h["jalan"], h["gang"]), ("Parit Tengah", ["Mekar Kurnia"]))
        h = parse_nama("Belanja Modal Saluran Pembuang Pasang Surut (Jl. Kenari. Gg, Kasturi Raja, Kec. Pontianak Kota)")
        self.assertEqual((h["jalan"], h["gang"]), ("Kenari", ["Kasturi Raja"]))

    def test_nama_jalan_tidak_terbaca(self):
        self.assertIsNone(parse_nama("Belanja Modal Jalan Kota (lokasi belum ditentukan)")["jalan"])


class TestBangun(unittest.TestCase):
    def test_ejaan_beda_digabung_jadi_satu_jalan(self):
        r = bangun([paket("1", "X (Jl. H. Rais A. Rahman, Gg. A, Kec. Pontianak Barat)", pagu=100),
                    paket("2", "X (Jalan H.Rais A Rahman, Gg. B, Kec. Pontianak Barat)", pagu=50),
                    paket("3", "X (Jl. Adi Sucipto, Gg. C)"), paket("4", "X (Jl. Adisucipto, Gg. C)")])
        self.assertEqual(len(r["jalan"]), 2)
        rais = next(j for j in r["jalan"] if "Rais" in j["nama"])
        self.assertEqual((rais["jumlah_paket"], rais["jumlah_gang"], rais["total_pagu"]), (2, 2, 150))
        self.assertEqual(len(rais["variasi"]), 1)

    def test_gang_sama_di_jalan_berbeda_adalah_gang_berbeda(self):
        r = bangun([paket("1", "X (Jl. A, Gg. Mawar)"), paket("2", "X (Jl. B, Gg. Mawar)")])
        self.assertEqual(len(r["gang"]), 2)

    def test_gang_dan_komplek_dibedakan(self):
        r = bangun([paket("1", "X (Jl. A, Gg. Mawar)"), paket("2", "X (Jl. A, Komp. Mawar Indah)")])
        self.assertEqual(sorted(g["tipe"] for g in r["gang"]), ["Gang", "Komplek"])

    def test_tidak_terbaca_dilaporkan(self):
        self.assertEqual(bangun([paket("9", "tanpa nama jalan")])["tidak_terbaca"], ["9"])

    def test_kunci(self):
        self.assertEqual(kunci("Kom. Yos. Sudarso"), kunci("Komyos Sudarso"))


if __name__ == "__main__":
    unittest.main()


class TestKelurahan(unittest.TestCase):
    def test_bersihkan_sisa_kata(self):
        self.assertEqual(parse_nama("X (Jl. A, Gg. B, Kel. Banjar Serasan Kecamatan Pontianak Timur)")["kelurahan"], "Banjar Serasan")
        self.assertEqual(parse_nama("X (Jl. A, Kel.Sungai Jawi Pontiaank Kota, Kota Pontianak)")["kelurahan"], "Sungai Jawi")
        self.assertEqual(parse_nama("X (Jl. A, Gg. B, Kelurahan Parit Mayor Pontianak Timur)")["kelurahan"], "Parit Mayor")

    def test_tanpa_kelurahan_kosong(self):
        h = parse_nama("X (Jl. A, Gg. B, Kec. Pontianak Timur)")
        self.assertIsNone(h["kelurahan"])
        self.assertEqual(h["kecamatan"], "Pontianak Timur")
