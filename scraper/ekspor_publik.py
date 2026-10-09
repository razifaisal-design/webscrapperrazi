"""Ekspor salinan PUBLIK (hanya baca) dashboard sebagai situs statis: kumpulan berkas HTML + JSON + Excel yang bisa ditaruh di hosting statis apa pun.

Tidak ada server dan tidak ada tombol pengambilan data: halaman yang sama dengan dashboard lokal dibaca dari berkas JSON hasil ekspor
(`statis.js` menggantikan pemanggilan /api/... dengan berkas). Isinya hanya data yang memang publik (SiRUP & SPSE), tanpa data pribadi."""
import datetime
import hashlib
import http.client
import json
import shutil
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from . import web
from .konfig import daftar_target, muat_target

AKAR = Path(__file__).resolve().parent
HALAMAN = {"dashboard.html": "index.html", "spse.html": "spse.html", "banding.html": "banding.html", "grafik.html": "grafik.html"}
TAUTAN = (('"/gaya.css"', '"gaya.css"'), ('"/bersama.js"', '"bersama.js"'),
          ('href="/"', 'href="index.html"'), ('href="/spse"', 'href="spse.html"'), ('href="/banding"', 'href="banding.html"'),
          ('href="/grafik"', 'href="grafik.html"'), ('"/grafik" + qsTarget()', '"grafik.html" + qsTarget()'))


class _Peladen:
    """Server lokal sesaat di port acak, dipakai untuk membaca jawaban API yang SAMA dengan yang dilihat dashboard."""

    def __init__(self, db_path, tahun_default=None):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), web.buat_handler(db_path, tahun_default))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def ambil(self, jalur):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=600)
        c.request("GET", jalur, headers={"Host": f"127.0.0.1:{self.port}"})
        r = c.getresponse()
        isi = r.read()
        c.close()
        return r.status, isi

    def tutup(self):
        self.srv.shutdown()
        self.srv.server_close()


def _tulis(path, isi):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(isi if isinstance(isi, bytes) else json.dumps(isi, ensure_ascii=False, separators=(",", ":")).encode())


