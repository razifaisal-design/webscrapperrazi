import re
import unittest
from pathlib import Path

YML = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "perbarui.yml").read_text(encoding="utf-8")


class TestWorkflow(unittest.TestCase):
    def test_jadwal_00_dan_13_wib(self):
        self.assertEqual(re.findall(r'- cron: "([^"]+)"', YML), ["0 17 * * *", "0 6 * * *"])          # UTC: 17:00 = 00:00 WIB, 06:00 = 13:00 WIB

    def test_aman(self):
        self.assertIn("permissions:\n  contents: read", YML)
        self.assertIn("cancel-in-progress: false", YML)
        self.assertNotRegex(YML, r"postgresql://\S+:\S+@")                                             # tidak ada kata sandi tertanam
        self.assertIn("secrets.SUPABASE_DB_URL", YML)

    def test_urutan_langkah(self):
        urut = [YML.index(x) for x in ("run: python -m unittest", "name: Cek akses", "run: python -m scraper tarik", "run: python -m scraper perbarui")]
        self.assertEqual(urut, sorted(urut))


if __name__ == "__main__":
    unittest.main()
