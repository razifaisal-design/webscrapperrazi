import unittest

from scraper.core.money import parse_rupiah


class TestRupiah(unittest.TestCase):
    def test_format_indonesia(self):
        self.assertEqual(parse_rupiah("Rp 150.000.000,00"), 150000000)  # bug Gemini: jadi x100
        self.assertEqual(parse_rupiah("8.915.000"), 8915000)
        self.assertEqual(parse_rupiah("1.500,50"), 1500.5)

    def test_angka_polos_dan_kosong(self):
        self.assertEqual(parse_rupiah("8915000"), 8915000)
        self.assertEqual(parse_rupiah(""), 0)
        self.assertEqual(parse_rupiah(None), 0)

    def test_negatif(self):
        self.assertEqual(parse_rupiah("-1.000"), -1000)
        self.assertEqual(parse_rupiah("(2.500)"), -2500)


if __name__ == "__main__":
    unittest.main()
