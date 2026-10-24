/* ═══════════════════════════════════════════════════════════
   notif.js — Notifikasi Risena Dashboard
   Dimuat SETELAH app.js dan mobile.js. Tidak mengubah logika app.js;
   hanya MEMBACA data global (products, materials, prices, cashflows)
   dan mengambil /api/consignments sendiri.

   Jenis notifikasi:
   • Stok produk & bahan  → stok ≤ minimum / habis
   • Margin               → margin < batas (default 15%) / harga jual di bawah HPP
   • Laporan keuangan     → ringkasan tiap 1 / 3 / 6 bulan (periode kalender)
   • Konsinyasi           → jatuh tempo (H-7 default) & lewat jatuh tempo
═══════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const KEY = 'risena_notif';
  const mq  = window.matchMedia('(max-width:768px)');
  const isMobile = () => mq.matches;
  const DAY = 86400000;

  // ── Ikon (stroke, viewBox 24) ─────────────────────────────
  const I = {
    bell:   '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    stok:   '<path d="M21 8l-9-5-9 5v8l9 5 9-5V8z"/><path d="M3.3 7.5L12 12.5l8.7-5"/><path d="M12 22V12.5"/>',
    bahan:  '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/>',
    margin: '<path d="M5 19L19 5"/><circle cx="7" cy="7" r="2.2"/><circle cx="17" cy="17" r="2.2"/>',
    laporan:'<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z"/><path d="M14 3v5h5"/><path d="M9 17v-3M12 17v-5M15 17v-2"/>',
    konsinyasi:'<path d="M4 9l1.5-5h13L20 9"/><path d="M4 9a2.7 2.7 0 0 0 5.3 0 2.7 2.7 0 0 0 5.4 0A2.7 2.7 0 0 0 20 9"/><path d="M5 12v8h14v-8"/><path d="M10 20v-5h4v5"/>',
    checks: '<path d="M2 12l5 5L18 6"/><path d="M12 16l1 1L22 7"/>',
    tune:   '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
    back:   '<path d="M15 6l-6 6 6 6"/>',
    ok:     '<path d="M20 6L9 17l-5-5"/>'
  };
  const svg = (k, cls) => `<svg viewBox="0 0 24 24" aria-hidden="true"${cls ? ` class="${cls}"` : ''}>${I[k]}</svg>`;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));

  // ── State tersimpan (dibaca / pengaturan) ─────────────────
  const DEF = { r1:true, r3:true, r6:true, margin:15, ksDays:7 };
  let st = { read:{}, set:Object.assign({}, DEF) };
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (raw) st = { read: raw.read || {}, set: Object.assign({}, DEF, raw.set || {}) };
  } catch (e) {}
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {} };

  let items = [];          // notifikasi aktif
  let filter = 'all';
  let view = 'list';       // 'list' | 'settings'
  let lastCount = null;
  let ksCache = { at:0, list:[] };
  let panel, overlay, openBell = null;

  // ── Logika notifikasi ─────────────────────────────────────
  const fmtMoney = n => (typeof fmtK === 'function' ? fmtK(n) : 'Rp ' + Math.round(n).toLocaleString('id-ID'));
  const fmtMoneyFull = n => (typeof fmt === 'function' ? fmt(n) : 'Rp ' + Math.round(n).toLocaleString('id-ID'));
  const num = n => (typeof fmtNum === 'function' ? fmtNum(n) : String(n));
  const sevOrder = { danger:0, warn:1, info:2 };

  function addMonths(d, m) { const x = new Date(d.getTime()); x.setMonth(x.getMonth() + m); return x; }

  function closedPeriods(now) {
    const y = now.getFullYear(), m = now.getMonth(), out = [];
    const mon = d => d.toLocaleDateString('id-ID', { month:'long', year:'numeric' });
    { const s = new Date(y, m - 1, 1), e = new Date(y, m, 1);
      out.push({ n:1, s, e, win:30, label:mon(s) }); }
    { const q = Math.floor(m / 3), s = new Date(y, (q - 1) * 3, 1), e = new Date(y, q * 3, 1);
      out.push({ n:3, s, e, win:45, label:'Kuartal ' + (s.getMonth() / 3 + 1) + ' ' + s.getFullYear() }); }
    { const h = Math.floor(m / 6), s = new Date(y, (h - 1) * 6, 1), e = new Date(y, h * 6, 1);
      out.push({ n:6, s, e, win:60, label:'Semester ' + (s.getMonth() / 6 + 1) + ' ' + s.getFullYear() }); }
    return out.filter(p => (now - p.e) / DAY <= p.win);
  }

  function compute() {
    const out = [], now = new Date(), S = st.set;
    const P = typeof products  !== 'undefined' ? products  : [];
    const M = typeof materials !== 'undefined' ? materials : [];
    const R = typeof prices    !== 'undefined' ? prices    : [];
    const C = typeof cashflows !== 'undefined' ? cashflows : [];

    // 1) Stok produk
    P.forEach(p => {
      if (p.stok > p.minStok) return;
      const empty = p.stok <= 0;
      out.push({ id:`p:${p.id}:${empty ? 0 : 1}`, kind:'stok', icon:'stok', sev:empty ? 'danger' : 'warn', page:'stok',
        title:p.nama, msg:`Sisa ${num(p.stok)} ${p.satuan || 'pcs'} · minimum ${num(p.minStok)}`,
        meta:'Stok produk · ' + (empty ? 'Habis' : 'Menipis') });
    });
    // 2) Stok bahan
    M.forEach(m => {
      if (m.stok > m.minStok) return;
      const empty = m.stok <= 0;
      out.push({ id:`b:${m.id}:${empty ? 0 : 1}`, kind:'stok', icon:'bahan', sev:empty ? 'danger' : 'warn', page:'bahan',
        title:m.nama, msg:`Sisa ${num(m.stok)} ${m.satuan || ''} · minimum ${num(m.minStok)}`.replace(/\s+·/, ' ·'),
        meta:'Stok bahan · ' + (empty ? 'Habis' : 'Menipis') });
    });
    // 3) Margin
    R.forEach(pr => {
      const hpp = (pr.components || []).reduce((a, c) => a + c.harga, 0) + (pr.overhead || 0);
      const mg  = pr.hargaJual > 0 ? Math.round((pr.hargaJual - hpp) / pr.hargaJual * 100) : 0;
      if (mg >= S.margin) return;
      const prod = P.find(x => x.id === pr.produkId);
      const neg = mg < 0;
      out.push({ id:`m:${pr.id}:${neg ? 'neg' : 'low'}`, kind:'margin', icon:'margin', sev:neg ? 'danger' : 'warn', page:'harga',
        title:(prod ? prod.nama : 'Produk') + ' — margin ' + mg + '%',
        msg:`HPP ${fmtMoneyFull(hpp)} · harga jual ${fmtMoneyFull(pr.hargaJual)}`,
        meta:'Margin · ' + (neg ? 'Di bawah HPP' : 'Di bawah ' + S.margin + '%') });
    });
    // 4) Laporan keuangan periodik
    closedPeriods(now).forEach(p => {
      if (!S['r' + p.n]) return;
      const rows = C.filter(c => c.date >= p.s && c.date < p.e);
      if (!rows.length) return;
      const inn = rows.filter(c => c.type === 'in').reduce((a, c) => a + c.amount, 0);
      const outc = rows.filter(c => c.type === 'out').reduce((a, c) => a + c.amount, 0);
      const net = inn - outc;
      out.push({ id:`r:${p.n}:${p.e.getFullYear()}-${p.e.getMonth()}`, kind:'laporan', icon:'laporan', sev:net < 0 ? 'warn' : 'info', page:'cashflow', period:p.n,
        title:'Laporan ' + p.n + ' bulan siap ditinjau',
        msg:`${p.label} · masuk ${fmtMoney(inn)} · keluar ${fmtMoney(outc)} · bersih ${fmtMoney(net)}`,
        meta:'Laporan keuangan · ' + p.label });
    });
    // 5) Konsinyasi: jatuh tempo
    ksCache.list.forEach(k => {
      if (k.status !== 'aktif') return;
      const start = new Date(k.tanggalMulai);
      if (isNaN(start) || !k.durasibulan) return;
      const due = addMonths(start, k.durasibulan);
      const days = Math.ceil((due - now) / DAY);
      if (days > S.ksDays) return;
      const over = days < 0;
      const sisa = Math.max(0, (k.qtySisa != null ? k.qtySisa : (k.qtyTitip - k.qtyTerjual - k.qtyKembali)));
      out.push({ id:`k:${k.id}:${over ? 'over' : 'soon'}`, kind:'konsinyasi', icon:'konsinyasi', sev:over ? 'danger' : 'warn', page:'konsinyasi',
        title:'Konsinyasi ' + k.tempat,
        msg:(over ? `Lewat ${-days} hari dari jatuh tempo` : days === 0 ? 'Jatuh tempo hari ini' : `Jatuh tempo ${days} hari lagi`) +
            ` · ${k.qtyTerjual || 0} terjual, ${sisa} pcs masih di toko. Saatnya tagih hasil penjualan.`,
        meta:'Tagihan konsinyasi · ' + (over ? 'Lewat tempo' : 'Segera jatuh tempo') });
    });

    out.sort((a, b) => sevOrder[a.sev] - sevOrder[b.sev]);
    return out;
  }

  const unread = () => items.filter(n => !st.read[n.id]).length;

  async function loadConsignments(force) {
    if (!force && Date.now() - ksCache.at < 120000) return;
    try {
      const list = await api('/api/consignments');
      if (Array.isArray(list)) ksCache = { at:Date.now(), list };
    } catch (e) { ksCache.at = Date.now(); }
  }

  const loggedIn = () => { const l = document.getElementById('login-screen'); return l && l.classList.contains('hidden'); };

  let busy = false;
  async function refresh(force) {
    if (busy || !loggedIn()) return;
    busy = true;
    try {
      await loadConsignments(force);
      items = compute();
      // buang status "dibaca" untuk kondisi yang sudah selesai, supaya muncul lagi bila terulang
      const hasData = (typeof products !== 'undefined') && (products.length + materials.length + prices.length) > 0;
      if (hasData) {
        const live = new Set(items.map(n => n.id));
        let dirty = false;
        Object.keys(st.read).forEach(k => { if (!live.has(k)) { delete st.read[k]; dirty = true; } });
        if (dirty) save();
      }
      paintBadges();
      if (document.body.classList.contains('nb-open')) paintPanel();
    } finally { busy = false; }
  }

  // ── Bell + badge ──────────────────────────────────────────
  function buildBells() {
    document.querySelectorAll('.page-header').forEach(h => {
      if (h.querySelector('.nb-bell')) return;
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'nb-bell';
      b.setAttribute('aria-label', 'Notifikasi'); b.setAttribute('aria-haspopup', 'dialog');
      b.innerHTML = svg('bell') + '<span class="nb-badge" hidden></span>';
      b.addEventListener('click', e => { e.stopPropagation(); toggle(b); });
      h.appendChild(b);
    });
  }

  function paintBadges() {
    const n = unread();
    document.querySelectorAll('.nb-bell').forEach(b => {
      const bd = b.querySelector('.nb-badge');
      bd.hidden = n === 0;
      bd.textContent = n > 9 ? '9+' : n;
      b.classList.toggle('has-unread', n > 0);
      b.setAttribute('aria-label', n ? `Notifikasi, ${n} belum dibaca` : 'Notifikasi');
      if (lastCount !== null && n > lastCount) {
        b.classList.remove('ring'); void b.offsetWidth; b.classList.add('ring');
      }
    });
    lastCount = n;
  }

  // ── Panel ─────────────────────────────────────────────────
  function buildPanel() {
    overlay = document.createElement('div');
    overlay.className = 'nb-overlay';
    overlay.addEventListener('click', close);
    panel = document.createElement('div');
    panel.className = 'nb-panel';
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', 'Notifikasi'); panel.tabIndex = -1;
    panel.addEventListener('click', onPanelClick);
    document.body.appendChild(overlay);
    document.body.appendChild(panel);
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && document.body.classList.contains('nb-open')) close(); });
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
  }

  const FILTERS = [['all','Semua'], ['stok','Stok'], ['margin','Margin'], ['laporan','Laporan'], ['konsinyasi','Konsinyasi']];

  function paintPanel() {
    if (view === 'settings') return paintSettings();
    const n = unread();
    const shown = items.filter(x => filter === 'all' || x.kind === filter);
    const chips = FILTERS.map(([k, l]) => {
      const c = k === 'all' ? items.length : items.filter(x => x.kind === k).length;
      return `<button type="button" class="nb-chip${filter === k ? ' on' : ''}" data-f="${k}">${l}${k === 'all' && c ? `<i>${c}</i>` : ''}</button>`;
    }).join('');
    const list = shown.length ? shown.map(x => `
      <button type="button" class="nb-item${st.read[x.id] ? '' : ' unread'}" data-id="${esc(x.id)}" data-sev="${x.sev}">
        <span class="nb-ico">${svg(x.icon)}</span>
        <span class="nb-body">
          <span class="nb-title">${esc(x.title)}</span>
          <span class="nb-msg">${esc(x.msg)}</span>
          <span class="nb-meta">${esc(x.meta)}</span>
        </span>
        ${st.read[x.id] ? '' : '<span class="nb-dot" aria-label="Belum dibaca"></span>'}
      </button>`).join('') : `
      <div class="nb-empty">
        <span class="nb-empty-ico">${svg('ok')}</span>
        <strong>Semua aman</strong>
        <span>${filter === 'all' ? 'Tidak ada yang perlu perhatian saat ini.' : 'Tidak ada notifikasi di kategori ini.'}</span>
      </div>`;
    panel.innerHTML = `
      <div class="nb-head">
        <div class="nb-head-t"><strong>Notifikasi</strong><span>${n ? n + ' belum dibaca' : 'Semua sudah dibaca'}</span></div>
        <button type="button" class="nb-ib" data-a="readall" title="Tandai semua dibaca" aria-label="Tandai semua dibaca"${n ? '' : ' disabled'}>${svg('checks')}</button>
        <button type="button" class="nb-ib" data-a="settings" title="Atur pengingat" aria-label="Atur pengingat">${svg('tune')}</button>
      </div>
      <div class="nb-chips">${chips}</div>
      <div class="nb-list">${list}</div>`;
  }

  function paintSettings() {
    const S = st.set;
    const sw = (k, t, d) => `
      <div class="nb-row"><div><strong>${t}</strong><span>${d}</span></div>
        <button type="button" class="nb-sw${S[k] ? ' on' : ''}" role="switch" aria-checked="${!!S[k]}" data-sw="${k}" aria-label="${t}"><i></i></button></div>`;
    const sel = (k, t, d, opts, suf) => `
      <div class="nb-row"><div><strong>${t}</strong><span>${d}</span></div>
        <select class="nb-sel" data-sel="${k}" aria-label="${t}">${opts.map(o => `<option value="${o}"${+S[k] === o ? ' selected' : ''}>${o}${suf}</option>`).join('')}</select></div>`;
    panel.innerHTML = `
      <div class="nb-head">
        <button type="button" class="nb-ib" data-a="back" title="Kembali" aria-label="Kembali">${svg('back')}</button>
        <div class="nb-head-t"><strong>Atur pengingat</strong><span>Disimpan di perangkat ini</span></div>
      </div>
      <div class="nb-list nb-set">
        <div class="nb-sec">Laporan keuangan</div>
        ${sw('r1', 'Setiap 1 bulan', 'Ringkasan bulan kalender sebelumnya')}
        ${sw('r3', 'Setiap 3 bulan', 'Ringkasan kuartal (Jan–Mar, Apr–Jun, …)')}
        ${sw('r6', 'Setiap 6 bulan', 'Ringkasan semester (Jan–Jun, Jul–Des)')}
        <div class="nb-sec">Peringatan lain</div>
        ${sel('margin', 'Batas margin', 'Ingatkan jika margin di bawah', [10, 15, 20, 30], '%')}
        ${sel('ksDays', 'Jatuh tempo konsinyasi', 'Ingatkan sebelum jatuh tempo', [3, 7, 14], ' hari')}
      </div>`;
  }

  function onPanelClick(e) {
    const t = e.target.closest('[data-f],[data-id],[data-a],[data-sw]');
    if (!t) return;
    if (t.dataset.f)  { filter = t.dataset.f; paintPanel(); return; }
    if (t.dataset.sw) { st.set[t.dataset.sw] = !st.set[t.dataset.sw]; save(); items = compute(); paintBadges(); paintSettings(); return; }
    if (t.dataset.a === 'readall')  { items.forEach(n => { st.read[n.id] = 1; }); save(); paintBadges(); paintPanel(); return; }
    if (t.dataset.a === 'settings') { view = 'settings'; paintPanel(); return; }
    if (t.dataset.a === 'back')     { view = 'list'; paintPanel(); return; }
    if (t.dataset.id) {
      const n = items.find(x => x.id === t.dataset.id);
      if (!n) return;
      st.read[n.id] = 1; save(); paintBadges();
      close();
      go(n);
    }
  }
  panelChange();
  function panelChange() {
    document.addEventListener('change', e => {
      const s = e.target.closest && e.target.closest('.nb-sel');
      if (!s) return;
      st.set[s.dataset.sel] = +s.value; save(); items = compute(); paintBadges();
    });
  }

  function go(n) {
    try {
      const el = document.querySelector(`.nav-item[onclick*="'${n.page}'"]`);
      navigate(n.page, el);
      if (n.period && typeof setPeriod === 'function') {
        const tab = document.querySelector(`#pt-cf .period-tab[onclick*="'cf',${n.period},"]`);
        setPeriod('cf', n.period, tab);
      }
      window.scrollTo({ top:0 });
    } catch (e) {}
  }

  // posisi popover desktop (di bawah tombol lonceng yang diklik)
  function place() {
    if (!panel || !document.body.classList.contains('nb-open') || !openBell) return;
    if (isMobile()) { panel.style.top = panel.style.right = ''; return; }
    const r = openBell.getBoundingClientRect();
    panel.style.top = Math.max(12, r.bottom + 12) + 'px';
    panel.style.right = Math.max(12, window.innerWidth - r.right) + 'px';
  }

  function toggle(bell) { document.body.classList.contains('nb-open') ? close() : open(bell); }
  function open(bell) {
    openBell = bell; view = 'list'; filter = 'all';
    paintPanel();
    document.body.classList.add('nb-open');
    bell.setAttribute('aria-expanded', 'true');
    place();
    panel.scrollTop = 0;
    setTimeout(() => panel.focus({ preventScroll:true }), 30);
    refresh(true);
  }
  function close() {
    document.body.classList.remove('nb-open');
    document.querySelectorAll('.nb-bell').forEach(b => b.setAttribute('aria-expanded', 'false'));
    if (openBell) try { openBell.focus({ preventScroll:true }); } catch (e) {}
    openBell = null;
  }

  // ── Hubungkan dengan app.js (tanpa mengubah file itu) ─────
  function hook() {
    if (typeof window.navigate === 'function') {
      const nav = window.navigate;
      window.navigate = function () { const r = nav.apply(this, arguments); setTimeout(() => refresh(), 60); return r; };
    }
    if (typeof window.api === 'function') {
      const orig = window.api;
      window.api = function (path, method) {
        const p = orig.apply(this, arguments);
        if (method && method !== 'GET') {
          Promise.resolve(p).then(() => { ksCache.at = 0; setTimeout(() => refresh(true), 700); }, () => {});
        }
        return p;
      };
    }
  }

  function init() {
    buildBells();
    buildPanel();
    hook();
    mq.addEventListener('change', () => { close(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
    setTimeout(() => refresh(true), 900);
    setTimeout(() => refresh(), 3000);
    setInterval(() => refresh(), 30000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
