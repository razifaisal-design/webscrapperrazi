import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scraper import cli


class TestMuatTarget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = {"default": "a", "targets": {"a": {
            "id_satker": 1, "tahun": 2026, "periksa": {"mak_kategori": [{"awalan": "X", "kategori": "Jalan"}]},
            "per_tahun": {"2025": {"periksa": {"mak_kategori": [{"awalan": "Y", "kategori": "Jalan"}]}}}}}}
        self.path = Path(self.tmp.name) / "t.json"
        self.path.write_text(json.dumps(cfg))
        p = mock.patch.object(cli, "TARGETS", self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_tanpa_tahun_pakai_config(self):
        _, t = cli.muat_target(None)
        self.assertEqual(t["tahun"], 2026)
        self.assertNotIn("per_tahun", t)

    def test_tahun_menimpa(self):
        self.assertEqual(cli.muat_target(None, 2024)[1]["tahun"], 2024)

    def test_override_khusus_tahun_dan_tidak_bocor_ke_tahun_lain(self):
        self.assertEqual(cli.muat_target(None, 2025)[1]["periksa"]["mak_kategori"][0]["awalan"], "Y")
        self.assertEqual(cli.muat_target(None, 2024)[1]["periksa"]["mak_kategori"][0]["awalan"], "X")
        self.assertEqual(cli.muat_target(None)[1]["periksa"]["mak_kategori"][0]["awalan"], "X")

    def test_target_tidak_dikenal(self):
        with self.assertRaises(SystemExit):
            cli.muat_target("tidak-ada")


if __name__ == "__main__":
    unittest.main()
