"""Nama Jalan / Gang / Komplek / Kecamatan dari nama paket FISIK. Fungsi murni.

Contoh: 'Belanja Modal Jalan Kota (Jl. Flora, Gg. Flora 4, Kec. Pontianak Utara)'
        -> jalan 'Flora', gang 'Flora 4', kecamatan 'Pontianak Utara'
"""
import difflib
import html
import re
from collections import Counter, defaultdict

_AWALAN = re.compile(r"^\s*Belanja Modal\s+(?:Jalan Kota|Saluran Pembuang(?:\s+Pasang\s+Surut)?)\s*[-–:]?\s*", re.I)
_BERHENTI = r"(?=,|\)|\(|\s+(?:Kec|Kel|Kelurahan|Kecamatan|RT|RW|Komp|Komplek|Perum|Perumahan|dan|Gg|Gang)\b|$)"
_NAMA = r"(?P<n>[^,()]+?)"
_JALAN = re.compile(r"\b(?:Jl|JI|Jln|Jalan)\b[.,]?\s*" + _NAMA + _BERHENTI, re.I)
_GANG = re.compile(r"\b(?:Gg|Gng|Gang)\b[.,]?\s*" + _NAMA + _BERHENTI, re.I)
_KOMPLEK = re.compile(r"\b(?:Komp|Komplek|Kompleks|Perum|Perumahan)\b[.,]?\s*" + _NAMA + _BERHENTI, re.I)
_KELURAHAN = re.compile(r"\bKel(?:urahan)?\b\.?\s*(?P<n>[A-Za-z' ]+?)(?=\s+(?:Pontianak|RT|RW|Kec)\b|,|\)|$)", re.I)
_KECAMATAN_DEFAULT = ("Pontianak Barat", "Pontianak Kota", "Pontianak Selatan",
                      "Pontianak Tenggara", "Pontianak Timur", "Pontianak Utara")


def _bersih_kelurahan(n):
    """'Banjar Serasan Kecamatan' -> 'Banjar Serasan'; 'Sungai Jawi Pontiaank Kota' -> 'Sungai Jawi'."""
    kata, hasil = (n or "").split(), []
    for k in kata:
        if k.lower().strip(".,") in ("kec", "kecamatan", "kota", "kel", "kelurahan") or \
                difflib.SequenceMatcher(None, k.lower(), "pontianak").ratio() >= 0.8:
            break
        hasil.append(k)
    return " ".join(hasil)


def kunci(nama):
    """Kunci identitas: huruf+angka saja, huruf kecil. 'H.Rais A Rahman' == 'H. Rais. A. Rahman'."""
    return re.sub(r"[^a-z0-9]+", "", (nama or "").lower())


def _bersih(n):
    n = re.sub(r"\([^)]*\)?", " ", n or "")          # buang keterangan dalam kurung, mis. (lanjutan)
    n = re.sub(r"\s+", " ", n).strip(" .,-;")
    return n


_KEC_PENANDA = re.compile(r"\bKec(?:amatan)?\b[.,]?\s*(?:Kec(?:amatan)?\b[.,]?\s*)?(?P<n>[A-Za-z0-9' ]+?)(?=\s*[,)(]|\s+(?:Kel|Kelurahan|RT|RW)\b|$)", re.I)
AMBANG = 0.82


def _huruf(s):
    return kunci(re.sub(r"\d+", "", s or ""))


def _cocokkan(raw, daftar):
    """-> (nama_resmi | None, salah_eja). Sama persis (abaikan spasi/huruf besar) = bukan salah eja."""
    k = _huruf(raw)
    if not k:
        return None, False
    peta = {kunci(d): d for d in daftar}
    if k in peta:
        return peta[k], False
    terbaik, skor = None, 0.0
    for kd, d in peta.items():
        r = difflib.SequenceMatcher(None, k, kd).ratio()
        if r > skor:
            terbaik, skor = d, r
    return (terbaik, True) if skor >= AMBANG else (None, False)


