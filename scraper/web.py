"""Dashboard lokal (hanya 127.0.0.1):  python -m scraper web [--port 8765]"""
import json
import sqlite3
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .cli import muat_target
from .core import rekap
from .core.klasifikasi import AturanError

HTML = Path(__file__).with_name("dashboard.html")


def buka_readonly(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def buat_handler(db_path):
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

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                return self._kirim(200, "text/html; charset=utf-8", HTML.read_bytes())
            if u.path == "/api/rekap":
                try:
                    nama, t = muat_target(parse_qs(u.query).get("target", [None])[0])
                    conn = buka_readonly(db_path)
                    try:
                        data = rekap.lengkap(conn, t)
                    finally:
                        conn.close()
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


def jalankan(db_path, port=8765, buka_browser=True):
    if not Path(db_path).exists():
        raise SystemExit(f"Database {db_path} belum ada. Jalankan dulu: python -m scraper run sirup")
    srv = ThreadingHTTPServer(("127.0.0.1", port), buat_handler(db_path))
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
