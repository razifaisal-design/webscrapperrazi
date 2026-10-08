/* Pembantu bersama untuk halaman SPSE dan Perbandingan (halaman SiRUP punya kodenya sendiri). */
const $ = (id) => document.getElementById(id);
const rp = new Intl.NumberFormat("id-ID");
const fmt = (n) => (n === null || n === undefined || n === "") ? "–" : "Rp " + rp.format(Math.round(n));
function ringkas(n) {
  n = n || 0;
  const t = (x, s) => "Rp " + x.toLocaleString("id-ID", { maximumFractionDigits: 2 }) + " " + s;
  if (Math.abs(n) >= 1e12) return t(n / 1e12, "T");
  if (Math.abs(n) >= 1e9) return t(n / 1e9, "M");
  if (Math.abs(n) >= 1e6) return t(n / 1e6, "jt");
  return "Rp " + rp.format(Math.round(n));
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const simpan = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
const baca = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } };
const unik = (arr) => [...new Set(arr.filter((x) => x !== null && x !== undefined && x !== ""))].sort();
const BLN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
/* '2026-08-19T20:00' -> '19 Agu 2026 20:00' */
function tgl(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(iso || "");
  return m ? `${+m[3]} ${BLN[+m[2] - 1]} ${m[1]}${m[4] ? ` ${m[4]}:${m[5]}` : ""}` : "";
}
const selisihTag = (n) => (n === null || n === undefined) ? "–" : n === 0 ? "–" : `<span class="${n < 0 ? "beda" : "pos"}">${n > 0 ? "+" : "−"}${fmt(Math.abs(n))}</span>`;
const seg = (kunci, opsi, nilai) => `<span class="seg">${opsi.map((o) => { const [v, l] = Array.isArray(o) ? o : [o, o];
  return `<button data-f="${kunci}" data-v="${esc(v)}" class="${String(v) === String(nilai) ? "aktif" : ""}">${esc(l)}</button>`; }).join("")}</span>`;
const sel = (kunci, label, opsi, nilai) => `<label class="flab">${esc(label)}<select data-f="${kunci}">${opsi.map((o) => { const [v, l] = Array.isArray(o) ? o : [o, o];
  return `<option value="${esc(v)}" ${String(v) === String(nilai) ? "selected" : ""}>${esc(l)}</option>`; }).join("")}</select></label>`;

function durasi(d) {
  d = Math.max(0, Math.round(d));
  if (d < 60) return `${d} detik`;
  const m = Math.round(d / 60);
  if (m < 60) return `±${m} menit`;
  const j = Math.floor(m / 60), mm = m % 60;
  return `±${j} jam${mm ? ` ${mm} menit` : ""}`;
}
function jamPukul(ms) {
  const t = new Date(ms), kini = new Date();
  const jam = t.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
  const hari = t.toDateString() === kini.toDateString() ? "" : ` (${t.toLocaleDateString("id-ID", { day: "numeric", month: "short" })})`;
  return `pukul <b>${jam}</b>${hari}`;
}
const PERMINTAAN = (jeda) => jeda + 0.3;                 // perkiraan detik per permintaan = jeda + waktu respons

/* Pengelola tugas latar belakang (tombol Ambil, Hentikan, polling /api/tugas). */
function postTugas(jalur, badan) {
  return fetch(jalur, { method: "POST", headers: { "Content-Type": "application/json", "X-Pantau": "1" }, body: JSON.stringify(badan || {}) });
}
const NAMA_STATUS = { berjalan: "Berjalan", selesai: "Selesai", gagal: "Gagal / ditolak server", dihentikan: "Dihentikan" };
function pasangTugas(o) {
  const S = { poll: null, status: "idle", t: null };
  const nampak = (t) => t && String(t.jenis || "").startsWith(o.awalan);
  function gambar(t) {
    S.t = t;
    const milik = nampak(t), jalan = t.status === "berjalan";
    $(o.mulai).disabled = jalan; $(o.henti).disabled = !jalan;
    const tahapTeks = t.tahap_ke ? `Tahap ${t.tahap_ke}/${t.tahap_total}: ${t.tahap_nama}` : "Daftar paket";
    $("jobTeks").textContent = jalan ? `● ${milik ? tahapTeks : "Tugas lain berjalan"}${milik && t.total ? ` ${t.selesai}/${t.total}` : "…"}` : "";
    o.render(t, milik);
    if (t.status === "idle" || !milik) { $("a-status").innerHTML = jalan && !milik ? `<div class="note warn" style="margin-top:10px">Ada tugas lain yang sedang berjalan (${esc(t.jenis)}, tahun ${esc(t.tahun)}). Tunggu selesai atau hentikan.</div>` : ""; return; }
    const persen = t.total ? Math.round(t.selesai * 100 / t.total) : 0;
    $("a-status").innerHTML = `<div class="sub" style="margin-top:10px"><b>${NAMA_STATUS[t.status] || t.status}</b> · ${tahapTeks} · tahun ${t.tahun} · ${t.koneksi} koneksi, jeda ${t.jeda} detik` +
      (t.total ? ` · ${t.selesai}/${t.total} (berhasil ${t.ok}, gagal ${t.gagal})` : "") + `</div>` +
      (t.total ? `<div class="progress"><i style="width:${persen}%"></i></div>` : "") +
      (t.peringatan ? `<div class="note warn" style="margin-top:8px">${esc(t.peringatan)}</div>` : "") +
      `<pre class="log" id="a-log">${esc((t.log || []).slice(-14).join("\n"))}</pre>`;
    const lg = $("a-log"); if (lg) lg.scrollTop = lg.scrollHeight;
  }
  async function cek() {
    try {
      const t = await (await fetch("/api/tugas", { cache: "no-store" })).json();
      $("basi").hidden = !t.kode_basi;
      const sebelum = S.status; S.status = t.status; gambar(t);
      if (t.status === "berjalan") mulaiPoll();
      else { clearInterval(S.poll); S.poll = null; if (sebelum === "berjalan" && o.selesai) await o.selesai(t); }
    } catch (e) {}
  }
  function mulaiPoll() { if (!S.poll) S.poll = setInterval(cek, 1000); }
  async function mulai() {
    try {
      const r = await postTugas("/api/tugas/mulai", o.badan());
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.status);
      gambar(j); mulaiPoll();
    } catch (e) { $("a-status").innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
  }
  $(o.mulai).addEventListener("click", mulai);
  $(o.henti).addEventListener("click", () => postTugas("/api/tugas/henti").then(cek));
  cek();
  setInterval(() => { if (!S.poll && !document.hidden) cek(); }, 15000);     // periksa kode basi walau tidak ada tugas
  return { cek, state: S };
}

/* Ambil data dari server dengan penanda 'sedang' agar auto-refresh tidak menumpuk. */
async function ambilJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.status);
  return j;
}
