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

from .db import norm_satker

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


def hitung(conn, lpse, jenis, tahun_list, id_satker, satker_nama, satker_alias=(), sekarang=None):
    """Return {baris, ringkas, peringatan}. `id_satker` = satu id atau daftar id SiRUP; `tahun_list` = tahun yang dibandingkan."""
    sekarang = sekarang or datetime.now().strftime("%Y-%m-%dT%H:%M")
    ids = [id_satker] if isinstance(id_satker, int) else list(id_satker)
    sasaran = {norm_satker(satker_nama), *(norm_satker(a) for a in satker_alias)}
    baris, peringatan = [], []
    for tahun in tahun_list:
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

        spse = _paket_spse(conn, lpse, jenis, tahun)
        tanpa_detail = [p for p in spse if not p["ada_detail"]]
        if tanpa_detail:
            peringatan.append(f"Tahun {tahun}: {len(tanpa_detail)} paket SPSE belum diambil detailnya, jadi instansinya belum diketahui "
                              f"dan belum ikut dibandingkan. Jalankan Ambil Data + Detail di halaman SPSE.")
        milik = [p for p in spse if p["ada_detail"] and norm_satker(p["satker"]) in sasaran]
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
        tanpa_pasangan = []
        for p in sisa:                                          # tahap 3: nama + instansi, hanya RUP yang belum terklaim
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

        def bentuk(p, cara, r):
            jad = _jadwal_paket(conn, lpse, jenis, p["kode_paket"])
            status, acuan = _tayang(jad, sekarang)
            kode_grup = pagu_grup.get(p["kode_paket"], [])
            pagu_ref = sum((aktif[k]["pagu"] or 0) for k in kode_grup) if kode_grup else None
            awal = None
            if acuan:
                asli = [x["mulai_asli_iso"] for x in acuan["riwayat"] if x.get("mulai_asli_iso")]
                awal = min(asli) if asli else None
            return {
                "kode_nontender": p["kode_paket"], "nama_spse": p["nama_paket"], "kode_rup_spse": ", ".join(x["kode_rup"] for x in p["rup"]),
                "tahapan": p["tahapan"], "metode_spse": p["metode"] or p["metode_daftar"], "link_spse": p["link"], "satker_spse": p["satker"],
                "kecocokan": cara, "status": status, "pagu_spse": p["pagu"], "hps": p["hps"],
                "harga_penawaran": p["harga_penawaran"], "harga_terkoreksi": p["harga_terkoreksi"], "hasil_negosiasi": p["hasil_negosiasi"],
                "nilai_kontrak": p["nilai_kontrak"], "pemenang": p["pemenang_nama"], "pemenang_terisi": p["pemenang_terisi"],
                "kontrak_terisi": p["kontrak_terisi"], "lengkap": p["lengkap"],
                "upload_mulai": acuan["mulai"] if acuan else None, "upload_sampai": acuan["sampai"] if acuan else None,
                "upload_mulai_awal": awal, "jadwal_diubah": sum(t["jumlah_perubahan"] for t in jad), "jadwal": jad,
                "jumlah_rup_gabungan": len(kode_grup), "pagu_sirup_gabungan": pagu_ref,
                "pagu_sama": (None if p["pagu"] is None or pagu_ref is None else abs(pagu_ref - p["pagu"]) < 1),
                "selisih_pagu": (None if p["pagu"] is None or pagu_ref is None else p["pagu"] - pagu_ref),
                "jumlah_paket_spse": len(klaim.get(r["kode_rup"], [])) if r else 1,
            }

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
            baris.append({"tahun": tahun, "kode_rup": None, "nama_sirup": None, "pagu_sirup": None, "kategori": "Non-Tender", "metode_sirup": None,
                          **bentuk(p, None, None), "status": "Tidak ada di SiRUP"})
    return {"baris": baris, "ringkas": ringkas(baris), "peringatan": peringatan}


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
