"""Direktori satker di SiRUP: cari satker lewat NAMA (bukan ID).

Alur di situs SiRUP (data publik): kategori (KOTA, KABUPATEN, PROVINSI, ...) -> K/L/PD (mis. 'Kota Pontianak', id 'D199') -> daftar
satker beserta idSatker-nya PER TAHUN. idSatker bisa berbeda tiap tahun dan penamaan satker bisa berubah sedikit (mis.
'PEMUKIMAN' vs 'PERMUKIMAN'), jadi pencocokan nama dilakukan setelah dinormalkan, dengan kemiripan sebagai cadangan."""
import difflib
import re

BASE = "https://sirup.inaproc.id/sirup/datatablectr"
KATEGORI = ("KOTA", "KABUPATEN", "PROVINSI", "KEMENTERIAN", "LEMBAGA", "BUMN", "BUMD", "LAINNYA", "PTNBH", "SWASTA", "INSTANSI")
AMBANG_MIRIP = 0.88


def norm(nama):
    """'Dinas Perumahan, Rakyat dan Kawasan' -> 'DINAS PERUMAHAN RAKYAT DAN KAWASAN' (tanpa tanda baca & spasi ganda)."""
    return " ".join(re.sub(r"[^0-9A-Z]+", " ", (nama or "").upper()).split())


def _int(x):
    try:
        return int(str(x).replace(".", "").strip() or 0)
    except ValueError:
        return 0


def daftar_klpd(client, kategori, tahun):
    """K/L/PD dalam satu kategori -> [{id, nama, paket}]."""
    j = client.get_json(f"{BASE}/datatablerupkldi2", params={"tahun": tahun, "jenisID": kategori, "sEcho": 1, "iDisplayStart": 0, "iDisplayLength": 2000})
    return [{"id": str(r[0]), "nama": str(r[1]).strip(), "paket": _int(r[2]) if len(r) > 2 else 0} for r in j.get("aaData", [])]


def cari_klpd(client, nama, tahun, kategori=None):
    """K/L/PD dengan nama itu (persis setelah dinormalkan) -> {id, nama, kategori} atau None. Kategori yang dicoba berurutan."""
    sasaran = norm(nama)
    for kat in ([kategori] if kategori else KATEGORI):
        for k in daftar_klpd(client, kat, tahun):
            if norm(k["nama"]) == sasaran:
                return {**k, "kategori": kat}
    return None


def daftar_satker(client, id_klpd, tahun):
    """Satker di bawah satu K/L/PD pada tahun itu -> [{id, nama, paket}] (paket = total paket penyedia + swakelola)."""
    j = client.get_json(f"{BASE}/datatableruprekapkldi", params={"idKldi": id_klpd, "tahun": tahun, "sEcho": 1, "iDisplayStart": 0, "iDisplayLength": 1000})
    hasil = []
    for r in j.get("aaData", []):
        total = _int(r[8]) if len(r) > 8 else _int(r[2]) + _int(r[4])
        hasil.append({"id": int(r[0]), "nama": str(r[1]).strip(), "paket": total})
    return hasil


def cari_nama(daftar, nama):
    """Kandidat satker untuk sebuah nama, paling cocok dulu: persis (dinormalkan) -> mengandung -> mirip. Yang paketnya banyak didahulukan
    bila namanya sama. -> [{id, nama, paket, cocok}]"""
    q = norm(nama)
    if not q:
        return []
    peringkat = []
    for s in daftar:
        n = norm(s["nama"])
        if n == q:
            skor, cocok = 3.0, "persis"
        elif q in n or n in q:
            skor, cocok = 2.0 + min(len(q), len(n)) / max(len(q), len(n)), "mengandung"
        else:
            r = difflib.SequenceMatcher(None, q, n).ratio()
            if r < AMBANG_MIRIP:
                continue
            skor, cocok = r, "mirip"
        peringkat.append((skor, s["paket"], s, cocok))
    peringkat.sort(key=lambda x: (-x[0], -x[1], x[2]["nama"]))
    return [{**s, "cocok": c} for _, _, s, c in peringkat]


def id_untuk_tahun(daftar, nama):
    """idSatker untuk nama itu pada daftar satu tahun: kandidat 'persis' (atau 'mirip' bila tak ada yang persis) dengan paket terbanyak.
    -> (id | None, kandidat_lain) ; kandidat_lain = id lain yang namanya sama (satker kembar di SiRUP)."""
    kand = cari_nama(daftar, nama)
    persis = [k for k in kand if k["cocok"] == "persis"]
    pakai = persis or [k for k in kand if k["cocok"] == "mirip"]
    if not pakai:
        return None, []
    terbaik = max(pakai, key=lambda k: k["paket"])
    return terbaik["id"], [k["id"] for k in pakai if k["id"] != terbaik["id"] and k["paket"] > 0]
