#!/bin/bash
# Klik dua kali: deteksi kesalahan data (mis. Saluran tercatat di MAK Jalan) -> data/temuan_*.csv
cd "$(dirname "$0")" || exit 1
.venv/bin/python -m scraper periksa
echo
read -n 1 -s -r -p "Tekan tombol apa saja untuk menutup..."
