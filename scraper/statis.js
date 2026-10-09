/* Mode salinan publik (hanya baca): menggantikan pemanggilan /api/... dengan berkas JSON hasil ekspor (folder data/).
   Dimuat paling awal supaya fetch sudah diganti sebelum skrip halaman berjalan. */
(function () {
  const BASE = location.href.replace(/[?#].*$/, "").replace(/[^/]*$/, "");
  const asli = window.fetch.bind(window);
  const cache = {};
  // Sumber data: Supabase (window.PANTAU_SUPABASE diisi saat terbit) atau berkas lokal data/ (ekspor statis biasa)
  const SB = window.PANTAU_SUPABASE || null;
  const sbPermintaan = (nama, kolom, terima) => asli(`${SB.url}/rest/v1/publik_berkas?nama=eq.${encodeURIComponent(nama)}&select=${kolom}`,
    { headers: { apikey: SB.kunci, Accept: terima } });
  const ambil = (nama) => SB
    ? sbPermintaan(nama, "isi", "application/vnd.pgrst.object+json").then(async (r) => {
        if (!r.ok) throw new Error("tidak ada di salinan publik: " + nama);
        return (await r.json()).isi;
      })
    : asli(BASE + "data/" + nama).then((r) => {
        if (!r.ok) throw new Error("tidak ada di salinan publik: " + nama);
        return r.json();
      });
  const muat = (nama) => cache[nama] || (cache[nama] = ambil(nama).catch((e) => { delete cache[nama]; throw e; }));
  async function unduhBerkas(nama) {
    if (!SB) { location.href = BASE + "data/" + nama; return; }
    let j;
    try { j = await muat(nama); } catch (e) { alert("Berkas belum tersedia: " + nama); return; }
    const bin = atob(j.base64), byte = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) byte[i] = bin.charCodeAt(i);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([byte], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    a.download = nama;
    document.body.appendChild(a); a.click(); a.remove();
    delete cache[nama];                                       // jangan simpan berkas besar di memori
  }

  const jawab = (obj, status) => new Response(JSON.stringify(obj), { status: status || 200, headers: { "Content-Type": "application/json" } });
  const norm = (s) => String(s || "").toUpperCase().split(/\s+/).filter(Boolean).join(" ");

  async function api(u) {
    const p = u.pathname, q = u.searchParams, meta = await muat("meta.json");
    const targetBawaan = (meta.target.find((t) => t.bawaan) || meta.target[0]).target;
    if (p === "/api/tugas") return { status: "idle", jenis: null, tahun: null, selesai: 0, total: 0, ok: 0, gagal: 0, log: [], kode_basi: false };
    if (p === "/api/satker") return muat("satker.json");
    if (p === "/api/jalan" || p === "/api/statistik") return muat(`${p.slice(5)}_${q.get("target") || targetBawaan}.json`);
    if (["/api/rekap", "/api/database", "/api/perubahan"].includes(p)) {
      const t = q.get("target") || targetBawaan;
      return muat(`${p.slice(5)}_${t}_${q.get("tahun") || meta.bawaan[t]}.json`);
    }
    if (p === "/api/spse/jadwal") return { kode_paket: q.get("kode"), jadwal: (await muat("jadwal_spse.json"))[q.get("kode")] || [] };
    if (p === "/api/spse") return spse(q, meta);
    if (p === "/api/banding") return banding(q, meta);
    throw new Error("tidak tersedia di salinan publik");
  }

  async function spse(q, meta) {
    const th = q.get("tahun") || String(meta.bawaan.spse), satker = q.get("satker") || "", sk = satker ? norm(satker) : null;
    const tahunList = th === "semua" ? meta.tahun_spse : [Number(th)];
    const bagian = await Promise.all(tahunList.map((y) => muat(`spse_${y}.json`)));
    const semua = bagian.flatMap((d) => d.baris), daftar = {};
    for (const b of semua) if (b.is_active && b.ada_detail) {
      const e = daftar[norm(b.satker)] || (daftar[norm(b.satker)] = { nama: b.satker, paket: 0, lengkap: 0 });
      e.paket++; e.lengkap += b.lengkap ? 1 : 0;
    }
    const baris = semua.filter((b) => sk === null || (b.ada_detail && norm(b.satker) === sk));
    const aktif = baris.filter((b) => b.is_active), lengkap = aktif.filter((b) => b.lengkap);
    const jum = (f) => lengkap.reduce((s, b) => s + (b[f] || 0), 0);
    return {
      lpse: bagian[0].lpse, jenis: "nontender", tahun: meta.tahun_spse, tahun_bawaan: meta.bawaan.spse, tahun_dipilih: th === "semua" ? "semua" : Number(th),
      satker: satker || null, satker_daftar: Object.values(daftar).sort((a, b) => a.nama.localeCompare(b.nama)),
      satker_belum_dicek: semua.filter((b) => b.is_active && !b.ada_detail).length, satker_sirup: [], rinci: "__semua", baris,
      ringkas: { paket_aktif: aktif.length, dengan_detail: aktif.filter((b) => b.ada_detail).length, terinci: lengkap.length, pagu: jum("pagu"), hps: jum("hps"),
                 harga_penawaran: jum("harga_penawaran"), hasil_negosiasi: jum("hasil_negosiasi"), nilai_kontrak: jum("nilai_kontrak"),
                 kontrak_terisi: lengkap.filter((b) => b.kontrak_terisi).length, pemenang_terisi: lengkap.filter((b) => b.pemenang_terisi).length,
                 jadwal_diubah: lengkap.filter((b) => b.jadwal_diubah).length, perlu_rinci: 0, perlu_lain: 0, alasan: {},
                 terakhir_detail: bagian.map((d) => d.ringkas.terakhir_detail).filter(Boolean).sort().pop() || null },
    };
  }

  function ringkasBanding(baris) {
    const per = {};
    for (const b of baris) { const e = per[b.status] || (per[b.status] = { jumlah: 0, pagu_sirup: 0 }); e.jumlah++; e.pagu_sirup += b.pagu_sirup || 0; }
    const cocok = baris.filter((b) => b.kode_nontender && b.pagu_sama !== null && b.pagu_sama !== undefined);
    return { per_status: per, total: baris.length, berpasangan: baris.filter((b) => b.kode_nontender && b.kode_rup).length,
             pagu_beda: cocok.filter((b) => !b.pagu_sama).length, pagu_sama: cocok.filter((b) => b.pagu_sama).length,
             jadwal_diubah: baris.filter((b) => (b.jadwal_diubah || 0) > 0).length, kontrak_terisi: baris.filter((b) => b.kontrak_terisi).length,
             pemenang_terisi: baris.filter((b) => b.pemenang_terisi).length };
  }

  async function banding(q, meta) {
    const th = q.get("tahun") || String(meta.bawaan.spse), satker = q.get("satker") || "", sk = satker ? norm(satker) : null;
    const tahunList = th === "semua" ? meta.tahun_spse.slice().reverse() : [Number(th)];
    const bagian = await Promise.all(tahunList.map((y) => muat(`banding_${y}.json`)));
    const baris = bagian.flatMap((d) => d.baris).filter((b) => sk === null || norm(b.satker) === sk), daftar = {};
    for (const d of bagian) for (const e of d.satker_daftar) {
      const x = daftar[norm(e.nama)] || (daftar[norm(e.nama)] = { nama: e.nama, paket_spse: 0, ada_sirup: false });
      x.paket_spse += e.paket_spse; x.ada_sirup = x.ada_sirup || e.ada_sirup;
    }
    let peringatan = [...new Set(bagian.flatMap((d) => d.peringatan))];
    if (sk !== null) peringatan = peringatan.filter((p) => !/belum diambil, jadi hanya ditampilkan dari sisi SPSE/.test(p));
    return { baris, ringkas: ringkasBanding(baris), peringatan, satker_daftar: Object.values(daftar).sort((a, b) => a.nama.localeCompare(b.nama)),
             tahun: bagian[0].tahun, tahun_bawaan: meta.bawaan.spse, tahun_dipilih: th === "semua" ? "semua" : Number(th), satker: satker || null, lpse: bagian[0].lpse };
  }

  window.fetch = async function (url, opt) {
    const u = new URL(typeof url === "string" ? url : url.url, location.href);
    if (!u.pathname.startsWith("/api/")) return asli(url, opt);
    if (opt && opt.method && opt.method.toUpperCase() !== "GET") return jawab({ error: "Ini salinan publik (hanya baca): pengambilan data hanya bisa dari dashboard lokal." }, 403);
    try { return jawab(await api(u)); }
    catch (e) { return jawab({ error: "Data ini tidak ada di salinan publik (" + e.message + ")." }, 404); }
  };

  // Unduhan Excel: berkas yang sudah dibuat saat ekspor (semua satker; gunakan filter Excel untuk satu satker)
  document.addEventListener("click", async (e) => {
    const a = e.target.closest && e.target.closest("a[href^='/api/']");
    if (!a) return;
    e.preventDefault();
    const u = new URL(a.getAttribute("href"), location.href), q = u.searchParams, meta = await muat("meta.json");
    const bawaan = (meta.target.find((t) => t.bawaan) || meta.target[0]).target, th = q.get("tahun") || meta.bawaan.spse;
    const berkas = u.pathname === "/api/spse/excel" ? `spse_${th}.xlsx` : u.pathname === "/api/banding/excel" ? `banding_${th}.xlsx`
      : u.pathname === "/api/excel" ? `excel_${q.get("target") || bawaan}_${q.get("tahun") || meta.bawaan[q.get("target") || bawaan]}.xlsx` : null;
    if (berkas) unduhBerkas(berkas);
  }, true);

  document.addEventListener("DOMContentLoaded", async () => {
    const gaya = document.createElement("style");
    gaya.textContent = "#bukaAmbil,#ambil,#bukaPeriksa,#periksa,#pb,#basi,#jobTeks,#interval,label[for=interval]{display:none!important}" +
      ".publik{background:var(--accent-soft);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:8px 14px;margin-bottom:12px;font-size:13px}";
    document.head.appendChild(gaya);
    try {
      const meta = await muat("meta.json"), w = document.querySelector(".wrap");
      const tgl = new Date(meta.dibuat).toLocaleString("id-ID", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
      const info = document.createElement("div");
      info.className = "publik";
      info.innerHTML = `<b>Salinan publik (hanya baca)</b> · data per ${tgl} · sumber: SiRUP dan SPSE LKPP (data publik). Halaman ini tidak mengambil data baru.`;
      if (w) w.insertBefore(info, w.firstChild.nextSibling || w.firstChild);
    } catch (e) {}
  });
})();
