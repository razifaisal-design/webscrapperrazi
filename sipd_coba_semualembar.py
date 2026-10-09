"""Percobaan SIPD SEMUA lembar — read-only terhadap PDF, tulis ke DB COBA saja (bukan pantau.db).

Pemakaian (Mac dan Windows):
  python3 sipd_coba_semualembar.py                      -> membuka BROWSER; pilih satu atau BANYAK PDF di halaman itu (Windows: python ...)
  python3 sipd_coba_semualembar.py a.pdf b.pdf ...      -> tanpa browser, langsung proses (baris perintah)

Memakai parser baris dari sipd_coba_3lembar.py (aturan terkunci: SIPD-CATATAN-PERCOBAAN.md), ditambah:
- SPESIFIKASI jadi kolom sendiri, di sebelah nama paket (Uraian) dan SEBELUM koefisien.
  Paket dengan 2 spesifikasi: teks dipisah " ; " (koefisien, satuan, harga ikut dipisah " ; " dengan urutan sama).
- MAK kategori Jalan / Saluran: nama paket fisik otomatis diberi awalan seperti di SiRUP/SPSE:
    Jalan  (1.04.05.2.01.0012 + 5.2.04.01.001.00004) -> "Belanja Modal Jalan Kota (<nama>)"
    Saluran(1.04.05.2.01.0011 + 5.2.04.02.002.00004) -> "Belanja Modal Saluran Pembuang Pasang Surut (<nama>)"
  Paket konsultan (blok [#] "Konsultansi") TIDAK diberi awalan, karena di SiRUP namanya apa adanya (mis. "Pengawasan PSU Jalan ...").
  Nama asli dari PDF disimpan juga (nama_pdf). Tanpa normalisasi/koreksi ejaan (aturan 7).
- Hierarki dibawa ke tiap paket: kode rekening, uraian rekening, sumber dana.
- Validasi: [-] vs spec, total dokumen, [#] vs paket, rekening vs [#], koefisien x harga.
- MURNI menulis isi PDF: tidak ada pencocokan ke SiRUP/SPSE dan tidak ada koreksi nama/ejaan.
"""
import hashlib
import re
import sqlite3
import sys
from pathlib import Path

AKAR = Path(__file__).resolve().parent
sys.path.insert(0, str(AKAR))
import sipd_coba_3lembar as dasar  # noqa: E402  (parser baris; main() di sana tidak ikut jalan)

DB = AKAR / "sipd_coba_semua.db"
PUSTAKA = ["pypdf", "openpyxl"]

# (sub kegiatan, kode rekening) -> (kategori, awalan nama paket di SiRUP/SPSE). Sama dengan config/kategori_home.json (Jalan PSU, Saluran PSU).
KATEGORI_MAK = {
    ("1.04.05.2.01.0012", "5.2.04.01.001.00004"): ("Jalan", "Belanja Modal Jalan Kota"),
    ("1.04.05.2.01.0011", "5.2.04.02.002.00004"): ("Saluran", "Belanja Modal Saluran Pembuang Pasang Surut"),
}

