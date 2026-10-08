#!/bin/bash
# Klik dua kali: ambil detail paket (lokasi, volume, uraian, spesifikasi) yang belum ada / berubah.
# Aman dihentikan (Ctrl+C) dan dilanjutkan; hanya paket baru/berubah yang diambil.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/python -m scraper detail sirup
echo
read -n 1 -s -r -p "Tekan tombol apa saja untuk menutup..."
