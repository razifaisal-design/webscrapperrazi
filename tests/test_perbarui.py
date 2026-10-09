import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scraper import cli, konfig, tugas
from scraper.core import db


class TestPerbarui(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "t.db")
        self.conn = db.buka(self.path)
        self.panggilan = []
        self.kode = {"semua": 0, "spse": 0, "periksa": 0}

        def semua(conn, target, **kw):
            self.panggilan.append(("sirup", target["satker_nama"], target["tahun"], kw["koneksi"], kw["jeda"]))
            return self.kode["semua"]

        def spse(conn, jenis, lpse, tahun, **kw):
            self.panggilan.append(("spse", tahun, kw["satker"], kw["koneksi"]))
            return self.kode["spse"]

        def periksa(conn, kodes, **kw):
            self.panggilan.append(("periksa", list(kodes)))
            return self.kode["periksa"]

        def ekspor(db_path, keluar, **kw):
            self.panggilan.append(("ekspor", str(keluar)))
            return {"berkas": 3, "ukuran_mb": 0.1}

        for nama, fn in (("run_semua", semua), ("run_spse_semua", spse), ("run_periksa_rup", periksa),
                         ("kode_rup_tak_berpasangan", lambda conn, th, sat=None: ["1", "2"])):
            p = mock.patch.object(tugas, nama, fn)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("scraper.ekspor_publik.ekspor", ekspor)
        p.start()
        self.addCleanup(p.stop)

    def jalan(self, **kw):
        logs = []
        kode = tugas.run_perbarui(self.conn, self.path, log=logs.append, keluar="/tmp/keluar-uji", **kw)
        return kode, logs

    def test_urutan_lengkap_dan_parameter(self):
        kode, logs = self.jalan(tahun=2025, koneksi=3, jeda=2)
        self.assertEqual(kode, 0)
        self.assertEqual([p[0] for p in self.panggilan], ["sirup", "spse", "periksa", "ekspor"])
        self.assertEqual(self.panggilan[0][2:], (2025, 3, 2))
        self.assertEqual(self.panggilan[1], ("spse", 2025, None, 3))              # rincian semua satker
        self.assertEqual(self.panggilan[2], ("periksa", ["1", "2"]))

    def test_opsi_rinci_dan_lewati_langkah(self):
        self.jalan(rinci="tidak", periksa=False, ekspor=False)
        self.assertEqual([p[0] for p in self.panggilan], ["sirup", "spse"])
        self.assertEqual(self.panggilan[1][2], "__tidak")
        self.panggilan.clear()
        self.jalan(rinci="DINAS X", periksa=False, ekspor=False)
        self.assertEqual(self.panggilan[1][2], "DINAS X")

    def test_diblokir_menghentikan_semuanya_dan_tidak_ekspor_data_setengah(self):
        self.kode["spse"] = 2
        kode, logs = self.jalan()
        self.assertEqual(kode, 2)
        self.assertEqual([p[0] for p in self.panggilan], ["sirup", "spse"])        # tidak periksa, tidak ekspor
        self.assertTrue(any("DIBLOKIR" in x for x in logs))

    def test_kegagalan_biasa_dicatat_tapi_alur_lanjut(self):
        self.kode["semua"] = 3                                                      # mis. tahun tidak ada datanya
        kode, logs = self.jalan()
        self.assertEqual(kode, 1)
        self.assertEqual([p[0] for p in self.panggilan], ["sirup", "spse", "periksa", "ekspor"])

    def test_unggah_hanya_bila_diminta_dan_setelah_ekspor_berhasil(self):
        dipanggil = []
        with mock.patch("scraper.unggah.unggah", lambda keluar=None, log=print: dipanggil.append(keluar) or (True, "https://x.workers.dev")):
            self.jalan()
            self.assertEqual(dipanggil, [])                                    # tanpa --unggah: tidak ada yang diunggah
            kode, logs = self.jalan(unggah=True)
            self.assertEqual((kode, len(dipanggil)), (0, 1))
            self.assertTrue(any("workers.dev" in x for x in logs))
            self.kode["spse"] = 2                                              # diblokir -> ekspor dan unggah tidak jalan
            self.jalan(unggah=True)
            self.assertEqual(len(dipanggil), 1)
        with mock.patch("scraper.unggah.unggah", lambda keluar=None, log=print: (False, "Node.js belum terpasang")):
            self.kode["spse"] = 0
            kode, logs = self.jalan(unggah=True)
            self.assertEqual(kode, 1)                                          # tidak terunggah = ada catatan, bukan sukses diam-diam
            self.assertTrue(any("TIDAK TERUNGGAH" in x for x in logs))

    def test_satker_tidak_terdaftar_ditolak(self):
        with self.assertRaises(ValueError):
            self.jalan(satker="Dinas Antah Berantah")
        self.assertEqual(self.panggilan, [])

    def test_satker_dipilih_lewat_nama(self):
        self.jalan(satker="dinas perumahan rakyat dan kawasan permukiman", ekspor=False, periksa=False)
        self.assertEqual(self.panggilan[0][1], "DINAS PERUMAHAN RAKYAT DAN KAWASAN PERMUKIMAN")

    def test_perintah_cli_terdaftar(self):
        parser = cli.buat_parser() if hasattr(cli, "buat_parser") else None
        self.assertTrue((Path(__file__).resolve().parents[1] / "Perbarui dan Ekspor Publik.command").exists())
        self.assertTrue(cli.cmd_perbarui)


if __name__ == "__main__":
    unittest.main()
