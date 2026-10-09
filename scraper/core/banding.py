"""Perbandingan SiRUP (rencana) dengan SPSE Non-Tender (pelaksanaan) untuk satu satker.

Pasangan RUP <-> paket SPSE ditentukan bertahap:
  1. KODE RUP: kode RUP di halaman Pengumuman SPSE sama dengan kode RUP di SiRUP;
  2. KODE RUP LAMA: RUP itu sudah diganti (revisi RUP) -> pakai RUP penggantinya di SiRUP;
  3. NAMA + INSTANSI: RUP diubah setelah paket tayang sehingga kodenya tidak ada lagi -> nama paket sama (setelah dinormalkan)
     dan instansi paket di SPSE adalah satker yang sama.
Hanya paket SPSE yang instansinya sama dengan satker target yang dipakai."""
import json
import re
from datetime import datetime

from .db import nama_kanonik, norm_satker

TAHAP_TAYANG = "upload dokumen penawaran"


def norm_nama(teks):
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (teks or "").lower()).split())


def _json(teks, bawaan):
    try:
        return json.loads(teks) if teks else bawaan
    except ValueError:
        return bawaan


def _kategori_sirup(r):
    if (r["jenis"] or "").lower() == "swakelola":
        return "Swakelola"
    m = (r["metode_pemilihan"] or "").lower()
    if "purchasing" in m or "katalog" in m:
        return "E-Katalog"
    if "kecuali" in m:
        return "Dikecualikan"
    if "tender" in m and "non" not in m or "seleksi" in m:
        return "Tender/Seleksi"
    return "Non-Tender"


def _jadwal_paket(conn, lpse, jenis, kode):
    hasil = []
    for r in conn.execute("SELECT * FROM spse_jadwal WHERE lpse=? AND jenis=? AND kode_paket=? ORDER BY no", (lpse, jenis, kode)):
        hasil.append({"no": r["no"], "tahap": r["tahap"], "mulai_teks": r["mulai_teks"], "sampai_teks": r["sampai_teks"],
                      "mulai": r["mulai"], "sampai": r["sampai"], "jumlah_perubahan": r["jumlah_perubahan"] or 0,
                      "riwayat": _json(r["riwayat_json"], [])})
    return hasil


def _tayang(jadwal, sekarang):
    """(status, tahap_acuan) menurut tahap pertama jadwal (Upload Dokumen Penawaran bila ada)."""
    if not jadwal:
        return "Jadwal belum diambil", None
    acuan = next((t for t in jadwal if (t["tahap"] or "").lower() == TAHAP_TAYANG), jadwal[0])
    if not acuan["mulai"]:
        return "Jadwal belum diambil", acuan
    return ("Sudah tayang" if acuan["mulai"] <= sekarang else "Belum tayang"), acuan


def _paket_spse(conn, lpse, jenis, tahun):
    sql = ("SELECT p.kode_paket, p.nama_paket, p.tahapan, p.metode AS metode_daftar, p.link, d.kode_rup, d.rup_json, d.satker, d.pagu, d.hps, "
           "d.metode, d.jenis_pengadaan, d.sumber_dana, d.pemenang_nama, d.harga_penawaran, d.harga_terkoreksi, d.hasil_negosiasi, "
           "d.nilai_kontrak, d.pemenang_terisi, d.kontrak_terisi, d.lengkap, d.diambil_pada, d.kode_paket AS ada_detail "
           "FROM spse_paket p LEFT JOIN spse_detail d ON d.lpse=p.lpse AND d.jenis=p.jenis AND d.kode_paket=p.kode_paket AND d.error IS NULL "
           "WHERE p.lpse=? AND p.jenis=? AND p.tahun=? AND p.is_active=1 ORDER BY p.kode_paket")
    hasil = []
    for r in conn.execute(sql, (lpse, jenis, tahun)):
        d = dict(r)
        d["rup"] = _json(d.pop("rup_json"), [])
        hasil.append(d)
    return hasil


