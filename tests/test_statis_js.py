import unittest
from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "scraper" / "statis.js").read_text(encoding="utf-8")


class TestStatisJs(unittest.TestCase):
    """Tidak ada Node di mesin ini, jadi pemeriksaan sederhana: setiap pembantu yang dipakai sudah didefinisikan (galat seperti 'jawab is not defined' lolos tanpa ini)."""

    def test_pembantu_yang_dipakai_terdefinisi(self):
        for nama in ("jawab", "norm", "muat", "asli", "cache", "unduhBerkas", "spse", "banding", "ringkasBanding", "api", "sbPermintaan", "ambil"):
            self.assertRegex(JS, rf"(const|function|async function) {nama}\b", nama)

    def test_data_selalu_diperiksa_kesegarannya(self):
        self.assertIn('cache: segar ? "no-store" : "default"', JS)                           # meta.json tanpa cache
        self.assertIn("ukuran=gte.-", JS)                                                    # alamat berkas data berubah tiap terbitan
        self.assertIn("m.dibuat !== versi", JS)                                              # penanda berubah -> buang salinan memori
        self.assertRegex(JS, r"const muat = async \(nama\) =>")

    def test_kunci_publikasi_tidak_pernah_dikirim_sebagai_bearer(self):
        self.assertNotIn("Authorization", JS)                                              # kunci publishable bukan JWT: hanya header apikey


if __name__ == "__main__":
    unittest.main()