SKEMA = """
CREATE TABLE IF NOT EXISTS sipd_dokumen(id INTEGER PRIMARY KEY, nama_berkas TEXT, hash TEXT UNIQUE,
  jenis_laporan TEXT, tahun INTEGER, satker_nama TEXT, kode_sub_kegiatan TEXT, nama_sub_kegiatan TEXT,
  versi INTEGER, jumlah_halaman INTEGER, total NUMERIC, status TEXT, catatan TEXT);
CREATE TABLE IF NOT EXISTS sipd_rekening(dokumen_id INTEGER, urutan INTEGER, kode_rekening TEXT, uraian TEXT, jumlah NUMERIC,
  halaman INTEGER, PRIMARY KEY(dokumen_id, urutan));
CREATE TABLE IF NOT EXISTS sipd_paket(dokumen_id INTEGER, urutan INTEGER,
  kode_sub_kegiatan TEXT, kode_rekening TEXT, uraian_rekening TEXT, sumber_dana TEXT, blok_uraian TEXT,
  kategori_mak TEXT, jenis TEXT,
  nama_paket TEXT,          -- nama seperti di SiRUP/SPSE (kategori Jalan/Saluran fisik: 'Belanja Modal ... (<nama PDF>)')
  nama_pdf TEXT,            -- nama persis di PDF
  spesifikasi TEXT,         -- spesifikasi; 2 spesifikasi dipisah ' ; '
  koefisien TEXT, satuan TEXT, harga_satuan TEXT,   -- ikut dipisah ' ; ' bila 2 spesifikasi
  n_spesifikasi INTEGER, jumlah NUMERIC, ppn TEXT, halaman INTEGER, PRIMARY KEY(dokumen_id, urutan));
CREATE TABLE IF NOT EXISTS sipd_spesifikasi(dokumen_id INTEGER, urutan_paket INTEGER, no INTEGER,
  uraian TEXT, koefisien TEXT, satuan TEXT, harga_satuan NUMERIC, jumlah NUMERIC, halaman INTEGER,
  PRIMARY KEY(dokumen_id, urutan_paket, no));
CREATE INDEX IF NOT EXISTS ix_sipd_paket_nama ON sipd_paket(nama_paket);
"""


def susun_paket(semua, kode_sub):
    """Daftar baris hasil parse_halaman (berurutan) -> (rekening[], paket[]). Tiap paket membawa rekening/[#]/sumber dana induknya."""
    rekening, paket = [], []
    rek = {"kode": "", "uraian": ""}
    pagar = {"uraian": "", "sumber_dana": ""}
    cur = None
    for r in semua:
        j = r["jenis"]
        if j == "rekening":
            rekening.append(r)
            if len(r["kode"].split(".")) >= 6:            # rekening daun (kode objek/rincian objek)
                rek = {"kode": r["kode"], "uraian": r["uraian"]}
                pagar = {"uraian": "", "sumber_dana": ""}
        elif j == "pagar":
            pagar = {"uraian": r["uraian"], "sumber_dana": r["sumber_dana"]}
        elif j == "minus":
            cur = {"nama_pdf": r["uraian"], "jumlah": r["jumlah"], "halaman": r["halaman"], "specs": [],
                   "kode_rekening": rek["kode"], "uraian_rekening": rek["uraian"],
                   "sumber_dana": pagar["sumber_dana"], "blok_uraian": pagar["uraian"]}
            paket.append(cur)
        elif j == "spec":
            if cur is None:
                raise ValueError(f"Spesifikasi tanpa [-] di halaman {r['halaman']}: {r['uraian'][:60]}")
            cur["specs"].append(r)
    for n, p in enumerate(paket, 1):
        p["urutan"] = n
        kat = KATEGORI_MAK.get((kode_sub, p["kode_rekening"]))
        konsultan = "konsultansi" in p["blok_uraian"].lower()
        p["jenis"] = "Konsultan" if konsultan else ("Fisik" if p["kode_rekening"].startswith("5.2") else "Operasional")
        p["kategori_mak"] = kat[0] if kat else ""
        # awalan hanya untuk paket FISIK kategori Jalan/Saluran (konsultan dan non-MAK ini dibiarkan apa adanya)
        p["nama_paket"] = f"{kat[1]} ({p['nama_pdf']})" if kat and not konsultan else p["nama_pdf"]
        sp = p["specs"]
        p["spesifikasi"] = " ; ".join(s["uraian"] for s in sp)
        p["koefisien"] = " ; ".join((s["koefisien"] or "-") for s in sp)
        p["satuan"] = " ; ".join(s["satuan"] for s in sp)
        p["harga_satuan"] = " ; ".join(str(s["harga"]) for s in sp)
    return rekening, paket


