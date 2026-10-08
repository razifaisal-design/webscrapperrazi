"""Sumber dana dirapikan menjadi SATU nilai (APBD atau APBDP), tanpa koma dan tanpa pengulangan.

Daftar SiRUP menggabungkan sumber dana semua rincian paket ('APBD, APBD, APBD'). Untuk paket yang rinciannya
campuran (APBD dan APBDP), dipilih yang dominan; hal itu dilaporkan sebagai peringatan, bukan disembunyikan."""
from collections import Counter


def _token(teks):
    return [t.strip() for t in str(teks or "").split(",") if t.strip()]


def kanon(teks):
    """'APBD, APBD, APBD' -> 'APBD'. Campuran: yang paling banyak disebut (seri -> yang pertama muncul)."""
    t = _token(teks)
    if not t:
        return ""
    hitung = Counter(t)
    tertinggi = max(hitung.values())
    return next(x for x in t if hitung[x] == tertinggi)


def himpunan(teks):
    """Sumber dana yang berbeda, urutan kemunculan: 'APBD, APBDP, APBD' -> ['APBD', 'APBDP']."""
    return list(dict.fromkeys(_token(teks)))


def dominan(rincian):
    """Dari rincian detail [{'sumber_dana': 'APBD', 'pagu': 100}, ...]: sumber dengan pagu terbesar. -> (dominan, [semua sumber])."""
    jumlah, urutan = Counter(), []
    for r in rincian or []:
        s = str(r.get("sumber_dana") or "").strip()
        if not s:
            continue
        if s not in jumlah:
            urutan.append(s)
        jumlah[s] += r.get("pagu") or 0
    if not urutan:
        return "", []
    tertinggi = max(jumlah.values())
    return next(x for x in urutan if jumlah[x] == tertinggi), urutan
