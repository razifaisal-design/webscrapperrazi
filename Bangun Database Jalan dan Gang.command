#!/bin/bash
# Klik dua kali: bangun database Nama Jalan & Nama Gang (paket fisik) + ekspor CSV lengkap.
cd "$(dirname "$0")" || exit 1
read -p "Tahun anggaran (Enter = tahun di config): " TAHUN
OPT=""; [ -n "$TAHUN" ] && OPT="--tahun $TAHUN"
.venv/bin/python -m scraper lokasi $OPT
echo
read -n 1 -s -r -p "Tekan tombol apa saja untuk menutup..."
