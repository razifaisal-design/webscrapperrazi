"""Konfigurasi target (config/targets.json): satker, tahun, aturan klasifikasi/pemeriksaan, dan idSatker per tahun."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / "config" / "targets.json"


def muat_target(nama, tahun=None, id_satker=None):
    """Target dari config.
    - `tahun` menimpa tahun di config; bagian "per_tahun" (mis. pemetaan MAK yang beda tiap tahun) ikut menimpa.
    - idSatker di SiRUP BISA BERBEDA tiap tahun (mis. 2020-2021 = 69427, 2022+ = 173394). Pemetaannya ada di
      `id_satker_per_tahun`; `id_satker_semua` = semua idSatker yang dikenal untuk satker ini.
    - `id_satker` (argumen) menimpa semuanya, mis. dari kolom 'ID satker' di dashboard."""
    cfg = json.loads(TARGETS.read_text(encoding="utf-8"))
    nama = nama or cfg["default"]
    if nama not in cfg["targets"]:
        raise SystemExit(f"Target '{nama}' tidak ada di {TARGETS}. Pilihan: {', '.join(cfg['targets'])}")
    t = dict(cfg["targets"][nama])
    t["nama"] = nama
    per_tahun = t.pop("per_tahun", {})
    per_id = {str(k): int(v) for k, v in (t.get("id_satker_per_tahun") or {}).items()}
    t["id_satker_semua"] = sorted({int(t["id_satker"])} | set(per_id.values()))
    if tahun:
        t["tahun"] = int(tahun)
        t.update(per_tahun.get(str(tahun), {}))
    if str(t["tahun"]) in per_id:
        t["id_satker"] = per_id[str(t["tahun"])]
    if id_satker:
        t["id_satker"] = int(id_satker)
        t["id_satker_semua"] = sorted(set(t["id_satker_semua"]) | {int(id_satker)})
    return nama, t


def simpan_id_satker(tahun, id_satker, nama=None):
    """Catat ke config bahwa tahun itu memakai idSatker tertentu (dipanggil setelah pengambilan data BERHASIL).
    Return True bila file berubah."""
    cfg = json.loads(TARGETS.read_text(encoding="utf-8"))
    nama = nama or cfg["default"]
    sasaran = cfg["targets"][nama]
    per = sasaran.setdefault("id_satker_per_tahun", {})
    if int(id_satker) == int(sasaran["id_satker"]):
        berubah = per.pop(str(tahun), None) is not None            # sama dengan bawaan -> tidak perlu dicatat
    else:
        berubah = per.get(str(tahun)) != int(id_satker)
        per[str(tahun)] = int(id_satker)
    if berubah:
        per_urut = dict(sorted(per.items()))
        sasaran["id_satker_per_tahun"] = per_urut
        tmp = TARGETS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, TARGETS)
    return berubah


def satker_sirup():
    """{nama satker: [semua idSatker SiRUP-nya]} untuk setiap target di config, ditambah nama lain (`spse.satker_alias`) bila ada.
    Dipakai untuk memasangkan satker di SPSE dengan data SiRUP; aplikasi tidak terkunci pada satu satker."""
    cfg = json.loads(TARGETS.read_text(encoding="utf-8"))
    hasil = {}
    for nama in cfg["targets"]:
        _, t = muat_target(nama)
        for n in [t["satker_nama"], *((t.get("spse") or {}).get("satker_alias") or [])]:
            hasil[n] = t["id_satker_semua"]
    return hasil


def _tulis(cfg):
    tmp = TARGETS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, TARGETS)


def _slug(teks):
    import re
    return "-".join(re.sub(r"[^0-9a-z]+", " ", teks.lower()).split())


def daftar_target():
    """Satker yang sudah terdaftar di config -> [{nama (kunci target), satker_nama, klpd_nama, id_satker_semua, bawaan}]."""
    cfg = json.loads(TARGETS.read_text(encoding="utf-8"))
    hasil = []
    for nama in cfg["targets"]:
        _, t = muat_target(nama)
        hasil.append({"nama": nama, "satker_nama": t["satker_nama"], "klpd_nama": t.get("klpd_nama"),
                      "id_satker_semua": t["id_satker_semua"], "bawaan": nama == cfg["default"]})
    return hasil


def catat_klpd_id(nama_target, klpd_id):
    cfg = json.loads(TARGETS.read_text(encoding="utf-8"))
    if cfg["targets"][nama_target].get("klpd_id") != klpd_id:
        cfg["targets"][nama_target]["klpd_id"] = klpd_id
        _tulis(cfg)


def tambah_target(satker_nama, klpd_nama, klpd_id, id_satker, id_per_tahun=None, tahun=None):
    """Daftarkan satker baru (dikenali lewat NAMA) ke config. Aturan klasifikasi/pemeriksaan khusus Perkim tidak ikut: satker baru
    memakai rekap umum (per MAK, per uraian, database paket); wilayah & LPSE diwarisi dari target bawaan bila K/L/PD-nya sama.
    Bila satker itu sudah terdaftar, idSatker-nya saja yang diperbarui. -> nama target (kunci)."""
    from .sources.direktori import norm
    cfg = json.loads(TARGETS.read_text(encoding="utf-8"))
    for kunci, t in cfg["targets"].items():
        if norm(t["satker_nama"]) == norm(satker_nama) and norm(t.get("klpd_nama")) == norm(klpd_nama):
            t["klpd_id"] = klpd_id
            per = {str(k): int(v) for k, v in (id_per_tahun or {}).items() if int(v) != int(t["id_satker"])}
            t["id_satker_per_tahun"] = dict(sorted({**(t.get("id_satker_per_tahun") or {}), **per}.items()))
            _tulis(cfg)
            return kunci
    bawaan = cfg["targets"][cfg["default"]]
    sama_klpd = norm(bawaan.get("klpd_nama")) == norm(klpd_nama)
    kunci = _slug(f"{satker_nama} {klpd_nama}")
    id_satker = int(id_satker)
    baru = {"klpd_nama": klpd_nama, "klpd_id": klpd_id, "id_satker": id_satker,
            "id_satker_per_tahun": {str(k): int(v) for k, v in sorted((id_per_tahun or {}).items()) if int(v) != id_satker},
            "satker_nama": satker_nama, "tahun": int(tahun or bawaan["tahun"]), "mak_segmen": bawaan.get("mak_segmen", 12),
            "umum": True}
    if sama_klpd:
        for k in ("lokasi", "spse"):
            if k in bawaan:
                baru[k] = bawaan[k]
    cfg["targets"][kunci] = baru
    _tulis(cfg)
    return kunci
