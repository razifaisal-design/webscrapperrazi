"""Deteksi kesalahan pada data paket yang sudah ber-detail. Fungsi murni: input = hasil rekap_mak.

Tingkat:  kesalahan  = hampir pasti salah / angka tidak sejalan
          peringatan = mencurigakan, perlu dilihat orang
"""
import re
from collections import defaultdict

from .mak import TANPA_MAK

JALAN, SALURAN = "Jalan", "Saluran"
BELUM_DIPETAKAN = "Belum dipetakan"

JUDUL = {
    "MAK_TIDAK_SESUAI": "MAK tidak sesuai kategori",
    "MAK_BELUM_DIPETAKAN": "MAK belum dipetakan",
    "TANPA_MAK": "Tanpa MAK",
    "NAMA_URAIAN_BERTENTANGAN": "Nama dan uraian bertentangan",
    "SATUAN_BERTENTANGAN": "Satuan volume bertentangan",
    "PAGU_TIDAK_SAMA": "Pagu detail ≠ pagu daftar",
    "KEMUNGKINAN_GANDA": "Kemungkinan paket ganda",
    "SUMBER_DANA_CAMPURAN": "Sumber dana campuran (APBD + APBDP)",
    "KECAMATAN_SALAH_EJA": "Salah eja kecamatan",
    "KECAMATAN_TIDAK_DIKENAL": "Kecamatan tidak dikenal",
    "KECAMATAN_TIDAK_ADA": "Kecamatan tidak tertulis",
    "KELURAHAN_SALAH_EJA": "Salah eja kelurahan",
    "KELURAHAN_TIDAK_DIKENAL": "Kelurahan tidak dikenal",
    "KELURAHAN_TIDAK_SESUAI_KECAMATAN": "Kelurahan tidak sesuai kecamatan",
}


def _tanpa_kurung(s):
    """Buang isi (...) — nama jalan di dalam kurung tidak boleh dianggap jenis pekerjaan."""
    return re.sub(r"\([^)]*(\)|$)", " ", s or "")


def _ada(teks, kata):
    return re.search(r"\b" + kata + r"\b", teks, re.I) is not None


def _jenis_dari_teks(teks):
    t = _tanpa_kurung(teks)
    j, s = _ada(t, "jalan"), _ada(t, "saluran")
    return JALAN if j and not s else SALURAN if s and not j else None


def _norm_nama(n):
    return re.sub(r"[^a-z0-9]+", " ", (n or "").lower()).strip()


def kategori_mak(mak, pemetaan):
    """Kategori yang seharusnya untuk sebuah MAK, atau None. Awalan harus berhenti di batas titik."""
    for aw, kat in pemetaan:
        if mak == aw or mak.startswith(aw + "."):
            return kat
    return None


