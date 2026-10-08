"""Pekerjaan pengambilan data - dipakai bersama oleh terminal (cli.py) dan dashboard (web.py).

Sopan santun ke server: tiap koneksi punya jeda sendiri antar permintaan, dan SEMUA koneksi berhenti seketika
bila server menolak (403/429)."""
import csv
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .core import database, db, rekap
from .core.http import DiblokirError, SopanClient
from .sources import sirup, sirup_detail

ROOT = Path(__file__).resolve().parents[1]
KONEKSI_MAKS, JEDA_MIN = 10, 0.2
WAKTU_PERMINTAAN = 0.15           # lama satu permintaan (detik) di luar jeda; diukur: 3 koneksi + jeda 1 dtk = 2,6 paket/dtk


def csv_path(target):
    return ROOT / "data" / f"sirup_{target['id_satker']}_{target['tahun']}.csv"


def laju(koneksi, jeda):
    """Perkiraan permintaan per detik ke server."""
    return koneksi / (jeda + WAKTU_PERMINTAAN)


def peringatan_laju(koneksi, jeda):
    r = laju(koneksi, jeda)
    if r > 3:
        return f"TINGGI (±{r:.1f} permintaan/detik): risiko diblokir server. Disarankan ≤ 3 permintaan/detik."
    if r > 1.5:
        return f"Sedang (±{r:.1f} permintaan/detik)."
    return None


def cek_param(koneksi, jeda):
    if not 1 <= int(koneksi) <= KONEKSI_MAKS:
        raise ValueError(f"koneksi harus 1-{KONEKSI_MAKS}")
    if float(jeda) < JEDA_MIN:
        raise ValueError(f"jeda minimal {JEDA_MIN} detik")


def ekspor_lengkap(conn, target):
    data = rekap.lengkap(conn, target)
    n = database.ekspor_csv(database.baris(conn, target, data), csv_path(target))
    return f"{csv_path(target)} ({n} baris, semua kolom)"


def bangun_lokasi(conn, target, db_path, log=print):
    data = rekap.lengkap(conn, target)
    nj, ng = database.simpan_lokasi(conn, target, data)
    log(f"Tabel ref_jalan: {nj} jalan | ref_gang: {ng} gang/komplek | paket_lokasi: {len(data['lokasi']['per_paket'])} paket fisik")
    if data["lokasi"]["tidak_terbaca"]:
        log(f"Nama jalan TIDAK terbaca pada {len(data['lokasi']['tidak_terbaca'])} paket: {', '.join(data['lokasi']['tidak_terbaca'][:10])}")
    log(f"DB  : {db_path}")
    log(f"CSV : {ekspor_lengkap(conn, target)}")


def _bangun_sebagian(conn, target, db_path, log):
    """Walau berhenti di tengah, detail yang sudah terambil langsung dimasukkan ke tabel Jalan/Gang tahun itu."""
    try:
        if ok_ada_detail(conn, target):
            log("Membangun database Nama Jalan & Nama Gang dari detail yang sudah terambil ...")
            bangun_lokasi(conn, target, db_path, log)
    except Exception as e:          # jangan sampai kegagalan di sini menutupi hasil utama
        log(f"(database Jalan/Gang belum diperbarui: {e!r})")


def ok_ada_detail(conn, target):
    return conn.execute(
        "SELECT 1 FROM sirup_detail d JOIN sirup_paket p ON p.kode_rup=d.kode_rup "
        "WHERE p.id_satker=? AND p.tahun=? AND d.error IS NULL LIMIT 1", (target["id_satker"], target["tahun"])).fetchone() is not None


