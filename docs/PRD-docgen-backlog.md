# Backlog — Generator Dokumen (di luar lingkup v1)

> Status: **ditunda.** Diringkas dari PRD awal "Modern Desktop Application Suite & PDF/Word Generator Engine". Akan dibuat PRD tersendiri setelah [PRD.md](PRD.md) Bagian 1–3 selesai.

## Ide inti
Membuat dokumen resmi (kontrak, RAB, laporan) berformat `.docx` dan `.pdf` lengkap dengan kop surat, memakai data dari Supabase.

## Keputusan yang sudah diambil
- Bahasa: **Python**. Tidak ada integrasi Java/`.jar` (yang dimaksud sebelumnya adalah JavaScript).
- Ekstraksi & pembersihan tabel PDF SIPD sudah masuk [PRD.md](PRD.md) Bagian 3, bukan modul ini.

## Rencana teknis kasar
- Template Word asli (kop, logo, margin) + `docxtpl` (tag Jinja2, loop tabel `{%tr for %}`).
- Konversi PDF lewat LibreOffice headless (satu jalur saja; jalur HTML/CSS dibuang).
- Format Indonesia: rupiah, terbilang, tanggal ("8 Oktober 2026").
- Unggah hasil ke bucket Supabase **privat**, akses lewat signed URL.

## Hal yang harus diputuskan nanti
- Bentuk aplikasi: desktop (PySide6) atau fitur di dashboard web.
- Ketergantungan LibreOffice di mesin pengguna (ukuran besar, tidak mudah dibundel).
- Target kinerja realistis: docx < 5 detik; docx + PDF < 15 detik (cold start LibreOffice).
- Packaging: code signing/notarization macOS, build Windows di mesin Windows/CI.
- Font yang tersedia sama di macOS & Windows agar PDF identik.