def jalankan(data, aturan=None):
    aturan = aturan or {}
    pemetaan = [(x["awalan"].rstrip("."), x["kategori"]) for x in aturan.get("mak_kategori", [])]
    satuan_salah = {k: [u.upper() for u in v] for k, v in aturan.get("satuan_salah", {}).items()}
    paket = data["paket"]
    temuan = []

    def tambah(p, tingkat, jenis, pesan, pagu=None):
        temuan.append({"kode_rup": p["kode_rup"], "nama_paket": p["nama_paket"], "link": p["link"],
                       "kategori": p["kategori"], "jenis_pekerjaan": p["jenis_pekerjaan"],
                       "tingkat": tingkat, "jenis": jenis, "judul": JUDUL[jenis], "pesan": pesan,
                       "pagu": p["pagu"] if pagu is None else pagu})

    matriks = defaultdict(lambda: defaultdict(lambda: {"pagu": 0, "paket": set()}))
    for p in paket.values():
        kat = p["kategori"]
        entri = p.get("mak") or []

        # 1. MAK vs kategori paket (inti permintaan: Saluran masuk MAK Jalan, atau sebaliknya)
        if kat in (JALAN, SALURAN):
            for mak, nilai in entri:
                seharusnya = kategori_mak(mak, pemetaan) if pemetaan else None
                kolom = seharusnya or BELUM_DIPETAKAN
                matriks[kat][kolom]["pagu"] += nilai
                matriks[kat][kolom]["paket"].add(p["kode_rup"])
                if seharusnya and seharusnya != kat:
                    tambah(p, "kesalahan", "MAK_TIDAK_SESUAI",
                           f"Paket {kat} (dari nama/uraian), tetapi MAK-nya adalah MAK {seharusnya}: {mak}", nilai)
                elif pemetaan and not seharusnya and mak != TANPA_MAK:
                    tambah(p, "peringatan", "MAK_BELUM_DIPETAKAN",
                           f"Paket {kat} memakai MAK yang belum ada di pemetaan: {mak}", nilai)

        if any(m == TANPA_MAK for m, _ in entri):
            tambah(p, "peringatan", "TANPA_MAK", "Detail paket tidak mencantumkan MAK.")

        # 2. nama paket bilang satu jenis, uraian bilang jenis lain
        a, b = _jenis_dari_teks(p["nama_paket"]), _jenis_dari_teks(p["uraian"])
        if a and b and a != b:
            tambah(p, "kesalahan", "NAMA_URAIAN_BERTENTANGAN",
                   f"Nama paket menyebut {a}, tetapi uraian menyebut {b}: \"{p['uraian']}\"")

        # 3. satuan volume yang jelas tidak cocok dengan kategori (mis. Jalan dengan M1)
        if kat in satuan_salah and p["jenis_pekerjaan"] == "Fisik":
            m = re.search(r"([A-Za-z][A-Za-z0-9'²]*)\s*$", p.get("volume") or "")
            if m and m.group(1).upper() in satuan_salah[kat]:
                tambah(p, "peringatan", "SATUAN_BERTENTANGAN",
                       f"Paket {kat} tetapi satuan volume \"{m.group(1)}\" (volume: {p['volume']})")

        # 3b. kesalahan input kecamatan / kelurahan (dibandingkan dengan daftar wilayah resmi)
        for m in p.get("lokasi_masalah", []):
            tambah(p, m["tingkat"], m["jenis"], m["pesan"])

        # 3c. rincian memakai lebih dari satu sumber dana: dihitung sebagai yang terbesar, tetapi dilaporkan
        if len(p.get("dana") or []) > 1:
            tambah(p, "peringatan", "SUMBER_DANA_CAMPURAN",
                   f"Rincian memakai {' dan '.join(p['dana'])}; di rekap dihitung sebagai {p['sumber_dana']} (pagu terbesar)")

        # 4. pagu detail harus sama dengan pagu di daftar SiRUP
        if abs((p["pagu"] or 0) - (p["pagu_daftar"] or 0)) >= 0.5:
            tambah(p, "kesalahan", "PAGU_TIDAK_SAMA",
                   f"Pagu di detail {p['pagu']:,.0f} berbeda dari pagu di daftar {p['pagu_daftar']:,.0f}".replace(",", "."))

    # 5. kemungkinan ganda: nama (dirapikan) + pagu + MAK sama, kode RUP berbeda
    grup = defaultdict(list)
    for p in paket.values():
        kunci = (_norm_nama(p["nama_paket"]), p["pagu"], tuple(sorted(m for m, _ in (p.get("mak") or []))))
        grup[kunci].append(p)
    for anggota in grup.values():
        if len(anggota) > 1:
            for p in anggota:
                lain = ", ".join(x["kode_rup"] for x in anggota if x is not p)
                tambah(p, "peringatan", "KEMUNGKINAN_GANDA", f"Nama, pagu, dan MAK sama dengan paket {lain}")

    temuan.sort(key=lambda t: (t["tingkat"] != "kesalahan", t["jenis"], -(t["pagu"] or 0)))
    ringkas = defaultdict(lambda: {"judul": "", "tingkat": "", "jumlah": 0, "pagu": 0})
    for t in temuan:
        r = ringkas[t["jenis"]]
        r.update(judul=t["judul"], tingkat=t["tingkat"])
        r["jumlah"] += 1
        r["pagu"] += t["pagu"] or 0

    hasil = {
        "jumlah_kesalahan": sum(1 for t in temuan if t["tingkat"] == "kesalahan"),
        "jumlah_peringatan": sum(1 for t in temuan if t["tingkat"] == "peringatan"),
        "ringkas": dict(ringkas),
        "temuan": temuan,
        "matriks": None,
    }
    if pemetaan:
        kolom = [k for k in dict.fromkeys(kt for _, kt in pemetaan)] + [BELUM_DIPETAKAN]
        hasil["matriks"] = {
            "kolom": kolom, "baris": [JALAN, SALURAN],
            "nilai": {b: {k: {"pagu": matriks[b][k]["pagu"], "paket": len(matriks[b][k]["paket"])} for k in kolom}
                      for b in (JALAN, SALURAN)}}
    return hasil
