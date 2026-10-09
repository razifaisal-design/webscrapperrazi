"""Pekerjaan pengambilan data - dipakai bersama oleh terminal (cli.py) dan dashboard (web.py).

Sopan santun ke server: tiap koneksi punya jeda sendiri antar permintaan, dan SEMUA koneksi berhenti seketika
bila server menolak (403/429)."""
import csv
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import konfig
from .core import database, db, rekap
from .core.http import DiblokirError, SopanClient
from .sources import direktori, sirup, sirup_detail, spse

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


# ======================= idSatker per tahun =======================
def tentukan_id_satker(conn, target, client, log=print):
    """Cari idSatker yang benar untuk tahun ini. SiRUP bisa memakai idSatker BERBEDA tiap tahun (mis. 2021 = 69427,
    2022+ = 173394); idSatker yang salah mengembalikan 0 paket tanpa error.
    Bila sudah ada data untuk id itu pada tahun itu: dipercaya. Bila belum: diuji id dari config lalu id lain yang dikenal.
    -> (idSatker | None, diganti)"""
    asal = int(target["id_satker"])
    if conn.execute("SELECT 1 FROM sirup_paket WHERE id_satker=? AND tahun=? LIMIT 1", (asal, target["tahun"])).fetchone():
        return asal, False
    urutan = [asal] + [i for i in target.get("id_satker_semua", []) if i != asal]
    if target.get("klpd_id"):                                   # satker dikenali lewat NAMA: tanya direktori SiRUP untuk tahun ini
        try:
            cid, kembar = direktori.id_untuk_tahun(direktori.daftar_satker(client, target["klpd_id"], target["tahun"]), target["satker_nama"])
            if cid:
                urutan = [cid] + [i for i in urutan if i != cid]
                if kembar:
                    log(f"Catatan: ada satker lain dengan nama yang sama di SiRUP tahun {target['tahun']} (idSatker {', '.join(map(str, kembar))}); dipakai yang paketnya terbanyak ({cid}).")
            else:
                log(f"Nama satker '{target['satker_nama']}' tidak ditemukan di direktori SiRUP tahun {target['tahun']}; mencoba idSatker yang dikenal.")
        except DiblokirError:
            raise
        except Exception as e:
            log(f"(direktori satker tidak bisa dibaca: {e!r}; mencoba idSatker yang dikenal)")
    for cid in urutan:
        total = sum(sirup.total_paket(client, jenis, dict(target, id_satker=cid)) for jenis in ("penyedia", "swakelola"))
        if total > 0:
            if cid != asal:
                log(f"idSatker {asal} tidak punya paket untuk tahun {target['tahun']}, tetapi idSatker {cid} punya {total} paket -> memakai {cid}.")
            return cid, cid != asal
        log(f"idSatker {cid}: 0 paket untuk tahun {target['tahun']}.")
    return None, False


def _pesan_id_tidak_ketemu(target):
    ids = ", ".join(str(i) for i in [target["id_satker"]] + [x for x in target.get("id_satker_semua", []) if x != target["id_satker"]])
    return (f"Tidak ada paket untuk tahun {target['tahun']} pada idSatker {ids}. Tahun ini kemungkinan memakai idSatker lain: "
            f"cari di alamat SiRUP (sirup.inaproc.id/sirup/home/penyediaSatker?idSatker=NNNN) lalu isi kolom 'ID satker' "
            f"(dashboard) atau opsi --id-satker.")


def _selesaikan_target(conn, target, jeda, buat_klien, log):
    """-> (target dengan idSatker yang benar | None, kode_keluar)."""
    client = buat_klien(jeda=jeda)
    try:
        sat, _ = tentukan_id_satker(conn, target, client, log)
    except DiblokirError as e:
        log(f"[BERHENTI] {e}")
        return None, 2
    except Exception as e:           # respons tak terduga / jaringan: catat jelas, jangan gagal tanpa jejak
        run_id = db.mulai_run(conn, target["id_satker"], target["tahun"])
        db.tutup_run(conn, run_id, "failed", 0, None, f"gagal menentukan idSatker: {e!r}")
        log(f"[GAGAL] Tidak bisa memeriksa idSatker untuk tahun {target['tahun']}: {e!r}")
        return None, 1
    finally:
        client.close()
    if sat is None:
        pesan = _pesan_id_tidak_ketemu(target)
        run_id = db.mulai_run(conn, target["id_satker"], target["tahun"])
        db.tutup_run(conn, run_id, "invalid", 0, 0, pesan)
        log("[TIDAK ADA DATA] " + pesan)
        return None, 3
    return dict(target, id_satker=sat), 0