def _baris_spse(conn, lpse, jenis, p, cara, sekarang, kode_grup=(), aktif=None, jumlah_paket=1, pagu_ekstra=0, n_ekstra=0):
    """Bagian baris perbandingan yang berasal dari sisi SPSE (jadwal, pagu, HPS, penawaran, negosiasi, kontrak, pemenang)."""
    jad = _jadwal_paket(conn, lpse, jenis, p["kode_paket"])
    status, acuan = _tayang(jad, sekarang)
    pagu_ref = (sum((aktif[k]["pagu"] or 0) for k in kode_grup) + pagu_ekstra) if (kode_grup or n_ekstra) else None
    awal = awal_sampai = None
    if acuan:
        # jadwal ORIGINAL = yang tertua di riwayat perubahan tahap itu (bila pernah diubah)
        riw = sorted(acuan["riwayat"], key=lambda x: x.get("tanggal_edit_iso") or "")
        if riw:
            awal, awal_sampai = riw[0].get("mulai_asli_iso"), riw[0].get("sampai_asli_iso")
    return {
        "kode_nontender": p["kode_paket"], "nama_spse": p["nama_paket"], "kode_rup_spse": ", ".join(x["kode_rup"] for x in p["rup"]),
        "tahapan": p["tahapan"], "metode_spse": p["metode"] or p["metode_daftar"], "link_spse": p["link"], "satker_spse": p["satker"],
        "kecocokan": cara, "status": status, "pagu_spse": p["pagu"], "hps": p["hps"],
        "harga_penawaran": p["harga_penawaran"], "harga_terkoreksi": p["harga_terkoreksi"], "hasil_negosiasi": p["hasil_negosiasi"],
        "nilai_kontrak": p["nilai_kontrak"], "pemenang": p["pemenang_nama"], "pemenang_terisi": p["pemenang_terisi"],
        "kontrak_terisi": p["kontrak_terisi"], "lengkap": p["lengkap"],
        "upload_mulai": acuan["mulai"] if acuan else None, "upload_sampai": acuan["sampai"] if acuan else None,
        "upload_mulai_awal": awal, "upload_sampai_awal": awal_sampai, "jadwal_diubah": sum(t["jumlah_perubahan"] for t in jad), "jadwal": jad,
        "jumlah_rup_gabungan": len(kode_grup) + n_ekstra, "pagu_sirup_gabungan": pagu_ref,
        "pagu_sama": (None if p["pagu"] is None or pagu_ref is None else abs(pagu_ref - p["pagu"]) < 1),
        "selisih_pagu": (None if p["pagu"] is None or pagu_ref is None else p["pagu"] - pagu_ref),
        "jumlah_paket_spse": jumlah_paket,
    }