def validasi(rekening, paket, total_pdf, lengkap):
    """-> (daftar_masalah, ringkasan). Masalah = teks; kosong berarti lolos."""
    masalah = []
    for p in paket:
        s = sum(x["jumlah"] for x in p["specs"])
        if abs(s - p["jumlah"]) > 1:
            masalah.append(f"[-] != sum(spec) hal {p['halaman']}: {p['nama_pdf'][:60]} | {p['jumlah']} vs {s}")
        if not p["specs"]:
            masalah.append(f"paket tanpa spesifikasi hal {p['halaman']}: {p['nama_pdf'][:60]}")
        for x in p["specs"]:
            f = dasar.parse_koefisien(x["koefisien"])
            if f and abs(round(f[0] * float(x["harga"])) - x["jumlah"]) > 1:
                masalah.append(f"koefisien x harga != jumlah hal {x['halaman']}: {x['uraian'][:50]}")
    # [#] vs paket di bawahnya, rekening daun vs [#]
    per_pagar, per_rek = {}, {}
    for p in paket:
        k = (p["kode_rekening"], p["sumber_dana"], p["blok_uraian"])
        per_pagar[k] = per_pagar.get(k, 0) + p["jumlah"]
        per_rek[p["kode_rekening"]] = per_rek.get(p["kode_rekening"], 0) + p["jumlah"]
    jml_rek = {r["kode"]: r["jumlah"] for r in rekening}
    for kode, s in per_rek.items():
        if kode in jml_rek and abs(jml_rek[kode] - s) > 1:
            masalah.append(f"rekening {kode} {jml_rek[kode]} != sum(paket) {s}")
    sum_paket = sum(p["jumlah"] for p in paket)
    if lengkap:
        if total_pdf is None:
            masalah.append("baris 'Jumlah : Rp...' (total dokumen) tidak ditemukan")
        elif abs(sum_paket - total_pdf) > 1:
            masalah.append(f"total dokumen {total_pdf} != sum(paket) {sum_paket} (selisih {sum_paket - total_pdf})")
    return masalah, {"paket": len(paket), "spesifikasi": sum(len(p["specs"]) for p in paket), "sum_paket": sum_paket}


def simpan(nama_berkas, h, meta, rekening, paket, total_pdf, lengkap, n_hal):
    con = sqlite3.connect(str(DB))
    con.executescript(SKEMA)
    with con:
        lama = con.execute("SELECT id FROM sipd_dokumen WHERE hash=?", (h,)).fetchone()
        if lama:                                           # dokumen yang sama diunggah ulang -> ganti isinya
            for t, k in (("sipd_rekening", "dokumen_id"), ("sipd_paket", "dokumen_id"), ("sipd_spesifikasi", "dokumen_id")):
                con.execute(f"DELETE FROM {t} WHERE {k}=?", (lama[0],))
            con.execute("DELETE FROM sipd_dokumen WHERE id=?", (lama[0],))
        cur = con.execute("INSERT INTO sipd_dokumen(nama_berkas,hash,jenis_laporan,tahun,satker_nama,kode_sub_kegiatan,nama_sub_kegiatan,"
                          "versi,jumlah_halaman,total,status,catatan) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (nama_berkas, h, "RKA-RINCIAN", 2026, meta["satker"], meta["kode_sub"], meta["nama_sub"], 1, n_hal, total_pdf,
                           "lengkap" if lengkap else "parsial", f"{n_hal} halaman"))
        did = cur.lastrowid
        con.executemany("INSERT INTO sipd_rekening VALUES(?,?,?,?,?,?)",
                        [(did, n, r["kode"], r["uraian"], r["jumlah"], r["halaman"]) for n, r in enumerate(rekening, 1)])
        for p in paket:
            con.execute("INSERT INTO sipd_paket VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (did, p["urutan"], meta["kode_sub"], p["kode_rekening"], p["uraian_rekening"], p["sumber_dana"], p["blok_uraian"],
                         p["kategori_mak"], p["jenis"], p["nama_paket"], p["nama_pdf"], p["spesifikasi"], p["koefisien"], p["satuan"],
                         p["harga_satuan"], len(p["specs"]), p["jumlah"], None, p["halaman"]))
            for no, s in enumerate(p["specs"], 1):
                con.execute("INSERT INTO sipd_spesifikasi VALUES(?,?,?,?,?,?,?,?,?)",
                            (did, p["urutan"], no, s["uraian"], s["koefisien"], s["satuan"], s["harga"], s["jumlah"], s["halaman"]))
    con.close()
    return did


