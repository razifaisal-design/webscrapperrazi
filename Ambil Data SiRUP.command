#!/bin/bash
# Klik dua kali: ambil data SiRUP terbaru -> data/pantau.db + data/sirup_*.csv
cd "$(dirname "$0")" || exit 1
read -p "Tahun anggaran (Enter = tahun di config): " TAHUN
OPT=""; [ -n "$TAHUN" ] && OPT="--tahun $TAHUN"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/python -m scraper run sirup $OPT
echo
echo "Perubahan terakhir:"
.venv/bin/python -m scraper events --limit 15 $OPT
echo
read -n 1 -s -r -p "Tekan tombol apa saja untuk menutup..."
