#!/bin/bash
# Klik dua kali: jalankan pembaruan data di SERVER GitHub (online), lalu tampilkan hasilnya di sini.
# Yang dijalankan: ambil data SiRUP + SPSE, periksa RUP, cadangkan & terbitkan ke Supabase (web publik ikut ter-update).
# Syarat sekali saja: kode sudah terkirim ke GitHub, dan secret SUPABASE_DB_URL sudah dipasang di repo.
cd "$(dirname "$0")" || exit 1
command -v gh >/dev/null 2>&1 || { echo "GitHub CLI (gh) belum terpasang. Pasang: brew install gh, lalu: gh auth login"; read -n 1 -s -r -p "Tekan tombol apa saja..."; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Belum login GitHub. Jalankan sekali: gh auth login"; read -n 1 -s -r -p "Tekan tombol apa saja..."; exit 1; }
if [ -n "$(git status --porcelain)" ]; then
  echo "Ada perubahan kode yang belum terkirim ke GitHub. Mengirim dulu ..."
  python3 push_github.py || { read -n 1 -s -r -p "Gagal mengirim. Tekan tombol apa saja..."; exit 1; }
fi
if ! gh secret list 2>/dev/null | grep -q SUPABASE_DB_URL; then
  echo "Secret SUPABASE_DB_URL belum ada di repo GitHub. Pasang dulu: GitHub > repo > Settings > Secrets and variables > Actions."
  read -n 1 -s -r -p "Tekan tombol apa saja..."; exit 1
fi
echo "Memulai pembaruan online ..."
gh workflow run perbarui.yml || { read -n 1 -s -r -p "Gagal memulai. Tekan tombol apa saja..."; exit 1; }
sleep 8
ID=$(gh run list --workflow perbarui.yml --limit 1 --json databaseId --jq '.[0].databaseId')
echo "Jalan nomor $ID dimulai. Memantau (boleh ditutup; proses tetap berjalan di GitHub) ..."
echo "Lihat di peramban: $(gh run view "$ID" --json url --jq .url)"
gh run watch "$ID" --exit-status --interval 20
HASIL=$?
echo
echo "=== Hasil cek akses SiRUP / SPSE dari server GitHub ==="
gh run view "$ID" --log 2>/dev/null | grep -E "^[^ ]+\s+.*(Cek akses|(200|403|000|404|429)  https)" | sed 's/^[^\t]*\t[^\t]*\t//' | head -6
echo
if [ $HASIL -eq 0 ]; then
  echo "SELESAI. Muat ulang halaman publik dengan Cmd+Shift+R; jam 'data per' di pita atas akan berubah."
else
  echo "ADA YANG GAGAL. Langkah yang gagal:"
  gh run view "$ID" --log-failed 2>/dev/null | tail -25
fi
read -n 1 -s -r -p "Tekan tombol apa saja untuk menutup..."
