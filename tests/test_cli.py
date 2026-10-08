import io
import unittest
from contextlib import redirect_stdout

from scraper import cli


class TestPerintahTerminal(unittest.TestCase):
    """Penjaga: setiap sub-perintah harus terbangun dan fungsinya ada (regresi: cmd_run/cmd_detail pernah hilang diam-diam)."""

    PERINTAH = [["ambil", "sirup"], ["run", "sirup"], ["detail", "sirup"], ["lokasi"], ["periksa"], ["web"], ["events"]]

    def test_semua_perintah_punya_bantuan_dan_fungsi(self):
        for p in self.PERINTAH:
            with self.subTest(perintah=p), redirect_stdout(io.StringIO()) as out:
                with self.assertRaises(SystemExit) as k:
                    cli.main(p + ["--help"])
                self.assertEqual(k.exception.code, 0)
                self.assertIn("usage", out.getvalue())

    def test_semua_fungsi_yang_dirujuk_parser_ada(self):
        for nama in ("cmd_run", "cmd_detail", "cmd_ambil", "cmd_lokasi", "cmd_periksa", "cmd_web", "cmd_events"):
            self.assertTrue(callable(getattr(cli, nama, None)), nama)

    def test_opsi_id_satker_tersedia_di_perintah_pengambilan(self):
        for p in (["ambil", "sirup"], ["run", "sirup"], ["detail", "sirup"]):
            with redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
                cli.main(p + ["--help"])
            self.assertIn("--id-satker", out.getvalue(), p)


if __name__ == "__main__":
    unittest.main()