# ======================= daftar RUP =======================
def run_daftar(conn, target, jeda=1.5, force=False, ekspor=True, log=print, buat_klien=SopanClient, berhenti=None):
    """Ambil seluruh daftar RUP satu satker+tahun. Return kode: 0 ok, 1 gagal, 2 diblokir, 3 tidak valid, 130 dihentikan."""
    cek_param(1, jeda)
    run_id = db.mulai_run(conn, target["id_satker"], target["tahun"])
    log(f"Run #{run_id} - {target['satker_nama']} ({target['klpd_nama']}) tahun {target['tahun']}")
    client = buat_klien(jeda=jeda)
    paket, totals = [], {}
    try:
        for jenis in ("penyedia", "swakelola"):
            if berhenti is not None and berhenti.is_set():
                db.tutup_run(conn, run_id, "failed", len(paket), None, "dihentikan pengguna")
                log("Dihentikan. Data lama tidak diubah.")
                return 130
            hasil, total = sirup.ambil_semua(client, jenis, target, log=log)
            paket += hasil
            totals[jenis] = total
    except DiblokirError as e:
        db.tutup_run(conn, run_id, "failed", len(paket), sum(totals.values()) or None, str(e))
        log(f"[BERHENTI] {e}")
        return 2
    except Exception as e:  # jaringan putus dll: data lama tidak disentuh
        db.tutup_run(conn, run_id, "failed", len(paket), sum(totals.values()) or None, repr(e))
        log(f"[GAGAL] {e!r} - data lama tidak diubah.")
        return 1
    finally:
        client.close()

    sebelumnya = db.jumlah_run_valid_terakhir(conn, target["id_satker"], target["tahun"])
    alasan = db.validasi(paket, totals, sebelumnya, force)
    if alasan:
        db.tutup_run(conn, run_id, "invalid", len(paket), sum(totals.values()), "; ".join(alasan))
        log("[RUN TIDAK VALID - data lama tidak diubah]\n  - " + "\n  - ".join(alasan))
        return 3

    r = db.finalisasi(conn, run_id, paket, target["id_satker"], target["tahun"])
    db.tutup_run(conn, run_id, "success", len(paket), sum(totals.values()))
    total_pagu = sum(p["pagu"] for p in paket)
    log(f"Selesai. {len(paket)} paket ({totals['penyedia']} penyedia + {totals['swakelola']} swakelola), "
        f"total pagu Rp {total_pagu:,.0f}".replace(",", "."))
    if r["baseline"]:
        log("Run pertama untuk tahun ini = data dasar (belum ada pembanding, perubahan belum dicatat).")
    else:
        log(f"Perubahan: {r['revisi']} REVISI RUP (nama sama, kode berganti), {r['baru']} baru, {r['berubah']} berubah, "
            f"{r['hilang']} hilang, {r['muncul_kembali']} muncul kembali")
    if ekspor:
        log(f"CSV : {ekspor_lengkap(conn, target)}")
    return 0


