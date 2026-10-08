"""Rekap untuk dashboard: hanya paket yang SUDAH diambil detailnya; pagu dijumlahkan per MAK."""
import json

TANPA_MAK = "(tanpa MAK)"


def norm_mak(mak):
    """Samakan penulisan: buang spasi dan titik di ujung."""
    m = (mak or "").strip().rstrip(".").strip()
    return m or TANPA_MAK


def rekap_mak(conn, id_satker, tahun):
    aktif = conn.execute(
        "SELECT COUNT(*) FROM sirup_paket WHERE id_satker=? AND tahun=? AND is_active=1", (id_satker, tahun)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT p.kode_rup,p.jenis,p.nama_paket,p.pagu,p.link,d.sumber_dana_json,d.diambil_pada "
        "FROM sirup_paket p JOIN sirup_detail d ON d.kode_rup=p.kode_rup AND d.error IS NULL "
        "WHERE p.id_satker=? AND p.tahun=? AND p.is_active=1",
        (id_satker, tahun),
    ).fetchall()

    per_mak, total_daftar, terakhir = {}, 0, None
    for r in rows:
        total_daftar += r["pagu"] or 0
        if r["diambil_pada"] and (terakhir is None or r["diambil_pada"] > terakhir):
            terakhir = r["diambil_pada"]
        rincian = json.loads(r["sumber_dana_json"] or "[]") or [{"mak": "", "pagu": r["pagu"] or 0}]
        for s in rincian:
            g = per_mak.setdefault(norm_mak(s.get("mak")), {"total_pagu": 0, "paket": {}})
            g["total_pagu"] += s.get("pagu") or 0
            p = g["paket"].setdefault(r["kode_rup"], {
                "kode_rup": r["kode_rup"], "nama_paket": r["nama_paket"], "jenis": r["jenis"],
                "link": r["link"], "pagu_paket": r["pagu"], "pagu_mak": 0})
            p["pagu_mak"] += s.get("pagu") or 0

    daftar = []
    for mak, g in per_mak.items():
        paket = sorted(g["paket"].values(), key=lambda x: -(x["pagu_mak"] or 0))
        daftar.append({"mak": mak, "jumlah_paket": len(paket), "total_pagu": g["total_pagu"], "paket": paket})
    daftar.sort(key=lambda x: -x["total_pagu"])

    total_mak = sum(x["total_pagu"] for x in daftar)
    return {
        "paket_aktif": aktif,
        "paket_dengan_detail": len(rows),
        "jumlah_mak": len(daftar),
        "total_pagu_mak": total_mak,
        "total_pagu_daftar": total_daftar,
        "selisih": total_mak - total_daftar,   # harus 0; bila tidak, data detail & daftar tidak sejalan
        "detail_terakhir_diambil": terakhir,
        "per_mak": daftar,
    }
