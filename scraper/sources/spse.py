"""SPSE / LPSE (spse.inaproc.id/<lpse>): daftar paket Non-Tender (Tender menyusul).

Halaman memuat tabel lewat DataTables sisi-server (POST /<lpse>/dt/pl?tahun=YYYY) dengan token pengaman dari halaman.
Dua perangkap yang ditangani di sini:
  * `recordsTotal` selalu 2147483647 (bukan jumlah sebenarnya) -> jumlah tidak bisa dipakai sebagai pembanding.
  * urutan bawaan (tanggal pengumuman) TIDAK stabil: paket bertanggal sama berpindah antar halaman, sehingga ada yang
    ganda dan ada yang terlewat. Kita urutkan menurut KODE PAKET (unik), lalu periksa tanpa-ganda, naik-murni, dan
    paket di ujung urutan terbalik semuanya ada."""
import re

from ..core.money import parse_rupiah

BASE = "https://spse.inaproc.id"
PER_HALAMAN = 100
JENIS = {"nontender": {"halaman": "nontender", "dt": "pl", "detail": "pengumumanpl"}}
_TOKEN = re.compile(r"d\.authenticityToken\s*=\s*'([0-9a-f]+)'")
_SATUAN = {"rb": 1e3, "jt": 1e6, "m": 1e9, "t": 1e12}
_JUMLAH_KOLOM = 6        # kolom DataTables yang didefinisikan halaman (kode, paket, instansi, tahapan, hps, jadwal)


class SpseError(RuntimeError):
    """Respons SPSE tidak seperti yang diharapkan."""


class Dihentikan(RuntimeError):
    """Pengambilan dihentikan pengguna."""


def url_halaman(lpse, jenis):
    return f"{BASE}/{lpse}/{JENIS[jenis]['halaman']}"


def url_detail(lpse, jenis, kode):
    return f"{BASE}/{lpse}/{JENIS[jenis]['halaman']}/{kode}/{JENIS[jenis]['detail']}"


def parse_halaman(html):
    """-> (token, [tahun yang ditawarkan di pilihan Tahun])."""
    m = _TOKEN.search(html)
    if not m:
        raise SpseError("token pengaman tidak ditemukan di halaman SPSE (struktur halaman berubah?)")
    pilih = re.search(r'<select[^>]*(?:name|id)="tahun"[^>]*>(.*?)</select>', html, re.S)
    tahun = sorted({int(v) for v in re.findall(r'<option[^>]*value="(\d{4})"', pilih.group(1))}, reverse=True) if pilih else []
    return m.group(1), tahun


_ELEMEN = re.compile(r"<(span|a|b|i|em|strong|small|div|label)\b[^>]*>.*?</\1\s*>", re.I | re.S)


def bersihkan_nama(teks):
    """Nama paket dari daftar SPSE kadang memuat penanda HTML, mis. '... <span class="badge">Pengadaan Langsung Ulang</span>'.
    Elemen itu (beserta tulisannya) dibuang; sisa tag dilepas; spasi dirapikan. Info mentahnya tetap ada di kolom `raw`."""
    import html
    t = _ELEMEN.sub(" ", str(teks or ""))
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(html.unescape(t).split())


def hps_perkiraan(teks):
    """HPS di daftar tertulis ringkas: '19,9 Jt' -> 19900000, '1,2 M' -> 1200000000. Hanya PERKIRAAN (pembulatan);
    nilai pasti ada di halaman detail. Tidak terbaca -> None."""
    t = str(teks or "").strip()
    m = re.fullmatch(r"(?:Rp\.?\s*)?([\d.,]+)\s*(Rb|Jt|M|T)?", t, re.I)
    if not m or not any(c.isdigit() for c in m.group(1)):
        return None
    try:
        nilai = float(parse_rupiah(m.group(1)))
    except ValueError:
        return None
    if m.group(2):
        nilai = nilai * _SATUAN[m.group(2).lower()]
    return int(round(nilai))


