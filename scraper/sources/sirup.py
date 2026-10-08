"""Sumber SiRUP (sirup.inaproc.id): daftar RUP per satuan kerja, penyedia + swakelola."""
from ..core.money import parse_rupiah

BASE = "https://sirup.inaproc.id/sirup"
PER_HALAMAN = 100  # sama dengan memilih "Tampilkan 100 entri"

ENDPOINT = {
    "penyedia": f"{BASE}/datatablectr/dataruppenyediasatker",
    "swakelola": f"{BASE}/datatablectr/datarupswakelolasatker",
}


def link_paket(jenis, kode_rup):
    if jenis == "penyedia":
        return f"{BASE}/home/detailPaketPenyediaPublic2017/{kode_rup}"
    return f"{BASE}/home/detailPaketSwakelolaPublic2017?idPaket={kode_rup}"


def parse_baris(jenis, baris, target):
    """Satu baris aaData -> dict paket. Fungsi murni (mudah dites)."""
    if jenis == "penyedia":
        # [id, nama, pagu, metode, sumber_dana, kode_rup, waktu]
        kode, nama, pagu, metode, dana, _kode2, waktu = baris[:7]
        penyelenggara = None
    else:
        # [id, penyelenggara, nama, pagu, sumber_dana, kode_rup, waktu]
        kode, penyelenggara, nama, pagu, dana, _kode2, waktu = baris[:7]
        metode = "Swakelola"
    kode = str(kode).strip()
    if not kode.isdigit():
        raise ValueError(f"Kode RUP tidak valid: {kode!r}")
    return {
        "kode_rup": kode,
        "tahun": target["tahun"],
        "klpd_nama": target["klpd_nama"],
        "id_satker": target["id_satker"],
        "jenis": jenis,
        "nama_paket": " ".join(str(nama).split()),
        "penyelenggara": penyelenggara,
        "pagu": parse_rupiah(pagu),
        "metode_pemilihan": " ".join(str(metode).split()),
        "sumber_dana": str(dana).strip(),
        "waktu_pemilihan": str(waktu).strip(),
        "link": link_paket(jenis, kode),
    }


def _params(target, mulai, jumlah):
    return {
        "tahun": target["tahun"],
        "idSatker": target["id_satker"],
        "sEcho": 1,
        "iDisplayStart": mulai,
        "iDisplayLength": jumlah,
        "sSearch": "",
        "iSortCol_0": 5,  # urut Kode RUP agar paging stabil
        "sSortDir_0": "asc",
        "iSortingCols": 1,
        "mDataProp_5": 5,
        "bSortable_5": "true",
    }


def ambil_semua(client, jenis, target, log=print):
    """Ambil semua halaman. Mengembalikan (daftar_paket, total_dilaporkan_situs)."""
    url = ENDPOINT[jenis]
    paket, total, mulai = [], None, 0
    while True:
        data = client.get_json(url, _params(target, mulai, PER_HALAMAN))
        total = int(data["iTotalDisplayRecords"])
        baris = data["aaData"]
        paket.extend(parse_baris(jenis, b, target) for b in baris)
        log(f"  [{jenis}] {len(paket)}/{total}")
        mulai += PER_HALAMAN
        if not baris or mulai >= total:
            break
    return paket, total
