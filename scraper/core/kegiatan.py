"""Jenis kegiatan + MAK Perbaikan + Jenis Perbaikan, supaya ada rekapan yang SEHARUSNYA benar.

Aturan (per paket, per MAK yang dipakai paket itu):
  kategori paket   = dari nama/uraian (Jalan / Saluran) -> inilah 'seharusnya'
  kategori MAK     = dari pemetaan MAK (config periksa.mak_kategori)
  SESUAI           : kategori paket == kategori MAK  -> Jenis Kegiatan = kategori itu, tanpa perbaikan
  SALAH_MAK        : beda                            -> Jenis Kegiatan = menurut MAK yang TERCATAT,
                                                        Jenis Perbaikan = kategori paket,
                                                        MAK Perbaikan  = MAK baku untuk kategori paket
  BELUM_DIPETAKAN  : MAK tidak ada di pemetaan       -> tidak bisa dinilai, dianggap benar
Konsultan diberi awalan 'Konsultan ' (mis. 'Konsultan Jalan'); 'Lainnya' tidak dinilai.
"""
from collections import defaultdict

from .mak import TANPA_MAK
from .periksa import JALAN, SALURAN, kategori_mak

SESUAI, SALAH_MAK, BELUM_DIPETAKAN, TIDAK_DINILAI = "Sesuai", "Salah MAK", "MAK belum dipetakan", "Tidak dinilai"


def _label(kategori, jenis_pekerjaan):
    if kategori in (JALAN, SALURAN):
        return f"Konsultan {kategori}" if jenis_pekerjaan == "Konsultan" else kategori
    return kategori or "Lainnya"


def tambahkan(data, aturan=None):
    """Mengisi tiap paket dengan: status_mak, jenis_kegiatan, jenis_perbaikan, mak_perbaikan, mak_akhir.
    Menambah data['perbaikan'] berisi rekap tercatat vs seharusnya (Semua / Fisik / Konsultan)."""
    aturan = aturan or {}
    peta = [(x["awalan"].rstrip("."), x["kategori"]) for x in aturan.get("mak_kategori", [])]
    baku = {x["kategori"]: x["mak_baku"] for x in aturan.get("mak_kategori", []) if x.get("mak_baku")}

    for p in data["paket"].values():
        kat = p["kategori"]
        jp = p.get("jenis_pekerjaan")
        entri = []  # (mak_tercatat, pagu, mak_akhir, status, kategori_menurut_mak)
        for mak, pagu in p.get("mak") or []:
            km = kategori_mak(mak, peta) if peta else None
            if kat not in (JALAN, SALURAN) or mak == TANPA_MAK or not peta:
                entri.append((mak, pagu, mak, TIDAK_DINILAI, None))
            elif km is None:
                entri.append((mak, pagu, mak, BELUM_DIPETAKAN, None))
            elif km == kat:
                entri.append((mak, pagu, mak, SESUAI, km))
            else:
                entri.append((mak, pagu, baku.get(kat, mak), SALAH_MAK, km))
        p["mak_entri"] = [
            {"mak": m, "pagu": v, "mak_akhir": a, "status": st, "kategori_mak": km} for m, v, a, st, km in entri]
        salah = [e for e in entri if e[3] == SALAH_MAK]
        p["status_mak"] = (SALAH_MAK if salah else BELUM_DIPETAKAN if any(e[3] == BELUM_DIPETAKAN for e in entri)
                           else SESUAI if any(e[3] == SESUAI for e in entri) else TIDAK_DINILAI)
        p["mak_perbaikan"] = sorted({e[2] for e in salah})
        p["mak_akhir"] = sorted({e[2] for e in entri}) or [TANPA_MAK]
        # jenis kegiatan = menurut MAK yang tercatat bila salah; selain itu = kategori paket
        km_salah = sorted({e[4] for e in salah})
        p["jenis_kegiatan"] = _label(km_salah[0], jp) if salah else _label(kat, jp)
        p["jenis_perbaikan"] = _label(kat, jp) if salah else None
        p["jenis_akhir"] = _label(kat, jp)

    data["perbaikan"] = {f: rekap_perbaikan(data["paket"].values(), f) for f in ("Semua", "Fisik", "Konsultan")}
    return data


def rekap_perbaikan(paket, filter_jp):
    """Per MAK: nilai yang TERCATAT vs yang SEHARUSNYA (setelah perbaikan), plus selisih."""
    mak = defaultdict(lambda: {"tercatat": {"pagu": 0, "paket": set()}, "seharusnya": {"pagu": 0, "paket": set()},
                               "jenis": set()})
    for p in paket:
        if filter_jp != "Semua" and p["jenis_pekerjaan"] != filter_jp:
            continue
        if p["kategori"] not in (JALAN, SALURAN):
            continue
        for e in p["mak_entri"]:
            a, b = mak[e["mak"]], mak[e["mak_akhir"]]
            a["tercatat"]["pagu"] += e["pagu"]
            a["tercatat"]["paket"].add(p["kode_rup"])
            b["seharusnya"]["pagu"] += e["pagu"]
            b["seharusnya"]["paket"].add(p["kode_rup"])
            b["jenis"].add(p["jenis_akhir"])
    baris = []
    for m, v in mak.items():
        t, s = v["tercatat"], v["seharusnya"]
        baris.append({"mak": m, "jenis": sorted(v["jenis"]),
                      "tercatat_pagu": t["pagu"], "tercatat_paket": len(t["paket"]),
                      "seharusnya_pagu": s["pagu"], "seharusnya_paket": len(s["paket"]),
                      "selisih_pagu": s["pagu"] - t["pagu"], "selisih_paket": len(s["paket"]) - len(t["paket"])})
    baris.sort(key=lambda x: -max(x["tercatat_pagu"], x["seharusnya_pagu"]))
    return {"mak": baris,
            "total_tercatat": sum(b["tercatat_pagu"] for b in baris),
            "total_seharusnya": sum(b["seharusnya_pagu"] for b in baris),
            "ada_perbaikan": any(b["selisih_pagu"] != 0 for b in baris)}
