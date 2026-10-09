"""Dashboard lokal (hanya 127.0.0.1):  python -m scraper web [--port 8765]"""
import collections
import datetime
import json
import sqlite3
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import tugas as _tugas
from .konfig import TARGETS, daftar_target, muat_target, satker_sirup
from .core import banding, database, db, excel, lokasi, rekap, semua_tahun, statistik
from .core.klasifikasi import AturanError

HTML = Path(__file__).with_name("dashboard.html")
HTML_GRAFIK = Path(__file__).with_name("grafik.html")
HALAMAN_STATIS = {"/spse": ("spse.html", "text/html; charset=utf-8"), "/banding": ("banding.html", "text/html; charset=utf-8"),
                  "/gaya.css": ("gaya.css", "text/css; charset=utf-8"), "/bersama.js": ("bersama.js", "text/javascript; charset=utf-8")}


def buka_readonly(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


class PengelolaTugas:
    """Satu tugas pengambilan data pada satu waktu, dijalankan di thread latar belakang."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._kunci = threading.Lock()
        self._henti = threading.Event()
        self._thread = None
        self._sampel = collections.deque(maxlen=600)      # (waktu, jumlah selesai) untuk menghitung kecepatan
        self._tahap_mulai = self._mulai_mono = time.monotonic()
        self._s = {"status": "idle", "jenis": None, "tahun": None, "koneksi": None, "jeda": None, "mulai": None,
                   "selesai": 0, "total": 0, "ok": 0, "gagal": 0, "log": [], "kode": None, "peringatan": None,
                   "tahap_ke": 0, "tahap_total": 0, "tahap_nama": None,
                   "laju": None, "sisa_detik": None, "berlalu_detik": 0, "berakhir": None, "lama_detik": None}

    def status(self):
        with self._kunci:
            st = json.loads(json.dumps(self._s))
            if st["status"] == "berjalan":
                st["berlalu_detik"] = round(time.monotonic() - self._mulai_mono)
            return st

    def _log(self, teks):
        with self._kunci:
            self._s["log"] = (self._s["log"] + str(teks).splitlines())[-120:]

    def _progres(self, selesai, total, ok, gagal):
        """Catat kemajuan + hitung kecepatan (jendela 30 detik terakhir; sebelum cukup data: rata-rata sejak tahap mulai)."""
        now = time.monotonic()
        with self._kunci:
            self._sampel.append((now, selesai))
            jendela = [(t, n) for t, n in self._sampel if now - t <= 30]
            laju = None
            if len(jendela) >= 2 and jendela[-1][0] > jendela[0][0] and jendela[-1][1] > jendela[0][1]:
                laju = (jendela[-1][1] - jendela[0][1]) / (jendela[-1][0] - jendela[0][0])
            elif selesai > 0 and now > self._tahap_mulai:
                laju = selesai / (now - self._tahap_mulai)
            sisa = None
            if total and selesai >= total:
                sisa = 0
            elif laju:
                sisa = round((total - selesai) / laju)
            self._s.update(selesai=selesai, total=total, ok=ok, gagal=gagal,
                           laju=round(laju, 3) if laju else None, sisa_detik=sisa)

    def _tahap(self, ke, total, nama):
        with self._kunci:
            self._sampel.clear()
            self._tahap_mulai = time.monotonic()
            self._s.update(tahap_ke=ke, tahap_total=total, tahap_nama=nama, selesai=0, total=0, ok=0, gagal=0,
                           laju=None, sisa_detik=None)

    def mulai(self, jenis, tahun, koneksi, jeda, usia_hari=7, semua=False, id_satker=None, satker=None, target=None):
        if jenis not in ("semua", "daftar", "detail", "spse_nontender", "spse_semua", "banding_periksa"):
            raise ValueError("jenis tugas tidak dikenal")
        spse_ = jenis.startswith("spse_") or jenis == "banding_periksa"          # boleh tahun 'semua'; tidak memakai idSatker SiRUP
        if spse_ and str(tahun) == "semua":                  # SPSE: 'semua' = semua tahun di pilihan SPSE
            koneksi, jeda, usia_hari = int(koneksi), float(jeda), int(usia_hari)
        else:
            koneksi, jeda, usia_hari, tahun = int(koneksi), float(jeda), int(usia_hari), int(tahun)
            if not 2000 <= tahun <= 2100 or not 0 <= usia_hari <= 3650:
                raise ValueError("tahun atau batas umur di luar jangkauan")
        if spse_ and jenis == "spse_nontender":
            koneksi = 1                                       # hanya daftar paket: selalu 1 koneksi
        target = target or None
        if target is not None and target not in [t["nama"] for t in daftar_target()]:
            raise ValueError("satker tidak dikenal; tambahkan dulu lewat nama")
        id_satker = int(id_satker) if id_satker not in (None, "") else None
        if id_satker is not None and not 1 <= id_satker <= 10**9:
            raise ValueError("idSatker di luar jangkauan")
        _tugas.cek_param(1 if jenis in ("daftar", "spse_nontender") else koneksi, jeda)
        with self._kunci:
            if self._s["status"] == "berjalan":
                raise RuntimeError("Masih ada tugas yang berjalan.")
            self._henti.clear()
            self._sampel.clear()
            self._tahap_mulai = self._mulai_mono = time.monotonic()
            self._s.update(laju=None, sisa_detik=None, berlalu_detik=0, berakhir=None, lama_detik=None,
                           status="berjalan", jenis=jenis, tahun=tahun, target=target, koneksi=1 if jenis in ("daftar", "spse_nontender") else koneksi,
                           tahap_ke=0, tahap_total=0, tahap_nama=None,
                           jeda=jeda, mulai=time.strftime("%Y-%m-%dT%H:%M:%S"), selesai=0, total=0, ok=0, gagal=0,
                           log=[], kode=None, peringatan=_tugas.peringatan_laju(1 if jenis in ("daftar", "spse_nontender") else koneksi, jeda))
        self._thread = threading.Thread(target=self._jalan, args=(jenis, tahun, koneksi, jeda, usia_hari, semua, id_satker, satker, target), daemon=True)
        self._thread.start()

    def _jalan(self, jenis, tahun, koneksi, jeda, usia_hari, semua, id_satker=None, satker=None, target=None):
        kode = 1
        conn = None
        try:
            conn = db.buka(self.db_path)
            if jenis == "banding_periksa":
                self._tahap(1, 1, "Periksa RUP ke SiRUP")
                kodes = _tugas.kode_rup_tak_berpasangan(conn, None if tahun == "semua" else [int(tahun)], None if satker in (None, "", "__semua") else satker)
                kode = _tugas.run_periksa_rup(conn, kodes, koneksi=koneksi, jeda=jeda, ulang=semua, log=self._log, berhenti=self._henti, progres=self._progres)
                return
            if jenis.startswith("spse_"):
                _, dasar = muat_target(None, None)
                lpse = (dasar.get("spse") or {}).get("lpse", "pontianak")
                # cakupan rincian lengkap: nama satker | '__tidak' (hanya Pengumuman) | kosong/'__semua' (semua satker)
                cakupan = None if satker in (None, "", "__semua") else str(satker)
                if jenis == "spse_semua":
                    kode = _tugas.run_spse_semua(conn, "nontender", lpse, tahun, jeda=jeda, usia_hari=usia_hari, semua=semua,
                                                 satker=cakupan, koneksi=koneksi, log=self._log,
                                                 progres=self._progres, tahap=self._tahap, berhenti=self._henti)
                else:
                    self._tahap(1, 1, "Daftar paket SPSE")
                    kode = _tugas.run_spse(conn, jenis.split("_", 1)[1], lpse, tahun, jeda=jeda, log=self._log, berhenti=self._henti)
                return
            _, target = muat_target(target, tahun, id_satker)
            if jenis == "semua":
                kode = _tugas.run_semua(conn, target, koneksi=koneksi, jeda=jeda, usia_hari=usia_hari, semua=semua,
                                        log=self._log, progres=self._progres, tahap=self._tahap, berhenti=self._henti,
                                        db_path=self.db_path)
            elif jenis == "daftar":
                kode = _tugas.run_daftar(conn, target, jeda=jeda, log=self._log, berhenti=self._henti)
            else:
                kode = _tugas.run_detail(conn, target, koneksi=koneksi, jeda=jeda, usia_hari=usia_hari, semua=semua,
                                         log=self._log, progres=self._progres, berhenti=self._henti, db_path=self.db_path)
        except Exception as e:                  # jangan biarkan thread mati diam-diam
            self._log(f"[GAGAL] {e!r}")
        finally:
            if conn:
                conn.close()
            with self._kunci:
                self._s["berakhir"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                self._s["lama_detik"] = round(time.monotonic() - self._mulai_mono)
                self._s["sisa_detik"] = 0 if kode in (0, 4) else self._s["sisa_detik"]
                self._s["kode"] = kode
                self._s["status"] = ("selesai" if kode in (0, 4) else "dihentikan" if kode == 130 else "gagal")

    def henti(self):
        self._henti.set()


def host_sah(handler):
    """Tolak Host selain 127.0.0.1/localhost (anti DNS-rebinding)."""
    port = handler.server.server_address[1]
    return handler.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost")


def sidik_kode():
    """Waktu ubah terbaru seluruh kode Python aplikasi. Python tidak membaca ulang kode yang berubah, jadi server yang
    sudah lama berjalan bisa memakai versi basi; perbedaan sidik ini menandakan itu."""
    return max((f.stat().st_mtime for f in Path(__file__).resolve().parent.rglob("*.py")), default=0)


def parse_tahun(q, tahun_default):
    th = q.get("tahun", [None])[0]
    if th == "semua":
        return "semua"
    return int(th) if th and th.isdigit() else tahun_default


def semua_dari_db(conn, tahun_default, nama=None):
    """[(target, data)] untuk setiap tahun di database; tiap tahun memakai aturannya sendiri (config per_tahun).
    `nama` = kunci target (satker) di config; kosong = target bawaan."""
    _, dasar = muat_target(nama, tahun_default)
    return semua_tahun.hitung_per_tahun(conn, lambda y: muat_target(nama, y)[1], dasar["id_satker_semua"])


def versi_db(conn, tahun_default):
    """Sidik jari ringan database + config: berubah bila ada data baru, detail baru, perubahan baru, atau config diedit."""
    a = tuple(conn.execute("SELECT COUNT(*), MAX(last_seen), SUM(is_active) FROM sirup_paket").fetchone())
    b = tuple(conn.execute("SELECT COUNT(*), MAX(diambil_pada) FROM sirup_detail").fetchone())
    c = conn.execute("SELECT COUNT(*) FROM paket_events").fetchone()[0]
    e = tuple(conn.execute("SELECT COUNT(*), MAX(last_seen), SUM(is_active) FROM spse_paket").fetchone())
    e += tuple(conn.execute("SELECT COUNT(*), MAX(diambil_pada), SUM(lengkap), SUM(error IS NOT NULL) FROM spse_detail").fetchone())
    e += tuple(conn.execute("SELECT COUNT(*), MAX(diambil_pada) FROM spse_jadwal").fetchone())
    e += tuple(conn.execute("SELECT COUNT(*), MAX(diambil_pada), SUM(ditemukan) FROM sirup_luar_daftar").fetchone())
    return f"{a}|{b}|{c}|{e}|{TARGETS.stat().st_mtime}|{tahun_default}"


def _konfig_spse():
    _, dasar = muat_target(None, None)
    return dasar, (dasar.get("spse") or {}).get("lpse", "pontianak")


_SQL_SPSE = ("SELECT p.tahun, p.kode_paket, p.nama_paket, p.tahapan, p.metode, p.kategori, p.hps_teks, p.nilai_kontrak_teks, p.link, p.is_active, "
             "d.kode_paket IS NOT NULL AS ada_detail, d.satker, d.kode_rup, d.sumber_dana, d.tahun_anggaran, d.pagu, d.hps, d.jenis_pengadaan, "
             "d.jenis_kontrak, d.tanggal_pembuatan, d.lokasi_ringkas, d.pemenang_nama, d.harga_penawaran, d.harga_terkoreksi, d.hasil_negosiasi, "
             "d.nilai_kontrak, d.pemenang_terisi, d.kontrak_terisi, d.lengkap, d.diambil_pada, "
             "(SELECT mulai FROM spse_jadwal j WHERE j.lpse=p.lpse AND j.jenis=p.jenis AND j.kode_paket=p.kode_paket "
             "ORDER BY lower(tahap)='upload dokumen penawaran' DESC, no LIMIT 1) AS upload_mulai, "
             "(SELECT sampai FROM spse_jadwal j WHERE j.lpse=p.lpse AND j.jenis=p.jenis AND j.kode_paket=p.kode_paket "
             "ORDER BY lower(tahap)='upload dokumen penawaran' DESC, no LIMIT 1) AS upload_sampai, "
             "(SELECT SUM(jumlah_perubahan) FROM spse_jadwal j WHERE j.lpse=p.lpse AND j.jenis=p.jenis AND j.kode_paket=p.kode_paket) AS jadwal_diubah "
             "FROM spse_paket p LEFT JOIN spse_detail d ON d.lpse=p.lpse AND d.jenis=p.jenis AND d.kode_paket=p.kode_paket AND d.error IS NULL "
             "WHERE p.lpse=? AND p.jenis='nontender'")


def data_satker(conn):
    """Satker yang sudah terdaftar di config beserta jumlah paket dan tahun yang sudah ada di database (tanpa ID untuk pengguna)."""
    hasil = []
    for t in daftar_target():
        ids = t["id_satker_semua"]
        mark = ",".join("?" * len(ids))
        baris = conn.execute(f"SELECT tahun, COUNT(*) FROM sirup_paket WHERE id_satker IN ({mark}) AND is_active=1 GROUP BY tahun ORDER BY tahun", ids).fetchall()
        hasil.append({"target": t["nama"], "satker": t["satker_nama"], "klpd": t["klpd_nama"], "bawaan": t["bawaan"],
                      "paket": sum(n for _, n in baris), "tahun": [y for y, _ in baris]})
    return {"satker": hasil}


def _param_satker(q):
    """Filter satker dari query: kosong / 'semua' = semua satker."""
    v = (q.get("satker", [""])[0] or "").strip()
    return None if v in ("", "semua") else v


def data_spse(conn, th, bawaan, satker=None, rinci=None):
    """Daftar paket SPSE + detail (satu tahun, atau 'semua'), difilter satker, plus ringkasan kemajuan pengambilan.
    `rinci` = cakupan rincian lengkap yang akan diambil: nama satker, '__semua', atau '__tidak' (bawaan: mengikuti filter satker)."""
    dasar, lpse = _konfig_spse()
    tahun_ada = sorted({r[0] for r in conn.execute("SELECT DISTINCT tahun FROM spse_paket WHERE lpse=? AND jenis='nontender'", (lpse,))}, reverse=True)
    yang = dasar["tahun"] if bawaan else th
    sql, par = _SQL_SPSE, [lpse]
    if yang != "semua":
        sql += " AND p.tahun=?"
        par.append(int(yang))
    semua_baris = [dict(r) for r in conn.execute(sql + " ORDER BY p.tahun DESC, p.kode_paket DESC", par)]
    sk = db.norm_satker(satker) if satker else None
    # daftar satker (tidak terfilter) untuk pilihan filter utama
    daftar = {}
    for b in semua_baris:
        if b["is_active"] and b["ada_detail"]:
            e = daftar.setdefault(db.norm_satker(b["satker"]), {"nama": b["satker"], "paket": 0, "lengkap": 0})
            e["paket"] += 1
            e["lengkap"] += 1 if b["lengkap"] else 0
    baris = [b for b in semua_baris if sk is None or (b["ada_detail"] and db.norm_satker(b["satker"]) == sk)]
    aktif = [b for b in baris if b["is_active"]]
    lengkap = [b for b in aktif if b["lengkap"]]
    cakupan = (satker if satker else "__semua") if rinci in (None, "") else rinci
    scope = None if cakupan == "__semua" else cakupan                     # None = semua dirinci; '__tidak' tidak cocok satker mana pun
    peta = {(b["tahun"], b["kode_paket"]): b for b in semua_baris if b["is_active"]}
    perlu_lain = perlu_rinci = 0
    alasan = {}
    for t in (tahun_ada if yang == "semua" else ([int(yang)] if int(yang) in tahun_ada else [])):
        for kode, a in db.status_detail_spse(conn, lpse, "nontender", t, 7, False, satker=scope):
            if not a:
                continue
            b = peta.get((t, kode))
            if sk is not None and not (b and b["ada_detail"] and db.norm_satker(b["satker"]) == sk):
                continue                                                  # di luar satker yang sedang dilihat
            alasan[a] = alasan.get(a, 0) + 1
            if b and b["ada_detail"]:
                perlu_rinci += 1                                          # rincian lengkap: ±5 permintaan
            else:
                perlu_lain += 1                                           # baru Pengumuman: 1 permintaan
    return {"lpse": lpse, "jenis": "nontender", "tahun": tahun_ada, "tahun_bawaan": dasar["tahun"], "tahun_dipilih": yang,
            "satker": satker, "satker_daftar": sorted(daftar.values(), key=lambda e: e["nama"]),
            "satker_belum_dicek": sum(1 for b in semua_baris if b["is_active"] and not b["ada_detail"]),
            "satker_sirup": sorted(satker_sirup()), "rinci": cakupan, "baris": baris,
            "ringkas": {"paket_aktif": len(aktif), "dengan_detail": sum(1 for b in aktif if b["ada_detail"]), "terinci": len(lengkap),
                        "pagu": sum(b["pagu"] or 0 for b in lengkap), "hps": sum(b["hps"] or 0 for b in lengkap),
                        "harga_penawaran": sum(b["harga_penawaran"] or 0 for b in lengkap),
                        "hasil_negosiasi": sum(b["hasil_negosiasi"] or 0 for b in lengkap), "nilai_kontrak": sum(b["nilai_kontrak"] or 0 for b in lengkap),
                        "kontrak_terisi": sum(1 for b in lengkap if b["kontrak_terisi"]), "pemenang_terisi": sum(1 for b in lengkap if b["pemenang_terisi"]),
                        "jadwal_diubah": sum(1 for b in lengkap if b["jadwal_diubah"]), "perlu_rinci": perlu_rinci, "perlu_lain": perlu_lain,
                        "alasan": {db.ALASAN_DETAIL_SPSE[k]: n for k, n in alasan.items()},
                        "terakhir_detail": conn.execute("SELECT MAX(diambil_pada) FROM spse_detail WHERE lpse=? AND error IS NULL", (lpse,)).fetchone()[0]}}


def data_banding(conn, th, bawaan, satker=None):
    dasar, lpse = _konfig_spse()
    tahun_spse = sorted({r[0] for r in conn.execute("SELECT DISTINCT tahun FROM spse_paket WHERE lpse=? AND jenis='nontender'", (lpse,))})
    yang = dasar["tahun"] if bawaan else th
    tahun_list = tahun_spse if yang == "semua" else [int(yang)]
    h = banding.hitung(conn, lpse, "nontender", tahun_list, satker_sirup(), satker)
    h.update(tahun=tahun_spse, tahun_bawaan=dasar["tahun"], tahun_dipilih=yang, satker=satker, lpse=lpse)
    return h


KOLOM_EXCEL_SPSE = [("NO", 6), ("TAHUN", 7), ("KODE NON TENDER", 16), ("KODE RUP (SPSE)", 16), ("NAMA PAKET", 60), ("SATKER / DINAS", 38), ("TAHAPAN", 22),
                    ("METODE", 18), ("JENIS PENGADAAN", 24), ("SUMBER DANA", 11), ("TAHUN ANGGARAN", 10), ("PAGU", 17), ("HPS", 17),
                    ("PEMENANG", 34), ("HARGA PENAWARAN", 17), ("HARGA TERKOREKSI", 17), ("HASIL NEGOSIASI", 17),
                    ("PEMENANG TERISI", 10), ("NILAI KONTRAK", 17), ("KONTRAK TERISI (PPK)", 12),
                    ("UPLOAD MULAI", 17), ("UPLOAD SAMPAI", 17), ("PERUBAHAN JADWAL", 10)]
KOLOM_EXCEL_BANDING = [("NO", 6), ("TAHUN", 7), ("SATKER / DINAS", 38), ("KODE RUP", 12), ("KODE NON TENDER", 16), ("KODE RUP DI SPSE", 16), ("NAMA PAKET SIRUP", 54),
                       ("NAMA PAKET SPSE", 54), ("METODE SIRUP", 18), ("STATUS", 28), ("KECOCOKAN", 40), ("DI DAFTAR SIRUP", 12), ("TAHAPAN SPSE", 22),
                       ("UPLOAD MULAI", 17), ("UPLOAD SAMPAI", 17), ("UPLOAD MULAI AWAL", 17), ("UPLOAD SAMPAI AWAL", 17), ("PERUBAHAN JADWAL", 10),
                       ("PAGU SIRUP", 17), ("PAGU SPSE", 17), ("PAGU SAMA", 10), ("SELISIH PAGU", 15), ("HPS", 17), ("HARGA PENAWARAN", 17),
                       ("HARGA TERKOREKSI", 17), ("HASIL NEGOSIASI", 17), ("NILAI KONTRAK", 17), ("PEMENANG", 34)]


def _waktu(iso):
    return (iso or "").replace("T", " ")


def baris_excel_spse(data):
    isi = []
    for n, b in enumerate([x for x in data["baris"] if x["lengkap"] and x["is_active"]], 1):
        isi.append([n, b["tahun"], b["kode_paket"], b["kode_rup"], b["nama_paket"], b["satker"], b["tahapan"], b["metode"], b["jenis_pengadaan"],
                    b["sumber_dana"], b["tahun_anggaran"], b["pagu"], b["hps"], b["pemenang_nama"], b["harga_penawaran"], b["harga_terkoreksi"],
                    b["hasil_negosiasi"], "Ya" if b["pemenang_terisi"] else "Belum", b["nilai_kontrak"], "Ya" if b["kontrak_terisi"] else "Belum",
                    _waktu(b["upload_mulai"]), _waktu(b["upload_sampai"]), b["jadwal_diubah"] or 0])
    return isi


def baris_excel_banding(data):
    isi = []
    for n, b in enumerate(data["baris"], 1):
        isi.append([n, b["tahun"], b.get("satker"), b.get("kode_rup"), b.get("kode_nontender"), b.get("kode_rup_spse"), b.get("nama_sirup"), b.get("nama_spse"),
                    b.get("metode_sirup"), b["status"], b.get("kecocokan"), (None if not b.get("kode_rup") else "Tidak (dicek via kode RUP)" if b.get("di_daftar") is False else "Ya"), b.get("tahapan"), _waktu(b.get("upload_mulai")), _waktu(b.get("upload_sampai")),
                    _waktu(b.get("upload_mulai_awal")), _waktu(b.get("upload_sampai_awal")), b.get("jadwal_diubah"), b.get("pagu_sirup"), b.get("pagu_spse"),
                    None if b.get("pagu_sama") is None else ("Sama" if b["pagu_sama"] else "BEDA"), b.get("selisih_pagu"), b.get("hps"),
                    b.get("harga_penawaran"), b.get("harga_terkoreksi"), b.get("hasil_negosiasi"), b.get("nilai_kontrak"), b.get("pemenang")])
    return isi


def buat_handler(db_path, tahun_default=None, tugas=None):
    tugas = tugas or PengelolaTugas(db_path)
    cache = {}
    sidik_awal = sidik_kode()

    def hitung_jalan(conn, nama=None):
        _, dasar = muat_target(nama, tahun_default)
        per_tahun, info = {}, []
        for t, d in semua_dari_db(conn, tahun_default, nama):
            per_tahun[t["tahun"]] = d["lokasi"]
            aktif, ada = d["paket_aktif"], d["paket_dengan_detail"]
            # 'lengkap' = detail hampir semua paket sudah diambil; tahun sebagian tidak boleh dipakai membandingkan
            info.append({"tahun": t["tahun"], "paket": aktif, "detail": ada, "jalan": len(d["lokasi"]["jalan"]),
                         "lengkap": bool(aktif) and ada >= 0.98 * aktif})
        daftar = lokasi.gabung_jalan(per_tahun)
        return 200, {"tahun": sorted({y for j in daftar for y in j["tahun"]}),
                     "tahun_lengkap": [i["tahun"] for i in info if i["lengkap"]], "tahun_info": info, "jalan": daftar,
                     "gang": lokasi.gabung_gang(per_tahun), "kecamatan": sorted({k for j in daftar for k in j["kecamatan"]}),
                     "tidak_terbaca": {str(y): len(L["tidak_terbaca"]) for y, L in per_tahun.items()}}

    class Handler(BaseHTTPRequestHandler):
        def _kirim(self, kode, tipe, isi):
            self.send_response(kode)
            self.send_header("Content-Type", tipe)
            self.send_header("Content-Length", str(len(isi)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(isi)

        def _json(self, kode, obj):
            self._kirim(kode, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode())

        def do_POST(self):
            u = urlparse(self.path)
            # pengaman: hanya dari halaman dashboard ini sendiri (bukan situs lain yang dibuka di browser)
            if not host_sah(self) or self.headers.get("X-Pantau") != "1" or \
                    (self.headers.get("Origin") and urlparse(self.headers["Origin"]).netloc != self.headers.get("Host")):
                return self._json(403, {"error": "Ditolak: permintaan tidak berasal dari dashboard."})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n < 10_000 else {}
            except (ValueError, json.JSONDecodeError):
                return self._json(400, {"error": "Isi permintaan bukan JSON."})
            if u.path == "/api/tugas/mulai":
                try:
                    tugas.mulai(body.get("jenis"), body.get("tahun"), body.get("koneksi", 1), body.get("jeda", 1.5),
                                body.get("usia_hari", 7), bool(body.get("semua")), body.get("id_satker"), body.get("satker"), body.get("target"))
                except RuntimeError as e:
                    return self._json(409, {"error": str(e)})
                except (ValueError, TypeError) as e:
                    return self._json(400, {"error": f"Parameter tidak valid: {e}"})
                return self._json(200, tugas.status())
            if u.path == "/api/satker/tambah":
                try:
                    kunci, resmi = _tugas.tambah_satker_nama(str(body.get("nama", "")).strip(), body.get("klpd") or None)
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                except Exception as e:                       # jaringan / respons SiRUP tak terduga
                    return self._json(502, {"error": f"Gagal membaca direktori SiRUP: {e!r}"})
                cache.clear()
                return self._json(200, {"target": kunci, "satker_nama": resmi})
            if u.path == "/api/tugas/henti":
                tugas.henti()
                return self._json(200, tugas.status())
            self._kirim(404, "text/plain; charset=utf-8", b"Tidak ditemukan")

        def _api(self, kunci, hitung):
            """Hitung payload JSON dengan cache: selama database & config tidak berubah, jawaban dipakai ulang
            (penting untuk mode 'Semua tahun' + auto-refresh 2 detik)."""
            try:
                conn = buka_readonly(db_path)
                try:
                    versi = versi_db(conn, tahun_default)
                    hit = cache.get(kunci)
                    if hit and hit[0] == versi:
                        return self._kirim(200, "application/json; charset=utf-8", hit[1])
                    status, obj = hitung(conn)
                finally:
                    conn.close()
                isi = json.dumps(obj, ensure_ascii=False).encode()
                if status == 200:
                    cache[kunci] = (versi, isi)
                    if len(cache) > 24:
                        cache.pop(next(iter(cache)))
                return self._kirim(status, "application/json; charset=utf-8", isi)
            except sqlite3.Error as e:
                return self._json(500, {"error": f"Database belum siap: {e}"})
            except AturanError as e:
                return self._json(500, {"error": f"Aturan klasifikasi salah: {e}"})
            except SystemExit as e:
                return self._json(400, {"error": str(e)})

        def _excel(self, q, th):
            """Unduh database ke Excel: semua tahun (satu sheet gabungan + satu sheet per tahun) atau satu tahun terpilih."""
            try:
                tidak_aktif = q.get("tidak_aktif", ["0"])[0] == "1"
                nama_target = q.get("target", [None])[0] or None
                conn = buka_readonly(db_path)
                try:
                    if th == "semua":
                        pasangan = semua_dari_db(conn, tahun_default, nama_target)
                    else:
                        _, t = muat_target(nama_target, th)
                        pasangan = [(t, rekap.lengkap(conn, t))]
                    per_tahun = {}
                    for t, d in pasangan:
                        rows = database.baris(conn, t, d)
                        per_tahun[t["tahun"]] = rows if tidak_aktif else [r for r in rows if r["aktif"]]
                finally:
                    conn.close()
                if not per_tahun or not any(per_tahun.values()):
                    return self._json(404, {"error": "Tidak ada data untuk tahun yang dipilih."})
                isi = excel.buat_xlsx(per_tahun, gabungan=(th == "semua"))
                nama = f"database_RUP_{'semua-tahun' if th == 'semua' else th}_{datetime.datetime.now():%Y-%m-%d_%Hh%M}.xlsx"
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", f'attachment; filename="{nama}"')
                self.send_header("Content-Length", str(len(isi)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(isi)
            except sqlite3.Error as e:
                self._json(500, {"error": f"Database belum siap: {e}"})
            except (AturanError, SystemExit) as e:
                self._json(500, {"error": str(e)})

        def _unduh_xlsx(self, isi, nama):
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", f'attachment; filename="{nama}"')
            self.send_header("Content-Length", str(len(isi)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(isi)

        def _excel_spse(self, q, th):
            try:
                conn = buka_readonly(db_path)
                try:
                    data = data_spse(conn, th, q.get("tahun") is None, _param_satker(q))
                finally:
                    conn.close()
                isi = baris_excel_spse(data)
                if not isi:
                    return self._json(404, {"error": "Belum ada paket SPSE yang dirinci lengkap untuk pilihan ini. Jalankan Ambil Data + Detail di halaman SPSE."})
                urls = [b["link"] for b in data["baris"] if b["lengkap"] and b["is_active"]]
                xlsx = excel.buat_xlsx_tabel({"SPSE Non-Tender": (KOLOM_EXCEL_SPSE, isi)}, {"SPSE Non-Tender": {2: urls}})
                self._unduh_xlsx(xlsx, f"SPSE_NonTender_{data['tahun_dipilih']}_{datetime.datetime.now():%Y-%m-%d_%Hh%M}.xlsx")
            except sqlite3.Error as e:
                self._json(500, {"error": f"Database belum siap: {e}"})
            except Exception as e:
                self._json(500, {"error": f"Gagal membuat Excel: {e!r}"})

        def _excel_banding(self, q, th):
            try:
                conn = buka_readonly(db_path)
                try:
                    data = data_banding(conn, th, q.get("tahun") is None, _param_satker(q))
                finally:
                    conn.close()
                if not data["baris"]:
                    return self._json(404, {"error": "Tidak ada data untuk dibandingkan."})
                xlsx = excel.buat_xlsx_tabel({"Perbandingan": (KOLOM_EXCEL_BANDING, baris_excel_banding(data))},
                                             {"Perbandingan": {3: [b.get("link_sirup") for b in data["baris"]], 4: [b.get("link_spse") for b in data["baris"]]}})
                self._unduh_xlsx(xlsx, f"Banding_SiRUP_SPSE_{data['tahun_dipilih']}_{datetime.datetime.now():%Y-%m-%d_%Hh%M}.xlsx")
            except sqlite3.Error as e:
                self._json(500, {"error": f"Database belum siap: {e}"})
            except Exception as e:
                self._json(500, {"error": f"Gagal membuat Excel: {e!r}"})

        def _jadwal_spse(self, q):
            kode = (q.get("kode", [""])[0]).strip()
            if not kode.isdigit():
                return self._json(400, {"error": "Parameter kode tidak valid."})
            try:
                conn = buka_readonly(db_path)
                try:
                    _, lpse = _konfig_spse()
                    data = banding._jadwal_paket(conn, lpse, "nontender", kode)
                finally:
                    conn.close()
                return self._json(200, {"kode_paket": kode, "jadwal": data})
            except sqlite3.Error as e:
                return self._json(500, {"error": f"Database belum siap: {e}"})

        def do_GET(self):
            u = urlparse(self.path)
            if not host_sah(self):
                return self._json(403, {"error": "Host tidak diizinkan."})
            q = parse_qs(u.query)
            th = parse_tahun(q, tahun_default)
            nama_target = q.get("target", [None])[0] or None
            kunci = (u.path, str(th), nama_target)
            if u.path == "/":
                return self._kirim(200, "text/html; charset=utf-8", HTML.read_bytes())
            if u.path == "/grafik":
                return self._kirim(200, "text/html; charset=utf-8", HTML_GRAFIK.read_bytes())
            if u.path in HALAMAN_STATIS:
                nama, tipe = HALAMAN_STATIS[u.path]
                return self._kirim(200, tipe, Path(__file__).with_name(nama).read_bytes())
            if u.path == "/api/spse/excel":
                return self._excel_spse(q, th)
            if u.path == "/api/banding/excel":
                return self._excel_banding(q, th)
            if u.path == "/api/spse/jadwal":
                return self._jadwal_spse(q)
            if u.path == "/api/satker":
                return self._api(("satker", nama_target), lambda conn: (200, data_satker(conn)))
            if u.path == "/api/satker/cari":
                try:
                    return self._json(200, _tugas.cari_satker_nama((q.get("q", [""])[0]).strip(), q.get("klpd", [None])[0]))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                except Exception as e:
                    return self._json(502, {"error": f"Gagal membaca direktori SiRUP: {e!r}"})
            if u.path == "/api/tugas":
                return self._json(200, {**tugas.status(), "kode_basi": sidik_kode() > sidik_awal})
            if u.path == "/api/excel":
                return self._excel(q, th)
            if u.path == "/api/statistik":
                def hitung(conn):
                    _, dasar = muat_target(nama_target, tahun_default)
                    data = statistik.statistik_semua(conn, lambda y: muat_target(nama_target, y)[1], dasar["id_satker_semua"])
                    data["target"] = {"satker_nama": dasar["satker_nama"], "klpd_nama": dasar["klpd_nama"]}
                    return 200, data
                return self._api(kunci, hitung)
            if u.path == "/api/spse":
                return self._api(kunci + (_param_satker(q), q.get("rinci", [""])[0]), lambda conn: (200, data_spse(conn, th, q.get("tahun") is None, _param_satker(q), q.get("rinci", [""])[0] or None)))
            if u.path == "/api/banding":
                return self._api(kunci + (_param_satker(q),), lambda conn: (200, data_banding(conn, th, q.get("tahun") is None, _param_satker(q))))
            if u.path == "/api/jalan":
                return self._api(kunci, lambda conn: hitung_jalan(conn, nama_target))          # daftar jalan/gang UNIK lintas semua tahun
            if u.path == "/api/perubahan":
                def hitung(conn):
                    if th == "semua":
                        baris = []
                        for t, _ in semua_dari_db(conn, tahun_default, nama_target):
                            baris += database.perubahan(conn, t)
                        baris.sort(key=lambda b: -b["id"])
                    else:
                        baris = database.perubahan(conn, muat_target(nama_target, th)[1])
                    return 200, {"baris": baris}
                return self._api(kunci, hitung)
            if u.path == "/api/database":
                def hitung(conn):
                    if th == "semua":
                        daftar = semua_dari_db(conn, tahun_default, nama_target)
                        if not daftar:
                            return 404, {"error": "Belum ada data di database."}
                        baris = []
                        for t, d in daftar:
                            baris += database.baris(conn, t, d)
                        return 200, {"versi": "|".join(d["versi"] for _, d in daftar), "kolom": database.KOLOM, "baris": baris}
                    _, t = muat_target(nama_target, th)
                    data = rekap.lengkap(conn, t)
                    return 200, {"versi": data["versi"], "kolom": database.KOLOM, "baris": database.baris(conn, t, data)}
                return self._api(kunci, hitung)
            if u.path == "/api/rekap":
                def hitung(conn):
                    if th == "semua":
                        daftar = semua_dari_db(conn, tahun_default, nama_target)
                        if not daftar:
                            return 404, {"error": "Belum ada data di database."}
                        data = semua_tahun.gabung(daftar)
                        t0 = daftar[0][0]
                        target = {"nama": "semua-tahun", **{k: v for k, v in t0.items() if k not in ("klasifikasi", "periksa", "lokasi")},
                                  "tahun": "semua", "semua": True, "tahun_daftar": [t["tahun"] for t, _ in daftar]}
                    else:
                        nama, t = muat_target(nama_target, th)
                        data = rekap.lengkap(conn, t)
                        target = {"nama": nama, **{k: v for k, v in t.items() if k not in ("klasifikasi", "periksa")}}
                    data["lokasi"].pop("per_paket", None)       # sudah ada di data["paket"]
                    data["target"] = target
                    return 200, data
                return self._api(kunci, hitung)
            self._kirim(404, "text/plain; charset=utf-8", b"Tidak ditemukan")

        def log_message(self, *a):  # senyap
            pass

    return Handler


def jalankan(db_path, port=8765, buka_browser=True, tahun=None):
    if not Path(db_path).exists():
        raise SystemExit(f"Database {db_path} belum ada. Jalankan dulu: python -m scraper run sirup")
    srv = ThreadingHTTPServer(("127.0.0.1", port), buat_handler(db_path, tahun))
    url = f"http://127.0.0.1:{port}/"
    print(f"Dashboard: {url}   (Ctrl+C untuk berhenti)")
    if buka_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nDihentikan.")
    finally:
        srv.server_close()
