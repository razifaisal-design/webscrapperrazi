"""Kategori paket untuk halaman Home: Jalan PSU, Saluran PSU, Jalan Kawasan Permukiman (config/kategori_home.json).
Penentuan murni dari MAK (sub kegiatan + rekening), hanya untuk tahun yang tercantum di `tahun_berlaku`. Yang tidak cocok -> None ('Lainnya')."""
import json
import re

from .. import konfig
from . import mak_ref

PATH = konfig.ROOT / "config" / "kategori_home.json"


def muat_aturan(path=None):
    return json.loads((path or PATH).read_text(encoding="utf-8"))


def kategori(mak_teks, tahun, aturan=None):
    """Kategori dari kolom MAK (boleh beberapa MAK dipisah ';'; yang pertama cocok dipakai). None = Lainnya / tahun tidak berlaku."""
    aturan = aturan or muat_aturan()
    if tahun not in aturan.get("tahun_berlaku", []):
        return None
    for mk in mak_ref.daftar_mak(mak_teks):
        sub, rek = mak_ref.kode_sub_kegiatan(mk), mak_ref.kode_rekening(mk)
        for k in aturan["kategori"]:
            if sub in k["sub_kegiatan"] and rek in k["rekening"]:
                return k["nama"]
    return None


def jenis_pekerjaan(nama_paket, pola_konsultan=None):
    """'Konsultan' bila nama paket memuat perencanaan/pengawasan/konsultan(si); selain itu 'Fisik'."""
    pola = pola_konsultan or konfig.muat_target(None)[1]["klasifikasi"]["konsultan"]
    return "Konsultan" if re.search(pola, nama_paket or "") else "Fisik"