def _catat_id_satker(target, log):
    """Setelah pengambilan BERHASIL: simpan idSatker tahun ini ke config bila berbeda dari bawaan."""
    try:
        if konfig.simpan_id_satker(target["tahun"], target["id_satker"], target.get("nama")):
            log(f"Config diperbarui: tahun {target['tahun']} memakai idSatker {target['id_satker']} (config/targets.json).")
    except Exception as e:                                  # catatan config tidak boleh menggagalkan pengambilan data
        log(f"(idSatker belum tercatat di config: {e!r})")


# ======================= daftar RUP =======================
def run_daftar(conn, target, jeda=1.5, force=False, ekspor=True, log=print, buat_klien=SopanClient, berhenti=None,
               resolusi=True):
    """Ambil seluruh daftar RUP satu satker+tahun. Return kode: 0 ok, 1 gagal, 2 diblokir, 3 tidak valid/tidak ada data,
    130 dihentikan. `resolusi`: tentukan dulu idSatker yang benar untuk tahun itu (lihat tentukan_id_satker)."""
    cek_param(1, jeda)
    if resolusi:
        target, kode = _selesaikan_target(conn, target, jeda, buat_klien, log)
        if target is None:
            return kode
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
    _catat_id_satker(target, log)
    total_pagu = sum(p["pagu"] for p in paket)
    log(f"Selesai. {len(paket)} paket ({totals['penyedia']} penyedia + {totals['swakelola']} swakelola), "
        f"total pagu Rp {total_pagu:,.0f}".replace(",", "."))
    if r["baseline"]:
        log("Run pertama untuk tahun ini = data dasar (belum ada pembanding, perubahan belum dicatat).")
    else:
        log(f"Perubahan: {r['revisi']} REVISI RUP (nama sama, kode berganti), {r['baru']} baru, {r['berubah']} berubah, "
            f"{r['hilang']} hilang, {r['muncul_kembali']} muncul kembali")
        if r.get("revisi_lintas"):
            log(f"             + {r['revisi_lintas']} revisi RUP yang terpotong antar pengambilan (RUP lama hilang di pengambilan sebelumnya) kini dipasangkan.")
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
    target, kode = _selesaikan_target(conn, target, jeda, buat_klien, log)     # idSatker yang benar utk tahun ini, dipakai kedua tahap
    if target is None:
        return kode
    if tahap:
        tahap(1, 2, "Daftar RUP")
    log("=== TAHAP 1/2: daftar RUP ===")
    kode = run_daftar(conn, target, jeda=jeda, force=force, ekspor=False, log=log, buat_klien=buat_klien, berhenti=berhenti,
                      resolusi=False)
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


# ======================= SPSE (LPSE): daftar paket =======================
def csv_spse_path(lpse, jenis, tahun="semua"):
    return ROOT / "data" / f"spse_{lpse}_{jenis}_{tahun}.csv"


