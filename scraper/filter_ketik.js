/* Filter yang BISA DIKETIK: setiap <select data-f="..."> (filter tabel) diubah menjadi kotak isian dengan daftar pilihan (datalist).
   Klik kotaknya untuk melihat semua pilihan, atau ketik sebagian nama untuk menyaring; Enter/pilih untuk menerapkan.
   Kode halaman tidak perlu diubah: elemen baru tetap membawa data-f, dan `.value`-nya tetap nilai pilihan (bukan teks tampilan). */
(function () {
  const asli = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  let urutan = 0;

  function ubah(sel) {
    if (!sel.isConnected || sel.dataset.ketik) return;
    const opsi = [...sel.options].map((o) => ({ v: o.value, l: o.textContent.trim() }));
    if (!opsi.length) return;
    const input = document.createElement("input"), dl = document.createElement("datalist");
    dl.id = "dl_ketik_" + (++urutan);
    opsi.forEach((o) => { const op = document.createElement("option"); op.value = o.l; dl.appendChild(op); });
    input.type = "text"; input.className = (sel.className ? sel.className + " " : "") + "ketik";
    input.setAttribute("list", dl.id); input.setAttribute("autocomplete", "off"); input.spellcheck = false;
    input.title = "Klik untuk melihat pilihan, atau ketik untuk mencari";
    for (const a of sel.attributes) if (a.name.startsWith("data-")) input.setAttribute(a.name, a.value);
    input.dataset.ketik = "1";
    let cur = opsi.find((o) => o.v === sel.value) || opsi[0];
    asli.set.call(input, cur.l);
    Object.defineProperty(input, "value", {                          // .value = nilai pilihan, bukan teks yang terlihat
      configurable: true,
      get() { return cur.v; },
      set(v) { const o = opsi.find((x) => x.v === String(v)); if (o) { cur = o; asli.set.call(input, o.l); } },
    });
    const pulih = () => asli.set.call(input, cur.l);
    input.addEventListener("focus", () => { input.placeholder = cur.l; asli.set.call(input, ""); });     // kosongkan agar semua pilihan tampil
    input.addEventListener("blur", () => { if (!asli.get.call(input).trim()) pulih(); });
    input.addEventListener("change", (e) => {
      const t = asli.get.call(input).trim().toLowerCase();
      const persis = opsi.find((x) => x.l.toLowerCase() === t);
      const mirip = t ? opsi.filter((x) => x.l.toLowerCase().includes(t)) : [];
      const awalan = t ? opsi.filter((x) => x.l.toLowerCase().startsWith(t)) : [];            // "jal" -> "Jalan" bila satu-satunya yang berawalan itu
      const o = persis || (awalan.length === 1 ? awalan[0] : null) || (mirip.length === 1 ? mirip[0] : null);
      if (!o) { e.stopImmediatePropagation(); pulih(); return; }     // teks tidak cocok: abaikan, kembalikan pilihan semula
      cur = o; pulih();
    });
    input.addEventListener("keydown", (e) => { if (e.key === "Escape") { pulih(); input.blur(); } });
    sel.replaceWith(input);
    input.after(dl);
  }

  const pindai = () => document.querySelectorAll("select[data-f]").forEach(ubah);
  new MutationObserver(pindai).observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener("DOMContentLoaded", pindai);
  pindai();
})();
