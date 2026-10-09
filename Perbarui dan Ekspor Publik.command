#!/bin/bash
# Klik dua kali: SATU PROSES - ambil data SiRUP + SPSE (daftar dan detail), periksa RUP yang tidak ada di daftar SiRUP,
# lalu buat salinan publik (folder publik/) yang siap diunggah ke hosting.
# Aman dihentikan (Ctrl+C) dan dilanjutkan: yang sudah terambil tetap tersimpan; yang sudah lengkap tidak diambil ulang.
cd "$(dirname "$0")" || exit 1
pilih() {   # pilih "judul" nomor_default opsi...  -> mencetak opsi terpilih (menu bernomor)
  local judul="$1" def="$2"; shift 2; local opsi=("$@") i
  echo "$judul" >&2
  for i in "${!opsi[@]}"; do echo "  $((i+1))) ${opsi[$i]}$([ "$((i+1))" = "$def" ] && echo '   (default)')" >&2; done
  read -p "Pilih nomor [$def]: " n
  n=${n:-$def}; echo "${opsi[$((n-1))]:-${opsi[$((def-1))]}}"
}
siapkan_cloudflare() {   # pastikan Node.js + login Cloudflare (sekali saja); kata sandi dikelola Wrangler, bukan aplikasi ini
  if ! command -v npx >/dev/null 2>&1; then
    echo "Node.js belum terpasang (dibutuhkan Wrangler, alat perintah Cloudflare)."
    if command -v brew >/dev/null 2>&1; then
      read -p "Pasang sekarang dengan Homebrew (brew install node)? [y/N]: " J
      [ "$J" = "y" ] || [ "$J" = "Y" ] && brew install node
    fi
    command -v npx >/dev/null 2>&1 || { echo "Pasang Node.js dari https://nodejs.org lalu jalankan lagi."; return 1; }
  fi
  if ! npx --yes wrangler@4 whoami >/dev/null 2>&1; then
    echo "Belum login Cloudflare. Peramban akan terbuka untuk memberi izin..."
    npx --yes wrangler@4 login || return 1
  fi
}
read -p "Tahun anggaran (Enter = tahun di config): " TAHUN
OPT=""; [ -n "$TAHUN" ] && OPT="--tahun $TAHUN"
K=$(pilih "Jumlah koneksi (lebih banyak = lebih cepat, tapi lebih berisiko diblokir):" 2 1 2 3 4 5)
J=$(pilih "Jeda tiap koneksi (detik):" 3 1 1.5 2 3)
DEF="N"; [ -f data/.pernah_unggah ] && DEF="Y"
read -p "Unggah ke Cloudflare setelah ekspor? [y/N] (Enter = $DEF): " U
U=${U:-$DEF}
UNGGAH=""
if [ "$U" = "y" ] || [ "$U" = "Y" ]; then
  if siapkan_cloudflare; then UNGGAH="--unggah"; else echo "Unggah dilewati (Cloudflare belum siap); ekspor tetap dijalankan."; fi
fi
echo "Tahun: ${TAHUN:-config} | koneksi $K | jeda $J detik | unggah: ${UNGGAH:-tidak}"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
.venv/bin/python -m scraper perbarui $OPT --koneksi $K --jeda $J $UNGGAH
KODE=$?
[ -n "$UNGGAH" ] && [ $KODE -eq 0 ] && touch data/.pernah_unggah
echo
if [ $KODE -eq 0 ]; then
  echo "Selesai. Salinan publik ada di folder: $(pwd)/publik"
  echo "Unggah isi folder itu ke hosting Anda (atau coba lokal: cd publik && python3 -m http.server 8000)."
else
  echo "Selesai dengan catatan (kode $KODE) - lihat ringkasan di atas."
fi
read -n 1 -s -r -p "Tekan tombol apa saja untuk menutup..."