def run_spse(conn, jenis="nontender", lpse="pontianak", tahun="semua", jeda=1.5, force=False, ekspor=True, log=print,
             buat_klien=SopanClient, berhenti=None, progres=None):
    """Ambil DAFTAR paket SPSE (tanpa detail) untuk satu tahun atau semua tahun di pilihan SPSE; 100 baris per halaman.
    Return kode: 0 ok, 1 ada tahun gagal, 2 diblokir, 3 tahun tidak tersedia, 130 dihentikan."""
    cek_param(1, jeda)
    sumber = db.sumber_spse(jenis)
    client = buat_klien(jeda=jeda)
    kode_akhir, ringkas_semua = 0, []
    try:
        sesi = spse.Sesi(client, lpse, jenis).buka()
        if tahun in (None, "semua"):
            daftar = list(sesi.tahun_tersedia)
        elif int(tahun) in sesi.tahun_tersedia:
            daftar = [int(tahun)]
        else:
            log(f"[TIDAK ADA] Tahun {tahun} tidak ada di pilihan SPSE {lpse}. Tahun yang tersedia: {', '.join(map(str, sesi.tahun_tersedia))}.")
            return 3
        log(f"SPSE {lpse} - {jenis}: {len(daftar)} tahun akan diambil ({', '.join(map(str, daftar))}), 100 baris per halaman.")
        for i, th in enumerate(daftar, 1):
            if berhenti is not None and berhenti.is_set():
                log("Dihentikan.")
                return 130
            run_id = db.mulai_run(conn, 0, th, sumber=sumber)
            log(f"=== Tahun {th} ({i}/{len(daftar)}) - Run #{run_id} ===")
            try:
                baris = [spse.parse_baris(r, lpse, jenis, th) for r in spse.rayap_tahun(sesi, th, log=log, berhenti=berhenti)]
            except spse.Dihentikan:
                db.tutup_run(conn, run_id, "failed", 0, None, "dihentikan pengguna")
                log("Dihentikan. Data lama tidak diubah.")
                return 130
            except DiblokirError as e:
                db.tutup_run(conn, run_id, "failed", 0, None, str(e))
                log(f"[BERHENTI] {e}")
                return 2
            except Exception as e:                       # satu tahun gagal tidak membatalkan tahun lain
                db.tutup_run(conn, run_id, "failed", 0, None, repr(e))
                log(f"[GAGAL] tahun {th}: {e!r} - data lama tidak diubah.")
                kode_akhir = 1
                continue
            alasan = db.validasi_spse(baris, db.jumlah_run_valid_spse(conn, jenis, th), force)
            if alasan:
                db.tutup_run(conn, run_id, "invalid", len(baris), None, "; ".join(alasan))
                log(f"[TIDAK VALID - data lama tidak diubah] tahun {th}: " + "; ".join(alasan))
                kode_akhir = 1
                continue
            r = db.finalisasi_spse(conn, run_id, baris, lpse, jenis, th)
            db.tutup_run(conn, run_id, "success", len(baris), None)
            ringkas_semua.append((th, len(baris)))
            log(f"Tahun {th}: {len(baris)} paket tersimpan" + (" (data dasar)." if r["baseline"] else
                f" - {r['baru']} baru, {r['berubah']} berubah, {r['hilang']} hilang, {r['muncul_kembali']} muncul kembali."))
            if progres:
                progres(i, len(daftar), len(ringkas_semua), i - len(ringkas_semua))
    except DiblokirError as e:
        log(f"[BERHENTI] {e}")
        return 2
    except Exception as e:
        log(f"[GAGAL] SPSE {lpse}: {e!r}")
        return 1
    finally:
        client.close()
    if ringkas_semua:
        log(f"Selesai. {sum(n for _, n in ringkas_semua)} paket dari {len(ringkas_semua)} tahun.")
    if ekspor:
        label = "semua" if tahun in (None, "semua") else int(tahun)
        n = database.ekspor_spse_csv(conn, lpse, jenis, csv_spse_path(lpse, jenis, label), label)
        log(f"CSV : {csv_spse_path(lpse, jenis, label)} ({n} baris)")
    return kode_akhir


def _ambil_detail_spse(client, lpse, jenis, kode, rinci):
    """Satu paket: Pengumuman dulu; bila `rinci(satker)` benar, lanjut Pemenang, Pemenang Berkontrak, Jadwal, dan
    riwayat perubahan tiap tahap yang pernah diubah. Return (detail, jadwal|None)."""
    pengumuman = spse.parse_pengumuman(client.get_text(spse.url_tab(lpse, jenis, kode, "pengumuman")))
    if pengumuman["kode_paket"] != kode:
        raise spse.SpseError(f"kode di halaman ({pengumuman['kode_paket']}) tidak sama dengan yang diminta")
    kosong = {"info": {}, "pemenang": []}
    if not rinci(pengumuman["satker"]):
        return spse.ringkas_detail(pengumuman, kosong, kosong), None
    pemenang = spse.parse_pemenang(client.get_text(spse.url_tab(lpse, jenis, kode, "pemenang")))
    kontrak = spse.parse_pemenang(client.get_text(spse.url_tab(lpse, jenis, kode, "kontrak")))
    jadwal = spse.parse_jadwal(client.get_text(spse.url_jadwal(lpse, jenis, kode)))
    for t in jadwal:
        t["riwayat"] = spse.parse_riwayat_jadwal(client.get_text(t["url_riwayat"])) if t["jumlah_perubahan"] and t["url_riwayat"] else []
    return spse.ringkas_detail(pengumuman, pemenang, kontrak), jadwal


