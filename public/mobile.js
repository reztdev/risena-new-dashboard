/* ═══════════════════════════════════════════════════════════
   mobile.js — Risena Dashboard · pendamping mobile.css
   Tidak mengubah logika app.js. Hanya:
   1. menyuntik bottom nav dan menyinkronkannya dengan navigate()
   2. memberi data-label pada sel tabel (untuk tampilan kartu)
   3. mengganti emoji ikon statistik / empty-state dengan SVG
═══════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  const mq = window.matchMedia('(max-width:768px)');
  const isMobile = () => mq.matches;

  /* ── 1. BOTTOM NAV ─────────────────────────────────────── */
  const ICON = {
    dashboard: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    order: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
    stok: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
    konsinyasi: '<path d="M4 9l1.5-5h13L20 9"/><path d="M5 9v11h14V9"/><path d="M4 9a2.67 2.67 0 0 0 5.33 0 2.67 2.67 0 0 0 5.34 0A2.67 2.67 0 0 0 20 9"/><path d="M10 20v-5h4v5"/>',
    more: '<rect x="4" y="4" width="6.5" height="6.5" rx="2"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="2"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="2"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="2"/>'
  };
  const TABS = [
    ['dashboard', 'Beranda'], ['order', 'Order'], ['stok', 'Stok'],
    ['konsinyasi', 'Konsinyasi'], ['more', 'Lainnya']
  ];
  const MAIN_PAGES = TABS.map(t => t[0]).filter(k => k !== 'more');

  function buildNav() {
    if (document.getElementById('bottom-nav')) return;
    const nav = document.createElement('nav');
    nav.className = 'bn';
    nav.id = 'bottom-nav';
    nav.setAttribute('aria-label', 'Navigasi utama');
    nav.innerHTML = TABS.map(([key, label]) =>
      `<button class="bn-item${key === 'dashboard' ? ' active' : ''}" data-tab="${key}" type="button">` +
      `<span class="bn-ico"><svg viewBox="0 0 24 24" aria-hidden="true">${ICON[key]}</svg></span>` +
      `<span class="bn-lbl">${label}</span></button>`).join('');
    nav.addEventListener('click', e => {
      const btn = e.target.closest('.bn-item');
      if (!btn) return;
      const key = btn.dataset.tab;
      if (key === 'more') { window.toggleSidebar && window.toggleSidebar(); return; }
      const side = document.querySelector(`.nav-item[onclick*="'${key}'"]`);
      window.navigate(key, side);
    });
    document.body.appendChild(nav);
  }

  function setActiveTab(page) {
    const key = MAIN_PAGES.includes(page) ? page : 'more';
    document.querySelectorAll('.bn-item').forEach(b => b.classList.toggle('active', b.dataset.tab === key));
  }

  // Bungkus navigate() supaya bottom nav ikut sinkron & halaman mulai dari atas
  function wrapNavigate() {
    const orig = window.navigate;
    if (typeof orig !== 'function' || orig.__wrapped) return;
    const wrapped = function (page, el) {
      const r = orig.apply(this, arguments);
      setActiveTab(page);
      window.scrollTo(0, 0);
      return r;
    };
    wrapped.__wrapped = true;
    window.navigate = wrapped;
  }

  // Bottom sheet "Lainnya": kunci scroll body & sembunyikan nav saat terbuka
  function watchSheet() {
    const sb = document.getElementById('sidebar');
    if (!sb) return;
    new MutationObserver(() => {
      const open = sb.classList.contains('open') && isMobile();
      document.body.classList.toggle('sheet-open', open);
    }).observe(sb, { attributes: true, attributeFilter: ['class'] });
  }

  /* ── 2. TABEL → KARTU ──────────────────────────────────── */
  const TITLE_RE = /^(nama|produk|keterangan|toko|konsinyee|customer|pelanggan|deskripsi|tanggal)/i;
  function decorateTables() {
    document.querySelectorAll('.page table').forEach(t => {
      const ths = [...t.querySelectorAll('thead th')];
      if (ths.length < 2) return;
      const labels = ths.map(th => th.textContent.trim());
      let titleIdx = labels.findIndex(l => TITLE_RE.test(l));
      if (titleIdx < 0) titleIdx = 0;
      t.classList.add('rt');
      t.querySelectorAll('tbody tr').forEach(tr => {
        const tds = [...tr.children];
        if (tds.length === 1 && tds[0].colSpan > 1) { tds[0].classList.add('td-empty'); return; }
        tds.forEach((td, i) => {
          if (td.dataset.label !== undefined) return;
          const lab = labels[i] || '';
          td.dataset.label = lab;
          if (i === titleIdx) td.classList.add('td-title');
          if (/^aksi$/i.test(lab) || (lab === '' && td.querySelector('button'))) td.classList.add('td-act');
          else if (!td.querySelector(':scope > .td-v')) {
            // bungkus isi sel supaya tidak terpisah ke dua sisi oleh flex
            const w = document.createElement('span');
            w.className = 'td-v';
            while (td.firstChild) w.appendChild(td.firstChild);
            td.appendChild(w);
          }
        });
      });
    });
  }

  /* ── 3. EMOJI → SVG ────────────────────────────────────── */
  const S = {
    wallet: '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
    cash: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2.2"/><path d="M6 12h.01M18 12h.01"/>',
    list: '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M12 11h4M12 16h4M8 11h.01M8 16h.01"/>',
    box: ICON.stok,
    layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    check: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    store: ICON.konsinyasi,
    up: '<path d="M7 17 17 7M8 7h9v9"/>',
    down: '<path d="M17 7 7 17M16 17H7V8"/>',
    scale: '<path d="M12 3v18M5 7h14M5 7l-3 7a3 3 0 0 0 6 0zM19 7l-3 7a3 3 0 0 0 6 0z"/>',
    trophy: '<path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0zM17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3"/>',
    trend: '<path d="m3 17 6-6 4 4 8-8M15 7h6v6"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    trash: '<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6"/>',
    lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    print: '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="9" rx="2"/><path d="M7 14h10v7H7z"/>',
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.8 1.1z"/>'
  };
  const STAT_MAP = {
    '💰': 'wallet', '💵': 'cash', '📋': 'list', '📦': 'box', '🧵': 'layers', '⚠️': 'alert', '⚠': 'alert',
    '✅': 'check', '🏪': 'store', '↑': 'up', '↓': 'down', '⚖': 'scale', '🏆': 'trophy', '📈': 'trend'
  };
  function svg(name) {
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${S[name]}</svg>`;
  }
  const BTN_MAP = { '✏️': 'edit', '✏': 'edit', '🗑': 'trash', '🗑️': 'trash', '🖨️': 'print', '🖨': 'print', '🔐': 'lock' };
  function swapButtons() {
    document.querySelectorAll('.btn').forEach(btn => {
      const first = btn.firstChild;
      if (!first || first.nodeType !== 3) return;
      const m = first.nodeValue.match(/^\s*(✏️|✏|🗑️|🗑|🖨️|🖨|🔐)\s*/);
      if (!m) return;
      first.nodeValue = first.nodeValue.slice(m[0].length);
      const tmp = document.createElement('span');
      tmp.innerHTML = svg(BTN_MAP[m[1]]);
      btn.insertBefore(tmp.firstChild, btn.firstChild);
    });
  }
  function swapIcons() {
    swapButtons();
    document.querySelectorAll('.stat-icon:not([data-svg])').forEach(el => {
      const key = STAT_MAP[el.textContent.trim()];
      el.dataset.svg = '1';
      if (key) { el.dataset.emoji = el.textContent.trim(); el.innerHTML = svg(key); }
    });
    document.querySelectorAll('.empty-icon:not([data-svg])').forEach(el => {
      const e = el.textContent.trim();
      el.dataset.svg = '1';
      el.dataset.emoji = e;
      el.innerHTML = svg(e === '✅' ? 'check' : e === '🔍' ? 'search' : 'inbox');
    });
  }

  /* ── 4. WARNA & FONT CHART (selaras palet baru, hanya di mobile) ── */
  function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function hexToRgb(h) {
    h = h.replace('#', '');
    if (h.length === 3) h = h.split('').map(c => c + c).join('');
    const n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const OLD = { '8b4513': '--accent', 'c4622d': '--accent', 'c9972a': '--gold', '3a7d44': '--green', '0d7377': '--teal', 'c0392b': '--red', '2d3561': '#8A5CF6' };
  function remapColor(c) {
    if (typeof c !== 'string') return c;
    const v = c.replace(/\s+/g, '').toLowerCase();
    let key, alpha;
    let m = v.match(/^#([0-9a-f]{6})/);
    if (m) key = m[1];
    else if ((m = v.match(/^rgba?\((\d+),(\d+),(\d+)(?:,([\d.]+))?\)$/))) {
      key = [m[1], m[2], m[3]].map(x => (+x).toString(16).padStart(2, '0')).join('');
      alpha = m[4];
    }
    const to = OLD[key];
    if (!to) return c;
    const hex = to.startsWith('--') ? cssVar(to) : to;
    if (!hex.startsWith('#')) return c;
    if (alpha === undefined && v.startsWith('#')) return hex;
    const [r, g, b] = hexToRgb(hex);
    return `rgba(${r},${g},${b},${alpha === undefined ? 1 : alpha})`;
  }
  function setupCharts() {
    if (!window.Chart) return;
    window.Chart.register({
      id: 'risenaMobile',
      beforeUpdate(chart) {
        if (!isMobile()) return;
        const F = window.Chart.defaults;
        F.font.family = "'Plus Jakarta Sans','DM Sans',system-ui,sans-serif";
        F.color = cssVar('--text3') || F.color;
        (chart.config.data.datasets || []).forEach(ds => {
          ['backgroundColor', 'borderColor', 'pointBackgroundColor', 'pointBorderColor', 'hoverBackgroundColor'].forEach(k => {
            if (ds[k] == null) return;
            ds[k] = Array.isArray(ds[k]) ? ds[k].map(remapColor) : remapColor(ds[k]);
          });
        });
      }
    });
  }


  /* ── 5. MODE GELAP / TERANG (default terang) ───────────── */
  const THEME_KEY = 'risena_theme';
  const SUN_CLOUD = '<svg class="ic ic-light" viewBox="0 0 24 24" aria-hidden="true"><circle cx="8.5" cy="8" r="3.3"/><path d="M8.5 1.6v1.3M2.1 8h1.3M3.9 3.4l.9.9M13.1 3.4l-.9.9"/><path class="cloud" d="M7.5 21a3.6 3.6 0 0 1-.4-7.18 5.1 5.1 0 0 1 9.8-.8A4 4 0 0 1 17 21z"/></svg>';
  const MOON_STARS = '<svg class="ic ic-dark" viewBox="0 0 24 24" aria-hidden="true"><path d="M19.5 14.6A8 8 0 1 1 9.4 4.5a6.4 6.4 0 0 0 10.1 10.1z"/><path class="star" d="M17.5 2.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/><path class="star" d="M21.2 8.6l.4 1 1 .4-1 .4-.4 1-.4-1-1-.4 1-.4z"/></svg>';
  function currentTheme() { return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'; }
  function applyTheme(t, persist) {
    if (t === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
    else document.documentElement.removeAttribute('data-theme');
    const meta = document.getElementById('meta-theme');
    if (meta) meta.content = t === 'dark' ? '#0D0F1F' : '#F1F2F8';
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.setAttribute('aria-pressed', t === 'dark' ? 'true' : 'false');
      btn.setAttribute('aria-label', t === 'dark' ? 'Ganti ke mode terang' : 'Ganti ke mode gelap');
      btn.title = btn.getAttribute('aria-label');
    }
    if (persist) { try { localStorage.setItem(THEME_KEY, t); } catch (e) {} }
  }
  function buildThemeToggle() {
    if (document.getElementById('theme-toggle')) return;
    const header = document.querySelector('#page-dashboard .page-header');
    if (!header) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'theme-toggle';
    btn.className = 'theme-toggle';
    btn.innerHTML = SUN_CLOUD + MOON_STARS;
    btn.addEventListener('click', () => {
      const next = currentTheme() === 'dark' ? 'light' : 'dark';
      const root = document.documentElement;
      root.classList.add('theme-anim');
      applyTheme(next, true);
      setTimeout(() => root.classList.remove('theme-anim'), 450);
      // gambar ulang chart di Beranda supaya warna teks ikut berubah
      const pg = document.getElementById('page-dashboard');
      if (pg && pg.classList.contains('active') && typeof window.renderDashboard === 'function') {
        try { window.renderDashboard(); } catch (e) {}
      }
    });
    header.appendChild(btn);
    applyTheme(currentTheme(), false);
  }

  /* ── 6. LOGIN: hero merek + tombol lihat password ──────── */
  const KAWUNG = '<svg viewBox="0 0 64 64" aria-hidden="true"><g fill="none" stroke="#fff" stroke-width="2.4" stroke-opacity=".95"><ellipse cx="32" cy="17" rx="8" ry="15"/><ellipse cx="32" cy="47" rx="8" ry="15"/><ellipse cx="17" cy="32" rx="15" ry="8"/><ellipse cx="47" cy="32" rx="15" ry="8"/></g><circle cx="32" cy="32" r="4.2" fill="#F2B94B"/></svg>';
  const EYE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  const EYE_OFF = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7c2 0 3.7.6 5.1 1.4M22 12s-3.5 7-10 7c-2 0-3.7-.6-5.1-1.4"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18"/></svg>';
  function buildLogin() {
    const screen = document.getElementById('login-screen');
    if (!screen) return;
    if (!screen.querySelector('.login-hero')) {
      const hero = document.createElement('div');
      hero.className = 'login-hero';
      hero.innerHTML = `<span class="brand-logo lh-logo" role="img" aria-label="Risena Collections"></span>` +
        `<div class="lh-sub">Kelola stok, order, dan konsinyasi di satu tempat.</div>`;
      screen.insertBefore(hero, screen.firstChild);
    }
    const pw = document.getElementById('login-password');
    if (pw && !document.getElementById('pw-toggle')) {
      const b = document.createElement('button');
      b.type = 'button';
      b.id = 'pw-toggle';
      b.className = 'pw-toggle';
      b.setAttribute('aria-label', 'Tampilkan password');
      b.innerHTML = EYE;
      b.addEventListener('click', () => {
        const show = pw.type === 'password';
        pw.type = show ? 'text' : 'password';
        b.innerHTML = show ? EYE_OFF : EYE;
        b.setAttribute('aria-label', show ? 'Sembunyikan password' : 'Tampilkan password');
      });
      pw.parentElement.appendChild(b);
    }
  }

  /* ── LOOP PEMROSESAN ───────────────────────────────────── */
  let raf = 0;
  function process() {
    raf = 0;
    if (!isMobile()) return;
    decorateTables();
    swapIcons();
  }
  function schedule() { if (!raf) raf = requestAnimationFrame(process); }

  function init() {
    setupCharts();
    buildLogin();
    buildThemeToggle();
    buildNav();
    wrapNavigate();
    watchSheet();
    // hanya childList → mengubah atribut/kelas tidak memicu loop
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    mq.addEventListener('change', () => {
      document.body.classList.remove('sheet-open');
      schedule();
    });
    // Sinkron awal bila halaman aktif bukan dashboard
    const active = document.querySelector('.page.active');
    if (active) setActiveTab(active.id.replace('page-', ''));
    schedule();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
