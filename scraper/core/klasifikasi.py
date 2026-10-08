"""Pengelompokan paket (mis. Jalan / Saluran) berdasarkan aturan di config/targets.json."""
import re

LAINNYA = "Lainnya"
FISIK, KONSULTAN = "Fisik", "Konsultan"
_FIELD = ("nama_paket", "uraian", "teks")


class AturanError(ValueError):
    pass


class Pengklasifikasi:
    def __init__(self, aturan):
        self._rules = []
        try:
            for r in aturan.get("kategori", []):
                cocok = r["cocok"]
                for f in cocok:
                    if f not in _FIELD:
                        raise AturanError(f"field aturan tidak dikenal: {f!r} (boleh: {', '.join(_FIELD)})")
                self._rules.append((r["nama"], {f: re.compile(p) for f, p in cocok.items()}))
            self._konsultan = re.compile(aturan["konsultan"]) if aturan.get("konsultan") else None
        except re.error as e:
            raise AturanError(f"regex aturan klasifikasi salah: {e}")
        self.kategori = [n for n in dict.fromkeys(n for n, _ in self._rules)] + [LAINNYA]

    def __call__(self, nama_paket, uraian):
        """-> (kategori, jenis). Jenis: 'Konsultan' bila teks memuat kata konsultan/perencanaan/pengawasan, selain itu 'Fisik'."""
        nilai = {"nama_paket": nama_paket or "", "uraian": uraian or "",
                 "teks": f"{nama_paket or ''} | {uraian or ''}"}
        jenis = KONSULTAN if self._konsultan and self._konsultan.search(nilai["teks"]) else FISIK
        for nama, pola in self._rules:
            if all(p.search(nilai[f]) for f, p in pola.items()):
                return nama, jenis
        return LAINNYA, jenis