def _cari_kelurahan(kata, daftar):
    """Dari kata-kata setelah 'Kel.': awalan terpanjang yang cocok persis dengan nama resmi; bila tak ada, yang paling mirip.
    -> (resmi | None, teks_tertulis, salah_eja)"""
    peta = {kunci(d): d for d in daftar}
    for n in range(len(kata), 0, -1):
        if kunci(" ".join(kata[:n])) in peta:
            return peta[kunci(" ".join(kata[:n]))], " ".join(kata[:n]), False
    terbaik = (None, "", 0.0)
    for n in range(1, len(kata) + 1):
        tulis = " ".join(kata[:n])
        for kd, d in peta.items():
            r = difflib.SequenceMatcher(None, kunci(tulis), kd).ratio()
            if r > terbaik[2]:
                terbaik = (d, tulis, r)
    if terbaik[2] >= AMBANG:
        return terbaik[0], terbaik[1], True
    return None, _bersih_kelurahan(" ".join(kata)), False


def _cari_kecamatan(s, daftar):
    """-> (resmi | None, tertulis | None, salah_eja, ada_penanda)"""
    m = _KEC_PENANDA.search(s)
    if m:
        raw = _bersih(re.sub(r"\d+", " ", m.group("n")))
        resmi, typo = _cocokkan(raw, daftar)
        return resmi, raw, typo, True
    for nm in daftar:                                  # tanpa 'Kec.': cari nama resminya di mana saja
        mm = re.search(r"\b" + r"\s+".join(map(re.escape, nm.split())) + r"\b", s, re.I)
        if mm:
            return nm, mm.group(0), False, False
    kata = re.findall(r"[A-Za-z]+", s)                 # salah ketik: 'Pontainak Utara'
    terbaik = (None, None, 0.0)
    for a, b in zip(kata, kata[1:]):
        for nm in daftar:
            r = difflib.SequenceMatcher(None, f"{a} {b}".lower(), nm.lower()).ratio()
            if r >= 0.88 and r > terbaik[2]:
                terbaik = (nm, f"{a} {b}", r)
    if terbaik[0]:
        return terbaik[0], terbaik[1], True, False
    return None, None, False, False


def parse_nama(nama_paket, kecamatan=_KECAMATAN_DEFAULT, wilayah=None):
    """-> dict: jalan, gang[], komplek[], kecamatan, kelurahan (nama RESMI, bisa None),
    kecamatan_asli, kelurahan_asli (tertulis di nama paket), masalah[] (kesalahan input kecamatan/kelurahan).
    wilayah = {kecamatan: [kelurahan,...]} sebagai sumber nama resmi."""
    s = html.unescape(nama_paket or "")
    s = _AWALAN.sub("", s)
    s = re.sub(r"^\s*\(?\s*(?:Pekerjaan\s+)?", "", s, flags=re.I)
    if wilayah:
        kecamatan = list(wilayah)

    m = _JALAN.search(s)
    jalan = _bersih(m.group("n")) if m else None
    sisa = s[m.end():] if m else s
    gang, komplek = [], []
    for g in _GANG.finditer(sisa):
        n = _bersih(g.group("n"))
        if n and kunci(n) not in {kunci(x) for x in gang}:
            gang.append(n)
    for k in _KOMPLEK.finditer(sisa):
        n = _bersih(k.group("n"))
        if n and kunci(n) not in {kunci(x) for x in komplek}:
            komplek.append(n)

    masalah = []
    kec, kec_asli, kec_typo, kec_penanda = _cari_kecamatan(s, kecamatan)
    if kec and kec_typo:
        masalah.append({"jenis": "KECAMATAN_SALAH_EJA", "tingkat": "peringatan",
                        "pesan": f"Kecamatan tertulis \"{kec_asli}\", seharusnya \"{kec}\""})
    elif not kec and kec_penanda:
        masalah.append({"jenis": "KECAMATAN_TIDAK_DIKENAL", "tingkat": "kesalahan",
                        "pesan": f"Kecamatan \"{kec_asli}\" bukan kecamatan di daftar resmi ({', '.join(kecamatan)})"})
    elif not kec:
        masalah.append({"jenis": "KECAMATAN_TIDAK_ADA", "tingkat": "peringatan",
                        "pesan": "Kecamatan tidak tertulis di nama paket"})

    kel, kel_asli = None, None
    mk = _KELURAHAN.search(s)
    if mk:
        kata = _bersih(mk.group("n")).split()[:5]
        if wilayah:
            semua_kel = [k for v in wilayah.values() for k in v]
            kel, kel_asli, kel_typo = _cari_kelurahan(kata, semua_kel)
            if kel and kel_typo:
                masalah.append({"jenis": "KELURAHAN_SALAH_EJA", "tingkat": "peringatan",
                                "pesan": f"Kelurahan tertulis \"{kel_asli}\", seharusnya \"{kel}\""})
            elif not kel and kel_asli:
                masalah.append({"jenis": "KELURAHAN_TIDAK_DIKENAL", "tingkat": "kesalahan",
                                "pesan": f"Kelurahan \"{kel_asli}\" tidak ada di daftar 29 kelurahan resmi"})
            if kel and kec:
                milik = [kc for kc, daftar in wilayah.items() if kunci(kel) in {kunci(x) for x in daftar}]
                if kec not in milik:
                    masalah.append({"jenis": "KELURAHAN_TIDAK_SESUAI_KECAMATAN", "tingkat": "kesalahan",
                                    "pesan": f"Kelurahan {kel} termasuk Kecamatan {' / '.join(milik)}, tetapi tertulis Kecamatan {kec}"})
        else:
            kel = kel_asli = _bersih_kelurahan(" ".join(kata)) or None
    return {"jalan": jalan or None, "gang": gang, "komplek": komplek, "kecamatan": kec, "kelurahan": kel,
            "kecamatan_asli": kec_asli, "kelurahan_asli": kel_asli, "masalah": masalah}


