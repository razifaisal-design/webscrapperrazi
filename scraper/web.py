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
from .cli import TARGETS, muat_target
from .core import database, db, excel, lokasi, rekap, semua_tahun, statistik
from .core.klasifikasi import AturanError

HTML = Path(__file__).with_name("dashboard.html")
HTML_GRAFIK = Path(__file__).with_name("grafik.html")


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

    def mulai(self, jenis, tahun, koneksi, jeda, usia_hari=7, semua=False):
        if jenis not in ("semua", "daftar", "detail"):
            raise ValueError("jenis harus 'semua', 'daftar' atau 'detail'")
        koneksi, jeda, usia_hari, tahun = int(koneksi), float(jeda), int(usia_hari), int(tahun)
        if not 2000 <= tahun <= 2100 or not 0 <= usia_hari <= 3650:
            raise ValueError("tahun atau batas umur di luar jangkauan")
        _tugas.cek_param(1 if jenis == "daftar" else koneksi, jeda)
        with self._kunci:
            if self._s["status"] == "berjalan":
                raise RuntimeError("Masih ada tugas yang berjalan.")
            self._henti.clear()
            self._sampel.clear()
            self._tahap_mulai = self._mulai_mono = time.monotonic()
            self._s.update(laju=None, sisa_detik=None, berlalu_detik=0, berakhir=None, lama_detik=None,
                           status="berjalan", jenis=jenis, tahun=tahun, koneksi=1 if jenis == "daftar" else koneksi,
                           tahap_ke=0, tahap_total=0, tahap_nama=None,
                           jeda=jeda, mulai=time.strftime("%Y-%m-%dT%H:%M:%S"), selesai=0, total=0, ok=0, gagal=0,
                           log=[], kode=None, peringatan=_tugas.peringatan_laju(1 if jenis == "daftar" else koneksi, jeda))
        self._thread = threading.Thread(target=self._jalan, args=(jenis, tahun, koneksi, jeda, usia_hari, semua), daemon=True)
        self._thread.start()

    def _jalan(self, jenis, tahun, koneksi, jeda, usia_hari, semua):
        kode = 1
        conn = None
        try:
            _, target = muat_target(None, tahun)
            conn = db.buka(self.db_path)
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


def parse_tahun(q, tahun_default):
    th = q.get("tahun", [None])[0]
    if th == "semua":
        return "semua"
    return int(th) if th and th.isdigit() else tahun_default


def semua_dari_db(conn, tahun_default):
    """[(target, data)] untuk setiap tahun di database; tiap tahun memakai aturannya sendiri (config per_tahun)."""
    _, dasar = muat_target(None, tahun_default)
    return semua_tahun.hitung_per_tahun(conn, lambda y: muat_target(None, y)[1], dasar["id_satker"])


def versi_db(conn, tahun_default):
    """Sidik jari ringan database + config: berubah bila ada data baru, detail baru, perubahan baru, atau config diedit."""
    a = tuple(conn.execute("SELECT COUNT(*), MAX(last_seen), SUM(is_active) FROM sirup_paket").fetchone())
    b = tuple(conn.execute("SELECT COUNT(*), MAX(diambil_pada) FROM sirup_detail").fetchone())
    c = conn.execute("SELECT COUNT(*) FROM paket_events").fetchone()[0]
    return f"{a}|{b}|{c}|{TARGETS.stat().st_mtime}|{tahun_default}"


def buat_handler(db_path, tahun_default=None, tugas=None):
    tugas = tugas or PengelolaTugas(db_path)
    cache = {}

    def hitung_jalan(conn):
        _, dasar = muat_target(None, tahun_default)
        per_tahun, info = {}, []
        for t, d in semua_dari_db(conn, tahun_default):
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
                                body.get("usia_hari", 7), bool(body.get("semua")))
                except RuntimeError as e:
                    return self._json(409, {"error": str(e)})
                except (ValueError, TypeError) as e:
                    return self._json(400, {"error": f"Parameter tidak valid: {e}"})
                return self._json(200, tugas.status())
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
                conn = buka_readonly(db_path)
                try:
                    if th == "semua":
                        pasangan = semua_dari_db(conn, tahun_default)
                    else:
                        _, t = muat_target(None, th)
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

        def do_GET(self):
            u = urlparse(self.path)
            if not host_sah(self):
                return self._json(403, {"error": "Host tidak diizinkan."})
            q = parse_qs(u.query)
            th = parse_tahun(q, tahun_default)
            kunci = (u.path, str(th), q.get("target", [None])[0])
            if u.path == "/":
                return self._kirim(200, "text/html; charset=utf-8", HTML.read_bytes())
            if u.path == "/grafik":
                return self._kirim(200, "text/html; charset=utf-8", HTML_GRAFIK.read_bytes())
            if u.path == "/api/tugas":
                return self._json(200, tugas.status())
            if u.path == "/api/excel":
                return self._excel(q, th)
            if u.path == "/api/statistik":
                def hitung(conn):
                    _, dasar = muat_target(None, tahun_default)
                    data = statistik.statistik_semua(conn, lambda y: muat_target(None, y)[1], dasar["id_satker"])
                    data["target"] = {"satker_nama": dasar["satker_nama"], "klpd_nama": dasar["klpd_nama"]}
                    return 200, data
                return self._api(kunci, hitung)
            if u.path == "/api/jalan":
                return self._api(kunci, hitung_jalan)          # daftar jalan/gang UNIK lintas semua tahun
            if u.path == "/api/perubahan":
                def hitung(conn):
                    if th == "semua":
                        baris = []
                        for t, _ in semua_dari_db(conn, tahun_default):
                            baris += database.perubahan(conn, t)
                        baris.sort(key=lambda b: -b["id"])
                    else:
                        baris = database.perubahan(conn, muat_target(None, th)[1])
                    return 200, {"baris": baris}
                return self._api(kunci, hitung)
            if u.path == "/api/database":
                def hitung(conn):
                    if th == "semua":
                        daftar = semua_dari_db(conn, tahun_default)
                        if not daftar:
                            return 404, {"error": "Belum ada data di database."}
                        baris = []
                        for t, d in daftar:
                            baris += database.baris(conn, t, d)
                        return 200, {"versi": "|".join(d["versi"] for _, d in daftar), "kolom": database.KOLOM, "baris": baris}
                    _, t = muat_target(q.get("target", [None])[0], th)
                    data = rekap.lengkap(conn, t)
                    return 200, {"versi": data["versi"], "kolom": database.KOLOM, "baris": database.baris(conn, t, data)}
                return self._api(kunci, hitung)
            if u.path == "/api/rekap":
                def hitung(conn):
                    if th == "semua":
                        daftar = semua_dari_db(conn, tahun_default)
                        if not daftar:
                            return 404, {"error": "Belum ada data di database."}
                        data = semua_tahun.gabung(daftar)
                        t0 = daftar[0][0]
                        target = {"nama": "semua-tahun", **{k: v for k, v in t0.items() if k not in ("klasifikasi", "periksa", "lokasi")},
                                  "tahun": "semua", "semua": True, "tahun_daftar": [t["tahun"] for t, _ in daftar]}
                    else:
                        nama, t = muat_target(q.get("target", [None])[0], th)
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