def run_spse_detail(conn, jenis="nontender", lpse="pontianak", tahun=2026, jeda=1.5, usia_hari=7, semua=False, limit=None,
                    satker=None, koneksi=1, log=print, buat_klien=SopanClient, berhenti=None, progres=None):
    """Ambil detail paket SPSE dengan `koneksi` koneksi paralel (tiap koneksi menunggu `jeda` detik antar permintaan).
    Tiap paket: tab Pengumuman (tanpa Syarat Kualifikasi). Untuk paket milik `satker` (kosong = semua paket): tab Pemenang
    (semua kolom), Pemenang Berkontrak (cek nilai kontrak sudah diisi PPK), Jadwal beserta riwayat perubahan tiap tahap.
    Hanya thread utama yang menulis ke database. Return kode: 0 ok, 2 diblokir, 4 ada yang gagal, 130 dihentikan."""
    cek_param(koneksi, jeda)
    koneksi = int(koneksi)
    berhenti = berhenti or threading.Event()
    status = db.status_detail_spse(conn, lpse, jenis, int(tahun), usia_hari, semua, satker=satker)
    antre = [k for k, a in status if a]
    # pemeriksaan awal: mana yang sudah lengkap, mana yang belum, dan kenapa
    rincian = {}
    for _, a in status:
        rincian[a] = rincian.get(a, 0) + 1
    log(f"Pemeriksaan awal {tahun}: {len(status)} paket di daftar - sudah lengkap {rincian.get(None, 0)}, perlu diambil {len(antre)}"
        + ("" if not antre else " (" + ", ".join(f"{n} {db.ALASAN_DETAIL_SPSE[a]}" for a, n in rincian.items() if a) + ")."))
    if limit:
        antre = antre[:limit]
    if not antre:
        log(f"Tidak ada detail SPSE yang perlu diambil untuk {tahun}: semuanya sudah lengkap. Centang 'Paksa ambil ulang semua detail' untuk mengambil ulang.")
        return 0
    sasaran = db.norm_satker(satker) if satker else None
    rinci = (lambda sat: sasaran is None or db.norm_satker(sat) == sasaran)             # noqa: E731
    log(f"SPSE {lpse} - {jenis} {tahun}: {len(antre)} paket" + (f"; rincian lengkap (pemenang, kontrak, jadwal) hanya untuk {satker}" if sasaran else "") +
        f"; {koneksi} koneksi, jeda {jeda:g} detik.")
    if peringatan_laju(koneksi, jeda):
        log(f"PERINGATAN laju: {peringatan_laju(koneksi, jeda)}")
    if progres:
        progres(0, len(antre), 0, 0)
    lokal, klien, blok = threading.local(), [], []

    def kerja(kode):
        if berhenti.is_set():
            return kode, None, None, "__batal__"
        if not hasattr(lokal, "k"):
            lokal.k = buat_klien(jeda=jeda)
            klien.append(lokal.k)
        try:
            detail, jadwal = _ambil_detail_spse(lokal.k, lpse, jenis, kode, rinci)
            return kode, detail, jadwal, None
        except DiblokirError as e:
            blok.append(e)
            berhenti.set()                      # semua koneksi berhenti
            return kode, None, None, "__batal__"
        except Exception as e:                  # satu paket gagal tidak menghentikan yang lain
            return kode, None, None, repr(e)

    hasil = {"ok": 0, "gagal": 0, "selesai": 0}

    def proses(f):
        kode, detail, jadwal, err = f.result()
        if err == "__batal__":
            return
        hasil["selesai"] += 1
        n = hasil["selesai"]
        if err is None:
            db.simpan_detail_spse(conn, lpse, jenis, kode, detail, jadwal=jadwal)
            hasil["ok"] += 1
            if jadwal is None:
                log(f"[{n}/{len(antre)}] {kode} {detail['satker'][:40]} (instansi lain - tanpa rincian)")
            else:
                log(f"[{n}/{len(antre)}] {kode} {detail['satker'][:30]} | pemenang: {detail['pemenang_nama'] or '-'} | kontrak: "
                    f"{'Rp {:,.0f}'.format(detail['nilai_kontrak']).replace(',', '.') if detail['kontrak_terisi'] else 'belum diisi'} | jadwal {len(jadwal)} tahap")
        else:
            db.simpan_detail_spse(conn, lpse, jenis, kode, None, err)
            hasil["gagal"] += 1
            log(f"[{n}/{len(antre)}] {kode} GAGAL: {err}")
        if progres:
            progres(n, len(antre), hasil["ok"], hasil["gagal"])

    ex = ThreadPoolExecutor(max_workers=koneksi)
    futures = [ex.submit(kerja, kode) for kode in antre]
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
        for f in futures:
            f.cancel()
        ex.shutdown(wait=True)                   # tunggu yang sedang berjalan selesai
        for f in futures:                        # simpan yang sudah terlanjur terambil
            if f not in sudah and not f.cancelled():
                proses(f)
        for k in klien:
            k.close()
    if blok:
        log(f"[BERHENTI] {blok[0]} - semua koneksi dihentikan; yang sudah diambil ({hasil['ok']}) tetap tersimpan.")
        return 2
    if berhenti.is_set() and hasil["selesai"] < len(antre):
        log(f"Dihentikan. {hasil['ok']} paket tersimpan; jalankan lagi untuk melanjutkan.")
        return 130
    log(f"Selesai. {hasil['ok']} paket berhasil, {hasil['gagal']} gagal.")
    return 4 if hasil["gagal"] else 0