def _tampil(varian):
    """Ejaan yang paling sering dipakai; seri -> yang pertama."""
    return Counter(varian).most_common(1)[0][0]


def bangun(paket_fisik, kecamatan=_KECAMATAN_DEFAULT, wilayah=None):
    """paket_fisik: iterable dict paket (kode_rup, nama_paket, kategori, pagu).
    -> {'per_paket': {kode: hasil_parse}, 'jalan': [...], 'gang': [...], 'tidak_terbaca': [kode,...]}"""
    per_paket, j, g, tidak = {}, {}, {}, []
    for p in paket_fisik:
        h = parse_nama(p["nama_paket"], kecamatan, wilayah)
        per_paket[p["kode_rup"]] = h
        if not h["jalan"]:
            tidak.append(p["kode_rup"])
            continue
        jk = kunci(h["jalan"])
        r = j.setdefault(jk, {"varian": [], "paket": [], "pagu": 0, "kecamatan": Counter(),
                              "jenis": Counter(), "gang": set()})
        r["varian"].append(h["jalan"])
        r["paket"].append(p["kode_rup"])
        r["pagu"] += p["pagu"] or 0
        r["jenis"][p["kategori"]] += 1
        if h["kecamatan"]:
            r["kecamatan"][h["kecamatan"]] += 1
        for tipe, daftar in (("Gang", h["gang"]), ("Komplek", h["komplek"])):
            for nm in daftar:
                gk = (jk, tipe, kunci(nm))
                x = g.setdefault(gk, {"varian": [], "paket": [], "pagu": 0, "kecamatan": Counter(),
                                      "jenis": Counter(), "tipe": tipe, "jalan_kunci": jk})
                x["varian"].append(nm)
                x["paket"].append(p["kode_rup"])
                x["pagu"] += p["pagu"] or 0
                x["jenis"][p["kategori"]] += 1
                if h["kecamatan"]:
                    x["kecamatan"][h["kecamatan"]] += 1
                r["gang"].add(gk)

    def _ringkas(r, **ekstra):
        return {"jumlah_paket": len(r["paket"]), "total_pagu": r["pagu"], "paket": r["paket"],
                "kecamatan": [k for k, _ in r["kecamatan"].most_common()],
                "jenis": dict(r["jenis"]), "variasi": sorted(set(r["varian"]) - {_tampil(r["varian"])}), **ekstra}

    jalan = sorted(
        ({"nama": "Jl. " + _tampil(r["varian"]), "jumlah_gang": len(r["gang"]), **_ringkas(r), "_k": k}
         for k, r in j.items()), key=lambda x: -x["total_pagu"])
    nama_jalan = {x["_k"]: x["nama"] for x in jalan}
    gang = sorted(
        ({"nama": ("Gg. " if x["tipe"] == "Gang" else "Komp. ") + _tampil(x["varian"]), "tipe": x["tipe"],
          "jalan": nama_jalan[x["jalan_kunci"]], **_ringkas(x)} for x in g.values()),
        key=lambda x: (x["jalan"], x["nama"]))
    for x in jalan:
        del x["_k"]
    return {"per_paket": per_paket, "jalan": jalan, "gang": gang, "tidak_terbaca": tidak}
