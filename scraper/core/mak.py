"""Penyamaan kode MAK: hanya N segmen pertama yang dipakai, sisanya diabaikan."""

TANPA_MAK = "(tanpa MAK)"
SEGMEN_DEFAULT = 12   # 1.04.03.2.03.0013.5.2.04.01.001.00004


def norm_mak(mak, segmen=SEGMEN_DEFAULT):
    """'1.04.03.2.03.0013.5.2.04.01.001.00004.8.1.02.02.09.0009.00002' -> '1.04.03.2.03.0013.5.2.04.01.001.00004'.
    Spasi dan titik di ujung juga dibuang. Kosong -> '(tanpa MAK)'."""
    m = (mak or "").strip().rstrip(".").strip()
    if not m:
        return TANPA_MAK
    return ".".join(m.split(".")[:segmen])


def mak_inti(teks_mak, segmen=SEGMEN_DEFAULT):
    """Untuk string 'MAK1; MAK2' (kolom detail.mak): himpunan MAK inti, terurut."""
    return "; ".join(sorted({norm_mak(x, segmen) for x in (teks_mak or "").split(";") if x.strip()}))