def _bandingkan(conn, lpse, jenis, tahun, ids, milik, tanpa_detail, sekarang, nama_satker, luar=None):
    """Pasangkan RUP SiRUP (idSatker `ids`) dengan paket SPSE `milik` untuk satu satker & satu tahun -> daftar baris."""
    baris = []
    sirup = [dict(r) for r in conn.execute(
        f"SELECT * FROM sirup_paket WHERE tahun=? AND id_satker IN ({','.join('?' * len(ids))}) ORDER BY kode_rup", (tahun, *ids))]
    aktif = {r["kode_rup"]: r for r in sirup if r["is_active"]}
    semua = {r["kode_rup"]: r for r in sirup}

    def pengganti(kode):
        for _ in range(5):
            r = semua.get(kode)
            if r is None:
                return None
            if r["is_active"]:
                return kode
            kode = r["kode_rup_pengganti"]
            if not kode:
                return None
        return None

    klaim = {}                                              # kode RUP SiRUP -> [(paket SPSE, cara)]
    sisa = []
    for p in milik:                                         # tahap 1-2: kode RUP
        cocok = []
        for r in p["rup"]:
            kode = r["kode_rup"]
            if kode in aktif:
                cocok.append((kode, "Kode RUP"))
            elif kode in semua and pengganti(kode):
                cocok.append((pengganti(kode), "Kode RUP (RUP sudah direvisi)"))
        if cocok:
            for kode, cara in dict.fromkeys(cocok):
                klaim.setdefault(kode, []).append((p, cara))
        else:
            sisa.append(p)
    luar = luar or {}

    def rup_luar(p):
        """RUP milik satker ini yang terbukti ADA di SiRUP lewat kodenya (dicek langsung), walau tidak tampil di daftar."""
        return [luar[r["kode_rup"]] for r in p["rup"]
                if r["kode_rup"] in luar and luar[r["kode_rup"]]["ditemukan"] and norm_satker(luar[r["kode_rup"]]["satker_nama"]) == norm_satker(nama_satker)]

    # kode RUP yang disebut SPSE didahulukan dari pencocokan nama: nama yang sama bisa dipakai dua RUP berbeda (mis. diumumkan ulang)
    sisa_nama = [p for p in sisa if not rup_luar(p)]
    tanpa_pasangan = [p for p in sisa if rup_luar(p)]
    for p in sisa_nama:                                     # tahap 3: nama + instansi, hanya RUP yang belum terklaim
        nama = {norm_nama(p["nama_paket"])} | {norm_nama(r["nama_paket"]) for r in p["rup"]}
        kandidat = [k for k, r in aktif.items() if k not in klaim and norm_nama(r["nama_paket"]) in nama]
        if kandidat:
            terbaik = min(kandidat, key=lambda k: abs((aktif[k]["pagu"] or 0) - (p["pagu"] or 0)))
            klaim.setdefault(terbaik, []).append((p, "Nama paket + instansi (RUP berubah)"))
        else:
            tanpa_pasangan.append(p)
    pagu_grup = {}                                          # paket SPSE -> jumlah pagu RUP SiRUP yang berpasangan
    for kode, lst in klaim.items():
        for p, _ in lst:
            pagu_grup.setdefault(p["kode_paket"], []).append(kode)

    def ekstra(p):
        """RUP lain di paket SPSE yang sama yang tidak tampil di daftar tetapi terbukti ada di SiRUP (dicek lewat kode): ikut dijumlahkan."""
        kode = {r["kode_rup"] for r in p["rup"]}
        rec = [luar[k] for k in sorted(kode) if k not in semua and k in luar and luar[k]["ditemukan"]
               and norm_satker(luar[k]["satker_nama"]) == norm_satker(nama_satker)]
        return sum(r["pagu"] or 0 for r in rec), len(rec)

    def bentuk(p, cara, r):
        pe, ne = ekstra(p)
        return _baris_spse(conn, lpse, jenis, p, cara, sekarang, pagu_grup.get(p["kode_paket"], []), aktif,
                           len(klaim.get(r["kode_rup"], [])) if r else 1, pe, ne)

    for kode, r in aktif.items():
        dasar = {"tahun": tahun, "kode_rup": kode, "nama_sirup": r["nama_paket"], "pagu_sirup": r["pagu"], "metode_sirup": r["metode_pemilihan"],
                 "jenis_sirup": r["jenis"], "link_sirup": r["link"], "sumber_dana": r["sumber_dana"], "kategori": _kategori_sirup(r)}
        if kode in klaim:
            # beberapa paket SPSE untuk satu RUP (mis. pengumuman ulang): utamakan yang tidak dibatalkan, lalu yang terbaru
            p, cara = sorted(klaim[kode], key=lambda x: ((x[0]["tahapan"] or "").lower().find("batal") >= 0, -int(x[0]["kode_paket"])))[0]
            baris.append({**dasar, **bentuk(p, cara, r)})
        else:
            kat = dasar["kategori"]
            st = {"Swakelola": "Swakelola (tidak di SPSE)", "E-Katalog": "E-Katalog (tidak di SPSE)", "Dikecualikan": "Dikecualikan",
                  "Tender/Seleksi": "Tender/Seleksi (belum diambil)"}.get(
                kat, "Belum dapat dipastikan (detail SPSE belum lengkap)" if tanpa_detail else "Belum ada di SPSE")
            baris.append({**dasar, "status": st, "kecocokan": None, "kode_nontender": None})
    for p in tanpa_pasangan:
        recs = [luar[r["kode_rup"]] for r in p["rup"] if r["kode_rup"] in luar]
        ada = [r for r in recs if r["ditemukan"]]
        milik_satker = [r for r in ada if norm_satker(r["satker_nama"]) == norm_satker(nama_satker)]
        spse_bag = _baris_spse(conn, lpse, jenis, p, None, sekarang)
        if milik_satker:                                    # RUP-nya ADA di SiRUP (dicek lewat kode), hanya tidak tampil di daftar satker
            pagu_ref = sum(r["pagu"] or 0 for r in milik_satker)
            spse_bag.update(kecocokan="Kode RUP (ada di SiRUP, tidak tampil di daftar satker)", jumlah_rup_gabungan=len(milik_satker),
                            pagu_sirup_gabungan=pagu_ref,
                            pagu_sama=None if p["pagu"] is None else abs(pagu_ref - p["pagu"]) < 1,
                            selisih_pagu=None if p["pagu"] is None else p["pagu"] - pagu_ref)
            r0 = milik_satker[0]
            baris.append({"tahun": tahun, "kode_rup": r0["kode_rup"], "nama_sirup": r0["nama_paket"], "pagu_sirup": r0["pagu"],
                          "metode_sirup": r0["metode_pemilihan"], "jenis_sirup": "penyedia", "link_sirup": r0["link"], "sumber_dana": None,
                          "kategori": _kategori_sirup({"jenis": "penyedia", "metode_pemilihan": r0["metode_pemilihan"]}), "di_daftar": False,
                          **spse_bag})
            continue
        if ada:
            status = "RUP di SiRUP milik satker lain"
        elif recs and all(not r["ditemukan"] for r in recs):
            status = "RUP tidak ada di SiRUP"
        else:
            status = "Tidak ada di daftar SiRUP"
        baris.append({"tahun": tahun, "kode_rup": None, "nama_sirup": None, "pagu_sirup": None, "kategori": "Non-Tender", "metode_sirup": None,
                      **spse_bag, "status": status,
                      **({"kecocokan": f"RUP {ada[0]['kode_rup']} milik {ada[0]['satker_nama']}"} if ada else {})})
    for b in baris:
        b["satker"] = nama_satker
    return baris


