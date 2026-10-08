"""Dashboard lokal (hanya 127.0.0.1):  python -m scraper web [--port 8765]"""
import json
import sqlite3
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import tugas as _tugas
from .cli import muat_target
from .core import database, db, rekap
from .core.klasifikasi import AturanError

HTML = Path(__file__).with_name("dashboard.html")


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
        self._s = {"status": "idle", "jenis": None, "tahun": None, "koneksi": None, "jeda": None, "mulai": None,
                   "selesai": 0, "total": 0, "ok": 0, "gagal": 0, "log": [], "kode": None, "peringatan": None,
                   "tahap_ke": 0, "tahap_total": 0, "tahap_nama": None}

    def status(self):
        with self._kunci:
            return json.loads(json.dumps(self._s))

    def _log(self, teks):
        with self._kunci:
            self._s["log"] = (self._s["log"] + str(teks).splitlines())[-120:]

    def _progres(self, selesai, total, ok, gagal):
        with self._kunci:
            self._s.update(selesai=selesai, total=total, ok=ok, gagal=gagal)

    def _tahap(self, ke, total, nama):
        with self._kunci:
            self._s.update(tahap_ke=ke, tahap_total=total, tahap_nama=nama, selesai=0, total=0, ok=0, gagal=0)

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
            self._s.update(status="berjalan", jenis=jenis, tahun=tahun, koneksi=1 if jenis == "daftar" else koneksi,
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
                self._s["kode"] = kode
                self._s["status"] = ("selesai" if kode in (0, 4) else "dihentikan" if kode == 130 else "gagal")

    def henti(self):
        self._henti.set()


def host_sah(handler):
    """Tolak Host selain 127.0.0.1/localhost (anti DNS-rebinding)."""
    port = handler.server.server_address[1]
    return handler.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost")


def buat_handler(db_path, tahun_default=None, tugas=None):
    tugas = tugas or PengelolaTugas(db_path)

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

        def do_GET(self):
            u = urlparse(self.path)
            if not host_sah(self):
                return self._json(403, {"error": "Host tidak diizinkan."})
            if u.path == "/api/tugas":
                return self._json(200, tugas.status())
            if u.path == "/api/perubahan":
                try:
                    q = parse_qs(u.query)
                    th = q.get("tahun", [None])[0]
                    _, t = muat_target(None, int(th) if th and th.isdigit() else tahun_default)
                    conn = buka_readonly(db_path)
                    try:
                        return self._json(200, {"baris": database.perubahan(conn, t)})
                    finally:
                        conn.close()
                except sqlite3.Error as e:
                    return self._json(500, {"error": f"Database belum siap: {e}"})
            if u.path == "/":
                return self._kirim(200, "text/html; charset=utf-8", HTML.read_bytes())
            if u.path == "/api/database":
                try:
                    q = parse_qs(u.query)
                    th = q.get("tahun", [None])[0]
                    nama, t = muat_target(q.get("target", [None])[0], int(th) if th and th.isdigit() else tahun_default)
                    conn = buka_readonly(db_path)
                    try:
                        data = rekap.lengkap(conn, t)
                        return self._json(200, {"versi": data["versi"], "kolom": database.KOLOM,
                                                "baris": database.baris(conn, t, data)})
                    finally:
                        conn.close()
                except sqlite3.Error as e:
                    return self._json(500, {"error": f"Database belum siap: {e}"})
                except (AturanError, SystemExit) as e:
                    return self._json(500, {"error": str(e)})
            if u.path == "/api/rekap":
                try:
                    q = parse_qs(u.query)
                    th = q.get("tahun", [None])[0]
                    nama, t = muat_target(q.get("target", [None])[0], int(th) if th and th.isdigit() else tahun_default)
                    conn = buka_readonly(db_path)
                    try:
                        data = rekap.lengkap(conn, t)
                    finally:
                        conn.close()
                    data["lokasi"].pop("per_paket", None)       # sudah ada di data["paket"]
                    data["target"] = {"nama": nama, **{k: v for k, v in t.items() if k not in ("klasifikasi", "periksa")}}
                    return self._json(200, data)
                except sqlite3.Error as e:
                    return self._json(500, {"error": f"Database belum siap: {e}"})
                except AturanError as e:
                    return self._json(500, {"error": f"Aturan klasifikasi salah: {e}"})
                except SystemExit as e:
                    return self._json(400, {"error": str(e)})
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
