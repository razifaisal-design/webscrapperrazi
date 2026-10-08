"""Statistik per tahun untuk halaman grafik: pagu Jalan/Saluran/total, per kecamatan, komposisi, metode, dll.

Klasifikasi memakai nama paket (+ uraian bila detail sudah diambil), jadi tahun yang detailnya belum lengkap tetap
bisa digrafikkan - hanya kurang akurat; hal itu ditandai lewat `lengkap` di tahun_info."""
import html
from collections import Counter, defaultdict

from . import db, lokasi
from .klasifikasi import LAINNYA, Pengklasifikasi
from .rekap import norm_uraian

TANPA_KEC = "(tanpa kecamatan)"
LENGKAP_MIN = 0.98          # detail >= 98% paket dianggap lengkap


def _kosong():
    return {"total": 0, "fisik": 0, "konsultan": 0, "paket": 0}


def statistik_tahun(conn, target):
    """-> (statistik, hasil_bangun_lokasi) untuk satu satker+tahun."""
    klas = Pengklasifikasi(target["klasifikasi"]) if target.get("klasifikasi") else None
    wilayah = (target.get("lokasi") or {}).get("wilayah")
    kec_resmi = list(wilayah) if wilayah else (target.get("lokasi") or {}).get("kecamatan") or lokasi._KECAMATAN_DEFAULT
    rows = conn.execute(
        "SELECT p.kode_rup,p.jenis,p.nama_paket,p.pagu,p.metode_pemilihan,p.sumber_dana,d.uraian, d.kode_rup AS ada "
        "FROM sirup_paket p LEFT JOIN sirup_detail d ON d.kode_rup=p.kode_rup AND d.error IS NULL "
        "WHERE p.id_satker=? AND p.tahun=? AND p.is_active=1", (target["id_satker"], target["tahun"])).fetchall()

    st = {"paket": len(rows), "detail": sum(1 for r in rows if r["ada"]), "pagu_dinas": 0,
          "jalan": _kosong(), "saluran": _kosong(), "lainnya": _kosong(),
          "kecamatan": defaultdict(lambda: {"jalan": 0, "saluran": 0}), "metode": Counter(), "sumber_dana": Counter(),
          "jenis": Counter()}
    fisik = []
    for r in rows:
        pagu = r["pagu"] or 0
        nama = html.unescape(r["nama_paket"] or "")
        st["pagu_dinas"] += pagu
        st["metode"][r["metode_pemilihan"] or "(kosong)"] += pagu
        st["sumber_dana"][r["sumber_dana"] or "(kosong)"] += pagu
        st["jenis"][r["jenis"]] += pagu
        kat, jp = klas(nama, norm_uraian(r["uraian"]) if r["uraian"] else "") if klas else (LAINNYA, "Fisik")
        kunci = {"Jalan": "jalan", "Saluran": "saluran"}.get(kat, "lainnya")
        b = st[kunci]
        b["total"] += pagu
        b["paket"] += 1
        b["konsultan" if jp == "Konsultan" else "fisik"] += pagu
        if kunci in ("jalan", "saluran"):
            kec = lokasi._cari_kecamatan(nama, kec_resmi)[0] or TANPA_KEC
            st["kecamatan"][kec][kunci] += pagu
            if jp == "Fisik":
                fisik.append({"kode_rup": r["kode_rup"], "nama_paket": nama, "kategori": kat, "pagu": pagu})
    L = lokasi.bangun(fisik, kec_resmi, wilayah)
    st["jalan_unik"], st["gang_unik"] = len(L["jalan"]), len(L["gang"])
    st["jalan_saluran"] = st["jalan"]["total"] + st["saluran"]["total"]
    st["kecamatan"] = {k: {**v, "total": v["jalan"] + v["saluran"]} for k, v in st["kecamatan"].items()}
    st["metode"], st["sumber_dana"], st["jenis"] = dict(st["metode"]), dict(st["sumber_dana"]), dict(st["jenis"])
    return st, L


def statistik_semua(conn, ambil_target, id_satker, top=10):
    """ambil_target(tahun) -> target config. Mengembalikan data untuk /api/statistik."""
    pilih = db.id_satker_per_tahun(conn, id_satker)             # idSatker bisa berbeda tiap tahun
    tahun = list(pilih)
    per, lok = {}, {}
    for th in tahun:
        per[str(th)], lok[th] = statistik_tahun(conn, dict(ambil_target(th), id_satker=pilih[th]))
    info = [{"tahun": th, "paket": per[str(th)]["paket"], "detail": per[str(th)]["detail"],
             "lengkap": bool(per[str(th)]["paket"]) and per[str(th)]["detail"] >= LENGKAP_MIN * per[str(th)]["paket"]} for th in tahun]
    daftar = sorted(lokasi.gabung_jalan(lok), key=lambda j: -j["total_pagu"])[:top]
    kecamatan = sorted({k for s in per.values() for k in s["kecamatan"]}, key=lambda k: (k == TANPA_KEC, k))
    return {"tahun": tahun, "tahun_info": info, "per_tahun": per, "kecamatan": kecamatan,
            "top_jalan": [{"nama": j["nama"], "total_pagu": j["total_pagu"], "jumlah_paket": j["jumlah_paket"],
                           "per_tahun": {t: v["pagu"] for t, v in j["per_tahun"].items()}} for j in daftar]}