def ekspor_excel(path, meta, rekening, paket, masalah):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Paket"
    ws.append(["Sub Kegiatan", f"{meta['kode_sub']} {meta['nama_sub']}"])
    ws.append([])
    ws.append(["No", "Kode Rekening", "Sumber Dana", "Uraian (Nama Paket)", "Spesifikasi", "Koefisien", "Satuan", "Harga", "Jumlah",
               "Kategori MAK", "Jenis", "Halaman"])
    for c in ws[3]:
        c.font = Font(bold=True)
    for p in paket:
        ws.append([p["urutan"], p["kode_rekening"], p["sumber_dana"], p["nama_paket"], p["spesifikasi"], p["koefisien"],
                   p["satuan"], p["harga_satuan"], p["jumlah"], p["kategori_mak"], p["jenis"], p["halaman"]])
    w2 = wb.create_sheet("Rekening")
    w2.append(["Kode Rekening", "Uraian", "Jumlah", "Halaman"])
    for r in rekening:
        w2.append([r["kode"], r["uraian"], r["jumlah"], r["halaman"]])
    w3 = wb.create_sheet("Validasi")
    w3.append(["Hasil validasi"])
    for m in (masalah or ["Semua validasi lolos"]):
        w3.append([m])
    wb.save(str(path))


def proses_pdf(pdf, nama_asli=None, log=print):
    """Parse satu PDF -> simpan ke DB coba + Excel. -> dict hasil (untuk CLI maupun halaman browser)."""
    from pypdf import PdfReader
    pdf = Path(pdf)
    nama_asli = nama_asli or pdf.name
    reader = PdfReader(str(pdf))
    n_hal = len(reader.pages)
    teks_hal = [pg.extract_text() or "" for pg in reader.pages]
    if not any(t.strip() for t in teks_hal):
        raise ValueError("PDF tidak berisi teks (mungkin hasil scan); tidak bisa dibaca")
    semua = []
    for h, teks in enumerate(teks_hal):
        semua.extend(dasar.parse_halaman(teks, h + 1))
    tak = [r for r in semua if r["jenis"] == "tak_terparse"]

    m_sub = re.search(r"Sub Kegiatan\s*:\s*([\d.]+)\s+(.+)", teks_hal[0])
    m_unit = re.search(r"Unit Organisasi\s*:\s*[\d.]+\s+(.+)", teks_hal[0])
    meta = {"kode_sub": m_sub.group(1) if m_sub else "", "nama_sub": m_sub.group(2).strip() if m_sub else "",
            "satker": m_unit.group(1).strip() if m_unit else ""}
    if not meta["kode_sub"]:
        raise ValueError("Bukan PDF 'Cetak RKA Rincian Belanja' SIPD (baris 'Sub Kegiatan' di halaman 1 tidak ditemukan)")
    m_tot = re.search(r"^Jumlah\s*:\s*Rp\.?\s*([\d.,]+)", teks_hal[-1], re.M)
    total_pdf = dasar.parse_rupiah(m_tot.group(1)) if m_tot else None

    rekening, paket = susun_paket(semua, meta["kode_sub"])
    masalah, ring = validasi(rekening, paket, total_pdf, True)
    for t in tak:
        masalah.append(f"TAK TERPARSE hal {t['halaman']}: {t['teks'][:100]}")

    h = hashlib.sha256(pdf.read_bytes()).hexdigest()
    did = simpan(nama_asli, h, meta, rekening, paket, total_pdf, not masalah, n_hal)
    xlsx = AKAR / f"sipd_semualembar_{meta['kode_sub']}.xlsx"
    ekspor_excel(xlsx, meta, rekening, paket, masalah)

    dua = [p for p in paket if len(p["specs"]) > 1]
    kat = {}
    for p in paket:
        k = f"{p['kategori_mak'] or '-'} / {p['jenis']}"
        kat[k] = kat.get(k, 0) + 1
    hasil = {"berkas": nama_asli, "kode_sub": meta["kode_sub"], "nama_sub": meta["nama_sub"], "satker": meta["satker"],
             "halaman": n_hal, "rekening": len(rekening), "paket": ring["paket"], "spesifikasi": ring["spesifikasi"],
             "tak_terparse": len(tak), "total_pdf": total_pdf, "sum_paket": ring["sum_paket"], "dua_spesifikasi": len(dua),
             "kategori": dict(sorted(kat.items())), "masalah": masalah, "lolos": not masalah,
             "excel": xlsx.name, "dokumen_id": did}
    log(f"PDF: {nama_asli}\nSub kegiatan: {meta['kode_sub']} {meta['nama_sub']}\nSatker: {meta['satker']}")
    log(f"halaman={n_hal} rekening={len(rekening)} paket={ring['paket']} spesifikasi={ring['spesifikasi']} tak_terparse={len(tak)}")
    log(f"total PDF={total_pdf} sum(paket)={ring['sum_paket']} | paket dengan >1 spesifikasi: {len(dua)}")
    log(f"kategori/jenis: {hasil['kategori']}")
    log("--- validasi ---")
    for m in masalah:
        log("SELISIH " + m)
    if not masalah:
        log("OK  semua validasi lolos (paket, total dokumen, rekening, koefisien x harga)")
    log(f"DB: {DB} (dokumen_id={did})\nExcel: {xlsx}")
    return hasil


