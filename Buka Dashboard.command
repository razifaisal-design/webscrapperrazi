#!/bin/bash
# Klik dua kali: buka dashboard rekap di browser (http://127.0.0.1:8765). Tutup jendela ini untuk menghentikan.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/python -m scraper web
