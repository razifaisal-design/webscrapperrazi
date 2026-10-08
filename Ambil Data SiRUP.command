#!/bin/bash
# Klik dua kali: SATU PROSES - ambil daftar RUP, lalu detail paket, lalu bangun database Nama Jalan & Gang + CSV.
# Aman dihentikan (Ctrl+C) dan dilanjutkan: detail yang sudah terambil tetap tersimpan.
cd "$(dirname "$0")" || exit 1
pilih() {   # pilih "judul" nomor_default opsi...  -> mencetak opsi terpilih (menu bernomor)
  local judul="$1" def="$2"; shift 2; local opsi=("$@") i
  echo "$judul" >&2
  for i in "${!opsi[@]}"; do echo "  $((i+1))) ${opsi[$i]}$([ "$((i+1))" = "$def" ] && echo '   (default)')" >&2; done
  read -p "Pilih nomor [$def]: " n
  n=${n:-$def}; echo "${opsi[$((n-1))]:-${opsi[$((def-1))]}}"
}
read -p "Tahun anggaran (Enter = tahun di config): " TAHUN
OPT=""; [ -n "$TAHUN" ] && OPT="--tahun $TAHUN"
K=$(pilih "Jumlah koneksi untuk detail (lebih banyak = lebih cepat, tapi lebih berisiko diblokir):" 1 1 2 3 5)
J=$(pilih "Jeda tiap koneksi (detik):" 3 0.5 1 1.5 2 3)
echo "Tahun: ${TAHUN:-config} | koneksi $K | jeda $J detik"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/python -m scraper ambil sirup $OPT --koneksi $K --jeda $J
echo
echo "Perubahan terakhir (revisi RUP = nama sama, kode berganti):"
.venv/bin/python -m scraper events --limit 15 $OPT
echo
read -n 1 -s -r -p "Tekan tombol apa saja untuk menutup..."