def parse_baris(baris, lpse, jenis, tahun):
    """Satu baris `data` DataTables -> dict paket. Indeks: 0 kode, 1 nama, 2 instansi, 3 tahapan, 4 HPS(ringkas),
    5 metode, 6 'Kategori - TA 2026', 7 versi SPSE, 8 nilai kontrak, 10 konsolidasi, 11 khusus OAP."""
    if not isinstance(baris, list) or len(baris) < 9:
        raise SpseError(f"baris tidak dikenali: {str(baris)[:120]}")
    kode = str(baris[0]).strip()
    if not kode.isdigit():
        raise SpseError(f"kode paket tidak valid: {kode!r}")
    kategori, _, ta = str(baris[6] or "").partition(" - TA ")
    flag = lambda i: len(baris) > i and str(baris[i]) == "1"      # noqa: E731
    return {
        "lpse": lpse, "jenis": jenis, "tahun": int(tahun), "kode_paket": kode,
        "nama_paket": bersihkan_nama(baris[1]), "instansi": str(baris[2] or "").strip(),
        "tahapan": str(baris[3] or "").strip(), "hps_teks": str(baris[4] or "").strip(),
        "hps_perkiraan": hps_perkiraan(baris[4]), "metode": str(baris[5] or "").strip(),
        "kategori": kategori.strip(), "tahun_anggaran": int(ta) if ta.strip().isdigit() else None,
        "versi_spse": str(baris[7] or "").strip(), "nilai_kontrak_teks": str(baris[8] or "").strip(),
        "konsolidasi": int(flag(10)), "oap": int(flag(11)), "link": url_detail(lpse, jenis, kode),
        "raw": baris}


class Sesi:
    """Sesi ke satu halaman SPSE: memegang token dan tahu cara memintanya ulang bila kedaluwarsa."""

    def __init__(self, client, lpse="pontianak", jenis="nontender"):
        if jenis not in JENIS:
            raise ValueError(f"jenis SPSE tidak dikenal: {jenis} (tersedia: {', '.join(JENIS)})")
        self.client, self.lpse, self.jenis = client, lpse, jenis
        self.token, self.tahun_tersedia = None, []

    def buka(self):
        self.token, self.tahun_tersedia = parse_halaman(self.client.get_text(url_halaman(self.lpse, self.jenis)))
        return self

    def _form(self, start, arah):
        d = {"draw": "1", "start": str(start), "length": str(PER_HALAMAN), "search[value]": "", "search[regex]": "false",
             "authenticityToken": self.token, "order[0][column]": "0", "order[0][dir]": arah}
        for i in range(_JUMLAH_KOLOM):
            d.update({f"columns[{i}][data]": str(i), f"columns[{i}][name]": "", f"columns[{i}][searchable]": "true",
                      f"columns[{i}][orderable]": "true", f"columns[{i}][search][value]": "", f"columns[{i}][search][regex]": "false"})
        return d

    def halaman(self, tahun, start, arah="asc"):
        url = f"{BASE}/{self.lpse}/dt/{JENIS[self.jenis]['dt']}"
        for percobaan in (1, 2):
            try:
                data = self.client.post_json(url, data=self._form(start, arah), params={"tahun": tahun},
                                             headers={"X-Requested-With": "XMLHttpRequest"})
            except ValueError:                      # bukan JSON (mis. halaman login karena token kedaluwarsa)
                data = None
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                return data["data"]
            if percobaan == 1:
                self.buka()                         # minta token baru lalu coba sekali lagi
        raise SpseError("respons SPSE bukan daftar paket (token kedaluwarsa atau struktur berubah)")


def _masalah_urutan(kode):
    if len(set(kode)) != len(kode):
        return f"{len(kode) - len(set(kode))} kode ganda antar-halaman"
    if kode != sorted(kode, key=int):
        return "urutan kode tidak naik murni"
    return None


def rayap_tahun(sesi, tahun, log=print, berhenti=None, ulang=2):
    """Ambil SEMUA baris satu tahun (100 per halaman, lalu halaman berikutnya) dengan pemeriksaan kelengkapan.
    Bila pemeriksaan gagal (data bergeser saat diambil) diulang dari awal sampai `ulang` kali."""
    masalah = None
    for percobaan in range(1, ulang + 2):
        baris, start, n = [], 0, 0
        while True:
            if berhenti is not None and berhenti.is_set():
                raise Dihentikan("dihentikan pengguna")
            data = sesi.halaman(tahun, start)
            baris += data
            n += 1
            log(f"  [{tahun}] halaman {n}: {len(data)} baris (total {len(baris)})")
            if len(data) < PER_HALAMAN:
                break
            start += PER_HALAMAN
        kode = [str(r[0]) for r in baris]
        masalah = _masalah_urutan(kode)
        if not masalah and baris:                      # paket di ujung urutan terbalik harus semuanya sudah terambil
            ada = set(kode)
            kurang = [str(r[0]) for r in sesi.halaman(tahun, 0, "desc") if str(r[0]) not in ada]
            if kurang:
                masalah = f"{len(kurang)} paket di ujung urutan terbalik tidak ikut terambil"
        if not masalah:
            return baris
        log(f"  PERINGATAN [{tahun}]: {masalah}; mengulang pengambilan ({percobaan}/{ulang + 1}).")
    raise SpseError(f"pengambilan tahun {tahun} tidak konsisten setelah {ulang + 1} percobaan: {masalah}")


