"""Sinkronkan (cerminkan) database lokal SQLite ke Supabase (Postgres) sebagai cadangan dan pusat data.

SQLite lokal tetap SUMBER KEBENARAN: tiap sinkronisasi mengganti isi tabel di Supabase dengan isi lokal dalam SATU transaksi
(TRUNCATE + COPY), jadi hasilnya selalu sama persis dengan lokal dan, bila gagal di tengah jalan, Supabase kembali ke keadaan semula.
Tabel di Supabase TIDAK dibuka ke publik: RLS aktif tanpa kebijakan dan hak anon/authenticated dicabut; hanya koneksi database
(kata sandi di .env lokal) yang bisa membaca/menulis.

Kredensial: SUPABASE_DB_URL di file .env (tidak ikut git) atau variabel lingkungan, mis.
  postgresql://postgres.<ref>:<KATA_SANDI>@aws-0-<wilayah>.pooler.supabase.com:5432/postgres   (Session pooler dari dasbor Supabase)"""
import json
import os
import sqlite3
import time

from .konfig import ROOT

TABEL = ("scrape_runs", "sirup_paket", "sirup_foto", "ref_sub_kegiatan", "ref_mak", "sirup_detail", "sirup_luar_daftar", "paket_events", "paket_lokasi", "ref_jalan", "ref_gang",
         "spse_paket", "spse_detail", "spse_jadwal")
TIPE = {"INTEGER": "bigint", "TEXT": "text", "NUMERIC": "numeric", "REAL": "double precision"}
RIWAYAT = ('CREATE TABLE IF NOT EXISTS public."sinkron_riwayat" (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, waktu timestamptz NOT NULL DEFAULT now(), '
           'jumlah jsonb NOT NULL, detik numeric)')


class SinkronError(RuntimeError):
    pass


def muat_env(path=None):
    """Baca .env sederhana (KEY=VALUE, # komentar). Variabel lingkungan yang sudah ada tidak ditimpa."""
    path = path or (ROOT / ".env")
    nilai = {}
    if path.exists():
        for baris in path.read_text(encoding="utf-8").splitlines():
            baris = baris.strip()
            if baris and not baris.startswith("#") and "=" in baris:
                k, v = baris.split("=", 1)
                nilai[k.strip()] = v.strip().strip('"').strip("'")
    return {**nilai, **{k: v for k, v in os.environ.items() if k.startswith("SUPABASE_") and v}}      # variabel lingkungan KOSONG tidak menimpa .env


def url_db(path=None):
    return muat_env(path).get("SUPABASE_DB_URL") or None


def skema_lokal(conn):
    """{tabel: [(kolom, tipe_pg, adalah_pk, urutan_pk)]} dari SQLite, hanya tabel yang ada."""
    hasil = {}
    for t in TABEL:
        info = list(conn.execute(f"PRAGMA table_info({t})"))
        if info:
            hasil[t] = [(r[1], TIPE.get((r[2] or "TEXT").upper(), "text"), r[5] > 0, r[5]) for r in info]
    return hasil