def hitung(conn, lpse, jenis, tahun_list, peta_sirup, satker=None, sekarang=None):
    """Return {baris, ringkas, peringatan, satker_daftar}.
    `peta_sirup` = {nama satker: [idSatker SiRUP, ...]} untuk satker yang data SiRUP-nya ada di database (nama dibandingkan setelah
    dinormalkan). `satker` = nama satu satker, atau None/'semua' = semua satker yang ada di SPSE maupun SiRUP.
    Satker yang ada di SPSE tetapi belum punya data SiRUP tetap ditampilkan (status 'SiRUP satker ini belum diambil'),
    bukan dianggap 'tidak ada di SiRUP'."""
    sekarang = sekarang or datetime.now().strftime("%Y-%m-%dT%H:%M")
    peta = {norm_satker(n): (n, list(ids)) for n, ids in peta_sirup.items()}
    pilih = None if satker in (None, "", "semua") else norm_satker(satker)
    luar = {r["kode_rup"]: dict(r) for r in conn.execute("SELECT * FROM sirup_luar_daftar WHERE error IS NULL")} \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='sirup_luar_daftar'").fetchone() else {}
    kan = nama_kanonik(
        r[0] for r in conn.execute("SELECT satker FROM spse_detail WHERE satker IS NOT NULL AND error IS NULL"))
    baris, peringatan, ada_spse = [], [], {}
    tanpa_sirup = set()
    for tahun in tahun_list:
        spse = _paket_spse(conn, lpse, jenis, tahun)
        tanpa_detail = [p for p in spse if not p["ada_detail"]]
        if tanpa_detail:
            peringatan.append(f"Tahun {tahun}: {len(tanpa_detail)} paket SPSE belum diambil detailnya, jadi satkernya belum diketahui "
                              f"dan belum ikut dibandingkan. Jalankan Ambil Data + Detail di halaman SPSE.")
        grup = {}
        for p in spse:
            if p["ada_detail"]:
                grup.setdefault(norm_satker(p["satker"]), (kan.get(norm_satker(p["satker"]), p["satker"]), []))[1].append(p)
        for k, (nama, lst) in grup.items():
            ada_spse[k] = ada_spse.get(k, (nama, 0))[0], ada_spse.get(k, (nama, 0))[1] + len(lst)
        for k in sorted(set(grup) | set(peta)):
            if pilih is not None and k != pilih:
                continue
            nama = peta[k][0] if k in peta else grup[k][0]                       # satker ber-SiRUP memakai nama resmi di config
            milik = grup[k][1] if k in grup else []
            if k in peta:
                baris += _bandingkan(conn, lpse, jenis, tahun, peta[k][1], milik, tanpa_detail, sekarang, nama, luar)
            else:
                tanpa_sirup.add(nama)
                for p in milik:
                    baris.append({"tahun": tahun, "kode_rup": None, "nama_sirup": None, "pagu_sirup": None, "kategori": "Non-Tender",
                                  "metode_sirup": None, "satker": nama, **_baris_spse(conn, lpse, jenis, p, None, sekarang),
                                  "status": "SiRUP satker ini belum diambil"})
    if tanpa_sirup and pilih is None:
        peringatan.append(f"{len(tanpa_sirup)} satker punya paket di SPSE tetapi data SiRUP-nya belum diambil, jadi hanya ditampilkan dari sisi SPSE.")
    daftar = [{"nama": n, "paket_spse": ada_spse.get(k, (n, 0))[1], "ada_sirup": k in peta} for k, (n, _) in sorted({**{k: (v[0], 0) for k, v in peta.items()}, **{k: (v[0], 0) for k, v in ada_spse.items()}}.items())]
    return {"baris": baris, "ringkas": ringkas(baris), "peringatan": peringatan, "satker_daftar": daftar}


def ringkas(baris):
    per = {}
    for b in baris:
        e = per.setdefault(b["status"], {"jumlah": 0, "pagu_sirup": 0})
        e["jumlah"] += 1
        e["pagu_sirup"] += b.get("pagu_sirup") or 0
    cocok = [b for b in baris if b.get("kode_nontender") and b.get("pagu_sama") is not None]
    return {"per_status": per, "total": len(baris), "berpasangan": sum(1 for b in baris if b.get("kode_nontender") and b.get("kode_rup")),
            "pagu_beda": sum(1 for b in cocok if not b["pagu_sama"]), "pagu_sama": sum(1 for b in cocok if b["pagu_sama"]),
            "jadwal_diubah": sum(1 for b in baris if (b.get("jadwal_diubah") or 0) > 0),
            "kontrak_terisi": sum(1 for b in baris if b.get("kontrak_terisi")), "pemenang_terisi": sum(1 for b in baris if b.get("pemenang_terisi"))}
