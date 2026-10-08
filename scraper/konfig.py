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