def run_spse_semua(conn, jenis="nontender", lpse="pontianak", tahun=2026, jeda=1.5, usia_hari=7, semua=False, force=False,
                   limit=None, satker=None, koneksi=1, log=print, progres=None, tahap=None, berhenti=None, buat_klien=SopanClient):
    """SATU PROSES SPSE: tahap 1 daftar paket (100 per halaman, selalu 1 koneksi), tahap 2 detail paket (`koneksi` paralel).
    Tahap 2 hanya jalan bila tahap 1 berhasil."""
    cek_param(koneksi, jeda)
    berhenti = berhenti or threading.Event()
    if tahap:
        tahap(1, 2, "Daftar paket SPSE")
    log("=== TAHAP 1/2: daftar paket SPSE ===")
    kode = run_spse(conn, jenis, lpse, tahun, jeda=jeda, force=force, ekspor=True, log=log, buat_klien=buat_klien, berhenti=berhenti)
    if kode != 0:
        log(f"Tahap 2 (detail) TIDAK dijalankan karena tahap 1 tidak berhasil (kode {kode}).")
        return kode
    if berhenti.is_set():
        return 130
    if tahap:
        tahap(2, 2, "Detail paket SPSE")
    log("=== TAHAP 2/2: detail paket SPSE ===")
    tahun_list = [t for (t,) in conn.execute("SELECT DISTINCT tahun FROM spse_paket WHERE lpse=? AND jenis=? ORDER BY tahun DESC", (lpse, jenis))] \
        if tahun in (None, "semua") else [int(tahun)]
    kode_akhir = 0
    for th in tahun_list:
        k = run_spse_detail(conn, jenis, lpse, th, jeda=jeda, usia_hari=usia_hari, semua=semua, limit=limit, satker=satker, koneksi=koneksi, log=log,
                            buat_klien=buat_klien, berhenti=berhenti, progres=progres)
        if k in (2, 130):
            return k
        kode_akhir = kode_akhir or k
    return kode_akhir


# ======================= satker dikenali lewat NAMA =======================
def _klpd_bawaan(klpd_nama=None, buat_klien=SopanClient, tahun=None):
    """(klpd_id, klpd_nama resmi, tahun) untuk K/L/PD yang dituju; bawaan = K/L/PD target bawaan di config."""
    cfg_nama, dasar = konfig.muat_target(None)
    klpd_nama = klpd_nama or dasar.get("klpd_nama")
    tahun = int(tahun or dasar["tahun"])
    if dasar.get("klpd_id") and (not klpd_nama or direktori.norm(klpd_nama) == direktori.norm(dasar.get("klpd_nama"))):
        return dasar["klpd_id"], dasar["klpd_nama"], tahun
    client = buat_klien(jeda=1.0)
    try:
        k = direktori.cari_klpd(client, klpd_nama, tahun)
    finally:
        client.close()
    if not k:
        raise ValueError(f"K/L/PD '{klpd_nama}' tidak ditemukan di SiRUP tahun {tahun}.")
    return k["id"], k["nama"], tahun


def cari_satker_nama(nama, klpd_nama=None, tahun=None, buat_klien=SopanClient):
    """Cari satker lewat NAMA di direktori SiRUP -> {klpd, tahun, kandidat:[{nama, paket, cocok}]} (tanpa idSatker untuk pengguna)."""
    klpd_id, klpd_resmi, tahun = _klpd_bawaan(klpd_nama, buat_klien, tahun)
    client = buat_klien(jeda=1.0)
    try:
        daftar = direktori.daftar_satker(client, klpd_id, tahun)
    finally:
        client.close()
    return {"klpd": klpd_resmi, "tahun": tahun, "kandidat": [{"nama": k["nama"], "paket": k["paket"], "cocok": k["cocok"]} for k in direktori.cari_nama(daftar, nama)]}


