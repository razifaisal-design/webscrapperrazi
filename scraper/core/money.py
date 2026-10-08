"""Parser rupiah Indonesia: titik = ribuan, koma = desimal."""
import re
from decimal import Decimal, InvalidOperation


def parse_rupiah(text):
    """'Rp 150.000.000,50' -> 150000000.5 ; '8915000' -> 8915000 ; kosong -> 0."""
    if text is None:
        return 0
    s = str(text).strip()
    if not s:
        return 0
    negatif = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = re.sub(r"[^0-9.,]", "", s)
    if not s:
        return 0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        nilai = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"Format rupiah tidak dikenali: {text!r}")
    if negatif:
        nilai = -nilai
    return int(nilai) if nilai == nilai.to_integral_value() else float(nilai)
