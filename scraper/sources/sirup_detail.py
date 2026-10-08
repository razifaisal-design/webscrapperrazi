"""Detail satu paket SiRUP (lokasi, volume, uraian, spesifikasi, dll). Parser = fungsi murni."""
import re
from html.parser import HTMLParser

from ..core.money import parse_rupiah
from .sirup import BASE

URL_DETAIL = {
    "penyedia": BASE + "/home/detailPaketPenyediaPublic2017/{kode}",
    "swakelola": BASE + "/home/detailPaketSwakelolaPublic2017?idPaket={kode}",
}


class DetailError(ValueError):
    """Halaman detail tidak berbentuk yang diharapkan."""


# ---------- pohon HTML minimal (stdlib) ----------
_VOID = {"br", "hr", "img", "input", "meta", "link"}


class _Node:
    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs or {}), parent, []


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = _Node("root")

    def handle_starttag(self, tag, attrs):
        n = _Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        if tag not in _VOID:
            self.cur = n

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(html):
    b = _Builder()
    b.feed(html)
    return b.root


def _text(n):
    if isinstance(n, str):
        return n
    if n.tag in ("script", "style"):
        return ""
    return "".join(_text(c) for c in n.children)


def _bersih(s):
    return " ".join(s.split())


def _txt(n):
    return _bersih(_text(n))


def _find_all(n, tag):
    for c in n.children:
        if isinstance(c, _Node):
            if c.tag == tag:
                yield c
            yield from _find_all(c, tag)


def _find_first(n, pred):
    for c in n.children:
        if isinstance(c, _Node):
            if pred(c):
                return c
            r = _find_first(c, pred)
            if r:
                return r
    return None


def _direct_rows(table):
    for c in table.children:
        if isinstance(c, _Node):
            if c.tag == "tr":
                yield c
            elif c.tag in ("tbody", "thead", "tfoot"):
                yield from _direct_rows(c)


def _cells(tr):
    return [c for c in tr.children if isinstance(c, _Node) and c.tag in ("td", "th")]


def _rows_text(table):
    return [[_txt(c) for c in _cells(tr)] for tr in _direct_rows(table)]


_NO = re.compile(r"^\d+\.?$")


def _bersih_nilai(s):
    return _bersih(s.lstrip(": ").strip())


def _lokasi(table):
    out = []
    for r in _rows_text(table):
        if r and _NO.match(r[0]) and len(r) >= 4:
            out.append({"provinsi": r[1], "kabupaten_kota": r[2], "detail": r[3]})
    return out


def _sumber_dana(table):
    out = []
    for r in _rows_text(table):
        if not (r and _NO.match(r[0])):
            continue
        pagu = parse_rupiah(r[-1])
        if len(r) >= 6:   # penyedia: no, sumber, T.A., KLPD, MAK, pagu
            out.append({"sumber_dana": r[1], "tahun": r[2], "klpd": r[3], "mak": r[4], "pagu": pagu})
        else:             # swakelola: no, sumber, KLPD, MAK, pagu
            out.append({"sumber_dana": r[1], "klpd": r[2], "mak": r[3], "pagu": pagu})
    return out


def _mulai_akhir(table):
    for r in _rows_text(table):
        if len(r) == 2 and r[0].lower() not in ("mulai", ""):
            return r[0], r[1]
    return "", ""


def _ringkas_lokasi(lokasi):
    return " | ".join(" / ".join(x for x in (l["provinsi"], l["kabupaten_kota"], l["detail"]) if x) for l in lokasi)


def _hasil(kode, nama, klpd, satker, tahun, lokasi, volume, uraian, spesifikasi, sumber_dana, total_pagu, extra):
    return {
        "kode_rup": kode, "nama_paket": nama, "klpd": klpd, "satuan_kerja": satker, "tahun_anggaran": tahun,
        "lokasi": lokasi, "lokasi_ringkas": _ringkas_lokasi(lokasi),
        "volume": volume, "uraian": uraian, "spesifikasi": spesifikasi,
        "sumber_dana": sumber_dana,
        "mak": "; ".join(s["mak"] for s in sumber_dana if s.get("mak")),
        "total_pagu": total_pagu, "extra": extra,
    }