def tambah_satker_nama(nama, klpd_nama=None, tahun=None, buat_klien=SopanClient):
    """Daftarkan satker (dikenali lewat nama) ke config. Nama harus cocok persis (setelah dinormalkan) atau hanya satu kandidat.
    -> (kunci_target, nama satker resmi). ValueError bila tidak ada / lebih dari satu kandidat."""
    klpd_id, klpd_resmi, tahun = _klpd_bawaan(klpd_nama, buat_klien, tahun)
    client = buat_klien(jeda=1.0)
    try:
        daftar = direktori.daftar_satker(client, klpd_id, tahun)
    finally:
        client.close()
    kand = direktori.cari_nama(daftar, nama)
    persis = [k for k in kand if k["cocok"] == "persis"]
    if len({direktori.norm(k["nama"]) for k in persis}) == 1:
        pilih = max(persis, key=lambda k: k["paket"])
    elif len(kand) == 1:
        pilih = kand[0]
    elif not kand:
        raise ValueError(f"Tidak ada satker bernama mirip '{nama}' di {klpd_resmi} (tahun {tahun}).")
    else:
        raise ValueError(f"Nama '{nama}' cocok dengan {len(kand)} satker: " + "; ".join(k["nama"] for k in kand[:6]) + ". Tulis nama yang lebih lengkap.")
    kunci = konfig.tambah_target(pilih["nama"], klpd_resmi, klpd_id, pilih["id"], None, tahun)
    return kunci, pilih["nama"]


# ======================= periksa RUP langsung ke SiRUP (lewat kode RUP) =======================
def kode_rup_tak_berpasangan(conn, tahun_list=None, satker=None):
    """Kode RUP yang disebut paket SPSE tetapi tidak ada di daftar SiRUP satkernya (status 'Tidak ada di daftar SiRUP'). Dihitung dari
    perbandingan yang sama dengan halaman Perbandingan."""
    from .core import banding
    nama, dasar = konfig.muat_target(None)
    lpse = (dasar.get("spse") or {}).get("lpse", "pontianak")
    if tahun_list is None:
        tahun_list = [t for (t,) in conn.execute("SELECT DISTINCT tahun FROM spse_paket WHERE lpse=? AND jenis='nontender' ORDER BY tahun", (lpse,))]
    h = banding.hitung(conn, lpse, "nontender", tahun_list, konfig.satker_sirup(), satker)
    kode = []
    for b in h["baris"]:
        if b["status"] == "SiRUP satker ini belum diambil":          # satker tanpa data SiRUP: tidak ada yang dibandingkan, jangan buka RUP-nya
            continue
        kode += [k.strip() for k in (b.get("kode_rup_spse") or "").split(",") if k.strip()]
    # yang perlu dibuka: kode RUP yang disebut SPSE tetapi tidak ada sama sekali di daftar SiRUP (aktif maupun tidak aktif);
    # termasuk RUP tambahan pada paket yang sebagian RUP-nya ada di daftar, dan paket yang cocok hanya lewat nama
    ada = {k for (k,) in conn.execute("SELECT kode_rup FROM sirup_paket")}
    nama_cocok = {k.strip() for b in h["baris"] if str(b.get("kecocokan") or "").startswith("Nama paket + instansi") and b["status"] != "SiRUP satker ini belum diambil"
                  for k in (b.get("kode_rup_spse") or "").split(",") if k.strip()}
    kode = [k for k in kode if k not in ada or k in nama_cocok]
    return list(dict.fromkeys(kode))


