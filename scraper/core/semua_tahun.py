"""Mode 'Semua tahun' untuk dashboard: tiap tahun dihitung sendiri dengan aturannya (pemetaan MAK bisa beda per tahun),
lalu digabung. Kode RUP unik lintas tahun, jadi paket tidak pernah bentrok."""
from . import kegiatan, lokasi, rekap
from .periksa import BELUM_DIPETAKAN, JALAN, SALURAN


def hitung_per_tahun(conn, ambil_target, id_satker):
    """[(target, data)] untuk setiap tahun yang ada di database (urut tahun)."""
    tahun = [r[0] for r in conn.execute("SELECT DISTINCT tahun FROM sirup_paket WHERE id_satker=? ORDER BY tahun", (id_satker,))]
    hasil = []
    for th in tahun:
        t = ambil_target(th)
        hasil.append((t, rekap.lengkap(conn, t)))
    return hasil


def _gabung_periksa(daftar):
    ringkas, temuan = {}, []
    for d in daftar:
        temuan += d["temuan"]
        for k, r in d["ringkas"].items():
            x = ringkas.setdefault(k, {"judul": r["judul"], "tingkat": r["tingkat"], "jumlah": 0, "pagu": 0})
            x["jumlah"] += r["jumlah"]
            x["pagu"] += r["pagu"]
    temuan.sort(key=lambda t: (t["tingkat"] != "kesalahan", t["jenis"], -(t["pagu"] or 0)))
    matriks = None
    punya = [d["matriks"] for d in daftar if d["matriks"]]
    if punya:
        kolom = list(dict.fromkeys(k for m in punya for k in m["kolom"]))
        nilai = {b: {k: {"pagu": 0, "paket": 0} for k in kolom} for b in (JALAN, SALURAN)}
        for m in punya:
            for b in (JALAN, SALURAN):
                for k, v in m["nilai"][b].items():
                    nilai[b][k]["pagu"] += v["pagu"]
                    nilai[b][k]["paket"] += v["paket"]
        matriks = {"kolom": kolom, "baris": [JALAN, SALURAN], "nilai": nilai}
    return {"jumlah_kesalahan": sum(d["jumlah_kesalahan"] for d in daftar),
            "jumlah_peringatan": sum(d["jumlah_peringatan"] for d in daftar),
            "ringkas": ringkas, "temuan": temuan, "matriks": matriks}


def gabung(daftar):
    """daftar = [(target, data)] -> satu `data` bergaya rekap.lengkap() untuk semua tahun."""
    if not daftar:
        return None
    datas = [d for _, d in daftar]
    paket = {}
    for d in datas:
        paket.update(d["paket"])
    daftar_mak, daftar_uraian = rekap.agregat_dari_paket(paket)
    klas = datas[0]["klasifikasi"]
    kec = next(((t.get("lokasi") or {}).get("wilayah") for t, _ in daftar if (t.get("lokasi") or {}).get("wilayah")), None)
    kec_daftar = list(kec) if kec else lokasi._KECAMATAN_DEFAULT
    fisik = [p for p in paket.values() if p["kategori"] in (JALAN, SALURAN) and p["jenis_pekerjaan"] == "Fisik"]
    total_mak = sum(g["total_pagu"] for g in daftar_mak)
    total_daftar = sum(d["total_pagu_daftar"] for d in datas)
    terakhir = max((d["detail_terakhir_diambil"] for d in datas if d["detail_terakhir_diambil"]), default=None)
    ev = {}
    for d in datas:
        for k, v in d["perubahan"]["per_jenis"].items():
            ev[k] = ev.get(k, 0) + v
    hasil = {
        "paket_aktif": sum(d["paket_aktif"] for d in datas),
        "paket_dengan_detail": sum(d["paket_dengan_detail"] for d in datas),
        "jumlah_mak": len(daftar_mak), "jumlah_uraian": len(daftar_uraian),
        "total_pagu_mak": total_mak, "total_pagu_daftar": total_daftar, "selisih": total_mak - total_daftar,
        "detail_terakhir_diambil": terakhir, "per_mak": daftar_mak, "per_uraian": daftar_uraian,
        "klasifikasi": rekap.ringkas_kategori(list(klas), paket.values()) if klas else None,
        "paket": paket,
        "perbaikan": {f: kegiatan.rekap_perbaikan(paket.values(), f) for f in ("Semua", "Fisik", "Konsultan")},
        "lokasi": lokasi.bangun(fisik, kec_daftar, kec),
        "periksa": _gabung_periksa([d["periksa"] for d in datas]),
        "perubahan": {"revisi": ev.get("REVISI_RUP", 0), "total": sum(ev.values()), "per_jenis": ev},
        "tahun_tersedia": datas[0]["tahun_tersedia"],
        "versi": "|".join(d["versi"] for d in datas),
    }
    for k, h in hasil["lokasi"]["per_paket"].items():          # nama jalan/gang diseragamkan lintas tahun
        paket[k].update(jalan=h["jalan"], gang=h["gang"], komplek=h["komplek"])
    return hasil