def ekspor(db_path, keluar, log=print, dengan_excel=True):
    keluar = Path(keluar)
    if keluar.exists():
        shutil.rmtree(keluar)
    (keluar / "data").mkdir(parents=True)
    srv = _Peladen(db_path)
    ringkasan = {"berkas": 0}
    log("Membuat salinan publik (rekap, database, SPSE, perbandingan, Excel): biasanya 1-2 menit, mohon tunggu ...")
    try:
        def simpan(jalur, nama, wajib=True):
            st, isi = srv.ambil(jalur)
            if st != 200:
                if wajib:
                    raise RuntimeError(f"{jalur} -> HTTP {st}: {isi[:200]!r}")
                return None
            _tulis(keluar / "data" / nama, isi)
            ringkasan["berkas"] += 1
            return json.loads(isi)

        dasar_nama, dasar = muat_target(None, None)
        meta = {"dibuat": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "bawaan": {}, "target": [], "tahun_spse": []}
        satker = simpan("/api/satker", "satker.json")
        meta["target"] = [{"target": s["target"], "satker": s["satker"], "bawaan": s["bawaan"], "tahun": s["tahun"]} for s in satker["satker"]]
        # --- SiRUP: per satker (target) dan per tahun
        for s in satker["satker"]:
            t = s["target"]
            q_t = "" if s["bawaan"] else f"target={t}"
            for api in ("jalan", "statistik"):
                simpan(f"/api/{api}" + (f"?{q_t}" if q_t else ""), f"{api}_{t}.json", wajib=False)
            _, td = muat_target(t, None)
            meta["bawaan"][t] = td["tahun"]
            for th in [*s["tahun"], "semua"]:
                log(f"  SiRUP {s['satker'][:40]} - {'semua tahun (agak lama)' if th == 'semua' else th}")
                parameter = "&".join(x for x in (f"tahun={th}", q_t) if x)
                for api in ("rekap", "database", "perubahan"):
                    simpan(f"/api/{api}?{parameter}", f"{api}_{t}_{th}.json", wajib=False)
                if dengan_excel:
                    st, isi = srv.ambil(f"/api/excel?{parameter}")
                    if st == 200:
                        _tulis(keluar / "data" / f"excel_{t}_{th}.xlsx", isi)
                        ringkasan["berkas"] += 1
        # --- SPSE & perbandingan: satu berkas per tahun, semua satker (filter satker dikerjakan di peramban)
        conn = web.buka_readonly(db_path)
        try:
            tahun_spse = sorted({r[0] for r in conn.execute("SELECT DISTINCT tahun FROM spse_paket WHERE jenis='nontender'")}, reverse=True)
            meta["tahun_spse"] = tahun_spse
            jadwal = {}
            for r in conn.execute("SELECT j.kode_paket, j.no, j.tahap, j.mulai_teks, j.sampai_teks, j.mulai, j.sampai, j.jumlah_perubahan, j.riwayat_json "
                                  "FROM spse_jadwal j JOIN spse_paket p ON p.lpse=j.lpse AND p.jenis=j.jenis AND p.kode_paket=j.kode_paket "
                                  "WHERE p.is_active=1 ORDER BY j.kode_paket, j.no"):
                jadwal.setdefault(r[0], []).append({"no": r[1], "tahap": r[2], "mulai_teks": r[3], "sampai_teks": r[4], "mulai": r[5], "sampai": r[6],
                                                    "jumlah_perubahan": r[7] or 0, "riwayat": json.loads(r[8] or "[]")})
        finally:
            conn.close()
        _tulis(keluar / "data" / "jadwal_spse.json", jadwal)
        for th in tahun_spse:
            log(f"  SPSE & perbandingan {th}" + (" (+ Excel)" if dengan_excel else ""))
            simpan(f"/api/spse?tahun={th}", f"spse_{th}.json")
            simpan(f"/api/banding?tahun={th}", f"banding_{th}.json")
            if dengan_excel:
                for nama, jalur in ((f"spse_{th}.xlsx", f"/api/spse/excel?tahun={th}"), (f"banding_{th}.xlsx", f"/api/banding/excel?tahun={th}")):
                    st, isi = srv.ambil(jalur)
                    if st == 200:
                        _tulis(keluar / "data" / nama, isi)
                        ringkasan["berkas"] += 1
        if dengan_excel:
            log("  Excel semua tahun (SPSE & perbandingan) ...")
            for nama, jalur in (("spse_semua.xlsx", "/api/spse/excel?tahun=semua"), ("banding_semua.xlsx", "/api/banding/excel?tahun=semua")):
                st, isi = srv.ambil(jalur)
                if st == 200:
                    _tulis(keluar / "data" / nama, isi)
                    ringkasan["berkas"] += 1
        meta["bawaan"]["spse"] = dasar["tahun"]
        _tulis(keluar / "data" / "meta.json", meta)
    finally:
        srv.tutup()
    log("  menyalin halaman ...")
    # --- halaman, gaya, skrip
    for sumber, tujuan in HALAMAN.items():
        h = (AKAR / sumber).read_text(encoding="utf-8")
        for a, b in TAUTAN:
            h = h.replace(a, b)
        h = h.replace("<head>", '<head>\n<script src="statis.js"></script>', 1)
        # skrip bersama dimuat setelah statis.js, jadi fetch sudah diganti sebelum halaman berjalan
        (keluar / tujuan).write_text(h, encoding="utf-8")
    shutil.copy(AKAR / "gaya.css", keluar / "gaya.css")
    shutil.copy(AKAR / "bersama.js", keluar / "bersama.js")
    shutil.copy(AKAR / "statis.js", keluar / "statis.js")
    (keluar / ".nojekyll").write_text("", encoding="utf-8")
    ringkasan["ukuran_mb"] = round(sum(f.stat().st_size for f in keluar.rglob("*") if f.is_file()) / 1e6, 1)
    return ringkasan