def run_periksa_rup(conn, kodes, koneksi=1, jeda=1.5, ulang=False, log=print, buat_klien=SopanClient, berhenti=None, progres=None):
    """Buka halaman detail RUP (sirup.inaproc.id/.../detailPaketPenyediaPublic2017/{kode}) untuk tiap kode di `kodes` yang belum
    pernah dicek (atau semuanya bila `ulang`). Tujuannya: paket yang tayang di SPSE seharusnya ada di SiRUP; di sini dibuktikan
    apakah RUP-nya memang ada walau tidak tampil di daftar satker. Return kode: 0 ok, 2 diblokir, 4 ada yang gagal, 130 dihentikan."""
    import httpx
    cek_param(koneksi, jeda)
    koneksi = int(koneksi)
    berhenti = berhenti or threading.Event()
    sudah = {k for (k,) in conn.execute("SELECT kode_rup FROM sirup_luar_daftar WHERE error IS NULL")}
    antre = [k for k in kodes if ulang or k not in sudah]
    log(f"Periksa RUP ke SiRUP: {len(kodes)} kode RUP, {len(antre)} perlu dibuka" + ("" if ulang else f" ({len(kodes) - len(antre)} sudah pernah dicek)") +
        f"; {koneksi} koneksi, jeda {jeda:g} detik.")
    if not antre:
        return 0
    if progres:
        progres(0, len(antre), 0, 0)
    lokal, klien, blok = threading.local(), [], []

    def kerja(kode):
        if berhenti.is_set():
            return kode, "batal", None
        if not hasattr(lokal, "k"):
            lokal.k = buat_klien(jeda=jeda)
            klien.append(lokal.k)
        try:
            return kode, "ada", sirup_detail.ambil_detail(lokal.k, "penyedia", kode)
        except DiblokirError as e:
            blok.append(e)
            berhenti.set()
            return kode, "batal", None
        except httpx.HTTPStatusError as e:                  # SiRUP membalas galat untuk kode yang tidak ada
            return kode, "tidak ada", f"HTTP {e.response.status_code}"
        except sirup_detail.DetailError as e:
            return kode, "tidak ada", str(e)
        except Exception as e:
            return kode, "galat", repr(e)

    hasil = {"ada": 0, "tidak ada": 0, "galat": 0, "selesai": 0}

    def proses(f):
        kode, st, d = f.result()
        if st == "batal":
            return
        link = sirup_detail.URL_DETAIL["penyedia"].format(kode=kode)
        if st == "ada":
            db.simpan_rup_luar_daftar(conn, kode, d, link=link)
            log(f"[{hasil['selesai'] + 1}/{len(antre)}] {kode} ADA di SiRUP: {d['satuan_kerja'][:34]} | {d['nama_paket'][:60]}")
        elif st == "tidak ada":
            db.simpan_rup_luar_daftar(conn, kode, None, ditemukan=0, error=None, link=link)
            log(f"[{hasil['selesai'] + 1}/{len(antre)}] {kode} TIDAK ADA di SiRUP ({d})")
        else:
            db.simpan_rup_luar_daftar(conn, kode, None, ditemukan=None, error=d, link=link)
            log(f"[{hasil['selesai'] + 1}/{len(antre)}] {kode} GALAT: {d}")
        hasil[st] += 1
        hasil["selesai"] += 1
        if progres:
            progres(hasil["selesai"], len(antre), hasil["ada"] + hasil["tidak ada"], hasil["galat"])

    ex = ThreadPoolExecutor(max_workers=koneksi)
    futures = [ex.submit(kerja, k) for k in antre]
    terproses = set()
    try:
        for f in as_completed(futures):
            proses(f)
            terproses.add(f)
            if berhenti.is_set():
                break
    finally:
        for f in futures:
            f.cancel()
        ex.shutdown(wait=True)
        for f in futures:
            if f not in terproses and not f.cancelled():
                proses(f)
        for k in klien:
            k.close()
    if blok:
        log(f"[BERHENTI] {blok[0]} - yang sudah dicek ({hasil['selesai']}) tetap tersimpan.")
        return 2
    if berhenti.is_set() and hasil["selesai"] < len(antre):
        log(f"Dihentikan. {hasil['selesai']} kode tersimpan; jalankan lagi untuk melanjutkan.")
        return 130
    log(f"Selesai. Ada di SiRUP: {hasil['ada']}, tidak ada: {hasil['tidak ada']}, galat: {hasil['galat']}.")
    return 4 if hasil["galat"] else 0


