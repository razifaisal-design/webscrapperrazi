"""CLI:  python -m scraper spse nontender | ambil sirup | run sirup | detail sirup | lokasi | periksa | web | events"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

from .core import db
from . import tugas
from .core.http import DiblokirError, SopanClient
from .sources import sirup, sirup_detail

from .konfig import ROOT, TARGETS, muat_target  # noqa: F401  (diekspor ulang untuk kompatibilitas)


def cmd_run(args):
    nama, target = muat_target(args.target, args.tahun, getattr(args, "id_satker", None))
    conn = db.buka(args.db)
    try:
        return tugas.run_daftar(conn, target, jeda=args.jeda, force=args.force, ekspor=not args.no_csv)
    except KeyboardInterrupt:
        print("\nDihentikan.")
        return 130


def cmd_detail(args):
    nama, target = muat_target(args.target, args.tahun, getattr(args, "id_satker", None))
    conn = db.buka(args.db)
    try:
        return tugas.run_detail(conn, target, koneksi=args.koneksi, jeda=args.jeda, usia_hari=args.usia_hari,
                                semua=args.semua, limit=args.limit, db_path=args.db)
    except ValueError as e:
        raise SystemExit(f"Parameter tidak valid: {e}")


def cmd_spse(args):
    _, target = muat_target(args.target, None)
    lpse = args.lpse or (target.get("spse") or {}).get("lpse", "pontianak")
    conn = db.buka(args.db)
    try:
        return tugas.run_spse(conn, args.jenis, lpse, args.tahun or target["tahun"], jeda=args.jeda, force=args.force, ekspor=not args.no_csv)
    except KeyboardInterrupt:
        print("\nDihentikan.")
        return 130
    except ValueError as e:
        raise SystemExit(f"Parameter tidak valid: {e}")


def cmd_spse_detail(args):
    _, target = muat_target(args.target, None)
    lpse = args.lpse or (target.get("spse") or {}).get("lpse", "pontianak")
    conn = db.buka(args.db)
    try:
        # cakupan rincian lengkap: --satker NAMA | semua | tidak (hanya Pengumuman); bawaan = satker di config (bisa diganti)
        pilih = args.satker if args.satker is not None else ("semua" if args.semua_satker else target["satker_nama"])
        satker = None if pilih.lower() == "semua" else "__tidak" if pilih.lower() == "tidak" else pilih
        return tugas.run_spse_detail(conn, args.jenis, lpse, int(args.tahun or target["tahun"]), jeda=args.jeda,
                                     usia_hari=args.usia_hari, semua=args.semua, limit=args.limit, satker=satker, koneksi=args.koneksi)
    except KeyboardInterrupt:
        print("\nDihentikan.")
        return 130
    except ValueError as e:
        raise SystemExit(f"Parameter tidak valid: {e}")


def cmd_ekspor_publik(args):
    from . import ekspor_publik
    ringkas = ekspor_publik.ekspor(args.db, args.keluar, dengan_excel=not args.tanpa_excel)
    print(f"Selesai: {ringkas['berkas']} berkas data, total {ringkas['ukuran_mb']} MB di {args.keluar}")
    print(f"Coba lokal:  cd {args.keluar} && python3 -m http.server 8000   lalu buka http://localhost:8000/")
    return 0


def cmd_perbarui(args):
    conn = db.buka(args.db)
    try:
        return tugas.run_perbarui(conn, args.db, tahun=args.tahun, koneksi=args.koneksi, jeda=args.jeda, usia_hari=args.usia_hari,
                                  rinci=args.rinci, satker=args.satker, periksa=not args.tanpa_periksa, ekspor=not args.tanpa_ekspor,
                                  keluar=args.keluar, unggah=args.unggah,
                                  sinkron=False if args.tanpa_sinkron else None)
    except KeyboardInterrupt:
        print("\nDihentikan. Yang sudah terambil tetap tersimpan; jalankan lagi untuk melanjutkan.")
        return 130
    except ValueError as e:
        raise SystemExit(f"Parameter tidak valid: {e}")


def cmd_sinkron(args):
    from . import sinkron
    try:
        jumlah = sinkron.sinkron(args.db)
    except sinkron.SinkronError as e:
        print(f"TIDAK TERCADANG: {e}")
        return 1
    print(f"Supabase dicerminkan: {sum(jumlah.values())} baris di {len(jumlah)} tabel.")
    return 0


def cmd_terbitkan(args):
    from . import ekspor_publik, sinkron
    kfg, url = ekspor_publik.muat_konfig_publik(), sinkron.url_db()
    if not kfg:
        print("config/publik.json belum lengkap (supabase_url dan kunci_publikasi).")
        return 1
    if not url:
        print("SUPABASE_DB_URL belum diisi di .env (lihat .env.example).")
        return 1
    try:
        r = ekspor_publik.terbitkan(args.db, args.keluar or str(ROOT / "publik"), url, kfg, dengan_excel=not args.tanpa_excel)
    except Exception as e:
        print(f"GAGAL menerbitkan: {type(e).__name__}: {str(e)[:300]}")
        return 1
    print(f"Terbit: {r['berkas']} berkas data di Supabase; halaman publik {r['ukuran_mb']} MB di {args.keluar or ROOT / 'publik'}")
    return 0


def cmd_tarik(args):
    from . import sinkron
    try:
        jumlah = sinkron.tarik(args.db, paksa=args.paksa)
    except sinkron.SinkronError as e:
        print(f"TIDAK DITARIK: {e}")
        return 1
    print(f"Database lokal dibangun dari Supabase: {sum(jumlah.values())} baris di {len(jumlah)} tabel.")
    return 0


def cmd_impor_mak(args):
    from .core import mak_ref
    conn = db.buka(args.db)
    try:
        r = mak_ref.impor(conn, args.berkas)
        n = mak_ref.isi_sub_kegiatan(conn)
    except sqlite3.Error as e:
        print(f"GAGAL membaca database MAK: {e}")
        return 1
    ada = conn.execute("SELECT COUNT(*) FROM sirup_detail WHERE sub_kegiatan_nama IS NOT NULL").fetchone()[0]
    tak = conn.execute("SELECT COUNT(*) FROM sirup_detail WHERE sub_kegiatan_kode IS NOT NULL AND sub_kegiatan_nama IS NULL").fetchone()[0]
    print(f"Field Sub Kegiatan diisi untuk {n} paket: {ada} ada namanya, {tak} belum diketahui (kode ada, tidak ada di referensi).")
    return 0


def cmd_unggah(args):
    from . import unggah
    ok, pesan = unggah.unggah()
    print(("Terunggah: " if ok else "TIDAK TERUNGGAH: ") + pesan)
    return 0 if ok else 1


def cmd_ambil(args):
    nama, target = muat_target(args.target, args.tahun, getattr(args, 'id_satker', None))
    conn = db.buka(args.db)
    try:
        return tugas.run_semua(conn, target, koneksi=args.koneksi, jeda=args.jeda, usia_hari=args.usia_hari,
                               semua=args.semua, limit=args.limit, force=args.force, db_path=args.db)
    except ValueError as e:
        raise SystemExit(f"Parameter tidak valid: {e}")


def cmd_lokasi(args):
    nama, target = muat_target(args.target, args.tahun, getattr(args, 'id_satker', None))
    tugas.bangun_lokasi(db.buka(args.db), target, args.db)
    return 0


def cmd_periksa(args):
    import csv
    from .core import rekap
    nama, target = muat_target(args.target, args.tahun, getattr(args, 'id_satker', None))
    conn = db.buka(args.db)
    data = rekap.lengkap(conn, target)
    pr = data["periksa"]
    print(f"{target['satker_nama']} - {data['paket_dengan_detail']} paket ber-detail (dari {data['paket_aktif']} aktif)")
    print(f"Kesalahan: {pr['jumlah_kesalahan']}   Peringatan: {pr['jumlah_peringatan']}\n")
    for jenis, r in pr["ringkas"].items():
        print(f"  [{r['tingkat']:10}] {r['judul']:<34} {r['jumlah']:>4} paket   Rp {r['pagu']:,.0f}".replace(",", "."))
    if pr["matriks"]:
        m = pr["matriks"]
        print("\nRekonsiliasi kategori paket x jenis MAK (Rp):")
        for b in m["baris"]:
            print("  " + f"{b:<8}" + "  ".join(f"{k}: {m['nilai'][b][k]['pagu']:,.0f} ({m['nilai'][b][k]['paket']})".replace(",", ".") for k in m["kolom"]))
    tampil = [t for t in pr["temuan"] if t["tingkat"] == "kesalahan"][: args.limit]
    if tampil:
        print(f"\n{len(tampil)} kesalahan teratas:")
        for t in tampil:
            print(f"  {t['kode_rup']}  {t['nama_paket'][:60]}\n      -> {t['pesan']}")
    path = ROOT / "data" / f"temuan_{target['id_satker']}_{target['tahun']}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["tingkat", "jenis", "kode_rup", "nama_paket", "pesan", "pagu_terkait", "link"])
        w.writerows([t["tingkat"], t["jenis"], t["kode_rup"], t["nama_paket"], t["pesan"], t["pagu"], t["link"]] for t in pr["temuan"])
    print(f"\nCSV : {path} ({len(pr['temuan'])} temuan)")
    return 1 if pr["jumlah_kesalahan"] else 0


def cmd_web(args):
    from . import web
    web.jalankan(args.db, args.port, not args.no_browser, args.tahun)
    return 0


def cmd_events(args):
    _, target = muat_target(args.target, args.tahun, getattr(args, 'id_satker', None))
    conn = db.buka(args.db)
    rows = conn.execute(
        "SELECT e.waktu,e.jenis_event,e.kunci,e.nama_paket,e.field,e.nilai_lama,e.nilai_baru,e.selisih "
        "FROM paket_events e JOIN sirup_paket p ON p.kode_rup=e.kunci WHERE p.id_satker=? "
        "ORDER BY e.id DESC LIMIT ?", (target["id_satker"], args.limit)).fetchall()
    if not rows:
        print("Belum ada perubahan tercatat.")
    for r in rows:
        det = f" {r['field']}: {r['nilai_lama']} -> {r['nilai_baru']}" if r["field"] else ""
        print(f"{r['waktu']}  {r['jenis_event']:<18} {r['kunci']}  {r['nama_paket'][:50]}{det}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scraper")
    ap.add_argument("--db", default=str(db.DB_DEFAULT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ambil data dan simpan ke database lokal")
    r.add_argument("sumber", choices=["sirup"])
    r.add_argument("--target", help="nama target di config/targets.json")
    r.add_argument("--tahun", type=int, help="tahun anggaran (default: dari config)")
    r.add_argument("--id-satker", type=int, help="idSatker SiRUP untuk tahun ini (default: dari config / dicari otomatis)")
    r.add_argument("--jeda", type=float, default=1.5, help="jeda antar request (detik)")
    r.add_argument("--force", action="store_true", help="terima penurunan jumlah > 20%%")
    r.add_argument("--no-csv", action="store_true")
    r.set_defaults(fn=cmd_run)
    sp = sub.add_parser("spse", help="ambil DAFTAR paket dari SPSE/LPSE (100 baris per halaman); detail menyusul")
    sp.add_argument("jenis", choices=["nontender"], help="jenis paket SPSE (tender menyusul)")
    sp.add_argument("--target")
    sp.add_argument("--lpse", help="kode LPSE di alamat spse.inaproc.id/<lpse> (default: dari config)")
    sp.add_argument("--tahun", default=None, help="tahun anggaran (default: tahun di config, mis. 2026), atau 'semua' = semua tahun di pilihan SPSE")
    sp.add_argument("--jeda", type=float, default=1.5, help="jeda antar permintaan, detik (default 1.5)")
    sp.add_argument("--force", action="store_true", help="terima penurunan jumlah paket > 20%%")
    sp.add_argument("--no-csv", action="store_true")
    sp.set_defaults(fn=cmd_spse)
    sd = sub.add_parser("spse-detail", help="ambil DETAIL paket SPSE (Pengumuman, Pemenang, Pemenang Berkontrak)")
    sd.add_argument("jenis", choices=["nontender"])
    sd.add_argument("--target")
    sd.add_argument("--lpse", help="kode LPSE (default: dari config)")
    sd.add_argument("--tahun", default=None, help="tahun anggaran (default: tahun di config)")
    sd.add_argument("--koneksi", type=int, default=1, help="jumlah koneksi paralel (1-10; default 1)")
    sd.add_argument("--jeda", type=float, default=1.5, help="jeda tiap koneksi antar permintaan, detik (default 1.5)")
    sd.add_argument("--limit", type=int, help="ambil hanya N paket (uji coba)")
    sd.add_argument("--usia-hari", type=int, default=7, help="ambil ulang detail yang lebih tua dari N hari (0 = nonaktif)")
    sd.add_argument("--semua", action="store_true", help="paksa ambil ulang semua")
    sd.add_argument("--satker", help="rincian lengkap (pemenang, kontrak, jadwal) hanya untuk satker ini; 'semua' = semua satker, 'tidak' = hanya Pengumuman (default: satker di config)")
    sd.add_argument("--semua-satker", action="store_true", help="sama dengan --satker semua")
    sd.set_defaults(fn=cmd_spse_detail)
    ep = sub.add_parser("ekspor-publik", help="buat salinan publik (hanya baca) dashboard: situs statis HTML + JSON yang bisa di-hosting")
    ep.add_argument("--keluar", default=str(ROOT / "publik"), help="folder hasil (default: publik/)")
    ep.add_argument("--tanpa-excel", action="store_true", help="lewati pembuatan berkas Excel (lebih cepat dan kecil)")
    ep.set_defaults(fn=cmd_ekspor_publik)
    sk = sub.add_parser("sinkron", help="cerminkan database lokal ke Supabase (cadangan); butuh SUPABASE_DB_URL di .env")
    sk.set_defaults(fn=cmd_sinkron)
    tk = sub.add_parser("tarik", help="bangun database lokal dari cermin di Supabase (untuk server/GitHub Actions atau komputer baru)")
    tk.add_argument("--paksa", action="store_true", help="ganti database lokal yang sudah ada (yang lama disimpan sebagai .sebelum-tarik)")
    tk.set_defaults(fn=cmd_tarik)
    tb = sub.add_parser("terbitkan", help="terbitkan data ke Supabase (dibaca langsung oleh web publik) dan buat halaman publik kecil di publik/")
    tb.add_argument("--keluar", help="folder halaman publik (default: publik/)")
    tb.add_argument("--tanpa-excel", action="store_true")
    tb.set_defaults(fn=cmd_terbitkan)
    im = sub.add_parser("impor-mak", help="impor database MAK/sub kegiatan (kode_mak.db) dan isi field Sub Kegiatan pada paket")
    im.add_argument("berkas", help="path kode_mak.db")
    im.set_defaults(fn=cmd_impor_mak)
    ug = sub.add_parser("unggah", help="unggah folder publik/ (salinan publik) ke Cloudflare dengan Wrangler")
    ug.set_defaults(fn=cmd_unggah)
    pb = sub.add_parser("perbarui", help="SATU PERINTAH: ambil data SiRUP + SPSE, periksa RUP, lalu ekspor salinan publik")
    pb.add_argument("--tahun", type=int, help="tahun anggaran (default: dari config)")
    pb.add_argument("--satker", help="hanya satu satker terdaftar (nama); default: semua satker terdaftar")
    pb.add_argument("--rinci", default="semua", help="cakupan rincian SPSE (pemenang, kontrak, jadwal): semua | tidak | nama satker (default semua)")
    pb.add_argument("--koneksi", type=int, default=1, help="jumlah koneksi paralel untuk detail (1-10; default 1)")
    pb.add_argument("--jeda", type=float, default=1.5, help="jeda tiap koneksi antar permintaan, detik (default 1.5)")
    pb.add_argument("--usia-hari", type=int, default=7, help="ambil ulang detail yang lebih tua dari N hari (0 = nonaktif)")
    pb.add_argument("--tanpa-periksa", action="store_true", help="lewati pemeriksaan RUP langsung ke SiRUP")
    pb.add_argument("--tanpa-ekspor", action="store_true", help="lewati ekspor salinan publik")
    pb.add_argument("--keluar", help="folder salinan publik (default: publik/)")
    pb.add_argument("--tanpa-sinkron", action="store_true", help="lewati cadangan ke Supabase (otomatis jalan bila SUPABASE_DB_URL ada di .env)")
    pb.add_argument("--unggah", action="store_true", help="setelah ekspor, unggah ke Cloudflare dengan Wrangler")
    pb.set_defaults(fn=cmd_perbarui)
    a = sub.add_parser("ambil", help="SATU PROSES: ambil daftar RUP, lalu detail paket, lalu bangun database Jalan/Gang")
    a.add_argument("sumber", choices=["sirup"])
    a.add_argument("--target")
    a.add_argument("--tahun", type=int, help="tahun anggaran (default: dari config)")
    a.add_argument("--id-satker", type=int, help="idSatker SiRUP untuk tahun ini (default: dari config / dicari otomatis)")
    a.add_argument("--koneksi", type=int, default=1, help="jumlah koneksi paralel untuk detail (1-10; default 1)")
    a.add_argument("--jeda", type=float, default=1.5, help="jeda tiap koneksi antar permintaan, detik (default 1.5)")
    a.add_argument("--usia-hari", type=int, default=7, help="ambil ulang detail yang lebih tua dari N hari (0 = nonaktif)")
    a.add_argument("--semua", action="store_true", help="paksa ambil ulang semua detail")
    a.add_argument("--limit", type=int, help="batasi jumlah detail (uji coba)")
    a.add_argument("--force", action="store_true", help="terima penurunan jumlah paket > 20%%")
    a.set_defaults(fn=cmd_ambil)
    d = sub.add_parser("detail", help="ambil detail tiap paket (lokasi, volume, uraian, spesifikasi)")
    d.add_argument("sumber", choices=["sirup"])
    d.add_argument("--target")
    d.add_argument("--tahun", type=int, help="tahun anggaran (default: dari config)")
    d.add_argument("--id-satker", type=int, help="idSatker SiRUP untuk tahun ini (default: dari config)")
    d.add_argument("--koneksi", type=int, default=1, help="jumlah koneksi paralel (1-10; default 1)")
    d.add_argument("--jeda", type=float, default=1.5, help="jeda tiap koneksi antar permintaan, detik (default 1.5)")
    d.add_argument("--limit", type=int, help="ambil hanya N paket (untuk uji coba)")
    d.add_argument("--usia-hari", type=int, default=7, help="ambil ulang detail yang lebih tua dari N hari (0 = nonaktif; default 7)")
    d.add_argument("--semua", action="store_true", help="ambil ulang semua, bukan hanya yang belum/berubah")
    d.set_defaults(fn=cmd_detail)
    lk = sub.add_parser("lokasi", help="bangun database Nama Jalan & Nama Gang (paket fisik) + ekspor CSV lengkap")
    lk.add_argument("--target")
    lk.add_argument("--tahun", type=int, help="tahun anggaran (default: dari config)")
    lk.set_defaults(fn=cmd_lokasi)
    k = sub.add_parser("periksa", help="deteksi kesalahan (mis. Saluran tercatat di MAK Jalan)")
    k.add_argument("--target")
    k.add_argument("--tahun", type=int, help="tahun anggaran (default: dari config)")
    k.add_argument("--limit", type=int, default=10, help="jumlah kesalahan yang ditampilkan di layar")
    k.set_defaults(fn=cmd_periksa)
    w = sub.add_parser("web", help="buka dashboard lokal di browser")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--no-browser", action="store_true")
    w.add_argument("--tahun", type=int, help="tahun yang tampil pertama kali (default: dari config)")
    w.set_defaults(fn=cmd_web)
    e = sub.add_parser("events", help="tampilkan perubahan terakhir")
    e.add_argument("--target")
    e.add_argument("--tahun", type=int, help="tahun anggaran (default: dari config)")
    e.add_argument("--limit", type=int, default=30)
    e.set_defaults(fn=cmd_events)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
