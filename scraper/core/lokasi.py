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


def _cari_awalan(kata, daftar, maks_kata=5):
    """Cocokkan AWAL rangkaian kata dengan daftar nama resmi (kata sisa setelah nama, mis. 'Kota Pontianak', diabaikan).
    Urutan: (1) persis, abaikan spasi/huruf besar -> awalan terpanjang; (2) paling mirip (salah ketik);
    (3) singkatan: semua kata termuat di tepat satu nama resmi ('Mayor' -> 'Parit Mayor').
    -> (resmi | None, teks_tertulis, salah_eja)"""
    kata = kata[:maks_kata]
    peta = {kunci(d): d for d in daftar}
    for n in range(len(kata), 0, -1):
        k = kunci(" ".join(kata[:n]))
        if k in peta:
            return peta[k], " ".join(kata[:n]), False
    terbaik = (None, "", 0.0)
    for n in range(1, len(kata) + 1):
        tulis = " ".join(kata[:n])
        for kd, d in peta.items():
            r = difflib.SequenceMatcher(None, kunci(tulis), kd).ratio()
            if r > terbaik[2]:
                terbaik = (d, tulis, r)
    if terbaik[2] >= AMBANG:
        return terbaik[0], terbaik[1], True
    for n in range(min(len(kata), 3), 0, -1):
        himpunan = {x.lower() for x in kata[:n]}
        cocok = [d for d in daftar if himpunan <= {w.lower() for w in d.split()}]
        if len(cocok) == 1:
            return cocok[0], " ".join(kata[:n]), True
    return None, " ".join(kata), False


def _cari_kelurahan(kata, daftar):
    resmi, tulis, typo = _cari_awalan(kata, daftar)
    return (resmi, tulis, typo) if resmi else (None, _bersih_kelurahan(" ".join(kata)), False)


def _cari_kecamatan(s, daftar):
    """-> (resmi | None, tertulis | None, salah_eja, ada_penanda)"""
    m = _KEC_PENANDA.search(s)
    if m:
        raw = _bersih(re.sub(r"\d+", " ", m.group("n")))
        resmi, tulis, typo = _cari_awalan(re.findall(r"[A-Za-z']+", raw), daftar, maks_kata=4)
        return resmi, (tulis if resmi else raw), typo, True
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
          "jalan": nama_jalan[x["jalan_kunci"]], "jalan_kunci": x["jalan_kunci"], "kunci": "|".join(gk), **_ringkas(x)}
         for gk, x in g.items()),
        key=lambda x: (x["jalan"], x["nama"]))
    for x in jalan:
        x["kunci"] = x.pop("_k")
    return {"per_paket": per_paket, "jalan": jalan, "gang": gang, "tidak_terbaca": tidak}


def gabung_jalan(per_tahun):
    """Daftar jalan UNIK lintas tahun (tanpa duplikat). per_tahun = {tahun: hasil bangun()}.
    Jalan yang sama (kunci sama, abaikan spasi/titik/huruf besar) di beberapa tahun menjadi satu baris."""
    hasil = {}
    for th in sorted(per_tahun):
        L = per_tahun[th]
        gang_jalan = defaultdict(list)
        for g in L["gang"]:
            gang_jalan[g["jalan_kunci"]].append(g)
        for j in L["jalan"]:
            r = hasil.setdefault(j["kunci"], {"nama": Counter(), "variasi": set(), "kecamatan": Counter(), "jenis": Counter(),
                                              "per_tahun": {}, "gang": {}, "paket": 0, "pagu": 0})
            r["nama"][j["nama"]] += j["jumlah_paket"]
            r["variasi"].update(j["variasi"])
            for kc in j["kecamatan"]:
                r["kecamatan"][kc] += 1
            r["jenis"].update(j["jenis"])
            r["paket"] += j["jumlah_paket"]
            r["pagu"] += j["total_pagu"]
            gg = gang_jalan.get(j["kunci"], [])
            r["per_tahun"][str(th)] = {"paket": j["jumlah_paket"], "pagu": j["total_pagu"], "gang": len(gg)}
            for g in gg:
                e = r["gang"].setdefault(g["kunci"], {"nama": g["nama"], "tipe": g["tipe"], "tahun": []})
                e["tahun"].append(th)
    daftar = []
    for k, r in hasil.items():
        tampil = r["nama"].most_common(1)[0][0]
        daftar.append({
            "kunci": k, "nama": tampil,
            "variasi": sorted((r["variasi"] | set(r["nama"])) - {tampil}),
            "kecamatan": [kc for kc, _ in r["kecamatan"].most_common()],
            "tahun": sorted(int(t) for t in r["per_tahun"]), "per_tahun": r["per_tahun"],
            "jumlah_paket": r["paket"], "total_pagu": r["pagu"], "jenis": dict(r["jenis"]),
            "jumlah_gang": len(r["gang"]), "gang": sorted(r["gang"].values(), key=lambda g: g["nama"])})
    return sorted(daftar, key=lambda x: x["nama"].lower())


def gabung_gang(per_tahun):
    """Daftar gang/komplek UNIK lintas tahun. Identitas = jalan + tipe + nama gang (abaikan spasi/titik/huruf besar).
    Gang bernama sama di jalan berbeda adalah tempat berbeda, jadi tidak digabung."""
    nama_jalan = Counter()
    hasil = {}
    for th in sorted(per_tahun):
        L = per_tahun[th]
        for j in L["jalan"]:
            nama_jalan[(j["kunci"], j["nama"])] += j["jumlah_paket"]
        for g in L["gang"]:
            r = hasil.setdefault(g["kunci"], {"nama": Counter(), "variasi": set(), "kecamatan": Counter(), "jenis": Counter(),
                                              "per_tahun": {}, "tipe": g["tipe"], "jalan_kunci": g["jalan_kunci"],
                                              "paket": 0, "pagu": 0})
            r["nama"][g["nama"]] += g["jumlah_paket"]
            r["variasi"].update(g["variasi"])
            for kc in g["kecamatan"]:
                r["kecamatan"][kc] += 1
            r["jenis"].update(g["jenis"])
            r["per_tahun"][str(th)] = {"paket": g["jumlah_paket"], "pagu": g["total_pagu"]}
            r["paket"] += g["jumlah_paket"]
            r["pagu"] += g["total_pagu"]
    terbaik = {}
    for (k, nm), n in nama_jalan.items():
        if k not in terbaik or n > terbaik[k][1]:
            terbaik[k] = (nm, n)
    pemakai = defaultdict(set)                       # nama gang (tanpa jalan) -> jalan-jalan yang memakainya
    for k, r in hasil.items():
        pemakai[k.split("|")[2]].add(r["jalan_kunci"])
    daftar = []
    for k, r in hasil.items():
        tampil = r["nama"].most_common(1)[0][0]
        daftar.append({
            "kunci": k, "nama": tampil, "tipe": r["tipe"], "jalan": terbaik[r["jalan_kunci"]][0],
            "variasi": sorted((r["variasi"] | set(r["nama"])) - {tampil}),
            "kecamatan": [kc for kc, _ in r["kecamatan"].most_common()],
            "tahun": sorted(int(t) for t in r["per_tahun"]), "per_tahun": r["per_tahun"],
            "jumlah_paket": r["paket"], "total_pagu": r["pagu"], "jenis": dict(r["jenis"]),
            "nama_sama_di_jalan_lain": len(pemakai[k.split("|")[2]]) - 1})
    return sorted(daftar, key=lambda x: (x["jalan"].lower(), x["nama"].lower()))
