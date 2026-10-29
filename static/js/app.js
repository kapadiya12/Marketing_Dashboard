/* BizDev Hub — interface behaviour.
   Sidebar, theme, command palette, shortcuts, charts, count-ups, clickable rows,
   status pills, bulk selection, exports, loading bar, tooltips and HTMX hooks. */
(function () {
  "use strict";
  const body = document.body;
  const root = document.documentElement;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } }
  };
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------------ sidebar */
  if (store.get("sidebar-collapsed") === "1" && window.innerWidth >= 992) body.classList.add("sidebar-collapsed");
  function toggleSidebar() {
    if (window.innerWidth < 992) { body.classList.toggle("sidebar-open"); return; }
    body.classList.toggle("sidebar-collapsed");
    store.set("sidebar-collapsed", body.classList.contains("sidebar-collapsed") ? "1" : "0");
  }

  /* ------------------------------------------------------------ theme */
  function syncThemeIcons() {
    const dark = root.getAttribute("data-bs-theme") === "dark";
    document.querySelectorAll(".theme-icon-light").forEach(el => el.classList.toggle("d-none", dark));
    document.querySelectorAll(".theme-icon-dark").forEach(el => el.classList.toggle("d-none", !dark));
  }
  function toggleTheme() {
    const next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-bs-theme", next);
    store.set("theme", next);
    syncThemeIcons();
    renderCharts(document, true);
  }

  /* ------------------------------------------------------------ charts */
  // Validated categorical palette (fixed order, never cycled) + status colours.
  const SERIES = {
    light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
  };
  const charts = {};
  function cssVar(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
  function renderCharts(scope, force) {
    if (typeof Chart === "undefined") return;
    const dark = root.getAttribute("data-bs-theme") === "dark";
    const ink = cssVar("--text-muted") || "#64748b";
    const grid = cssVar("--border") || "#e4e8f1";
    const surface = cssVar("--surface") || "#fff";
    Chart.defaults.font.family = "Inter, system-ui, sans-serif";
    Chart.defaults.color = ink;
    (scope || document).querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
      if (charts[canvas.id] && !force && charts[canvas.id].canvas === canvas) return;
      const dataEl = document.getElementById(canvas.dataset.chart);
      if (!dataEl) return;
      let spec;
      try { spec = JSON.parse(dataEl.textContent); } catch (e) { return; }
      if (charts[canvas.id]) charts[canvas.id].destroy();
      const isRound = spec.type === "doughnut" || spec.type === "pie";
      const horizontal = spec.options && spec.options.indexAxis === "y";
      const palette = dark ? SERIES.dark : SERIES.light;
      const toMode = function (c) {
        if (Array.isArray(c)) return c.map(toMode);
        if (!dark || typeof c !== "string") return c;
        const idx = SERIES.light.indexOf(c.toLowerCase());
        if (idx >= 0) return SERIES.dark[idx];
        return c.toLowerCase() === "#cbd5e1" ? "#3a4560" : c.toLowerCase() === "#b7d3f6" ? "#2b4a75" : c;
      };
      const datasets = spec.datasets.map(function (ds, i) {
        const d = Object.assign({}, ds);
        d.backgroundColor = toMode(d.backgroundColor);
        d.borderColor = toMode(d.borderColor);
        if (spec.type === "bar") {
          d.borderRadius = 4; d.borderSkipped = "start"; d.maxBarThickness = 36;
          d.borderWidth = 0;
        }
        if (spec.type === "line") {
          const c = d.borderColor || palette[i % palette.length];
          d.borderColor = c; d.borderWidth = 2; d.cubicInterpolationMode = "monotone"; d.pointRadius = 3;
          d.pointHoverRadius = 6; d.pointBackgroundColor = c; d.pointBorderColor = surface; d.pointBorderWidth = 2;
          d.fill = spec.datasets.length === 1;
          d.backgroundColor = function (ctx) {
            const area = ctx.chart.chartArea;
            if (!area) return "transparent";
            const g = ctx.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
            g.addColorStop(0, c + "33"); g.addColorStop(1, c + "00");
            return g;
          };
        }
        if (isRound) { d.borderColor = surface; d.borderWidth = 2; d.hoverOffset = 6; }
        return d;
      });
      const options = {
        responsive: true,
        maintainAspectRatio: false,
        animation: reduceMotion ? false : { duration: 700, easing: "easeOutQuart" },
        interaction: { mode: isRound ? "nearest" : "index", intersect: false },
        plugins: {
          legend: {
            display: isRound || spec.datasets.length > 1,
            position: isRound ? (window.innerWidth < 576 ? "bottom" : "right") : "top",
            align: isRound ? "center" : "end",
            labels: { boxWidth: 8, boxHeight: 8, usePointStyle: true, pointStyle: "circle", padding: 14, font: { size: 11.5 } }
          },
          tooltip: {
            backgroundColor: dark ? "#0b0f19" : "#0f172a", titleColor: "#fff", bodyColor: "#e2e8f0",
            borderColor: dark ? "#303a54" : "#0f172a", borderWidth: 1, padding: 10, cornerRadius: 10,
            boxPadding: 4, usePointStyle: true, titleFont: { weight: "600" },
            callbacks: (spec.links || spec.filter) ? { footer: function () { return "Click to view records"; } } : {}
          }
        },
        scales: isRound ? {} : {
          x: {
            grid: { display: horizontal, color: grid, drawTicks: false }, border: { display: false },
            ticks: { font: { size: 11 }, maxRotation: 40, autoSkip: true, padding: 6, precision: horizontal ? 0 : undefined },
            beginAtZero: horizontal
          },
          y: {
            beginAtZero: true, grid: { display: !horizontal, color: grid, drawTicks: false }, border: { display: false },
            ticks: { font: { size: 11 }, padding: 8, precision: horizontal ? undefined : 0 }
          }
        }
      };
      if (spec.options) Object.assign(options, { indexAxis: spec.options.indexAxis || "x" });
      if (isRound) options.cutout = spec.type === "doughnut" ? "66%" : 0;
      if (spec.links || spec.filter) {
        canvas.parentElement.classList.add("clickable");
        options.onClick = function (evt, elements) {
          if (!elements || !elements.length) return;
          const idx = elements[0].index;
          if (spec.links && spec.links[idx]) { window.location.href = spec.links[idx]; return; }
          if (spec.filter && spec.filter.values[idx] !== undefined) {
            const url = new URL(window.location.href);
            url.searchParams.delete(spec.filter.param);
            url.searchParams.set(spec.filter.param, spec.filter.values[idx]);
            ["page", "preset"].forEach(k => url.searchParams.delete(k));
            window.location.href = url.toString();
          }
        };
        options.onHover = function (evt, elements) {
          evt.native.target.style.cursor = elements && elements.length ? "pointer" : "default";
        };
      }
      charts[canvas.id] = new Chart(canvas, { type: spec.type, data: { labels: spec.labels, datasets: datasets }, options: options });
    });
  }

  /* ------------------------------------------------------------ count-up numbers & meters */
  function animateNumbers(scope) {
    (scope || document).querySelectorAll("[data-count]:not([data-counted])").forEach(function (el) {
      el.setAttribute("data-counted", "1");
      const target = parseFloat(el.dataset.count);
      if (!isFinite(target) || reduceMotion || target === 0) return;
      const suffix = el.dataset.suffix || "";
      const fmt = new Intl.NumberFormat("en-IN");
      const start = performance.now();
      const dur = Math.min(1100, 500 + target * 8);
      function step(now) {
        const p = Math.min(1, (now - start) / dur);
        const eased = 1 - Math.pow(1 - p, 3);
        el.textContent = fmt.format(Math.round(target * eased)) + suffix;
        if (p < 1) requestAnimationFrame(step); else el.textContent = fmt.format(target) + suffix;
      }
      el.textContent = "0" + suffix;
      requestAnimationFrame(step);
    });
    (scope || document).querySelectorAll("[data-width]:not([data-grown])").forEach(function (el) {
      el.setAttribute("data-grown", "1");
      const w = el.dataset.width;
      if (reduceMotion) { el.style.width = w; return; }
      el.style.width = "0";
      requestAnimationFrame(() => requestAnimationFrame(() => { el.style.width = w; }));
    });
  }

  /* ------------------------------------------------------------ toasts & tooltips */
  function showToasts(scope) {
    if (typeof bootstrap === "undefined") return;
    (scope || document).querySelectorAll(".toast:not(.shown)").forEach(function (el) {
      el.classList.add("shown");
      new bootstrap.Toast(el, { delay: 5000 }).show();
    });
  }
  function toast(message, kind) {
    const c = document.getElementById("toast-container");
    if (!c) return;
    const icons = { success: "bi-check-circle-fill", danger: "bi-exclamation-octagon-fill", warning: "bi-exclamation-triangle-fill", info: "bi-info-circle-fill" };
    c.insertAdjacentHTML("beforeend",
      '<div class="toast align-items-center border-0 text-bg-' + kind + '" role="alert"><div class="d-flex"><div class="toast-body"><i class="bi ' + (icons[kind] || icons.info) + '"></i>' + message + '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div></div>');
    showToasts(c);
  }
  function initTooltips(scope) {
    if (typeof bootstrap === "undefined" || window.matchMedia("(hover: none)").matches) return;
    (scope || document).querySelectorAll(".icon-btn[title], .btn-sm[title], a.btn[title], [data-tip]").forEach(function (el) {
      if (el.dataset.tipReady || el.getAttribute("data-bs-toggle") === "dropdown") return;
      el.dataset.tipReady = "1";
      new bootstrap.Tooltip(el, { title: el.dataset.tip || el.getAttribute("title"), placement: "bottom", trigger: "hover", delay: { show: 350, hide: 0 } });
    });
  }

  /* ------------------------------------------------------------ status pills */
  function paintStatus(select) {
    const opt = select.options[select.selectedIndex];
    if (opt && opt.dataset.color) select.dataset.color = opt.dataset.color;
  }

  /* ------------------------------------------------------------ command palette */
  let paletteItems = [];
  let paletteIndex = 0;
  let paletteModal = null;
  let searchTimer = null;
  function paletteData() {
    const el = document.getElementById("palette-data");
    try { return el ? JSON.parse(el.textContent) : []; } catch (e) { return []; }
  }
  function esc(s) { return String(s || "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function score(item, q) {
    if (!q) return item.group === "Create" ? 0 : 1;
    const hay = (item.label + " " + (item.hint || "") + " " + item.group).toLowerCase();
    const label = item.label.toLowerCase();
    if (label.startsWith(q)) return 4;
    if (label.includes(q)) return 3;
    const words = q.split(/\s+/).filter(Boolean);
    if (words.every(w => hay.includes(w))) return 2;
    let i = 0;
    for (const ch of label) { if (ch === q[i]) i++; if (i === q.length) return 1; }
    return 0;
  }
  function renderPalette(q) {
    const list = document.getElementById("palette-list");
    if (!list) return;
    const query = (q || "").trim().toLowerCase();
    const scored = paletteData().map(it => ({ it: it, s: score(it, query) })).filter(x => x.s > 0);
    scored.sort((a, b) => b.s - a.s);
    // Keep results grouped: groups ordered by their best match, items by score within a group.
    const top = scored.slice(0, query ? 14 : 22);
    const order = [];
    top.forEach(x => { if (order.indexOf(x.it.group) < 0) order.push(x.it.group); });
    paletteItems = order.flatMap(g => top.filter(x => x.it.group === g).map(x => x.it));
    paletteIndex = 0;
    let html = "", group = null;
    paletteItems.forEach(function (it, i) {
      if (it.group !== group) { group = it.group; html += '<div class="palette-group">' + esc(group) + "</div>"; }
      const swatch = it.color ? ' style="background:' + esc(it.color) + ';color:#fff"' : "";
      html += '<a class="palette-item' + (i === 0 ? " active" : "") + '" role="option" data-index="' + i + '" href="' + esc(it.url) + '">' +
        '<i class="bi ' + esc(it.icon) + ' ico"' + swatch + "></i><span>" + esc(it.label) + "</span>" +
        (it.hint ? "<small>" + esc(it.hint) + "</small>" : "") + "</a>";
    });
    list.innerHTML = html || '<div class="p-3 small text-muted">No pages match. Records matching your search appear below.</div>';
    const rec = document.getElementById("palette-records");
    clearTimeout(searchTimer);
    if (query.length >= 2) {
      searchTimer = setTimeout(function () {
        fetch("/search/?q=" + encodeURIComponent(query), { headers: { "HX-Request": "true" } })
          .then(r => r.ok ? r.text() : "")
          .then(function (t) { rec.innerHTML = t ? '<div class="palette-group px-3">Records</div><div class="px-1 pb-2">' + t + "</div>" : ""; })
          .catch(function () { rec.innerHTML = ""; });
      }, 220);
    } else { rec.innerHTML = ""; }
  }
  function movePalette(delta) {
    const nodes = document.querySelectorAll("#palette-list .palette-item");
    if (!nodes.length) return;
    nodes[paletteIndex] && nodes[paletteIndex].classList.remove("active");
    paletteIndex = (paletteIndex + delta + nodes.length) % nodes.length;
    nodes[paletteIndex].classList.add("active");
    nodes[paletteIndex].scrollIntoView({ block: "nearest" });
  }
  function openPalette() {
    const el = document.getElementById("palette");
    if (!el || typeof bootstrap === "undefined") return;
    paletteModal = paletteModal || new bootstrap.Modal(el);
    const input = document.getElementById("palette-input");
    input.value = "";
    renderPalette("");
    paletteModal.show();
    el.addEventListener("shown.bs.modal", () => input.focus(), { once: true });
  }

  /* ------------------------------------------------------------ loading bar */
  const bar = document.getElementById("loading-bar");
  let barTimer = null;
  function startBar() {
    if (!bar) return;
    clearTimeout(barTimer);
    bar.classList.add("active");
    bar.style.width = "25%";
    barTimer = setTimeout(() => { bar.style.width = "70%"; }, 250);
  }
  // A clicked submit button spins and is disabled until the next page arrives (or after 30 s, e.g. a download).
  function busy(btn, label) {
    if (!btn || btn.tagName !== "BUTTON") return;
    const form = btn.form;
    btn.dataset.idleHtml = btn.innerHTML;
    setTimeout(() => {  // after the browser has read the button's name/value into the submission
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>' + label;
    }, 0);
    setTimeout(() => idle(btn, form), 30000);
  }
  function idle(btn, form) {
    if (btn && btn.dataset.idleHtml !== undefined) { btn.disabled = false; btn.innerHTML = btn.dataset.idleHtml; delete btn.dataset.idleHtml; }
    if (form) delete form.dataset.submitting;
  }
  // Sidebar links start loading when the pointer rests on one (or a finger touches it), so the page is
  // usually on its way before the click. One at a time, each page once.
  const prefetched = new Set();
  let prefetchTimer = null;
  function prefetch(a) {
    if (!a || prefetched.has(a.href) || a.origin !== window.location.origin || a.target || a.hasAttribute("download")
        || a.href === window.location.href || /[?&]format=|\/logout|\/email-marketing\//.test(a.href)) return;
    prefetched.add(a.href);
    const l = document.createElement("link");
    l.rel = "prefetch"; l.href = a.href; l.as = "document";
    document.head.appendChild(l);
  }
  document.addEventListener("mouseover", function (e) {
    const a = e.target.closest && e.target.closest(".sidebar a[href]");
    clearTimeout(prefetchTimer);
    if (a) prefetchTimer = setTimeout(() => prefetch(a), 80);
  });
  document.addEventListener("touchstart", function (e) {
    prefetch(e.target.closest && e.target.closest(".sidebar a[href]"));
  }, { passive: true });

  // Back/forward restores a page from cache with its buttons still spinning.
  window.addEventListener("pageshow", function (e) {
    if (!e.persisted) return;
    document.querySelectorAll("button[data-idle-html]").forEach(b => idle(b, b.form));
    document.querySelectorAll("form[data-submitting]").forEach(f => delete f.dataset.submitting);
    document.querySelectorAll(".row-pending").forEach(r => r.classList.remove("row-pending"));
  });
  function endBar() {
    if (!bar) return;
    clearTimeout(barTimer);
    bar.style.width = "100%";
    setTimeout(() => { bar.classList.remove("active"); bar.style.width = "0"; }, 300);
  }

  /* ------------------------------------------------------------ events */
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-sidebar-toggle]")) toggleSidebar();
    if (e.target.closest(".sidebar-backdrop")) body.classList.remove("sidebar-open");
    if (e.target.closest("[data-theme-toggle]")) toggleTheme();
    if (e.target.closest("[data-palette-open]")) { e.preventDefault(); openPalette(); }
    if (e.target.closest("#back-to-top")) window.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" });
    const ft = e.target.closest("[data-filter-toggle]");
    if (ft) { const box = document.querySelector(".filter-collapsible"); if (box) box.classList.toggle("open"); }

    // Export links always use the page's current filters.
    const exp = e.target.closest("[data-export-format]");
    if (exp) {
      e.preventDefault();
      const current = new URL(window.location.href);
      const target = new URL(exp.dataset.exportPath || current.pathname, window.location.origin);
      current.searchParams.forEach(function (v, k) {
        if (k !== "page" && k !== "view" && k !== "format") target.searchParams.append(k, v);
      });
      target.searchParams.set("format", exp.dataset.exportFormat);
      toast("Preparing your " + exp.dataset.exportFormat.toUpperCase() + " download…", "info");
      window.location.href = target.toString();
      return;
    }

    // Clickable table rows (ignore clicks on controls inside the row).
    const row = e.target.closest("tr[data-href]");
    if (row && !e.target.closest("a, button, input, select, label, textarea, .dropdown")) {
      if (e.ctrlKey || e.metaKey) window.open(row.dataset.href, "_blank");
      else window.location.href = row.dataset.href;
    }

    // Internal navigation → loading bar.
    const link = e.target.closest("a[href]");
    if (link && !e.defaultPrevented && !link.target && !link.hasAttribute("download") && !e.ctrlKey && !e.metaKey &&
        link.origin === window.location.origin && !link.getAttribute("href").startsWith("#") &&
        !link.hasAttribute("data-bs-toggle") && !/[?&]format=|template=|kind=/.test(link.href)) {
      startBar();
    }
  });

  document.addEventListener("change", function (e) {
    if (e.target.matches("[data-check-all]")) {
      document.querySelectorAll("input[name=ids]").forEach(cb => { cb.checked = e.target.checked; });
    }
    if (e.target.matches("input[name=ids], [data-check-all]")) {
      const n = document.querySelectorAll("input[name=ids]:checked").length;
      const b = document.querySelector("[data-bulk-bar]");
      if (b) { b.classList.toggle("d-none", n === 0); const c = b.querySelector("[data-count]"); if (c) c.textContent = n; }
      document.querySelectorAll("input[name=ids]").forEach(cb => cb.closest("tr") && cb.closest("tr").classList.toggle("table-active", cb.checked));
    }
    if (e.target.matches("[data-bulk-action]")) {
      const v = e.target.value;
      document.querySelectorAll("[data-bulk-extra]").forEach(el => el.classList.toggle("d-none", el.dataset.bulkExtra !== v));
    }
    if (e.target.matches("select[name=period][data-custom-toggle]")) {
      document.querySelectorAll("[data-custom-range]").forEach(el => el.classList.toggle("d-none", e.target.value !== "custom"));
    }
    if (e.target.matches("select.status-select")) paintStatus(e.target);
  });

  document.addEventListener("submit", function (e) {
    const form = e.target;
    if (form.id === "bulk-form" && e.submitter && e.submitter.value === "apply") {
      const action = form.querySelector("[data-bulk-action]").value;
      if (action === "delete" && !window.confirm("Permanently delete the selected records? This cannot be undone.")) { e.preventDefault(); return; }
      if (action.startsWith("export")) { toast("Preparing your download…", "info"); return; }
      if (form.dataset.submitting) { e.preventDefault(); return; }
      form.dataset.submitting = "1";
      // Show the change at once: selected rows fade, the button spins until the page comes back.
      const labels = { delete: "Deleting…", archive: "Archiving…", restore: "Restoring…", status: "Updating…", assign: "Assigning…" };
      document.querySelectorAll("input[name=ids]:checked").forEach(cb => { const tr = cb.closest("tr"); if (tr) tr.classList.add("row-pending"); });
      busy(e.submitter, labels[action] || "Working…");
      startBar();
      return;
    }
    const msg = form.dataset.confirm || (e.submitter && e.submitter.dataset.confirm);
    if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
    if (!form.hasAttribute("hx-get") && !form.hasAttribute("hx-post") && form.method.toLowerCase() === "post") {
      // A second click while the first is still saving would send everything twice.
      if (form.dataset.submitting) { e.preventDefault(); return; }
      form.dataset.submitting = "1";
      busy(e.submitter || form.querySelector("button[type=submit], button:not([type])"), "Saving…");
      if (!form.querySelector("input[type=file]")) startBar();
    }
  });

  // Palette keyboard + typing
  document.addEventListener("input", function (e) { if (e.target.id === "palette-input") renderPalette(e.target.value); });
  document.addEventListener("keydown", function (e) {
    const inPalette = e.target && e.target.id === "palette-input";
    if (inPalette) {
      if (e.key === "ArrowDown") { e.preventDefault(); movePalette(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); movePalette(-1); }
      else if (e.key === "Enter") {
        const item = paletteItems[paletteIndex];
        if (item) { e.preventDefault(); startBar(); window.location.href = item.url; }
      }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
    const typing = e.target.closest && e.target.closest("input, textarea, select, [contenteditable]");
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "/") { e.preventDefault(); const s = document.getElementById("id_q"); if (s) s.focus(); else openPalette(); }
    else if (e.key === "?") { const m = document.getElementById("shortcuts"); if (m) bootstrap.Modal.getOrCreateInstance(m).show(); }
    else if (e.key === "D" && e.shiftKey) toggleTheme();
    else if (e.key.toLowerCase() === "n") { const add = document.querySelector("[data-shortcut-new]"); if (add) { startBar(); window.location.href = add.href; } }
    else if (e.key.toLowerCase() === "g") { window.__g = Date.now(); }
    else if (window.__g && Date.now() - window.__g < 900) {
      if (e.key.toLowerCase() === "d") { startBar(); window.location.href = "/dashboard/"; }
      if (e.key.toLowerCase() === "t") { startBar(); window.location.href = "/tasks/"; }
      window.__g = 0;
    }
  });
  document.addEventListener("mousemove", function (e) {
    const it = e.target.closest && e.target.closest(".palette-item");
    if (!it) return;
    document.querySelectorAll(".palette-item.active").forEach(n => n.classList.remove("active"));
    it.classList.add("active");
    paletteIndex = parseInt(it.dataset.index, 10) || 0;
  });

  // Back to top
  const btt = document.getElementById("back-to-top");
  window.addEventListener("scroll", function () { if (btt) btt.classList.toggle("show", window.scrollY > 500); }, { passive: true });

  /* ------------------------------------------------------------ init & HTMX hooks */
  function init(scope) {
    renderCharts(scope, scope !== document);
    showToasts(scope);
    animateNumbers(scope);
    initTooltips(scope);
    (scope || document).querySelectorAll("select.status-select").forEach(paintStatus);
  }
  document.addEventListener("DOMContentLoaded", function () { syncThemeIcons(); init(document); });
  document.addEventListener("htmx:beforeRequest", startBar);
  document.addEventListener("htmx:afterRequest", function (e) {
    endBar();
    const elt = e.detail.elt;
    if (e.detail.successful && elt && elt.matches && elt.matches("select.status-select")) {
      elt.classList.add("saved");
      setTimeout(() => elt.classList.remove("saved"), 900);
      const label = elt.options[elt.selectedIndex] ? elt.options[elt.selectedIndex].text : "";
      toast("Status updated" + (label ? " to “" + esc(label) + "”" : ""), "success");
    }
  });
  document.addEventListener("htmx:afterSwap", function (e) { init(e.detail.target); });
  document.addEventListener("htmx:responseError", function () { endBar(); toast("Something went wrong. Please refresh and try again.", "danger"); });
  window.addEventListener("pageshow", endBar);
  window.addEventListener("resize", function () { if (window.innerWidth >= 992) body.classList.remove("sidebar-open"); });
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function (ev) {
      if (!store.get("theme")) { root.setAttribute("data-bs-theme", ev.matches ? "dark" : "light"); syncThemeIcons(); renderCharts(document, true); }
    });
  }
})();
