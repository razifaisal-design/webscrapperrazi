#!/bin/bash
# Klik dua kali: ambil data SiRUP terbaru -> data/pantau.db + data/sirup_*.csv
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/python -m scraper run sirup
echo
echo "Perubahan terakhir:"
.venv/bin/python -m scraper events --limit 15
echo
read -n 1 -s -r -p "Tekan tombol apa saja untuk menutup..."
