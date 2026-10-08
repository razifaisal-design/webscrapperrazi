#!/bin/bash
# Klik dua kali file ini di Finder untuk mengirim perubahan ke GitHub.
cd "$(dirname "$0")" || exit 1
python3 push_github.py
echo
read -n 1 -s -r -p "Tekan tombol apa saja untuk menutup..."
