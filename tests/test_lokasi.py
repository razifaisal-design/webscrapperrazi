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


class TestGabungJalan(unittest.TestCase):
    def _bangun(self, *nama, pagu=100):
        return bangun([paket(str(i), n, pagu=pagu) for i, n in enumerate(nama, 1)])

    def test_jalan_sama_beda_tahun_dan_ejaan_jadi_satu_baris(self):
        from scraper.core.lokasi import gabung_jalan
        a = self._bangun("X (Jl. Adisucipto, Gg. A, Kec. Pontianak Timur)", "X (Jl. Flora, Gg. B, Kec. Pontianak Utara)")
        b = self._bangun("X (Jl. Adi Sucipto, Gg. A, Kec. Pontianak Timur)", "X (Jl. Danau Sentarum, Gg. C, Kec. Pontianak Kota)", pagu=50)
        g = gabung_jalan({2025: a, 2026: b})
        self.assertEqual(len(g), 3)                                     # Adisucipto = Adi Sucipto
        adi = next(j for j in g if "sucipto" in j["nama"].lower())
        self.assertEqual((adi["tahun"], adi["jumlah_paket"], adi["total_pagu"]), ([2025, 2026], 2, 150))
        self.assertEqual(adi["per_tahun"]["2025"]["paket"], 1)
        self.assertEqual(len(adi["variasi"]), 1)                        # ejaan lain tercatat
        self.assertEqual(adi["kecamatan"], ["Pontianak Timur"])

    def test_gang_yang_sama_di_dua_tahun_dihitung_sekali(self):
        from scraper.core.lokasi import gabung_jalan
        a = self._bangun("X (Jl. Flora, Gg. Mawar, Kec. Pontianak Utara)")
        b = self._bangun("X (Jl. Flora, Gg. Mawar, Kec. Pontianak Utara)", "X (Jl. Flora, Gg. Melati, Kec. Pontianak Utara)")
        flora = gabung_jalan({2025: a, 2026: b})[0]
        self.assertEqual(flora["jumlah_gang"], 2)
        mawar = next(x for x in flora["gang"] if "Mawar" in x["nama"])
        self.assertEqual(mawar["tahun"], [2025, 2026])

    def test_urut_nama_dan_satu_tahun_saja_berfungsi(self):
        from scraper.core.lokasi import gabung_jalan
        g = gabung_jalan({2026: self._bangun("X (Jl. Zebra, Gg. A)", "X (Jl. Anggrek, Gg. A)")})
        self.assertEqual([j["nama"] for j in g], ["Jl. Anggrek", "Jl. Zebra"])
        self.assertEqual(gabung_jalan({}), [])

    def test_kunci_pada_jalan_dan_gang(self):
        r = self._bangun("X (Jl. Flora, Gg. Mawar)")
        self.assertEqual(r["jalan"][0]["kunci"], "flora")
        self.assertEqual((r["gang"][0]["jalan_kunci"], r["gang"][0]["kunci"]), ("flora", "flora|Gang|mawar"))


class TestGabungGang(unittest.TestCase):
    def _b(self, *nama, pagu=100):
        return bangun([paket(str(i), n, pagu=pagu) for i, n in enumerate(nama, 1)])

    def test_gang_sama_beda_tahun_dan_ejaan_jadi_satu(self):
        from scraper.core.lokasi import gabung_gang
        a = self._b("X (Jl. Flora, Gg. Karya Bakti 2, Kec. Pontianak Utara)")
        b = self._b("X (Jl. Flora, Gg.Karyabakti 2, Kec. Pontianak Utara)", pagu=50)
        g = gabung_gang({2025: a, 2026: b})
        self.assertEqual(len(g), 1)
        self.assertEqual((g[0]["tahun"], g[0]["jumlah_paket"], g[0]["total_pagu"], g[0]["jalan"]), ([2025, 2026], 2, 150, "Jl. Flora"))
        self.assertEqual(len(g[0]["variasi"]), 1)

    def test_nama_gang_sama_di_jalan_berbeda_tidak_digabung_tapi_ditandai(self):
        from scraper.core.lokasi import gabung_gang
        g = gabung_gang({2026: self._b("X (Jl. A, Gg. Mawar)", "X (Jl. B, Gg. Mawar)", "X (Jl. B, Gg. Melati)")})
        self.assertEqual(len(g), 3)
        mawar = [x for x in g if "Mawar" in x["nama"]]
        self.assertEqual([x["nama_sama_di_jalan_lain"] for x in mawar], [1, 1])
        self.assertEqual(next(x for x in g if "Melati" in x["nama"])["nama_sama_di_jalan_lain"], 0)

    def test_gang_dan_komplek_bernama_sama_dibedakan(self):
        from scraper.core.lokasi import gabung_gang
        g = gabung_gang({2026: self._b("X (Jl. A, Gg. Indah)", "X (Jl. A, Komp. Indah)")})
        self.assertEqual(sorted(x["tipe"] for x in g), ["Gang", "Komplek"])

    def test_kosong_dan_urutan(self):
        from scraper.core.lokasi import gabung_gang
        self.assertEqual(gabung_gang({}), [])
        g = gabung_gang({2026: self._b("X (Jl. B, Gg. Z)", "X (Jl. A, Gg. Y)")})
        self.assertEqual([x["jalan"] for x in g], ["Jl. A", "Jl. B"])


class TestNamaLama(unittest.TestCase):
    def test_awalan_pengadaan_jalan_kabupaten_kota_tidak_terbaca_sebagai_nama_jalan(self):
        h = parse_nama("Belanja modal Pengadaan Jalan Kabupaten/Kota (Peningkatan Kualitas Lingkungan Permukiman Kota Pontianak Jl. PGA, Gang Karya 1 Kec. Pontianak Kota)")
        self.assertEqual((h["jalan"], h["gang"], h["kecamatan"]), ("PGA", ["Karya 1"], "Pontianak Kota"))

    def test_awalan_bangunan_pembuang_pengaman_sungai(self):
        h = parse_nama("Belanja modal Pengadaan Bangunan Pembuang Pengaman Sungai (Jl. Tanjung Raya 2, Gg. Mawar, Kec. Pontianak Timur)")
        self.assertEqual((h["jalan"], h["gang"], h["kecamatan"]), ("Tanjung Raya 2", ["Mawar"], "Pontianak Timur"))

    def test_nama_lama_tanpa_lokasi_jalan_tidak_menghasilkan_jalan_palsu(self):
        h = parse_nama("Belanja modal Pengadaan Bangunan Pembuang Pengaman Sungai (Belanja modal Pengadaan Bangunan Pembuang Pengaman Sungai)")
        self.assertIsNone(h["jalan"])