HALAMAN_UNGGAH = """<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SIPD: baca PDF RKA Rincian</title>
<style>
:root{--bg:#f6f8f6;--kartu:#fff;--teks:#1b2a1f;--redup:#5c6d61;--hijau:#1f7a4d;--garis:#d9e2db;--merah:#b3261e;--kuning:#8a6100}
@media (prefers-color-scheme:dark){:root{--bg:#121a15;--kartu:#1a251e;--teks:#e6efe8;--redup:#9bb0a1;--hijau:#4cc38a;--garis:#2b3a31;--merah:#ff8a80;--kuning:#e8c15a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--teks);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 4px}p.s{color:var(--redup);margin:0 0 18px}
.kartu{background:var(--kartu);border:1px solid var(--garis);border-radius:16px;padding:18px;margin-bottom:14px}
#zona{border:2px dashed var(--garis);border-radius:16px;padding:28px;text-align:center;cursor:pointer}
#zona.on{border-color:var(--hijau)}button{background:var(--hijau);color:#fff;border:0;border-radius:999px;padding:9px 18px;font:inherit;cursor:pointer}
button.l{background:transparent;color:var(--teks);border:1px solid var(--garis)}button:disabled{opacity:.5;cursor:default}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:6px 8px;border-bottom:1px solid var(--garis);text-align:left;vertical-align:top}
.ok{color:var(--hijau);font-weight:600}.gagal{color:var(--merah);font-weight:600}.sel{color:var(--kuning);font-weight:600}
small{color:var(--redup)}a{color:var(--hijau)}ul{margin:6px 0 0;padding-left:18px}
</style></head><body><main>
<h1>Baca PDF SIPD (RKA Rincian Belanja)</h1>
<p class="s">Pilih satu atau banyak PDF. Hanya membaca isi PDF apa adanya: tanpa koreksi nama dan tanpa pencocokan ke SiRUP/SPSE. Berkas diproses di komputer ini saja.</p>
<div class="kartu"><div id="zona">Klik di sini untuk memilih PDF (boleh lebih dari satu), atau seret berkas ke sini<br><small id="dipilih">Belum ada berkas dipilih</small></div>
<input id="berkas" type="file" accept="application/pdf,.pdf" multiple hidden>
<p style="margin:14px 0 0"><button id="mulai" disabled>Baca PDF</button> <button id="reset" class="l" disabled>Kosongkan</button></p></div>
<div id="hasil"></div>
<div class="kartu"><button id="tutup" class="l">Selesai - hentikan program</button> <small>Hasil tersimpan di sipd_coba_semua.db dan berkas Excel di folder skrip.</small></div>
</main><script>
const T="__TOKEN__";let daftar=[];const $=i=>document.getElementById(i);
const rp=n=>n==null?"-":"Rp "+Number(n).toLocaleString("id-ID");
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function tampil(){$("dipilih").textContent=daftar.length?daftar.length+" berkas: "+daftar.map(f=>f.name).join(", "):"Belum ada berkas dipilih";$("mulai").disabled=!daftar.length;$("reset").disabled=!daftar.length}
function tambah(fs){for(const f of fs){if(/\\.pdf$/i.test(f.name)&&!daftar.some(x=>x.name===f.name&&x.size===f.size))daftar.push(f)}tampil()}
$("zona").onclick=()=>$("berkas").click();$("berkas").onchange=e=>{tambah(e.target.files);e.target.value=""};
$("zona").ondragover=e=>{e.preventDefault();$("zona").classList.add("on")};$("zona").ondragleave=()=>$("zona").classList.remove("on");
$("zona").ondrop=e=>{e.preventDefault();$("zona").classList.remove("on");tambah(e.dataTransfer.files)};
$("reset").onclick=()=>{daftar=[];tampil()};
$("tutup").onclick=async()=>{await fetch("/selesai?t="+T,{method:"POST"}).catch(()=>{});document.body.innerHTML="<main><h1>Program dihentikan</h1><p class='s'>Jendela ini boleh ditutup.</p></main>"};
function kartu(h){const st=h.lolos?'<span class="ok">LOLOS</span>':'<span class="sel">ADA SELISIH ('+h.masalah.length+')</span>';
 let k=Object.entries(h.kategori).map(([a,b])=>esc(a)+": "+b).join(" &middot; ");
 let m=h.masalah.length?"<ul>"+h.masalah.slice(0,15).map(x=>"<li>"+esc(x)+"</li>").join("")+(h.masalah.length>15?"<li>... dan "+(h.masalah.length-15)+" lainnya</li>":"")+"</ul>":"";
 return '<div class="kartu"><b>'+esc(h.berkas)+'</b> '+st+'<table><tr><th>Sub kegiatan</th><td>'+esc(h.kode_sub)+' '+esc(h.nama_sub)+'</td></tr><tr><th>Satker</th><td>'+esc(h.satker)+'</td></tr>'
 +'<tr><th>Isi</th><td>'+h.halaman+' halaman, '+h.paket+' paket, '+h.spesifikasi+' spesifikasi ('+h.dua_spesifikasi+' paket bertanda ; karena 2 spesifikasi), tidak terbaca: '+h.tak_terparse+'</td></tr>'
 +'<tr><th>Total</th><td>PDF '+rp(h.total_pdf)+' &middot; jumlah paket '+rp(h.sum_paket)+'</td></tr><tr><th>Kategori</th><td>'+k+'</td></tr></table>'+m
 +'<p style="margin:10px 0 0"><a href="/unduh?t='+T+'&f='+encodeURIComponent(h.excel)+'">Unduh Excel ('+esc(h.excel)+')</a></p></div>'}
$("mulai").onclick=async()=>{$("mulai").disabled=true;$("reset").disabled=true;const out=$("hasil");out.innerHTML="";
 for(let i=0;i<daftar.length;i++){const f=daftar[i];const bar=document.createElement("div");bar.className="kartu";bar.innerHTML="Membaca "+(i+1)+"/"+daftar.length+": "+esc(f.name)+" ...";out.appendChild(bar);
  try{const r=await fetch("/baca?t="+T,{method:"POST",headers:{"X-Nama":encodeURIComponent(f.name),"Content-Type":"application/pdf"},body:f});const j=await r.json();
   if(!r.ok)throw new Error(j.galat||r.status);bar.outerHTML=kartu(j)}catch(e){bar.innerHTML='<b>'+esc(f.name)+'</b> <span class="gagal">GAGAL</span><br>'+esc(e.message)}}
 daftar=[];tampil()};
</script></body></html>"""


