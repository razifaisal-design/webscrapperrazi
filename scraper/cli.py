"""CLI:  python -m scraper run sirup | detail sirup | events"""
import argparse
import json
import sys
import time
from pathlib import Path

from .core import db
from .core.http import DiblokirError, SopanClient
from .sources import sirup, sirup_detail

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / "config" / "targets.json"


def muat_target(nama):
    cfg = json.loads(TARGETS.read_text(encoding="utf-8"))
    nama = nama or cfg["default"]
    if nama not in cfg["targets"]:
        raise SystemExit(f"Target '{nama}' tidak ada di {TARGETS}. Pilihan: {', '.join(cfg['targets'])}")
    return nama, cfg["targets"][nama]


def csv_path(target):
    return ROOT / "data" / f"sirup_{target['id_satker']}_{target['tahun']}.csv"


def cmd_run(args):
    nama, target = muat_target(args.target)
    conn = db.buka(args.db)
    run_id = db.mulai_run(conn, target["id_satker"], target["tahun"])
    print(f"Run #{run_id} - {target['satker_nama']} ({target['klpd_nama']}) tahun {target['tahun']}")
    client = SopanClient(jeda=args.jeda)
    paket, totals = [], {}
    try:
        for jenis in ("penyedia", "swakelola"):
            hasil, total = sirup.ambil_semua(client, jenis, target)
            paket += hasil
            totals[jenis] = total
    except DiblokirError as e:
        db.tutup_run(conn, run_id, "failed", len(paket), sum(totals.values()) or None, str(e))
        print(f"[BERHENTI] {e}")
        return 2
    except Exception as e:  # jaringan putus dll: data lama tidak disentuh
        db.tutup_run(conn, run_id, "failed", len(paket), sum(totals.values()) or None, repr(e))
        print(f"[GAGAL] {e!r} - data lama tidak diubah.")
        return 1
    finally:
        client.close()

    sebelumnya = db.jumlah_run_valid_terakhir(conn, target["id_satker"], target["tahun"])
    alasan = db.validasi(paket, totals, sebelumnya, args.force)
    if alasan:
        db.tutup_run(conn, run_id, "invalid", len(paket), sum(totals.values()), "; ".join(alasan))
        print("[RUN TIDAK VALID - data lama tidak diubah]\n  - " + "\n  - ".join(alasan))
        return 3

    r = db.finalisasi(conn, run_id, paket, target["id_satker"], target["tahun"])
    db.tutup_run(conn, run_id, "success", len(paket), sum(totals.values()))
    total_pagu = sum(p["pagu"] for p in paket)
    print(f"\nSelesai. {len(paket)} paket ({totals['penyedia']} penyedia + {totals['swakelola']} swakelola), "
          f"total pagu Rp {total_pagu:,.0f}".replace(",", "."))
    if r["baseline"]:
        print("Run pertama = data dasar (belum ada pembanding, event tidak dicatat).")
    else:
        print(f"Perubahan: {r['baru']} baru, {r['berubah']} berubah, {r['hilang']} hilang, "
              f"{r['muncul_kembali']} muncul kembali, {r['revisi']} kemungkinan revisi RUP")
    if not args.no_csv:
        n = db.ekspor_csv(conn, target["id_satker"], target["tahun"], csv_path(target))
        print(f"CSV : {csv_path(target)} ({n} baris, termasuk kolom link)")
    print(f"DB  : {Path(args.db)}")
    return 0


def cmd_detail(args):
    nama, target = muat_target(args.target)
    conn = db.buka(args.db)
    antre = db.paket_perlu_detail(conn, target["id_satker"], target["tahun"], args.semua)
    if args.limit:
        antre = antre[: args.limit]
    if not antre:
        print("Semua detail paket sudah terbaru. (Gunakan --semua untuk mengambil ulang semuanya.)")
        return 0
    perkiraan = len(antre) * (args.jeda + 0.4) / 60
    print(f"{len(antre)} paket akan diambil detailnya (perkiraan ±{perkiraan:.0f} menit). Ctrl+C aman: yang sudah diambil tersimpan.")
    run_id = db.mulai_run(conn, target["id_satker"], target["tahun"], sumber="SIRUP_DETAIL")
    client = SopanClient(jeda=args.jeda)
    ok, gagal, mulai = 0, [], time.monotonic()
    try:
        for i, p in enumerate(antre, 1):
            try:
                d = sirup_detail.ambil_detail(client, p["jenis"], p["kode_rup"])
                db.simpan_detail(conn, run_id, p["kode_rup"], p["nama_paket"], p["pagu"], d)
                ok += 1
            except sirup_detail.DetailError as e:
                db.catat_gagal_detail(conn, p["kode_rup"], str(e))
                gagal.append((p["kode_rup"], str(e)))
            if i % 25 == 0 or i == len(antre):
                sisa = (time.monotonic() - mulai) / i * (len(antre) - i) / 60
                print(f"  {i}/{len(antre)}  berhasil {ok}, gagal {len(gagal)}  (sisa ±{sisa:.0f} menit)")
    except DiblokirError as e:
        db.tutup_run(conn, run_id, "failed", ok, len(antre), str(e))
        print(f"[BERHENTI] {e} - yang sudah diambil ({ok}) tetap tersimpan.")
        return 2
    except KeyboardInterrupt:
        db.tutup_run(conn, run_id, "failed", ok, len(antre), "dihentikan pengguna")
        print(f"\nDihentikan. {ok} detail tersimpan; jalankan lagi untuk melanjutkan.")
        return 130
    finally:
        client.close()
    db.tutup_run(conn, run_id, "success" if not gagal else "invalid", ok, len(antre),
                 "; ".join(f"{k}: {m}" for k, m in gagal[:20]) or None)
    print(f"\nSelesai. Detail berhasil: {ok}, gagal: {len(gagal)}")
    for k, m in gagal[:10]:
        print(f"  gagal {k}: {m}")
    n = db.ekspor_csv(conn, target["id_satker"], target["tahun"], csv_path(target))
    print(f"CSV : {csv_path(target)} ({n} baris, sudah berisi lokasi/volume/uraian/spesifikasi)")
    return 0 if not gagal else 4


def cmd_web(args):
    from . import web
    web.jalankan(args.db, args.port, not args.no_browser)
    return 0


def cmd_events(args):
    _, target = muat_target(args.target)
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
    r.add_argument("--jeda", type=float, default=1.5, help="jeda antar request (detik)")
    r.add_argument("--force", action="store_true", help="terima penurunan jumlah > 20%%")
    r.add_argument("--no-csv", action="store_true")
    r.set_defaults(fn=cmd_run)
    d = sub.add_parser("detail", help="ambil detail tiap paket (lokasi, volume, uraian, spesifikasi)")
    d.add_argument("sumber", choices=["sirup"])
    d.add_argument("--target")
    d.add_argument("--jeda", type=float, default=1.5)
    d.add_argument("--limit", type=int, help="ambil hanya N paket (untuk uji coba)")
    d.add_argument("--semua", action="store_true", help="ambil ulang semua, bukan hanya yang belum/berubah")
    d.set_defaults(fn=cmd_detail)
    w = sub.add_parser("web", help="buka dashboard lokal di browser")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--no-browser", action="store_true")
    w.set_defaults(fn=cmd_web)
    e = sub.add_parser("events", help="tampilkan perubahan terakhir")
    e.add_argument("--target")
    e.add_argument("--limit", type=int, default=30)
    e.set_defaults(fn=cmd_events)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
