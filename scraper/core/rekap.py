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


def ringkas_kategori(nama_kategori, paket):
    hasil = {}
    for nama in nama_kategori:
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


def agregat_dari_paket(paket):
    """Daftar per-MAK dan per-uraian dari dict paket (dipakai satu tahun maupun gabungan semua tahun)."""
    per_mak, per_uraian = {}, {}
    for kode, p in paket.items():
        gu = per_uraian.setdefault(p["uraian"].lower(), {"uraian": p["uraian"], "total_pagu": 0, "paket": []})
        gu["total_pagu"] += p["pagu"]
        gu["paket"].append(kode)
        for mak, nilai in p["mak"]:
            g = per_mak.setdefault(mak, {"total_pagu": 0, "paket": {}})
            g["total_pagu"] += nilai
            g["paket"][kode] = g["paket"].get(kode, 0) + nilai
    daftar_mak = sorted(
        ({"mak": mak, "jumlah_paket": len(g["paket"]), "total_pagu": g["total_pagu"],
          "paket": sorted(([k, v] for k, v in g["paket"].items()), key=lambda x: -x[1])}
         for mak, g in per_mak.items()), key=lambda x: -x["total_pagu"])
    daftar_uraian = sorted(
        ({"uraian": g["uraian"], "jumlah_paket": len(g["paket"]), "total_pagu": g["total_pagu"],
          "paket": sorted(g["paket"], key=lambda k: -paket[k]["pagu"])}
         for g in per_uraian.values()), key=lambda x: -x["total_pagu"])
    return daftar_mak, daftar_uraian


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

    paket, total_daftar, terakhir = {}, 0, None
    for r in rows:
        total_daftar += r["pagu"] or 0
        if r["diambil_pada"] and (terakhir is None or r["diambil_pada"] > terakhir):
            terakhir = r["diambil_pada"]
        rincian = json.loads(r["sumber_dana_json"] or "[]") or [{"mak": "", "pagu": r["pagu"] or 0}]
        pagu_detail = sum(s.get("pagu") or 0 for s in rincian)
        uraian = norm_uraian(r["uraian"])
        kategori, jenis_kerja = klas(r["nama_paket"], uraian) if klas else (None, None)
        paket[r["kode_rup"]] = {
            "tahun": tahun, "kode_rup": r["kode_rup"], "nama_paket": r["nama_paket"], "jenis": r["jenis"], "link": r["link"],
            "uraian": uraian, "volume": r["volume"], "pagu": pagu_detail, "pagu_daftar": r["pagu"], "mak": [],
            "kategori": kategori, "jenis_pekerjaan": jenis_kerja}

        gabung = {}
        for s_ in rincian:
            m = norm_mak(s_.get("mak"), mak_segmen)
            gabung[m] = gabung.get(m, 0) + (s_.get("pagu") or 0)
        paket[r["kode_rup"]]["mak"] = [[m, v] for m, v in gabung.items()]

    daftar_mak, daftar_uraian = agregat_dari_paket(paket)

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
        "klasifikasi": ringkas_kategori(klas.kategori, paket.values()) if klas else None,
        "paket": paket,
    }


def aturan_periksa_tahun(target):
    """Pemetaan MAK Jalan/Saluran dan aturan satuan dibuat dari data tahun tertentu (`berlaku_tahun` di config).
    Untuk tahun lain aturan itu dimatikan - bukan dipaksakan - karena pemisahan MAK dan satuan ukur bisa berbeda
    (mis. 2023-2025 Jalan dan Saluran memakai satu MAK yang sama). Pemeriksaan lain tetap berjalan."""
    aturan = dict(target.get("periksa") or {})
    berlaku = aturan.get("berlaku_tahun")
    if berlaku and target["tahun"] not in berlaku:
        aturan.pop("mak_kategori", None)
        aturan.pop("satuan_salah", None)
    return aturan


def lengkap(conn, target):
    """Rekap + jenis kegiatan/MAK perbaikan + nama jalan/gang + pemeriksaan, untuk satu target config."""
    import html
    from . import kegiatan, lokasi, periksa
    data = rekap_mak(conn, target["id_satker"], target["tahun"], target.get("klasifikasi"),
                     target.get("mak_segmen", SEGMEN_DEFAULT))
    for p in data["paket"].values():
        p["nama_paket"] = html.unescape(p["nama_paket"])   # SiRUP mengirim apostrof sebagai &#x27;
    aturan_periksa = aturan_periksa_tahun(target)
    kegiatan.tambahkan(data, aturan_periksa)
    wilayah = (target.get("lokasi") or {}).get("wilayah")
    kec = list(wilayah) if wilayah else (target.get("lokasi") or {}).get("kecamatan") or lokasi._KECAMATAN_DEFAULT
    fisik = [p for p in data["paket"].values() if p["kategori"] in ("Jalan", "Saluran") and p["jenis_pekerjaan"] == "Fisik"]
    data["lokasi"] = lokasi.bangun(fisik, kec, wilayah)
    for kode, h in data["lokasi"]["per_paket"].items():
        data["paket"][kode].update(jalan=h["jalan"], gang=h["gang"], komplek=h["komplek"],
                                   kecamatan=h["kecamatan"], kelurahan=h["kelurahan"],
                                   kecamatan_asli=h["kecamatan_asli"], kelurahan_asli=h["kelurahan_asli"],
                                   lokasi_masalah=h["masalah"])
    data["periksa"] = periksa.jalankan(data, aturan_periksa)
    # penanda 'data berubah' untuk auto-refresh halaman Database
    v = conn.execute("SELECT MAX(last_seen), COUNT(*) FROM sirup_paket WHERE id_satker=? AND tahun=?",
                     (target["id_satker"], target["tahun"])).fetchone()
    ev = dict(conn.execute(
        "SELECT e.jenis_event, COUNT(*) FROM paket_events e JOIN sirup_paket p ON p.kode_rup=e.kunci "
        "WHERE p.id_satker=? AND p.tahun=? GROUP BY e.jenis_event", (target["id_satker"], target["tahun"])).fetchall())
    data["perubahan"] = {"revisi": ev.get("REVISI_RUP", 0), "total": sum(ev.values()), "per_jenis": ev}
    data["tahun_tersedia"] = sorted({r[0] for r in conn.execute(
        "SELECT DISTINCT tahun FROM sirup_paket WHERE id_satker=?", (target["id_satker"],))} | {target["tahun"]})
    data["versi"] = f"{v[0]}|{v[1]}|{data['paket_dengan_detail']}|{data['detail_terakhir_diambil']}"
    return data
