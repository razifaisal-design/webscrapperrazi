#!/bin/bash
# Klik dua kali: unggah folder publik/ (salinan publik yang sudah dibuat) ke Cloudflare dengan Wrangler, tanpa mengambil data baru.
# Pertama kali: memasang Node.js bila belum ada dan membuka peramban untuk login Cloudflare.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
if ! command -v npx >/dev/null 2>&1; then
  echo "Node.js belum terpasang (dibutuhkan Wrangler, alat perintah Cloudflare)."
  if command -v brew >/dev/null 2>&1; then
    read -p "Pasang sekarang dengan Homebrew (brew install node)? [y/N]: " J
    [ "$J" = "y" ] || [ "$J" = "Y" ] && brew install node
  fi
  command -v npx >/dev/null 2>&1 || { echo "Pasang Node.js dari https://nodejs.org lalu jalankan lagi."; read -n 1 -s -r -p "Tekan tombol apa saja..."; exit 1; }
fi
if ! npx --yes wrangler@4 whoami >/dev/null 2>&1; then
  echo "Belum login Cloudflare. Peramban akan terbuka untuk memberi izin..."
  npx --yes wrangler@4 login || { read -n 1 -s -r -p "Login gagal. Tekan tombol apa saja..."; exit 1; }
fi
[ -f publik/index.html ] || .venv/bin/python -m scraper ekspor-publik
.venv/bin/python -m scraper unggah && touch data/.pernah_unggah
echo
read -n 1 -s -r -p "Tekan tombol apa saja untuk menutup..."
