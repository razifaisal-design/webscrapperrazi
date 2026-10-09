"""Unggah salinan publik (folder publik/) ke Cloudflare dengan Wrangler (alat perintah resmi Cloudflare).

Yang dibutuhkan sekali saja di komputer ini: Node.js (https://nodejs.org atau `brew install node`) dan login Cloudflare lewat
peramban (`npx wrangler login`). Kredensial dikelola Wrangler sendiri; aplikasi ini tidak pernah membaca atau menyimpan kata sandi/token."""
import re
import shutil
import subprocess

from .konfig import ROOT

NAMA_PROYEK = "spring-flower-c5ae"          # harus sama dengan "name" di wrangler.jsonc


def _jalankan(perintah, cwd, waktu=600):
    return subprocess.run(perintah, cwd=str(cwd), capture_output=True, text=True, timeout=waktu)


def unggah(keluar=None, log=print, jalankan=_jalankan, cari=shutil.which):
    """-> (ok, alamat | pesan). Tidak melempar galat: hasilnya dijelaskan di `pesan` agar pemanggil bisa melanjutkan."""
    keluar = keluar or (ROOT / "publik")
    if not (keluar / "index.html").exists():
        return False, f"Folder {keluar} belum berisi salinan publik. Jalankan dulu: python -m scraper ekspor-publik"
    if not (ROOT / "wrangler.jsonc").exists():
        return False, "wrangler.jsonc tidak ada di folder proyek."
    npx = cari("npx")
    if not npx:
        return False, ("Node.js belum terpasang, jadi Wrangler belum bisa dipakai. Pasang sekali: brew install node  "
                       "(atau unduh dari https://nodejs.org), lalu jalankan lagi.")
    log("Memeriksa login Cloudflare ...")
    cek = jalankan([npx, "--yes", "wrangler@4", "whoami"], ROOT, 180)
    if cek.returncode != 0 or re.search(r"not authenticated|not logged in|You are not", cek.stdout + cek.stderr, re.I):
        return False, "Belum login ke Cloudflare. Jalankan sekali di Terminal:  npx wrangler login   (peramban akan terbuka untuk izin), lalu ulangi."
    log(f"Mengunggah {keluar} sebagai proyek '{NAMA_PROYEK}' ...")
    r = jalankan([npx, "--yes", "wrangler@4", "deploy"], ROOT)
    keluaran = (r.stdout or "") + "\n" + (r.stderr or "")
    if r.returncode != 0:
        return False, "Wrangler gagal (kode %d): %s" % (r.returncode, keluaran.strip()[-600:])
    m = re.search(r"https://[A-Za-z0-9.-]+\.workers\.dev", keluaran)
    return True, m.group(0) if m else "Terunggah (alamat tidak terbaca dari keluaran Wrangler; lihat dasbor Cloudflare)."