def jalankan_browser():
    """Server lokal (hanya 127.0.0.1) + halaman pemilih PDF di browser bawaan (Mac/Windows/Linux). Banyak PDF sekaligus."""
    import json
    import secrets
    import tempfile
    import threading
    import webbrowser
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlparse

    token = secrets.token_urlsafe(16)
    kunci = threading.Lock()                       # SQLite/Excel satu-satu
    batas = 300 * 1024 * 1024
    tmp = Path(tempfile.mkdtemp(prefix="sipd_pdf_"))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _kirim(self, kode, tipe, data, tambahan=None):
            self.send_response(kode)
            self.send_header("Content-Type", tipe)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (tambahan or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _sah(self, q):
            return q.get("t", [""])[0] == token

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/":
                self._kirim(200, "text/html; charset=utf-8", HALAMAN_UNGGAH.replace("__TOKEN__", token).encode())
            elif u.path == "/unduh" and self._sah(q):
                nama = Path(q.get("f", [""])[0]).name                    # hanya nama berkas, tanpa folder
                f = AKAR / nama
                if re.fullmatch(r"sipd_semualembar_[\d.]+\.xlsx", nama) and f.exists():
                    self._kirim(200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f.read_bytes(),
                                {"Content-Disposition": f'attachment; filename="{nama}"'})
                else:
                    self._kirim(404, "text/plain", b"tidak ada")
            else:
                self._kirim(404, "text/plain", b"tidak ada")

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._sah(q):
                return self._kirim(403, "application/json", b'{"galat":"token salah"}')
            if u.path == "/selesai":
                self._kirim(200, "application/json", b"{}")
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if u.path != "/baca":
                return self._kirim(404, "application/json", b'{"galat":"tidak ada"}')
            from urllib.parse import unquote
            n = int(self.headers.get("Content-Length") or 0)
            nama = unquote(self.headers.get("X-Nama", "berkas.pdf"))
            nama = Path(nama.replace("\\", "/")).name or "berkas.pdf"
            if n <= 0 or n > batas:
                return self._kirim(413, "application/json", json.dumps({"galat": "ukuran berkas tidak valid"}).encode())
            data = self.rfile.read(n)
            if not data.startswith(b"%PDF"):
                return self._kirim(400, "application/json", json.dumps({"galat": "bukan berkas PDF"}).encode())
            f = tmp / f"{secrets.token_hex(6)}.pdf"
            f.write_bytes(data)
            try:
                with kunci:
                    hasil = proses_pdf(f, nama_asli=nama, log=lambda s: print("   " + s.replace("\n", "\n   ")))
                self._kirim(200, "application/json", json.dumps(hasil).encode())
            except Exception as e:                                         # laporkan ke halaman, jangan matikan server
                print(f"GAGAL {nama}: {e}")
                self._kirim(422, "application/json", json.dumps({"galat": str(e)}).encode())
            finally:
                f.unlink(missing_ok=True)

    srv = None
    for port in (8780, 8781, 8782, 0):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), H)
            break
        except OSError:
            continue
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"Halaman pemilih PDF: {url}\n(Tekan Ctrl+C atau klik 'Selesai' di browser untuk berhenti)")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        for f in tmp.glob("*"):
            f.unlink(missing_ok=True)
        try:
            tmp.rmdir()
        except OSError:
            pass
    return 0


def main():
    dasar.pastikan_pustaka()
    berkas = [Path(a) for a in sys.argv[1:]]
    if not berkas:
        return jalankan_browser()
    kode = 0
    for pdf in berkas:
        try:
            hasil = proses_pdf(pdf)
            kode = kode or (0 if hasil["lolos"] else 1)
        except Exception as e:
            print(f"GAGAL {pdf}: {e}")
            kode = 1
        print()
    return kode


if __name__ == "__main__":
    sys.exit(main())