# ---------- penyedia ----------
def parse_penyedia(html):
    root = _tree(html)
    detil = _find_first(root, lambda n: n.attrs.get("id") == "detil")
    tabel = detil and _find_first(detil, lambda n: n.tag == "table" and n.attrs.get("class", "").split() == ["table"])
    if tabel is None:
        raise DetailError("tabel detail penyedia tidak ditemukan")
    v, extra, lokasi, sumber_dana, total = {}, {}, [], [], 0
    for tr in _direct_rows(tabel):
        c = _cells(tr)
        if len(c) < 2:
            continue
        label, nilai = _txt(c[0]).lower(), c[1]
        inner = _find_first(nilai, lambda n: n.tag == "table")
        if label == "lokasi pekerjaan" and inner:
            lokasi = _lokasi(inner)
        elif label == "sumber dana" and inner:
            sumber_dana = _sumber_dana(inner)
        elif label.startswith("pengadaan berkelanjutan") and inner:
            for r in _rows_text(inner):
                if len(r) == 2:
                    extra["spp_" + r[0].lower().replace("aspek ", "")] = r[1]
        elif label in ("pemanfaatan barang/jasa", "jadwal pelaksanaan kontrak", "jadwal pemilihan penyedia") and inner:
            kunci = {"pemanfaatan barang/jasa": "pemanfaatan", "jadwal pelaksanaan kontrak": "kontrak",
                     "jadwal pemilihan penyedia": "pemilihan"}[label]
            extra[kunci + "_mulai"], extra[kunci + "_akhir"] = _mulai_akhir(inner)
        elif label == "total pagu":
            total = parse_rupiah(_txt(nilai))
        else:
            v[label] = _txt(nilai)
    if not v.get("kode rup"):
        raise DetailError("Kode RUP tidak ada di halaman detail")
    for lbl, kunci in (("jenis pengadaan", "jenis_pengadaan"), ("metode pemilihan", "metode_pemilihan"),
                       ("produk dalam negeri", "produk_dalam_negeri"), ("usaha kecil", "usaha_kecil"),
                       ("pra dipa / dpa", "pra_dipa"), ("tanggal umumkan paket", "tanggal_umumkan")):
        if lbl in v:
            extra[kunci] = v.pop(lbl)
    extra["jenis_pengadaan"] = extra.get("jenis_pengadaan", "").rstrip(", ").strip()
    pakai = {"kode rup", "nama paket", "nama klpd", "satuan kerja", "tahun anggaran",
             "volume pekerjaan", "uraian pekerjaan", "spesifikasi pekerjaan"}
    lain = {k: x for k, x in v.items() if k not in pakai}
    if lain:
        extra["lainnya"] = lain
    return _hasil(v["kode rup"], v.get("nama paket", ""), v.get("nama klpd", ""), v.get("satuan kerja", ""),
                  v.get("tahun anggaran", ""), lokasi, v.get("volume pekerjaan", ""), v.get("uraian pekerjaan", ""),
                  v.get("spesifikasi pekerjaan", ""), sumber_dana, total, extra)


# ---------- swakelola ----------
def parse_swakelola(html):
    root = _tree(html)
    dl = _find_first(root, lambda n: n.tag == "dl")
    if dl is None:
        raise DetailError("daftar detail swakelola tidak ditemukan")
    v, lokasi, sumber_dana, total = {}, [], [], 0
    label = None
    for c in dl.children:
        if not isinstance(c, _Node):
            continue
        if c.tag == "dt":
            label = _txt(c).lower()
        elif c.tag == "dd" and label:
            inner = _find_first(c, lambda n: n.tag == "table")
            if label == "lokasi pekerjaan" and inner:
                lokasi = _lokasi(inner)
            elif label == "sumber dana" and inner:
                sumber_dana = _sumber_dana(inner)
                total = sum(s["pagu"] for s in sumber_dana)
            else:
                v.setdefault(label, _bersih_nilai(_txt(c)))
    if not v.get("kode rup"):
        raise DetailError("Kode RUP tidak ada di halaman detail")
    extra = {k: v[k] for k in ("tipe swakelola", "penyelenggara swakelola", "awal", "akhir") if k in v}
    extra = {{"tipe swakelola": "tipe_swakelola", "penyelenggara swakelola": "penyelenggara_swakelola",
              "awal": "pelaksanaan_mulai", "akhir": "pelaksanaan_akhir"}[k]: x for k, x in extra.items()}
    return _hasil(v["kode rup"], v.get("nama paket", ""), v.get("kldi", ""), v.get("satuan kerja", ""),
                  v.get("tahun anggaran", ""), lokasi, v.get("volume", ""), v.get("deskripsi", ""), "",
                  sumber_dana, total, extra)


PARSER = {"penyedia": parse_penyedia, "swakelola": parse_swakelola}


def ambil_detail(client, jenis, kode):
    """Unduh + parse satu halaman detail. Memastikan kode RUP di halaman = kode yang diminta."""
    d = PARSER[jenis](client.get_text(URL_DETAIL[jenis].format(kode=kode)))
    if d["kode_rup"] != str(kode):
        raise DetailError(f"kode di halaman {d['kode_rup']} != diminta {kode}")
    return d