def ddl(skema):
    """Daftar pernyataan SQL idempoten: buat tabel, tambah kolom baru, aktifkan RLS, cabut hak publik."""
    sql = []
    for t, kolom in skema.items():
        pk = [k for k, _, p, _ in sorted(kolom, key=lambda x: x[3]) if p]
        isi = ", ".join(f'"{k}" {tp}' for k, tp, _, _ in kolom)
        sql.append(f'CREATE TABLE IF NOT EXISTS public."{t}" ({isi}' + (f', PRIMARY KEY ({", ".join(chr(34) + k + chr(34) for k in pk)})' if pk else "") + ")")
        sql += [f'ALTER TABLE public."{t}" ADD COLUMN IF NOT EXISTS "{k}" {tp}' for k, tp, _, _ in kolom]
        sql.append(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY')
        sql.append(f'REVOKE ALL ON TABLE public."{t}" FROM anon, authenticated')
    sql += [RIWAYAT, 'ALTER TABLE public."sinkron_riwayat" ENABLE ROW LEVEL SECURITY', 'REVOKE ALL ON TABLE public."sinkron_riwayat" FROM anon, authenticated']
    return sql


def _bersih(v):
    return v.replace("\x00", "") if isinstance(v, str) else v


def sinkron(db_path, url=None, log=print, connect=None):
    """Cerminkan semua tabel. -> {tabel: jumlah_baris}. Melempar SinkronError dengan pesan jelas bila kredensial/skema bermasalah."""
    url = url or url_db()
    if not url:
        raise SinkronError("SUPABASE_DB_URL belum diisi di file .env. Ambil 'Connection string' (Session pooler) dari dasbor Supabase "
                           "(Project Settings > Database), lalu tulis satu baris di .env:  SUPABASE_DB_URL=postgresql://...")
    if "[YOUR-PASSWORD]" in url or "YOUR-PASSWORD" in url:
        raise SinkronError("SUPABASE_DB_URL di .env masih berisi [YOUR-PASSWORD]. Ganti dengan kata sandi database Supabase "
                           "(tanpa kurung siku; karakter khusus ditulis percent-encode, mis. @ menjadi %40).")
    if connect is None:
        try:
            import psycopg
        except ImportError as e:
            raise SinkronError("Pustaka psycopg belum terpasang. Jalankan: .venv/bin/pip install -r requirements.txt") from e
        connect = psycopg.connect
    lokal = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        skema = skema_lokal(lokal)
        mulai = time.monotonic()
        try:
            pg = connect(url, connect_timeout=30)
        except Exception as e:
            raise SinkronError(f"Tidak bisa terhubung ke Supabase: {type(e).__name__}. Periksa SUPABASE_DB_URL (kata sandi, Session pooler).") from None
        jumlah = {}
        with pg:
            with pg.cursor() as cur:
                for s in ddl(skema):
                    cur.execute(s)
                cur.execute("TRUNCATE " + ", ".join(f'public."{t}"' for t in skema))
                for t, kolom in skema.items():
                    nama = [k for k, _, _, _ in kolom]
                    n = 0
                    with cur.copy(f'COPY public."{t}" ({", ".join(chr(34) + k + chr(34) for k in nama)}) FROM STDIN') as cp:
                        for baris in lokal.execute(f'SELECT {", ".join(chr(34) + k + chr(34) for k in nama)} FROM "{t}"'):
                            cp.write_row([_bersih(v) for v in baris])
                            n += 1
                    cur.execute(f'SELECT count(*) FROM public."{t}"')
                    ada = cur.fetchone()[0]
                    if ada != n:
                        raise SinkronError(f"{t}: {n} baris lokal tetapi {ada} di Supabase - dibatalkan, Supabase tidak berubah.")
                    jumlah[t] = n
                    log(f"  {t}: {n} baris")
                cur.execute("INSERT INTO public.sinkron_riwayat (jumlah, detik) VALUES (%s, %s)", (json.dumps(jumlah), round(time.monotonic() - mulai, 1)))
        return jumlah
    finally:
        lokal.close()


def tarik(db_path, url=None, log=print, connect=None, paksa=False):
    """Kebalikan sinkron: bangun database SQLite lokal dari cermin di Supabase. Dipakai di server/GitHub Actions yang tidak menyimpan database
    antar-jalan, dan di komputer baru. Menulis ke berkas sementara lalu menggantinya hanya bila SEMUA tabel berhasil dan jumlahnya cocok.
    Database yang sudah ada TIDAK ditimpa kecuali `paksa` (yang lama disimpan sebagai <nama>.sebelum-tarik). -> {tabel: jumlah_baris}"""
    from decimal import Decimal
    from pathlib import Path

    from .core import database, db
    url = url or url_db()
    if not url:
        raise SinkronError("SUPABASE_DB_URL belum diisi (.env atau variabel lingkungan).")
    if "YOUR-PASSWORD" in url:
        raise SinkronError("SUPABASE_DB_URL masih berisi [YOUR-PASSWORD].")
    db_path = Path(db_path)
    if db_path.exists() and db_path.stat().st_size > 0 and not paksa:
        raise SinkronError(f"{db_path} sudah ada. Database lokal tidak ditimpa; pakai --paksa bila memang ingin menggantinya dengan isi Supabase.")
    if connect is None:
        try:
            import psycopg
        except ImportError as e:
            raise SinkronError("Pustaka psycopg belum terpasang. Jalankan: pip install -r requirements.txt") from e
        connect = psycopg.connect
    sementara = db_path.with_name(db_path.name + ".tarik")
    sementara.unlink(missing_ok=True)
    lokal = db.buka(sementara)
    lokal.executescript(database.SKEMA_LOKASI)
    try:
        try:
            pg = connect(url, connect_timeout=30)
        except Exception as e:
            raise SinkronError(f"Tidak bisa terhubung ke Supabase: {type(e).__name__}.") from None
        jumlah = {}
        with pg:
            with pg.cursor() as cur:
                for t in TABEL:
                    kol_lokal = [r[1] for r in lokal.execute(f"PRAGMA table_info({t})")]
                    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s", (t,))
                    kol_remote = {r[0] for r in cur.fetchall()}
                    kol = [k for k in kol_lokal if k in kol_remote]
                    if not kol:
                        log(f"  {t}: tidak ada di Supabase (dilewati)")
                        continue
                    cur.execute(f'SELECT {", ".join(chr(34) + k + chr(34) for k in kol)} FROM public."{t}"')
                    isi = [tuple((int(v) if v == v.to_integral_value() else float(v)) if isinstance(v, Decimal) else v for v in baris) for baris in cur.fetchall()]
                    with lokal:
                        lokal.executemany(f'INSERT OR REPLACE INTO "{t}" ({", ".join(chr(34) + k + chr(34) for k in kol)}) VALUES ({", ".join("?" * len(kol))})', isi)
                    ada = lokal.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    if ada != len(isi):
                        raise SinkronError(f"{t}: {len(isi)} baris di Supabase tetapi {ada} di berkas lokal - dibatalkan, database lokal tidak berubah.")
                    jumlah[t] = ada
                    log(f"  {t}: {ada} baris")
        lokal.commit()
        lokal.close()
        if db_path.exists():
            os.replace(db_path, db_path.with_name(db_path.name + ".sebelum-tarik"))
        os.replace(sementara, db_path)
        return jumlah
    except BaseException:
        try:
            lokal.close()
        except Exception:
            pass
        sementara.unlink(missing_ok=True)
        raise
