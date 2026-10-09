import subprocess
import tempfile
import unittest
from pathlib import Path

from scraper import unggah


def hasil(kode=0, out="", err=""):
    return subprocess.CompletedProcess([], kode, out, err)


class TestUnggah(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.keluar = Path(self.tmp.name)
        (self.keluar / "index.html").write_text("x")
        self.cmd = []

    def jalan(self, balasan, cari=lambda n: "/usr/bin/npx"):
        def fake(perintah, cwd, waktu=600):
            self.cmd.append(perintah[3:])
            return balasan.pop(0)
        return unggah.unggah(self.keluar, log=lambda *a: None, jalankan=fake, cari=cari)

    def test_berhasil_dan_alamat_terbaca(self):
        ok, pesan = self.jalan([hasil(0, "You are logged in"), hasil(0, "Deployed pantau-pengadaan\n  https://pantau-pengadaan.razi-faisal.workers.dev\n")])
        self.assertEqual((ok, pesan), (True, "https://pantau-pengadaan.razi-faisal.workers.dev"))
        self.assertEqual([c[0] for c in self.cmd], ["whoami", "deploy"])

    def test_node_belum_terpasang(self):
        ok, pesan = self.jalan([], cari=lambda n: None)
        self.assertFalse(ok)
        self.assertIn("Node.js", pesan)
        self.assertEqual(self.cmd, [])

    def test_belum_login_tidak_mengunggah(self):
        ok, pesan = self.jalan([hasil(0, "You are not authenticated")])
        self.assertFalse(ok)
        self.assertIn("wrangler login", pesan)
        self.assertEqual([c[0] for c in self.cmd], ["whoami"])

    def test_wrangler_gagal_dilaporkan(self):
        ok, pesan = self.jalan([hasil(0, "ok"), hasil(1, "", "boom: kuota")])
        self.assertFalse(ok)
        self.assertIn("boom", pesan)

    def test_folder_belum_diekspor(self):
        (self.keluar / "index.html").unlink()
        ok, pesan = self.jalan([])
        self.assertFalse(ok)
        self.assertIn("ekspor-publik", pesan)


if __name__ == "__main__":
    unittest.main()
