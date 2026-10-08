"""Rekap untuk dashboard: hanya paket yang SUDAH diambil detailnya.
Pagu dijumlahkan per MAK, per Uraian, dan (bila ada aturan) per kategori Jalan/Saluran."""
import json

from .klasifikasi import FISIK, KONSULTAN, LAINNYA, Pengklasifikasi
from .mak import SEGMEN_DEFAULT, TANPA_MAK, norm_mak

TANPA_URAIAN = "(tanpa uraian)"


def norm_uraian(uraian):
    """'A; A; B;' -> 'A; B' : rapikan spasi, buang pengulangan segmen identik, buang ';' di ujung."""
    bagian, lihat = [], set()
    for x in (uraian or "").split(";"):
        x = " ".join(x.split())
        if x and x.lower() not in lihat:
            lihat.add(x.lower())
            bagian.append(x)
    return "; ".join(bagian) or TANPA_URAIAN


def _ringkas_kategori(klas, paket):
    hasil = {}
    for nama in klas.kategori:
        hasil[nama] = {"total_pagu": 0, "jumlah_paket": 0,
                       FISIK: {"total_pagu": 0, "jumlah_paket": 0},
                       KONSULTAN: {"total_pagu": 0, "jumlah_paket": 0}, "paket": []}
    for p in paket:
        g = hasil[p["kategori"]]
        for b in (g, g[p["jenis_pekerjaan"]]):
            b["total_pagu"] += p["pagu"]
            b["jumlah_paket"] += 1
        g["paket"].append(p["kode_rup"])
    return hasil


def rekap_mak(conn, id_satker, tahun, aturan=None, mak_segmen=SEGMEN_DEFAULT):
    klas = Pengklasifikasi(aturan) if aturan else None
    aktif = conn.execute(
        "SELECT COUNT(*) FROM sirup_paket WHERE id_satker=? AND tahun=? AND is_active=1", (id_satker, tahun)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT p.kode_rup,p.jenis,p.nama_paket,p.pagu,p.link,d.sumber_dana_json,d.uraian,d.volume,d.diambil_pada "
        "FROM sirup_paket p JOIN sirup_detail d ON d.kode_rup=p.kode_rup AND d.error IS NULL "
        "WHERE p.id_satker=? AND p.tahun=? AND p.is_active=1",
        (id_satker, tahun),
    ).fetchall()

    per_mak, per_uraian, paket, total_daftar, terakhir = {}, {}, {}, 0, None
    for r in rows:
        total_daftar += r["pagu"] or 0
        if r["diambil_pada"] and (terakhir is None or r["diambil_pada"] > terakhir):
            terakhir = r["diambil_pada"]
        rincian = json.loads(r["sumber_dana_json"] or "[]") or [{"mak": "", "pagu": r["pagu"] or 0}]
        pagu_detail = sum(s.get("pagu") or 0 for s in rincian)
        uraian = norm_uraian(r["uraian"])
        kategori, jenis_kerja = klas(r["nama_paket"], uraian) if klas else (None, None)
        paket[r["kode_rup"]] = {
            "kode_rup": r["kode_rup"], "nama_paket": r["nama_paket"], "jenis": r["jenis"], "link": r["link"],
            "uraian": uraian, "volume": r["volume"], "pagu": pagu_detail, "pagu_daftar": r["pagu"], "mak": [],
            "kategori": kategori, "jenis_pekerjaan": jenis_kerja}

        gu = per_uraian.setdefault(uraian.lower(), {"uraian": uraian, "total_pagu": 0, "paket": []})
        gu["total_pagu"] += pagu_detail
        gu["paket"].append(r["kode_rup"])

        gabung = {}
        for s in rincian:
            m = norm_mak(s.get("mak"), mak_segmen)
            gabung[m] = gabung.get(m, 0) + (s.get("pagu") or 0)
        paket[r["kode_rup"]]["mak"] = [[m, v] for m, v in gabung.items()]
        for s in rincian:
            g = per_mak.setdefault(norm_mak(s.get("mak"), mak_segmen), {"total_pagu": 0, "paket": {}})
            g["total_pagu"] += s.get("pagu") or 0
            g["paket"][r["kode_rup"]] = g["paket"].get(r["kode_rup"], 0) + (s.get("pagu") or 0)

    daftar_mak = sorted(
        ({"mak": mak, "jumlah_paket": len(g["paket"]), "total_pagu": g["total_pagu"],
          "paket": sorted(([k, v] for k, v in g["paket"].items()), key=lambda x: -x[1])}
         for mak, g in per_mak.items()), key=lambda x: -x["total_pagu"])
    daftar_uraian = sorted(
        ({"uraian": g["uraian"], "jumlah_paket": len(g["paket"]), "total_pagu": g["total_pagu"],
          "paket": sorted(g["paket"], key=lambda k: -paket[k]["pagu"])}
         for g in per_uraian.values()), key=lambda x: -x["total_pagu"])

    total_mak = sum(x["total_pagu"] for x in daftar_mak)
    return {
        "paket_aktif": aktif,
        "paket_dengan_detail": len(rows),
        "jumlah_mak": len(daftar_mak),
        "jumlah_uraian": len(daftar_uraian),
        "total_pagu_mak": total_mak,
        "total_pagu_daftar": total_daftar,
        "selisih": total_mak - total_daftar,   # harus 0; bila tidak, data detail & daftar tidak sejalan
        "detail_terakhir_diambil": terakhir,
        "per_mak": daftar_mak,
        "per_uraian": daftar_uraian,
        "klasifikasi": _ringkas_kategori(klas, paket.values()) if klas else None,
        "paket": paket,
    }


def lengkap(conn, target):
    """Rekap + hasil pemeriksaan untuk satu target dari config/targets.json."""
    from . import periksa
    data = rekap_mak(conn, target["id_satker"], target["tahun"], target.get("klasifikasi"),
                     target.get("mak_segmen", SEGMEN_DEFAULT))
    data["periksa"] = periksa.jalankan(data, target.get("periksa"))
    return data