# ---------------------------------------------------------------- detail paket (tab Pengumuman / Pemenang / Pemenang Berkontrak)
TAB_EVALUASI = {"pemenang": "pemenang", "kontrak": "pemenangberkontrak"}


def url_tab(lpse, jenis, kode, tab):
    """'pengumuman' = halaman detail utama; 'pemenang' / 'kontrak' = tab evaluasi."""
    if tab == "pengumuman":
        return url_detail(lpse, jenis, kode)
    return f"{BASE}/{lpse}/evaluasi{JENIS[jenis]['halaman']}/{kode}/{TAB_EVALUASI[tab]}"


def _teks(html):
    import html as _h
    s = re.sub(r"<br\s*/?>|</li>|</p>", " ", html or "", flags=re.I)
    return " ".join(_h.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ").split())


_PASANG = re.compile(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", re.S | re.I)


def _isi_halaman(html):
    i = html.find('<div class="content"')
    if i < 0:
        raise SpseError("halaman detail tidak dikenali (tidak ada blok konten)")
    return html[i:]


def pisah_tahun_anggaran(teks):
    """'APBD 2026' -> ('APBD', 2026); 'APBD-P 2026' -> ('APBD-P', 2026); tanpa tahun -> (teks, None)."""
    m = re.fullmatch(r"(.*?)\s*(\d{4})", (teks or "").strip())
    return (m.group(1).strip(), int(m.group(2))) if m else ((teks or "").strip(), None)


def parse_pengumuman(html):
    """Tab Pengumuman: semua bagian KECUALI 'Syarat Kualifikasi' (dipotong sebelum bagian itu)."""
    isi = _isi_halaman(html)
    k = re.search(r"<th[^>]*>\s*Syarat Kualifikasi", isi)
    if k:
        isi = isi[:k.start()]
    rup = []
    a = isi.find("Rencana Umum Pengadaan")
    if a >= 0:
        b = isi.find("</table>", a)
        potong = isi[a:b + 8]
        for tr in re.findall(r"<tr>(.*?)</tr>", potong, re.S | re.I):
            sel = [_teks(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
            if len(sel) >= 3:
                rup.append({"kode_rup": sel[0], "nama_paket": sel[1], "sumber_dana": sel[2]})
        isi = isi[:a] + isi[b + 8:]
    kv = {_teks(l): v for l, v in _PASANG.findall(isi)}
    if "Kode Paket" not in kv:
        raise SpseError("halaman Pengumuman tidak memuat 'Kode Paket'")
    lokasi = [_teks(x) for x in re.findall(r"<li>(.*?)</li>", kv.get("Lokasi Pekerjaan", ""), re.S | re.I)]
    t = lambda nama: _teks(kv.get(nama, ""))                      # noqa: E731
    sumber_dana, tahun_anggaran = pisah_tahun_anggaran(t("Tahun Anggaran"))
    return {
        "kode_paket": t("Kode Paket"), "nama_paket": t("Nama Paket"), "rup": rup,
        "uraian_singkat": t("Uraian Singkat Pekerjaan"), "tanggal_pembuatan": t("Tanggal Pembuatan"),
        "tahap": t("Tahap Paket Saat Ini"), "instansi": t("K/L/PD/Instansi Lainnya"), "satker": t("Satuan Kerja"),
        "jenis_pengadaan": t("Jenis Pengadaan"), "metode": t("Metode Pengadaan"),
        "oap": t("Khusus Orang Asli Papua (OAP)"), "sumber_dana": sumber_dana, "tahun_anggaran": tahun_anggaran,
        "pagu": parse_rupiah(t("Nilai Pagu Paket")) if t("Nilai Pagu Paket") else None,
        "hps": parse_rupiah(t("Nilai HPS Paket")) if t("Nilai HPS Paket") else None,
        "jenis_kontrak": t("Jenis Kontrak"), "lokasi": lokasi,
    }


def parse_pemenang(html):
    """Tab Pemenang / Pemenang Berkontrak: info paket + daftar pemenang (kolom mengikuti judul tabel di halaman).
    Daftar kosong = belum ada pemenang / belum ada kontrak."""
    isi = _isi_halaman(html)
    a = isi.find("Nama Pemenang")
    info = {_teks(l): _teks(v) for l, v in _PASANG.findall(isi[:a] if a >= 0 else isi)}
    pemenang = []
    if a >= 0:
        awal = isi.rfind("<table", 0, a)
        tabel = isi[awal:isi.find("</table>", a)]
        judul = [_teks(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", tabel, re.S | re.I)]
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tabel, re.S | re.I):
            sel = [_teks(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
            if sel and len(sel) == len(judul):
                pemenang.append(dict(zip(judul, sel)))
    return {"info": info, "pemenang": pemenang}


def _angka(teks):
    return parse_rupiah(teks) if teks and re.search(r"\d", teks) else None


def ringkas_detail(pengumuman, pemenang, kontrak):
    """Gabungkan tiga tab menjadi satu baris `spse_detail` (JSON lengkap + kolom turunan)."""
    p = pemenang["pemenang"][0] if pemenang["pemenang"] else {}
    k = kontrak["pemenang"][0] if kontrak["pemenang"] else {}
    nilai_kontrak = _angka(k.get("Harga Kontrak"))
    return {
        **{f: pengumuman[f] for f in ("uraian_singkat", "tanggal_pembuatan", "tahap", "instansi", "satker", "jenis_pengadaan",
                                      "metode", "oap", "sumber_dana", "tahun_anggaran", "pagu", "hps", "jenis_kontrak")},
        "kode_rup": ", ".join(r["kode_rup"] for r in pengumuman["rup"]),
        "rup_json": pengumuman["rup"], "lokasi_json": pengumuman["lokasi"], "lokasi_ringkas": "; ".join(pengumuman["lokasi"]),
        "pemenang_json": pemenang["pemenang"], "pemenang_nama": "; ".join(x.get("Nama Pemenang", "") for x in pemenang["pemenang"]),
        "harga_penawaran": _angka(p.get("Harga Penawaran")), "harga_terkoreksi": _angka(p.get("Harga Terkoreksi")),
        "hasil_negosiasi": _angka(p.get("Hasil Negosiasi")),
        "kontrak_json": kontrak["pemenang"], "nilai_kontrak": nilai_kontrak,
        "pemenang_terisi": int(bool(pemenang["pemenang"])), "kontrak_terisi": int(nilai_kontrak is not None),
    }


# ---------------------------------------------------------------- jadwal & riwayat perubahan jadwal
_BULAN = {"januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6, "juli": 7, "agustus": 8, "september": 9,
          "oktober": 10, "november": 11, "desember": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "agu": 8,
          "agt": 8, "sep": 9, "okt": 10, "nov": 11, "des": 12}


def tanggal_id(teks):
    """'19 Agustus 2026 20:00' -> '2026-08-19T20:00' (waktu setempat/WIB, tanpa zona). Tidak dikenali -> None."""
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", " ".join((teks or "").split()))
    bulan = _BULAN.get(m.group(2).lower()) if m else None
    if not m or not bulan:
        return None
    return f"{int(m.group(3)):04d}-{bulan:02d}-{int(m.group(1)):02d}T{int(m.group(4) or 0):02d}:{int(m.group(5) or 0):02d}"


def url_jadwal(lpse, jenis, kode):
    return f"{BASE}/{lpse}/{JENIS[jenis]['halaman']}/{kode}/jadwal"


def parse_jadwal(html):
    """Tabel jadwal: [{no, tahap, mulai_teks, sampai_teks, mulai, sampai, jumlah_perubahan, url_riwayat}]."""
    isi = _isi_halaman(html)
    hasil = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", isi, re.S | re.I):
        sel = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(sel) < 5 or not _teks(sel[0]).isdigit():
            continue
        perubahan = _teks(sel[4])
        n = re.search(r"(\d+)\s*kali", perubahan)
        href = re.search(r'href="([^"]+)"', sel[4])
        hasil.append({"no": int(_teks(sel[0])), "tahap": _teks(sel[1]), "mulai_teks": _teks(sel[2]), "sampai_teks": _teks(sel[3]),
                      "mulai": tanggal_id(_teks(sel[2])), "sampai": tanggal_id(_teks(sel[3])),
                      "jumlah_perubahan": int(n.group(1)) if n else 0, "url_riwayat": (BASE + href.group(1)) if href and href.group(1).startswith("/") else None})
    if not hasil and "<th" not in isi:
        raise SpseError("halaman Jadwal tidak dikenali")
    return hasil


def parse_riwayat_jadwal(html):
    """Riwayat perubahan satu tahap: [{tanggal_edit, mulai_asli, sampai_asli, keterangan}] (jadwal ORIGINAL sebelum diubah)."""
    isi = _isi_halaman(html)
    hasil = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", isi, re.S | re.I):
        sel = [_teks(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
        if len(sel) >= 5 and sel[0].isdigit():
            hasil.append({"tanggal_edit": sel[1], "mulai_asli": sel[2], "sampai_asli": sel[3], "keterangan": sel[4],
                          "tanggal_edit_iso": tanggal_id(sel[1]), "mulai_asli_iso": tanggal_id(sel[2]), "sampai_asli_iso": tanggal_id(sel[3])})
    return hasil