# ======================= satu perintah: ambil semua data -> periksa RUP -> ekspor publik =======================
def run_perbarui(conn, db_path, tahun=None, koneksi=1, jeda=1.5, usia_hari=7, rinci="semua", satker=None, periksa=True, ekspor=True,
                 keluar=None, unggah=False, sinkron=None, log=print, berhenti=None):
    """Alur lengkap seperti yang dilakukan di dashboard, lalu salinan publik:
      1. SiRUP: daftar RUP + detail untuk tiap satker terdaftar (atau hanya `satker`);
      2. SPSE Non-Tender: daftar + detail (`rinci` = cakupan rincian: 'semua' | 'tidak' | nama satker);
      3. periksa langsung ke SiRUP kode RUP yang tidak ada di daftar satker;
      4. ekspor salinan publik (hanya baca) ke `keluar`;
      5. (opsional, `unggah`) unggah salinan itu ke Cloudflare dengan Wrangler;
      6. cerminkan database lokal ke Supabase (cadangan): `sinkron` None = otomatis bila SUPABASE_DB_URL ada di .env, True = wajib, False = lewati.
    Diblokir (kode 2) menghentikan semuanya; kegagalan lain dicatat dan alur dilanjutkan. Return kode terburuk (0 bila semua baik)."""
    cek_param(koneksi, jeda)
    berhenti = berhenti or threading.Event()
    hasil = {}

    def catat(nama, kode):
        hasil[nama] = kode
        log(f"--- {nama}: {'OK' if kode == 0 else f'kode {kode}'}")
        return kode in (2, 130)                      # diblokir / dihentikan: berhenti total

    daftar = konfig.daftar_target()
    if satker:
        daftar = [t for t in daftar if direktori.norm(t["satker_nama"]) == direktori.norm(satker) or t["nama"] == satker]
        if not daftar:
            raise ValueError(f"satker '{satker}' belum terdaftar. Tambahkan lewat dashboard (Tambah satker / dinas).")
    henti = False
    for t in daftar:
        if henti or berhenti.is_set():
            break
        _, target = konfig.muat_target(t["nama"], tahun)
        log(f"=== SiRUP: {t['satker_nama']} (TA {target['tahun']}) ===")
        henti = catat(f"SiRUP {t['satker_nama']}", run_semua(conn, target, koneksi=koneksi, jeda=jeda, usia_hari=usia_hari, log=log,
                                                             berhenti=berhenti, db_path=db_path))
    _, dasar = konfig.muat_target(None, tahun)
    lpse = (dasar.get("spse") or {}).get("lpse", "pontianak")
    if not henti and not berhenti.is_set():
        cakupan = None if str(rinci).lower() == "semua" else "__tidak" if str(rinci).lower() == "tidak" else rinci
        log(f"=== SPSE Non-Tender {lpse} (TA {dasar['tahun']}) ===")
        henti = catat("SPSE Non-Tender", run_spse_semua(conn, "nontender", lpse, dasar["tahun"], jeda=jeda, usia_hari=usia_hari, satker=cakupan,
                                                         koneksi=koneksi, log=log, berhenti=berhenti))
    if periksa and not henti and not berhenti.is_set():
        kodes = kode_rup_tak_berpasangan(conn, [int(dasar["tahun"])])
        log(f"=== Periksa RUP ke SiRUP: {len(kodes)} kode RUP tidak ada di daftar satker ===")
        henti = catat("Periksa RUP", run_periksa_rup(conn, kodes, koneksi=koneksi, jeda=jeda, log=log, berhenti=berhenti))
    if not (2 in hasil.values()) and not berhenti.is_set() and sinkron is not False:
        from . import sinkron as _sinkron
        # otomatis HANYA untuk database utama proyek: database lain (mis. uji coba) tidak boleh menimpa cermin di Supabase
        utama = Path(db_path).resolve() == db.DB_DEFAULT.resolve()
        if sinkron is True or (utama and _sinkron.url_db()):
            log("=== Cadangan ke Supabase ===")
            try:
                jumlah = _sinkron.sinkron(db_path, log=log)
                log(f"Supabase dicerminkan: {sum(jumlah.values())} baris di {len(jumlah)} tabel.")
                hasil["Cadangan Supabase"] = 0
            except _sinkron.SinkronError as e:
                log(f"[TIDAK TERCADANG] {e}")
                hasil["Cadangan Supabase"] = 1
        else:
            log("(Cadangan Supabase dilewati: SUPABASE_DB_URL belum diisi di .env)")
    if ekspor and not berhenti.is_set() and hasil.get("SPSE Non-Tender", 0) != 2:
        log("=== Ekspor salinan publik ===")
        try:
            from . import ekspor_publik
            from . import sinkron as _sk
            kfg = ekspor_publik.muat_konfig_publik()
            url = _sk.url_db()
            utama = Path(db_path).resolve() == db.DB_DEFAULT.resolve()
            target_keluar = keluar or (konfig.ROOT / "publik")
            if kfg and url and utama:                       # web publik membaca data langsung dari Supabase; folder publik/ hanya halaman kecil
                r = ekspor_publik.terbitkan(db_path, target_keluar, url, kfg, log=log)
                log(f"Data diterbitkan ke Supabase ({r['berkas']} berkas); halaman publik: {r['ukuran_mb']} MB di {target_keluar}")
            else:
                r = ekspor_publik.ekspor(db_path, target_keluar, log=log)
                log(f"Salinan publik (statis, memuat data): {r['berkas']} berkas, {r['ukuran_mb']} MB di {target_keluar}")
            hasil["Ekspor publik"] = 0
        except Exception as e:
            log(f"[GAGAL] ekspor publik: {e!r}")
            hasil["Ekspor publik"] = 1
    if unggah and hasil.get("Ekspor publik") == 0 and not berhenti.is_set():
        from . import unggah as _unggah
        log("=== Unggah ke Cloudflare ===")
        ok, pesan = _unggah.unggah(None if keluar is None else Path(keluar), log=log)
        log(("Terunggah: " if ok else "[TIDAK TERUNGGAH] ") + pesan)
        hasil["Unggah Cloudflare"] = 0 if ok else 1
    log("=== RINGKASAN ===")
    for nama, kode in hasil.items():
        log(f"  {nama}: {'OK' if kode in (0, 4) else 'DIBLOKIR' if kode == 2 else 'DIHENTIKAN' if kode == 130 else f'gagal (kode {kode})'}")
    if 2 in hasil.values():
        return 2
    if 130 in hasil.values():
        return 130
    return 0 if all(k in (0, 4) for k in hasil.values()) else 1