# ======================= detail paket =======================
def run_detail(conn, target, koneksi=1, jeda=1.5, usia_hari=7, semua=False, limit=None, log=print, progres=None,
               berhenti=None, buat_klien=SopanClient, ambil=sirup_detail.ambil_detail, db_path="data/pantau.db"):
    """Ambil detail paket dengan `koneksi` koneksi paralel, tiap koneksi menunggu `jeda` detik antar permintaan.
    Return kode: 0 ok, 2 diblokir, 4 ada yang gagal, 130 dihentikan."""
    cek_param(koneksi, jeda)
    koneksi = int(koneksi)
    berhenti = berhenti or threading.Event()
    antre = db.paket_perlu_detail(conn, target["id_satker"], target["tahun"], semua, usia_hari)
    if limit:
        antre = antre[:limit]
    if not antre:
        umur = f"semua diambil kurang dari {usia_hari} hari lalu dan " if usia_hari else "batas umur dinonaktifkan; "
        log(f"Tidak ada detail yang perlu diambil ulang: {umur}pagu/nama di daftar tidak berubah.")
        log("Catatan: ini hanya membandingkan dengan daftar yang tersimpan. Ambil Data SiRUP dulu untuk tahu perubahan terbaru di situs;")
        log("         gunakan 'ambil ulang semua' untuk memaksa, atau perkecil batas umur.")
        log("Membangun database Nama Jalan & Nama Gang ...")
        bangun_lokasi(conn, target, db_path, log)
        return 0

    peringatan = peringatan_laju(koneksi, jeda)
    menit = len(antre) / laju(koneksi, jeda) / 60
    log(f"{len(antre)} paket akan diambil detailnya: {koneksi} koneksi, jeda {jeda} detik, perkiraan ±{menit:.0f} menit.")
    if peringatan:
        log(f"PERINGATAN laju: {peringatan}")
    run_id = db.mulai_run(conn, target["id_satker"], target["tahun"], sumber="SIRUP_DETAIL")
    if progres:
        progres(0, len(antre), 0, 0)             # total diketahui sejak awal (untuk bilah progres & perkiraan waktu)
    lokal, klien = threading.local(), []

    blok = []

    def kerja(p):
        if berhenti.is_set():
            return p, None, "__batal__"
        if not hasattr(lokal, "k"):
            lokal.k = buat_klien(jeda=jeda)
            klien.append(lokal.k)
        try:
            return p, ambil(lokal.k, p["jenis"], p["kode_rup"]), None
        except DiblokirError as e:
            blok.append(e)
            berhenti.set()                      # semua koneksi berhenti
            return p, None, "__batal__"
        except sirup_detail.DetailError as e:
            return p, None, str(e)
        except Exception as e:                  # jaringan putus pada satu paket: catat, lanjut
            return p, None, repr(e)

    hasil = {"ok": 0, "gagal": [], "selesai": 0}
    mulai = time.monotonic()

    def proses(f):
        """Simpan satu hasil. Dipakai juga untuk hasil yang sudah terambil saat dihentikan (jangan dibuang)."""
        p, d, err = f.result()
        if err == "__batal__":
            return
        if err is None:
            db.simpan_detail(conn, run_id, p["kode_rup"], p["nama_paket"], p["pagu"], d)
            hasil["ok"] += 1
        else:
            db.catat_gagal_detail(conn, p["kode_rup"], err)
            hasil["gagal"].append((p["kode_rup"], err))
        hasil["selesai"] += 1
        n = hasil["selesai"]
        if progres:
            progres(n, len(antre), hasil["ok"], len(hasil["gagal"]))
        if n % 25 == 0 or n == len(antre):
            sisa = (time.monotonic() - mulai) / n * (len(antre) - n) / 60
            log(f"  {n}/{len(antre)}  berhasil {hasil['ok']}, gagal {len(hasil['gagal'])}  (sisa ±{sisa:.0f} menit)")

    ex = ThreadPoolExecutor(max_workers=koneksi)
    futures = [ex.submit(kerja, p) for p in antre]
    sudah = set()
    try:
        for f in as_completed(futures):
            proses(f)
            sudah.add(f)
            if berhenti.is_set():
                break
    except KeyboardInterrupt:
        berhenti.set()
    finally:
        berhenti.set() if blok else None
        for f in futures:
            f.cancel()
        ex.shutdown(wait=True)                   # tunggu yang sedang berjalan selesai
        for f in futures:                        # simpan yang sudah terlanjur terambil
            if f not in sudah and not f.cancelled():
                proses(f)
        for k in klien:
            k.close()
    ok, gagal, selesai, diblokir = hasil["ok"], hasil["gagal"], hasil["selesai"], (blok[0] if blok else None)

    if diblokir:
        db.tutup_run(conn, run_id, "failed", ok, len(antre), str(diblokir))
        log(f"[BERHENTI] {diblokir} - semua koneksi dihentikan; yang sudah diambil ({ok}) tetap tersimpan.")
        _bangun_sebagian(conn, target, db_path, log)
        return 2
    if berhenti.is_set() and selesai < len(antre):
        db.tutup_run(conn, run_id, "failed", ok, len(antre), "dihentikan pengguna")
        log(f"Dihentikan. {ok} detail tersimpan; jalankan lagi untuk melanjutkan.")
        _bangun_sebagian(conn, target, db_path, log)
        return 130
    db.tutup_run(conn, run_id, "success" if not gagal else "invalid", ok, len(antre),
                 "; ".join(f"{k}: {m}" for k, m in gagal[:20]) or None)
    log(f"Selesai. Detail berhasil: {ok}, gagal: {len(gagal)}")
    for k, m in gagal[:10]:
        log(f"  gagal {k}: {m}")
    log("Membangun database Nama Jalan & Nama Gang ...")
    bangun_lokasi(conn, target, db_path, log)
    return 0 if not gagal else 4


# ======================= satu proses: daftar RUP -> detail paket -> database =======================
def run_semua(conn, target, koneksi=1, jeda=1.5, usia_hari=7, semua=False, limit=None, force=False, log=print,
              progres=None, tahap=None, berhenti=None, buat_klien=SopanClient, ambil=sirup_detail.ambil_detail,
              db_path="data/pantau.db"):
    """Tahap 1: ambil daftar RUP (menangkap paket baru / revisi RUP). Tahap 2: ambil detail paket yang belum ada,
    berubah, atau sudah lewat batas umur. Lalu bangun database Jalan/Gang + CSV. Tahap 2 hanya jalan bila tahap 1 berhasil,
    supaya detail tidak diambil dari daftar yang basi atau tidak valid."""
    cek_param(koneksi, jeda)
    berhenti = berhenti or threading.Event()
    if tahap:
        tahap(1, 2, "Daftar RUP")
    log("=== TAHAP 1/2: daftar RUP ===")
    kode = run_daftar(conn, target, jeda=jeda, force=force, ekspor=False, log=log, buat_klien=buat_klien, berhenti=berhenti)
    if kode != 0:
        log(f"Tahap 2 (detail) TIDAK dijalankan karena tahap 1 tidak berhasil (kode {kode}).")
        return kode
    if berhenti.is_set():
        log("Dihentikan sebelum tahap 2.")
        return 130
    if tahap:
        tahap(2, 2, "Detail paket")
    log("=== TAHAP 2/2: detail paket ===")
    return run_detail(conn, target, koneksi=koneksi, jeda=jeda, usia_hari=usia_hari, semua=semua, limit=limit, log=log,
                      progres=progres, berhenti=berhenti, buat_klien=buat_klien, ambil=ambil, db_path=db_path)
