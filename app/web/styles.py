"""Shared CSS + nav — paper desk aesthetic (not generic AI dark cards).

Product-mode redesign (Operate): desk ledger for clearing the Tadoku queue,
then reading immersion stock. Cream blotter + iron-gall frames + kiln clay CTA.
"""

from app.web.icons import icon

SHARED_CSS = """
:root {
  /* surfaces — dark blotter desk + bright ledger leaf (v2, clearly different) */
  --paper: #cfc4ae;          /* blotter felt — was pale cream */
  --paper-2: #c0b498;
  --panel: #fffaf0;          /* bright leaf */
  --panel-2: #f5edd9;
  /* ink — iron gall */
  --ink: #14110e;
  --ink-soft: #2e2922;
  --muted: #534c41;
  --faint: #655d50; /* ≥4.5:1 on panel */
  --line: #d8cdba;
  --line-strong: #b9aa8f;
  /* brand CTA — kiln clay (hotter) */
  --accent: #c2410c;
  --accent-hover: #9a3412;
  --accent-ink: #fff7ed;
  /* semantic status */
  --green: #166534;
  --green-bg: #dcfce7;
  --amber: #a16207;
  --amber-bg: #fef3c7;
  --red: #991b1b;
  --red-bg: #fee2e2;
  --blue: #1e3a5f; /* stamp blue — Ready */
  --blue-bg: #dbeafe;
  /* external tool brand (icon tints only) */
  --plex: #e5a00d;
  --tautulli: #cc7b19;
  --sheets: #0F9D58;
  --youtube: #ff0000;
  --tadoku: #1a5c7a;
  /* shape + frames */
  --radius: 2px;
  --border-ink: 2px solid var(--ink);
  --border-soft: 1px solid var(--line-strong);
  --frame-work: 2.5px solid var(--ink);
  --frame-quiet: 1px solid var(--line-strong);
  /* spacing */
  --sp-1: 0.25rem;
  --sp-2: 0.5rem;
  --sp-3: 0.75rem;
  --sp-4: 1rem;
  --sp-5: 1.5rem;
  --sp-6: 2.5rem;
  /* type */
  --font: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  --mono: "IBM Plex Mono", "Cascadia Code", ui-monospace, Consolas, monospace;
  --display: "IBM Plex Serif", Georgia, "Times New Roman", serif;
  --text-xs: 0.68rem;
  --text-sm: 0.80rem;
  --text-md: 0.94rem;
  --text-lg: 1.15rem;
  --text-xl: 1.55rem;
  --text-metric: 2.15rem;
  /* layout */
  --page-max: 1120px;
  --page-max-wide: 1280px;
  --topbar-h: 3.4rem;
  --sheet-shadow: 0 8px 28px rgba(20, 17, 14, 0.14), 0 1px 0 rgba(20, 17, 14, 0.08);
  --radius-inner: 1px; /* nested: child ≤ parent */
  --hit: 2.75rem; /* ≥44px touch target */
  --control-fs: 0.9rem;
}
*, *::before, *::after { box-sizing: border-box; }
html {
  scroll-behavior: smooth;
  color-scheme: light; /* native controls / scrollbars match light ledger */
}
body {
  margin: 0;
  min-height: 100vh;
  min-height: 100dvh;
  font-family: var(--font);
  font-size: var(--text-md);
  /* notches / home indicator */
  padding-left: env(safe-area-inset-left, 0);
  padding-right: env(safe-area-inset-right, 0);
  padding-bottom: env(safe-area-inset-bottom, 0);
  /* Cork/blotter desk — clearly not pale cream */
  background-color: var(--paper);
  background-image:
    radial-gradient(ellipse 120% 80% at 50% -20%, rgba(255, 250, 240, 0.35), transparent 55%),
    repeating-linear-gradient(
      90deg,
      transparent,
      transparent 11px,
      rgba(80, 60, 30, 0.04) 12px
    ),
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 11px,
      rgba(80, 60, 30, 0.04) 12px
    );
  color: var(--ink);
  line-height: 1.45;
  -webkit-font-smoothing: antialiased;
}
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
:focus {
  scroll-margin-top: calc(var(--topbar-h) + 0.75rem);
}
/* Skip link — keyboard first */
.skip-link {
  position: absolute;
  left: -9999px;
  top: 0.5rem;
  z-index: 100;
  padding: 0.55rem 0.9rem;
  background: var(--ink);
  color: var(--panel);
  font-weight: 700;
  font-size: var(--text-sm);
  text-decoration: none;
  border-radius: var(--radius);
  border: 2px solid var(--accent);
}
.skip-link:focus,
.skip-link:focus-visible {
  left: 0.5rem;
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  color: var(--panel);
  text-decoration: none;
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; text-underline-offset: 2px; }
code {
  font-family: var(--mono);
  font-size: 0.86em;
  background: var(--paper-2);
  border: 1px solid var(--line);
  padding: 0.08rem 0.35rem;
  border-radius: 2px;
}

/* ── Top bar: ink stamp strip (high-contrast vs old cream bar) ── */
.topbar {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 0;
  border-bottom: 3px solid var(--accent);
  background: var(--ink);
  color: var(--panel);
  position: sticky;
  top: 0;
  z-index: 20;
  overflow: visible;
  min-height: var(--topbar-h);
  box-shadow: 0 4px 16px rgba(20, 17, 14, 0.28);
}
.topbar-brand {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.65rem 1rem;
  color: var(--panel);
  font-weight: 700;
  font-size: 0.95rem;
  letter-spacing: -0.01em;
  text-decoration: none;
  border-right: 1px solid rgba(255, 250, 240, 0.12);
  background: rgba(255, 250, 240, 0.04);
}
.topbar-brand:hover { text-decoration: none; background: rgba(255, 250, 240, 0.1); color: var(--panel); }
.topbar-brand.active {
  box-shadow: inset 0 -3px 0 var(--accent);
  background: rgba(194, 65, 12, 0.2);
}
.topbar-brand .mark {
  width: 34px; height: 34px;
  display: grid; place-items: center;
  border: 1px solid var(--line-strong);
  background: #0b1220;
  color: var(--accent-ink);
  flex-shrink: 0;
  border-radius: 8px;
  overflow: hidden;
  padding: 0;
}
.topbar-brand .mark img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}
.topbar-brand .mark svg { width: 18px; height: 18px; }
.topbar-brand .brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.15;
  gap: 0.05rem;
}
.topbar-brand .brand-text strong {
  font-weight: 700;
  font-size: 0.92rem;
  color: var(--panel);
}
.topbar-brand .brand-text span {
  font-weight: 600;
  font-size: 0.68rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(255, 250, 240, 0.55);
}
.topbar-nav {
  display: flex;
  align-items: stretch;
  flex: 1;
  min-width: 0;
  /* Must stay visible — overflow-x:auto clips the More dropdown */
  overflow: visible;
}
/* Primary links only (direct children) — not menu items inside More */
.topbar-nav > a,
.topbar-nav > .nav-more > summary {
  display: flex;
  align-items: center;
  padding: 0 0.95rem;
  color: rgba(255, 250, 240, 0.78);
  font-size: var(--text-md);
  font-weight: 600;
  text-decoration: none;
  border-right: 1px solid rgba(255, 250, 240, 0.1);
  white-space: nowrap;
  background: transparent;
  cursor: pointer;
  font-family: inherit;
  list-style: none;
  height: 100%;
  box-sizing: border-box;
  border: none;
  border-right: 1px solid rgba(255, 250, 240, 0.1);
  margin: 0;
}
.topbar-nav > a:hover,
.topbar-nav > .nav-more > summary:hover {
  background: rgba(255, 250, 240, 0.08);
  color: var(--panel);
  text-decoration: none;
}
.topbar-nav > a.active,
.topbar-nav > .nav-more.active > summary {
  color: var(--panel);
  background: rgba(255, 250, 240, 0.1);
  box-shadow: inset 0 -3px 0 var(--accent);
}
.topbar-nav > .nav-more {
  position: relative;
  display: flex;
  align-items: stretch;
  flex-shrink: 0;
}
.topbar-nav > .nav-more > summary {
  /* keep native disclosure behavior with flex summary */
  appearance: none;
  -webkit-appearance: none;
}
.topbar-nav > .nav-more > summary::-webkit-details-marker { display: none; }
.topbar-nav > .nav-more > summary::marker { content: ""; }
.topbar-nav > .nav-more > summary::after {
  content: "▾";
  font-size: 0.65rem;
  margin-left: 0.35rem;
  opacity: 0.7;
}
.topbar-nav > .nav-more[open] > summary {
  color: var(--panel);
  background: rgba(255, 250, 240, 0.12);
}
.nav-more-menu {
  position: absolute;
  top: calc(100% - 1px);
  left: 0;
  min-width: 12rem;
  z-index: 50;
  border: 2px solid var(--ink);
  background: var(--panel);
  color: var(--ink);
  box-shadow: 0 12px 32px rgba(20, 17, 14, 0.28);
  display: flex;
  flex-direction: column;
  padding: 0.25rem 0;
}
.nav-more-menu a {
  display: block !important;
  width: 100%;
  box-sizing: border-box;
  padding: 0.55rem 0.9rem !important;
  border: none !important;
  border-right: 0 !important;
  box-shadow: none !important;
  font-size: var(--text-sm);
  color: var(--ink-soft);
  text-decoration: none;
  font-weight: 600;
  white-space: nowrap;
  background: transparent;
  height: auto !important;
}
.nav-more-menu a:hover {
  background: var(--paper-2);
  color: var(--ink);
  text-decoration: none;
}
.nav-more-menu a.active {
  background: var(--paper);
  color: var(--ink);
  box-shadow: inset 3px 0 0 var(--accent) !important;
}
@media (max-width: 700px) {
  .topbar-nav {
    flex-wrap: wrap;
  }
}
.topbar-tools {
  display: flex;
  align-items: stretch;
  margin-left: auto;
  flex-wrap: wrap;
}
.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0 0.75rem;
  min-height: 2.75rem;
  color: rgba(255, 250, 240, 0.82);
  font-size: var(--text-sm);
  font-weight: 700;
  letter-spacing: 0.02em;
  text-decoration: none;
  border-left: 1px solid rgba(255, 250, 240, 0.1);
  background: transparent;
  touch-action: manipulation;
}
.tool-btn:hover { background: rgba(255, 250, 240, 0.1); color: var(--panel); text-decoration: none; }
.tool-btn .ico {
  width: 18px; height: 18px;
  display: grid; place-items: center;
  flex-shrink: 0;
}
.tool-btn .ico svg { width: 16px; height: 16px; display: block; }
.tool-btn .tool-label { }
.tool-btn.plex .ico { color: #1a1a1a; background: var(--plex); border-radius: 3px; padding: 1px; }
.tool-btn.tautulli .ico { color: var(--tautulli); }
.tool-btn.sheets .ico { color: var(--sheets); }
.tool-btn.tadoku .ico { color: var(--tadoku); }
.tool-btn.youtube .ico { color: var(--youtube); }
.health-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0 0.75rem;
  border-left: 1px solid rgba(255, 250, 240, 0.1);
  font-family: var(--mono);
  font-size: var(--text-xs);
  font-weight: 700;
  color: rgba(255, 250, 240, 0.7);
  background: transparent;
  white-space: nowrap;
}
.health-chip.ok { display: none; }
.health-chip.warn { color: #fde68a; background: rgba(161, 98, 7, 0.35); }
.health-chip.bad { color: #fecaca; background: rgba(153, 27, 27, 0.45); }
.health-chip .status-dot { margin-right: 0; }
@media (max-width: 960px) {
  .tool-btn .tool-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }
  .tool-btn { padding: 0 0.55rem; position: relative; }
}

/* ── Layout: content as a floating ledger sheet on the blotter ── */
.page {
  max-width: var(--page-max);
  margin: 1rem auto 2.5rem;
  padding: 1.15rem 1.25rem 1.75rem;
  background: var(--panel);
  border: 2px solid var(--ink);
  box-shadow: var(--sheet-shadow);
  border-radius: 1px;
}
.page-wide { max-width: var(--page-max-wide); }
@media (max-width: 720px) {
  .page {
    margin: 0.5rem max(0.4rem, env(safe-area-inset-left, 0)) 1.5rem max(0.4rem, env(safe-area-inset-right, 0));
    padding: 0.85rem 0.75rem 1.25rem;
  }
}

/* Action ledger — bold queue ticket */
.ledger {
  display: grid;
  grid-template-columns: 1.2fr 1fr 1fr;
  gap: 0;
  border: 3px solid var(--ink);
  background: var(--panel);
  margin-bottom: var(--sp-3);
  box-shadow: 4px 4px 0 rgba(20, 17, 14, 0.12);
  position: relative;
}
.ledger::before {
  content: "QUEUE PULSE";
  position: absolute;
  top: -0.55rem;
  left: 0.75rem;
  font-family: var(--mono);
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  background: var(--accent);
  color: var(--accent-ink);
  padding: 0.1rem 0.45rem;
  line-height: 1.3;
}
.ledger.ledger-queue {
  grid-template-columns: 1.2fr 1fr 1fr;
}
.ledger.ledger-5 {
  grid-template-columns: 1.35fr 1fr 1fr 1fr 0.85fr;
}
@media (max-width: 900px) {
  .ledger, .ledger.ledger-queue { grid-template-columns: 1fr 1fr 1fr; }
  .ledger.ledger-5 { grid-template-columns: 1fr 1fr 1fr; }
}
@media (max-width: 520px) {
  .ledger, .ledger.ledger-queue, .ledger.ledger-5 { grid-template-columns: 1fr 1fr; }
}
.ledger-cell {
  padding: 0.7rem 0.95rem 0.75rem;
  border-right: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line);
  min-width: 0;
  background: var(--panel);
}
.ledger-cell:last-child { border-right: 0; }
/* Stamp only when work exists (JS adds .has-work) */
.ledger-cell.priority {
  border-right: 2px solid var(--ink);
}
.ledger-cell.priority.has-work {
  background: var(--amber-bg);
}
.ledger-cell.priority.ready-cell.has-work {
  background: var(--blue-bg);
}
.ledger-cell .k {
  font-size: var(--text-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--muted);
  margin-bottom: 0.2rem;
  font-family: var(--mono);
}
.ledger-cell .v {
  font-family: var(--mono);
  font-size: var(--text-metric);
  font-weight: 700;
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
  line-height: 1.0;
  color: var(--ink);
}
.ledger-cell.priority .v { font-size: 2.35rem; }
.ledger-cell.priority.has-work .v { color: var(--amber); }
.ledger-cell.ready-cell.has-work .v { color: var(--blue); }
.ledger-cell .s {
  font-size: var(--text-xs);
  color: var(--faint);
  margin-top: 0.2rem;
  font-family: var(--mono);
}
/* Pipeline desk note — hard to miss */
.desk-note {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.85rem;
  margin: 0 0 var(--sp-4);
  padding: 0.65rem 0.85rem;
  border: 2px solid var(--ink);
  background: linear-gradient(90deg, var(--amber-bg) 0%, var(--panel-2) 55%);
  font-size: var(--text-sm);
  color: var(--ink-soft);
  line-height: 1.4;
  box-shadow: 2px 2px 0 rgba(20, 17, 14, 0.08);
}
.desk-note.hidden { display: none; }
.desk-note-pipe b {
  font-weight: 700;
  color: var(--ink);
  font-size: 0.95em;
}
.desk-note-pipe .pipe-arrow {
  color: var(--accent);
  font-family: var(--mono);
  font-weight: 700;
  margin: 0 0.2rem;
}
.desk-note-dismiss {
  margin-left: auto;
  font-size: var(--text-xs);
  font-weight: 700;
  padding: 0.3rem 0.55rem;
  min-height: 1.75rem;
  background: var(--panel);
  border-color: var(--ink);
  color: var(--ink-soft);
}
.desk-note-dismiss:hover { color: var(--ink); background: var(--paper-2); }

/* Immersion volume — secondary ledger (context, not primary work) */
.immersion-panel {
  border: var(--frame-work);
  background: var(--panel);
  margin: var(--sp-3) 0 var(--sp-3);
  overflow: hidden;
}
.immersion-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.35rem 1rem;
  padding: 0.5rem 0.9rem;
  background: var(--panel-2);
  color: var(--ink);
  border-bottom: 1px solid var(--line-strong);
}
.immersion-head h2 {
  margin: 0;
  font-family: var(--display);
  font-size: var(--text-md);
  font-weight: 600;
  letter-spacing: 0.01em;
}
.immersion-sub {
  font-family: var(--mono);
  font-size: var(--text-xs);
  color: var(--muted);
  font-weight: 500;
}
.immersion-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0;
}
.immersion-card {
  position: relative;
  padding: 0.85rem 0.95rem 0.75rem;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  min-width: 0;
  background: var(--panel);
}
.immersion-card::before {
  content: "";
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
  background: var(--line-strong);
}
.immersion-card .ik {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  margin-bottom: 0.25rem;
}
.immersion-card .iv {
  font-family: var(--mono);
  font-size: 1.45rem; /* one step under pulse metrics */
  font-weight: 700;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
  line-height: 1.05;
  color: var(--ink);
}
.immersion-card .iu {
  font-size: 0.7rem;
  color: var(--faint);
  margin-top: 0.28rem;
  font-family: var(--mono);
}
.immersion-card.skeleton .iv { color: var(--faint); }
/* Tone: left rail + metric color only (no full-card gradients) */
.immersion-card.tone-listen::before { background: var(--blue); }
.immersion-card.tone-listen .iv { color: var(--blue); }
.immersion-card.tone-chars::before { background: var(--accent); }
.immersion-card.tone-chars .iv { color: var(--accent); }
.immersion-card.tone-pages::before { background: var(--green); }
.immersion-card.tone-pages .iv { color: var(--green); }
.immersion-card.tone-comic::before { background: #7a3d6a; }
.immersion-card.tone-comic .iv { color: #7a3d6a; }
.immersion-card.tone-sent::before { background: var(--amber); }
.immersion-card.tone-sent .iv { color: var(--amber); }
.immersion-card.tone-write::before { background: #3d6b4f; }
.immersion-card.tone-write .iv { color: #3d6b4f; }
.immersion-card.tone-speak::before { background: #5c3d7a; }
.immersion-card.tone-speak .iv { color: #5c3d7a; }
.immersion-card.tone-study::before { background: var(--tadoku); }
.immersion-card.tone-study .iv { color: var(--tadoku); }
.immersion-card.tone-other::before { background: var(--muted); }
@media (max-width: 600px) {
  .immersion-grid { grid-template-columns: 1fr 1fr; }
  .immersion-card .iv { font-size: 1.45rem; }
}

/* Year immersion chart (collapsible, inside immersion panel) */
.immersion-chart-fold {
  border-top: 1px solid var(--line-strong);
  background: var(--panel-2);
}
.immersion-chart-fold > summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem 0.75rem;
  padding: 0.55rem 0.9rem;
  font-weight: 700;
  font-size: 0.82rem;
  color: var(--ink-soft);
  user-select: none;
  background: var(--paper-2);
  border-bottom: 1px solid transparent;
}
.immersion-chart-fold > summary::-webkit-details-marker { display: none; }
.immersion-chart-fold[open] > summary {
  border-bottom-color: var(--line);
  color: var(--ink);
}
.immersion-chart-fold > summary .chev {
  font-family: var(--mono);
  font-size: 0.75rem;
  opacity: 0.65;
  transition: transform 0.15s;
}
.immersion-chart-fold[open] > summary .chev { transform: rotate(90deg); }
.immersion-chart-fold > summary .chart-title {
  font-family: var(--display);
  font-weight: 600;
  letter-spacing: 0.01em;
}
.immersion-chart-fold > summary .chart-sub {
  font-family: var(--mono);
  font-size: 0.72rem;
  font-weight: 500;
  color: var(--muted);
  margin-left: auto;
}
.immersion-chart-body {
  padding: 0.55rem 0.75rem 0.85rem;
}
.immersion-chart-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.55rem;
  margin-bottom: 0.45rem;
}
.immersion-chart-toolbar .hint {
  font-size: 0.7rem;
  color: var(--faint);
  font-family: var(--mono);
  margin-left: auto;
}
.series-chip {
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.6rem 0.35rem 0.45rem;
  min-height: 2rem;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  background: var(--panel);
  font-family: var(--font);
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--ink-soft);
  cursor: pointer;
}
.series-chip:hover { background: var(--paper); color: var(--ink); }
.series-chip .dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.series-chip.on {
  border-color: var(--ink);
  color: var(--ink);
  background: var(--panel);
  box-shadow: inset 0 0 0 1px var(--ink);
}
.series-chip.off {
  opacity: 1;
  color: var(--muted);
  background: var(--paper-2);
  border-style: dashed;
  border-color: var(--line);
  box-shadow: none;
}
.immersion-chart-wrap {
  position: relative;
  height: min(38vh, 320px);
  min-height: 220px;
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 2px;
}
.immersion-chart-wrap canvas {
  width: 100% !important;
  height: 100% !important;
  display: block;
  cursor: crosshair;
}
.immersion-chart-tip {
  position: absolute;
  pointer-events: none;
  z-index: 5;
  background: var(--ink);
  color: var(--accent-ink);
  font-size: 0.75rem;
  padding: 0.45rem 0.6rem;
  border-radius: 4px;
  box-shadow: 0 6px 20px rgba(28, 25, 20, 0.25);
  max-width: 240px;
  display: none;
  line-height: 1.35;
}
.immersion-chart-tip strong {
  display: block;
  margin-bottom: 0.15rem;
  font-size: 0.78rem;
}
.immersion-chart-tip .row {
  font-family: var(--mono);
  font-size: 0.72rem;
  opacity: 0.92;
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.immersion-chart-tip .row .dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.immersion-chart-empty {
  display: none;
  position: absolute;
  inset: 0;
  place-items: center;
  font-size: 0.85rem;
  color: var(--faint);
  font-weight: 600;
  text-align: center;
  padding: 1rem;
}
.immersion-chart-empty.show { display: grid; }

/* Activity heat map (GitHub-style contribution calendar) */
.immersion-heat-wrap {
  position: relative;
  overflow-x: auto;
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 2px;
  padding: 0.55rem 0.65rem 0.45rem;
  min-height: 120px;
}
.immersion-heat {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.35rem 0.45rem;
  min-width: min(100%, 720px);
  width: max-content;
  max-width: 100%;
}
.heat-dows {
  display: grid;
  grid-template-rows: repeat(7, var(--heat-cell, 12px));
  gap: var(--heat-gap, 3px);
  align-content: start;
  padding-top: 1.15rem; /* align under month row */
}
.heat-dows span {
  font-family: var(--mono);
  font-size: 0.62rem;
  font-weight: 600;
  color: var(--faint);
  line-height: var(--heat-cell, 12px);
  height: var(--heat-cell, 12px);
  text-align: right;
  padding-right: 0.1rem;
  user-select: none;
}
.heat-dows span.blank { visibility: hidden; }
.heat-main {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  min-width: 0;
}
.heat-months {
  display: flex;
  position: relative;
  height: 0.9rem;
  font-family: var(--mono);
  font-size: 0.62rem;
  font-weight: 600;
  color: var(--muted);
  user-select: none;
}
.heat-months span {
  position: absolute;
  top: 0;
  white-space: nowrap;
}
.heat-weeks {
  display: flex;
  gap: var(--heat-gap, 3px);
}
.heat-week {
  display: grid;
  grid-template-rows: repeat(7, var(--heat-cell, 12px));
  gap: var(--heat-gap, 3px);
}
.heat-cell {
  width: var(--heat-cell, 12px);
  height: var(--heat-cell, 12px);
  min-width: var(--heat-cell, 12px);
  min-height: var(--heat-cell, 12px);
  border-radius: 2px;
  border: 1px solid rgba(28, 25, 20, 0.08);
  background: var(--paper-2);
  box-sizing: border-box;
  cursor: default;
  padding: 0;
  margin: 0;
  font-size: 0;
  line-height: 0;
  font-weight: 400;
  appearance: none;
  display: block;
  color: transparent;
}
button.heat-cell:hover {
  background: inherit; /* override global button:hover */
}
.heat-cell.future {
  background: transparent;
  border-color: transparent;
  pointer-events: none;
}
.heat-cell.l0 { background: #e4dcc8; border-color: rgba(26, 23, 18, 0.08); }
.heat-cell.l1 { background: #e0c0a0; border-color: rgba(184, 78, 31, 0.14); }
.heat-cell.l2 { background: #d07a48; border-color: rgba(184, 78, 31, 0.2); }
.heat-cell.l3 { background: #b84e1f; border-color: rgba(26, 23, 18, 0.12); }
.heat-cell.l4 { background: #7a3512; border-color: rgba(26, 23, 18, 0.18); }
button.heat-cell.l0:hover { background: #e4dcc8; }
button.heat-cell.l1:hover { background: #e0c0a0; }
button.heat-cell.l2:hover { background: #d07a48; }
button.heat-cell.l3:hover { background: #b84e1f; }
button.heat-cell.l4:hover { background: #7a3512; }
.heat-cell:not(.future):hover,
.heat-cell:not(.future):focus-visible {
  outline: 2px solid var(--ink);
  outline-offset: 1px;
  z-index: 1;
  position: relative;
}
button.heat-cell {
  min-height: 0;
  min-width: 0;
  padding: 0;
}
.immersion-heat-legend {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.28rem;
  margin-top: 0.4rem;
  font-family: var(--mono);
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--faint);
}
.immersion-heat-legend .heat-swatch {
  width: 11px;
  height: 11px;
  border-radius: 2px;
  border: 1px solid rgba(28, 25, 20, 0.08);
  display: inline-block;
}
.immersion-heat-legend .heat-swatch.l0 { background: #e4dcc8; }
.immersion-heat-legend .heat-swatch.l1 { background: #e0c0a0; }
.immersion-heat-legend .heat-swatch.l2 { background: #d07a48; }
.immersion-heat-legend .heat-swatch.l3 { background: #b84e1f; }
.immersion-heat-legend .heat-swatch.l4 { background: #7a3512; }
@media (max-width: 700px) {
  .immersion-heat {
    --heat-cell: 10px;
    --heat-gap: 2px;
  }
}

.mast {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.35rem 1rem;
  margin: 0 0 var(--sp-4);
  padding: 0 0 0.65rem;
  border-bottom: 2px solid var(--ink);
}
.mast h1 {
  margin: 0;
  font-family: var(--display);
  font-size: var(--text-xl);
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1.15;
  text-wrap: balance;
}
.mast .meta {
  font-size: var(--text-xs);
  color: var(--muted);
  font-family: var(--mono);
}
.status-dot {
  display: inline-block;
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--green);
  margin-right: 0.35rem;
  vertical-align: middle;
}
.status-dot.warn { background: var(--amber); }
.status-dot.bad { background: var(--red); }

/* Queue page chrome (non-collapsible full page) — work frame */
.queue-page-chrome {
  border: var(--frame-work);
  background: var(--panel);
  margin: 0.5rem 0 1rem;
  padding: 0.75rem 0.85rem 1rem;
}
.queue-page-chrome .fold-toolbar { margin-top: 0; }
/* Collapsible blocks — work frame (primary ops) */
.fold {
  border: var(--frame-work);
  background: var(--panel);
  margin: 0.5rem 0 0.85rem;
}
/* Quiet folds: secondary (GSM, recent, etc.) — don't shout ink heads */
.fold.fold-quiet {
  border: var(--frame-quiet);
  margin: 0.45rem 0 0.65rem;
}
.fold.fold-quiet > summary {
  background: var(--panel-2);
  color: var(--ink);
  border-bottom: 1px solid var(--line);
  font-size: var(--text-sm);
  font-weight: 700;
}
.fold.fold-quiet > summary .count-badge.zero {
  background: var(--line-strong);
  color: var(--ink);
}
.fold.fold-quiet > summary .sub { color: var(--muted); opacity: 1; }
.fold > summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.85rem;
  padding: 0.65rem 0.9rem;
  background: var(--ink);
  color: var(--panel);
  font-weight: 700;
  font-size: 0.92rem;
  user-select: none;
}
.fold > summary::-webkit-details-marker { display: none; }
.fold > summary .chev {
  font-family: var(--mono);
  font-size: 0.85rem;
  opacity: 0.7;
  transition: transform 0.15s;
}
.fold[open] > summary .chev { transform: rotate(90deg); }
.fold > summary .count-badge {
  font-family: var(--mono);
  font-size: 0.78rem;
  font-weight: 700;
  background: var(--accent);
  color: #fff;
  padding: 0.15rem 0.45rem;
  border-radius: 2px;
}
.fold > summary .count-badge.zero { background: #4a453c; }
.fold > summary .sub {
  font-weight: 500;
  font-size: 0.78rem;
  opacity: 0.75;
  margin-left: auto;
}
.fold-body { padding: 0.75rem 0.85rem 1rem; }
.fold-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
  margin-bottom: 0.75rem;
  padding-bottom: 0.65rem;
  border-bottom: 1px solid var(--line);
}
.inbox-ops-bar {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
  flex: 1 1 auto;
  min-width: 0;
}
/* Sticky submit/msg on Inbox only — keeps primary CTA under topbar */
.page-inbox .inbox-ops-bar {
  position: sticky;
  top: calc(var(--topbar-h) + env(safe-area-inset-top, 0px));
  z-index: 15;
  background: var(--panel);
  border-bottom: 1px solid var(--line-strong, var(--line));
  margin: 0 -0.15rem 0.35rem;
  padding: 0.45rem 0.35rem 0.5rem;
}
.page-inbox .fold-toolbar {
  align-items: flex-start;
}
.page-inbox {
  padding-bottom: calc(5.5rem + env(safe-area-inset-bottom, 0px));
}
.page-inbox .mast .count-badge {
  vertical-align: middle;
}
.fold-toolbar .msg {
  font-size: 0.8rem;
  color: var(--muted);
  font-family: var(--mono);
  min-height: 1.1em;
  flex: 1;
}
.fold-toolbar .links {
  font-size: 0.78rem;
  color: var(--muted);
}
.process-cluster {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  flex-shrink: 0;
}
.auto-chip {
  font-family: var(--mono);
  font-size: 0.75rem;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: var(--muted);
  opacity: 0.9;
  white-space: nowrap;
  user-select: none;
  padding: 0.15rem 0.15rem;
}
.auto-chip.off { opacity: 0.55; }
.auto-chip.soon { color: var(--accent); opacity: 1; }
.contest-line {
  font-size: 0.78rem;
  color: var(--muted);
  margin: 0 0 0.65rem;
  font-family: var(--mono);
}
.session-banner {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  margin: 0 0 0.75rem;
  padding: 0.65rem 0.75rem;
  border: 1px solid var(--ink);
  border-radius: 3px;
  background: var(--paper-2);
  font-size: 0.82rem;
  line-height: 1.35;
}
.session-banner.hidden { display: none; }
.session-banner.bad {
  border-color: #a33;
  background: #fdecea;
  color: #5c1a14;
}
.session-banner.warn {
  border-color: #b8860b;
  background: #fff8e6;
  color: #5c4a10;
}
.session-banner a { color: inherit; font-weight: 700; }
.session-banner-form {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
}
.session-banner-form input {
  flex: 1 1 10rem;
  min-width: 8rem;
  font-family: var(--mono);
  font-size: 0.78rem;
  padding: 0.35rem 0.5rem;
  border: 1px solid var(--ink);
  border-radius: 2px;
  background: #fff;
}
.session-banner-form input[type="password"] {
  flex: 1 1 10rem;
}
.session-banner-form button:disabled {
  opacity: 0.55;
  cursor: wait;
}

/* GSM fold (Queue / Home) */
.fold-gsm .gsm-banner {
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--paper-2);
  font-size: 0.86rem;
  line-height: 1.4;
  margin-bottom: 0.75rem;
}
.fold-gsm .gsm-banner.ok { border-color: color-mix(in srgb, var(--green, #2a7a4b) 40%, var(--line)); }
.fold-gsm .gsm-banner.warn { border-color: color-mix(in srgb, var(--warn, #b8860b) 45%, var(--line)); }
.fold-gsm .gsm-banner.bad { border-color: color-mix(in srgb, var(--red, #b33) 45%, var(--line)); }
.fold-gsm .gsm-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.55rem;
  margin-bottom: 0.75rem;
}
@media (max-width: 520px) {
  .fold-gsm .gsm-stats { grid-template-columns: 1fr; }
}
.fold-gsm .gsm-stat {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 0.55rem 0.7rem;
}
.fold-gsm .gsm-stat .k {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  font-weight: 600;
}
.fold-gsm .gsm-stat .v {
  font-family: var(--mono);
  font-size: 1.25rem;
  font-weight: 700;
  margin-top: 0.15rem;
}
.fold-gsm .gsm-stat .s {
  font-size: 0.78rem;
  color: var(--muted);
  margin-top: 0.15rem;
}
.fold-gsm .gsm-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: 0.35rem;
}
.fold-gsm .gsm-msg {
  min-height: 1.1rem;
  font-size: 0.82rem;
  font-family: var(--mono);
  margin: 0.25rem 0 0.5rem;
}
.fold-gsm .gsm-msg.ok { color: var(--green, #2a7a4b); }
.fold-gsm .gsm-msg.warn { color: var(--warn, #9a6b00); }
.fold-gsm .gsm-msg.bad { color: var(--red, #b33); }
.fold-gsm .gsm-count-meta {
  margin: 0 0 0.55rem;
  padding: 0.5rem 0.65rem;
  border: 1px dashed var(--line);
  border-radius: 4px;
  background: var(--paper-2);
  font-size: 0.8rem;
  line-height: 1.4;
}
.fold-gsm .gsm-raw-strip-caption {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--muted);
  margin: 0 0 0.25rem;
  letter-spacing: 0.01em;
}
.fold-gsm .gsm-raw-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.55rem 1.1rem;
  font-family: var(--mono);
  font-size: 0.92rem;
  margin-bottom: 0.4rem;
  padding: 0.35rem 0.45rem;
  border-radius: 3px;
  background: var(--panel);
  border: 1px solid var(--line);
}
.fold-gsm .gsm-raw-strip.is-active-strip,
.fold-gsm .gsm-raw-strip.is-active-raw {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--line));
  background: color-mix(in srgb, var(--accent) 7%, var(--panel));
}
.fold-gsm .gsm-raw-strip.has-savings {
  border-color: color-mix(in srgb, var(--warn, #9a6b00) 45%, var(--line));
}
.fold-gsm .gsm-count-warn {
  color: var(--warn, #9a6b00);
  font-weight: 600;
  margin: 0.15rem 0 0.35rem;
}
.fold-gsm .gsm-raw-strip-pair {
  display: inline-flex;
  align-items: baseline;
  gap: 0.35rem;
  opacity: 0.55;
}
.fold-gsm .gsm-raw-strip-pair.is-chosen {
  opacity: 1;
}
.fold-gsm .gsm-raw-strip-label {
  font-weight: 700;
  color: var(--muted);
  text-transform: none;
  letter-spacing: 0;
  font-size: 0.82rem;
}
.fold-gsm .gsm-raw-strip-val {
  font-weight: 700;
  font-size: 1.05rem;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.fold-gsm .gsm-raw-strip-tag {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--accent, #3a6ea5);
  margin-left: 0.1rem;
}
.fold-gsm .gsm-raw-strip-diff {
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--warn, #9a6b00);
  margin-left: auto;
}
.fold-gsm .gsm-raw-strip-diff.same {
  color: var(--muted);
  font-weight: 600;
}
.fold-gsm .gsm-count-delta-log {
  margin-top: 0.35rem;
  color: var(--ink);
}
.fold-gsm .gsm-count-mode {
  font-weight: 600;
  color: var(--muted);
  font-size: 0.85em;
}
.fold-gsm .gsm-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-bottom: 0.2rem;
}
.fold-gsm .gsm-chip {
  display: inline-block;
  padding: 0.12rem 0.45rem;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--muted);
  font-size: 0.74rem;
  font-weight: 600;
  font-family: var(--mono);
}
.fold-gsm .gsm-chip.on {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
  color: var(--ink);
  background: color-mix(in srgb, var(--accent) 10%, var(--panel));
}
.fold-gsm .gsm-count-delta {
  display: block;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 0.78rem;
}
.fold-gsm .gsm-adv-auto {
  margin-top: 0.55rem;
}
.fold-gsm .gsm-table-wrap {
  max-height: 14rem;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 4px;
  margin-bottom: 0.65rem;
}
.fold-gsm .gsm-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
}
.fold-gsm .gsm-table th,
.fold-gsm .gsm-table td {
  padding: 0.4rem 0.55rem;
  border-bottom: 1px solid var(--line);
  text-align: left;
}
.fold-gsm .gsm-table th {
  color: var(--muted);
  font-weight: 600;
  position: sticky;
  top: 0;
  background: var(--panel);
}
.fold-gsm .gsm-table .gsm-col-check {
  width: 1.75rem;
  padding-left: 0.45rem;
  padding-right: 0.15rem;
  vertical-align: middle;
}
.fold-gsm .gsm-table .gsm-col-check input {
  width: 1rem;
  height: 1rem;
  margin: 0;
  cursor: pointer;
  accent-color: var(--accent, #3b6d9c);
}
.fold-gsm .gsm-table .gsm-clear-game {
  margin-left: 0.5rem;
  padding: 0.15rem 0.45rem;
  font-size: 0.75rem;
  vertical-align: middle;
}
.fold-gsm .gsm-table tr.gsm-row-off td:not(.gsm-col-check) {
  opacity: 0.45;
}

/* Audiobookshelf panel */
.fold-abs .abs-body { display: flex; flex-direction: column; gap: 0.65rem; }
.fold-abs .abs-banner { margin-bottom: 0; }
.fold-abs .abs-timeline {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  padding: 0.7rem 0.8rem 0.65rem;
}
.fold-abs .abs-timeline-labels {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.45rem;
}
.fold-abs .abs-tl-side { display: flex; flex-direction: column; gap: 0.1rem; min-width: 0; }
.fold-abs .abs-tl-right { text-align: right; align-items: flex-end; }
.fold-abs .abs-tl-k {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  font-weight: 600;
}
.fold-abs .abs-tl-v {
  font-family: var(--mono);
  font-size: 0.92rem;
  font-weight: 650;
  color: var(--ink);
}
.fold-abs .abs-bar-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.9rem;
  margin-top: 0.45rem;
  font-size: 0.76rem;
  color: var(--muted);
  align-items: center;
}
.fold-abs .abs-bar-total { margin-left: auto; }
.fold-abs .abs-dot {
  display: inline-block;
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 50%;
  margin-right: 0.28rem;
  vertical-align: middle;
}
.fold-abs .abs-dot.logged { background: #b7e0c2; }
.fold-abs .abs-dot.pending { background: #1f6b3a; }
.fold-abs .abs-dot.empty { background: color-mix(in srgb, var(--line) 70%, var(--panel-2, #ddd)); border: 1px solid var(--line); box-sizing: border-box; }
/* Duration bar: already logged (light) | to log (dark) | remaining */
.fold-abs .abs-bar-stack {
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
  width: 100%;
  min-width: 0;
}
.fold-abs .abs-dur-bar {
  display: flex;
  width: 100%;
  height: 8px;
  border-radius: 999px;
  overflow: hidden;
  background: color-mix(in srgb, var(--line) 45%, var(--panel-2, var(--panel)));
  border: 1px solid var(--line);
}
.fold-abs .abs-dur-bar .abs-seg {
  display: block;
  height: 100%;
  min-width: 0;
  flex: 0 0 auto; /* width set inline as % of bar */
  box-sizing: border-box;
}
.fold-abs .abs-dur-bar .abs-seg.logged {
  background: #b7e0c2; /* already logged — light green */
}
.fold-abs .abs-dur-bar .abs-seg.pending {
  background: #1f6b3a; /* to log — dark green */
}
.fold-abs .abs-dur-bar .abs-seg.empty {
  background: color-mix(in srgb, var(--line) 35%, var(--panel-2, var(--panel)));
}
.fold-abs .abs-dur-total {
  font-size: 0.68rem;
  line-height: 1.15;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fold-abs .abs-dur-total .abs-dur-k {
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 650;
  font-size: 0.62rem;
  margin-right: 0.2rem;
}
.fold-abs .abs-dur-total.muted { opacity: 0.75; font-style: italic; }
.fold-abs .abs-actions { margin-bottom: 0; }
.fold-abs .abs-list-wrap {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  overflow: hidden;
}
.fold-abs .abs-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.4rem 0.65rem;
  border-bottom: 1px solid var(--line);
  background: var(--panel-2, var(--paper-2));
  font-size: 0.78rem;
  color: var(--muted);
}
.fold-abs .abs-select-all {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  cursor: pointer;
  user-select: none;
  color: var(--ink-soft, var(--ink));
  font-weight: 600;
}
.fold-abs .abs-select-all input {
  width: 1rem;
  height: 1rem;
  margin: 0;
  accent-color: var(--accent, #3b6d9c);
  cursor: pointer;
}
/* Table = hard column lock across rows */
.fold-abs .abs-list-scroll {
  max-height: 18rem;
  overflow: auto;
  scrollbar-gutter: stable;
}
.fold-abs .abs-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.fold-abs .abs-col-check { width: 2rem; }
.fold-abs .abs-col-cover { width: 3.25rem; }
.fold-abs .abs-col-main { width: auto; }
.fold-abs .abs-col-bar { width: 12rem; }
.fold-abs .abs-col-mins { width: 5.25rem; }
.fold-abs .abs-col-log { width: 3.5rem; }
.fold-abs .abs-table td {
  padding: 0.5rem 0.4rem;
  vertical-align: middle;
  border-bottom: 1px solid var(--line);
}
.fold-abs .abs-table tr:last-child td { border-bottom: 0; }
.fold-abs .abs-row:hover td {
  background: color-mix(in srgb, var(--accent, #3b6d9c) 5%, transparent);
}
.fold-abs .abs-td-check {
  padding-left: 0.55rem;
  padding-right: 0.15rem;
  text-align: center;
}
.fold-abs .abs-check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin: 0;
}
.fold-abs .abs-check input {
  width: 1rem;
  height: 1rem;
  margin: 0;
  accent-color: var(--accent, #3b6d9c);
  cursor: pointer;
}
.fold-abs .abs-td-cover {
  width: 3.25rem;
  text-align: center;
}
.fold-abs .abs-cover {
  display: inline-block;
  width: 40px;
  height: 40px;
  border-radius: 6px;
  object-fit: cover;
  vertical-align: middle;
  background: var(--paper-2, var(--panel-2));
  border: 1px solid var(--line);
}
.fold-abs .abs-cover-ph {
  background:
    linear-gradient(135deg,
      color-mix(in srgb, var(--line) 70%, transparent),
      color-mix(in srgb, var(--accent, #3b6d9c) 18%, var(--panel)));
}
.fold-abs .abs-td-main {
  min-width: 0;
  overflow: hidden;
}
.fold-abs .abs-title {
  font-weight: 650;
  font-size: 0.88rem;
  line-height: 1.25;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fold-abs .abs-meta {
  font-size: 0.72rem;
  color: var(--muted);
  margin-top: 0.12rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fold-abs .abs-td-bar {
  width: 12rem;
  padding-left: 0.35rem;
  padding-right: 0.35rem;
}
.fold-abs .abs-td-mins {
  width: 5.25rem;
  text-align: right;
  white-space: nowrap;
  padding-right: 0.35rem;
  line-height: 1.15;
}
.fold-abs .abs-mins-val {
  font-family: var(--mono);
  font-size: 0.88rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: #1f6b3a;
}
.fold-abs .abs-mins-k {
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 650;
  color: var(--muted);
  margin-top: 0.1rem;
}
.fold-abs .abs-td-log {
  width: 3.5rem;
  padding-right: 0.55rem;
  padding-left: 0.15rem;
  text-align: right;
}
.fold-abs .abs-row-log {
  display: inline-block;
  width: 3rem;
  min-width: 3rem;
  max-width: 3rem;
  margin: 0;
  padding: 0.28rem 0;
  font-size: 0.78rem;
  line-height: 1.2;
  text-align: center;
  box-sizing: border-box;
}
.fold-abs .abs-empty {
  padding: 1rem 0.75rem;
  text-align: center;
  color: var(--muted);
  font-size: 0.84rem;
}
@media (max-width: 640px) {
  .fold-abs .abs-col-bar { width: 7.5rem; }
  .fold-abs .abs-col-mins { width: 4.25rem; }
  .fold-abs .abs-td-bar { width: 7.5rem; }
  .fold-abs .abs-bar-total { margin-left: 0; width: 100%; }
}

/* Settings panels (Counting + Auto logging) */
.fold-gsm .gsm-adv {
  border: 1px solid var(--line-strong);
  border-radius: 3px;
  background: var(--panel);
  padding: 0;
  overflow: hidden;
}
.fold-gsm .gsm-adv > summary {
  cursor: pointer;
  font-weight: 700;
  font-size: 0.84rem;
  padding: 0.55rem 0.75rem;
  list-style: none;
  color: var(--ink-soft);
  background: var(--panel-2);
  border-bottom: 1px solid transparent;
  user-select: none;
}
.fold-gsm .gsm-adv[open] > summary {
  border-bottom-color: var(--line);
  color: var(--ink);
}
.fold-gsm .gsm-adv > summary::-webkit-details-marker { display: none; }
.fold-gsm .gsm-adv > summary::before {
  content: "▸";
  display: inline-block;
  width: 1em;
  margin-right: 0.25rem;
  color: var(--muted);
  font-size: 0.78em;
  transition: transform 0.12s ease;
}
.fold-gsm .gsm-adv[open] > summary::before {
  transform: rotate(90deg);
}
.fold-gsm .gsm-settings {
  padding: 0.7rem 0.75rem 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.fold-gsm .gsm-hint {
  font-size: 0.8rem;
  color: var(--muted);
  line-height: 1.45;
  margin: 0;
  text-wrap: pretty;
}
.fold-gsm .gsm-toggle-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  border: 1px solid var(--line);
  border-radius: 3px;
  background: var(--panel-2);
  overflow: hidden;
}
.fold-gsm .gsm-toggle {
  display: grid;
  grid-template-columns: 1.15rem 1fr;
  column-gap: 0.65rem;
  align-items: start;
  margin: 0;
  padding: 0.6rem 0.7rem;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
  font-weight: 400;
  color: var(--ink);
}
.fold-gsm .gsm-toggle:last-child {
  border-bottom: 0;
}
.fold-gsm .gsm-toggle:hover {
  background: color-mix(in srgb, var(--panel) 70%, var(--panel-2));
}
.fold-gsm .gsm-toggle input[type="checkbox"] {
  margin: 0.2rem 0 0;
  width: 1rem;
  height: 1rem;
  accent-color: var(--accent);
  cursor: pointer;
  flex-shrink: 0;
}
.fold-gsm .gsm-toggle-text {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}
.fold-gsm .gsm-toggle-title {
  font-size: 0.86rem;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.3;
}
.fold-gsm .gsm-toggle-desc {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--muted);
  line-height: 1.4;
  text-wrap: pretty;
}
.fold-gsm .gsm-toggle-compact {
  align-items: center;
  padding: 0.45rem 0.55rem;
  border: 1px solid var(--line);
  border-radius: 3px;
  background: var(--panel-2);
  min-height: 2.4rem;
}
.fold-gsm .gsm-toggle-compact input[type="checkbox"] {
  margin-top: 0;
}
.fold-gsm .gsm-live-effect {
  margin: 0;
  padding: 0.5rem 0.65rem;
  font-size: 0.78rem;
  font-family: var(--mono);
  line-height: 1.4;
  color: var(--muted);
  background: var(--paper-2);
  border: 1px dashed var(--line-strong);
  border-radius: 3px;
  text-wrap: pretty;
}
.fold-gsm .gsm-settings-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
  padding-top: 0.15rem;
}
.fold-gsm .gsm-skip-history {
  font-size: 0.78rem;
  font-weight: 600;
  opacity: 0.92;
  margin-left: auto;
}
.fold-gsm .gsm-section {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding: 0.7rem 0.75rem;
  border: 1px solid var(--line);
  border-radius: 3px;
  background: var(--panel-2);
}
.fold-gsm .gsm-section + .gsm-section {
  margin-top: 0;
}
.fold-gsm .gsm-section-head {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.fold-gsm .gsm-section-title {
  margin: 0;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--ink);
  line-height: 1.3;
}
.fold-gsm .gsm-section-desc {
  margin: 0;
  font-size: 0.78rem;
  color: var(--muted);
  line-height: 1.4;
  font-weight: 500;
  text-wrap: pretty;
}
.fold-gsm .gsm-field-grid {
  display: grid;
  gap: 0.65rem 0.85rem;
  align-items: end;
}
.fold-gsm .gsm-field-grid-cont {
  grid-template-columns: auto minmax(6.5rem, 1fr) minmax(5.5rem, 1fr);
}
.fold-gsm .gsm-field-grid-daily {
  grid-template-columns: auto minmax(7.5rem, 10rem) minmax(0, 1fr);
  align-items: center;
}
.fold-gsm .gsm-field {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  min-width: 0;
  margin: 0;
}
.fold-gsm .gsm-field-label {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: var(--muted);
  line-height: 1.2;
}
.fold-gsm .gsm-field input[type="number"],
.fold-gsm .gsm-field select {
  width: 100%;
  max-width: 11rem;
  font: inherit;
  font-family: var(--mono);
  font-size: 0.86rem;
  font-variant-numeric: tabular-nums;
  padding: 0.4rem 0.5rem;
  border: 1px solid var(--line-strong);
  border-radius: 2px;
  background: var(--panel);
  color: var(--ink);
  min-height: 2.15rem;
}
.fold-gsm .gsm-field select {
  max-width: 9.5rem;
  cursor: pointer;
}
.fold-gsm .gsm-field-mode .gsm-pref-mode {
  width: fit-content;
}
.fold-gsm .gsm-pref-mode {
  display: inline-flex;
  border: 1px solid var(--line-strong);
  border-radius: 3px;
  overflow: hidden;
  background: var(--panel);
}
.fold-gsm .gsm-pref-mode button {
  border: 0;
  border-radius: 0;
  background: transparent;
  padding: 0.4rem 0.85rem;
  font-size: 0.8rem;
  font-weight: 700;
  min-height: 2.15rem;
  color: var(--muted);
}
.fold-gsm .gsm-pref-mode button + button {
  border-left: 1px solid var(--line-strong);
}
.fold-gsm .gsm-pref-mode button:hover {
  background: color-mix(in srgb, var(--panel-2) 80%, var(--panel));
  color: var(--ink);
}
.fold-gsm .gsm-pref-mode button.on {
  background: var(--accent);
  color: var(--accent-ink);
}
.fold-gsm .gsm-pref-mode button.on:hover {
  background: var(--accent-hover);
  color: var(--accent-ink);
}
.fold-gsm .gsm-tz {
  margin: 0;
  font-size: 0.76rem;
  font-family: var(--mono);
  color: var(--muted);
  line-height: 1.35;
  align-self: end;
  padding-bottom: 0.45rem;
  min-width: 0;
}
@media (max-width: 560px) {
  .fold-gsm .gsm-field-grid-cont,
  .fold-gsm .gsm-field-grid-daily {
    grid-template-columns: 1fr 1fr;
  }
  .fold-gsm .gsm-field-mode,
  .fold-gsm .gsm-toggle-compact {
    grid-column: 1 / -1;
  }
  .fold-gsm .gsm-tz {
    grid-column: 1 / -1;
    padding-bottom: 0;
    align-self: start;
  }
  .fold-gsm .gsm-field input[type="number"],
  .fold-gsm .gsm-field select {
    max-width: none;
  }
  .fold-gsm .gsm-skip-history {
    margin-left: 0;
    width: 100%;
    text-align: left;
  }
}
.fold-gsm #gsm-refresh-btn.gsm-busy {
  opacity: 0.75;
  cursor: wait;
}
.fold-gsm .gsm-stats.gsm-flash {
  animation: gsm-flash 0.7s ease;
}
@keyframes gsm-flash {
  0% { box-shadow: 0 0 0 0 transparent; }
  30% {
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 55%, transparent);
    background: color-mix(in srgb, var(--accent) 8%, transparent);
  }
  100% { box-shadow: 0 0 0 0 transparent; }
}
.fold-gsm .gsm-stats.gsm-flash .gsm-stat {
  border-color: color-mix(in srgb, var(--accent) 40%, var(--line));
}
@media (max-width: 640px) {
  .fold-gsm .col-hide-sm { display: none; }
}

/* Queue groups (shared home + /queue) */
button {
  font-family: inherit;
  cursor: pointer;
  border: 1px solid var(--ink);
  border-radius: var(--radius);
  font-weight: 700;
  font-size: 0.82rem;
  padding: 0.4rem 0.75rem;
  min-height: 2rem;
  background: var(--panel);
  color: var(--ink);
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
}
button:hover { background: var(--paper-2); border-color: var(--ink-soft); }
button:active { background: var(--panel-2); }
button:disabled { opacity: 0.45; cursor: not-allowed; }
/* Primary CTA — process remains supported alias indefinitely */
button.process,
button.primary,
.btn.primary,
.btn-primary {
  background: var(--accent);
  color: var(--accent-ink);
  border-color: #8f3f14;
}
button.process:hover,
button.primary:hover,
.btn.primary:hover,
.btn-primary:hover { background: var(--accent-hover); }
/* Shared tab strip (logs / progress aliases) */
.app-tabs,
.logs-tabs,
.prog-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  border-bottom: 1px solid var(--line-strong);
  margin-bottom: 0.65rem;
  overflow-x: auto;
  scrollbar-width: thin;
}
.app-tab,
.logs-tab,
.prog-tab {
  appearance: none;
  border: none;
  background: transparent;
  font-family: inherit;
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--ink-soft);
  padding: 0.55rem 0.85rem;
  cursor: pointer;
  border-bottom: 3px solid transparent;
  margin-bottom: -1px;
  white-space: nowrap;
}
.app-tab:hover,
.logs-tab:hover,
.prog-tab:hover { color: var(--ink); background: var(--paper-2); }
.app-tab.active,
.logs-tab.active,
.prog-tab.active {
  color: var(--ink);
  border-bottom-color: var(--accent);
  background: var(--panel);
}
.empty-state {
  padding: 1.25rem 0.5rem;
  text-align: center;
  color: var(--muted);
  font-size: 0.9rem;
  border: 1px dashed var(--line-strong);
  background: var(--panel-2);
}
.home-insight {
  border: var(--frame-quiet);
  background: var(--panel);
  margin: 0.55rem 0 0.75rem;
}
.home-insight > summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem 0.75rem;
  padding: 0.5rem 0.85rem;
  font-weight: 700;
  font-size: var(--text-sm);
  font-family: var(--display);
  color: var(--ink-soft);
  background: var(--panel-2);
  user-select: none;
}
.home-insight > summary::-webkit-details-marker { display: none; }
.home-insight[open] > summary { color: var(--ink); border-bottom: 1px solid var(--line); }
.home-insight > summary .chev {
  font-family: var(--mono);
  font-size: 0.75rem;
  opacity: 0.65;
  transition: transform 0.15s;
}
.home-insight[open] > summary .chev { transform: rotate(90deg); }
.home-nav-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 0.5rem 0 1rem;
}
.help-fold {
  border: var(--frame-quiet);
  background: var(--panel);
  margin: 0.5rem 0;
}
.help-fold > summary {
  list-style: none;
  cursor: pointer;
  padding: 0.5rem 0.85rem;
  font-size: var(--text-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  user-select: none;
}
.help-fold > summary::-webkit-details-marker { display: none; }
.help-fold[open] > summary { border-bottom: 1px solid var(--line); color: var(--ink); }
.help-fold .help-body { padding: 0.75rem 0.95rem 1rem; }
@media (max-width: 900px) {
  .col-hide-md { display: none !important; }
}
@media (max-width: 700px) {
  .col-hide-sm { display: none !important; }
}
button.approve, button.approve-group {
  background: var(--green);
  color: #fff;
  border-color: #1f4a28;
}
button.approve:hover, button.approve-group:hover { background: #255a30; }
button.skip, button.skip-group {
  background: var(--ink-soft);
  color: #fff;
  border-color: var(--ink);
}
button.skip:hover, button.skip-group:hover { background: #2e2a24; }
button.secondary { background: var(--paper-2); }
button.danger {
  background: var(--red);
  color: #fff;
  border-color: #7a2a24;
}
button.danger:hover { background: #8a3028; }
button.danger.log-del-btn.is-armed {
  background: #7f1d1d;
  border-color: #450a0a;
  animation: log-del-pulse 1s ease infinite alternate;
}
@keyframes log-del-pulse {
  from { filter: brightness(1); }
  to { filter: brightness(1.12); }
}
.recent-table .col-actions-q {
  width: 1%;
  white-space: nowrap;
  text-align: right;
}
.recent-table .log-del-btn {
  font-size: 0.75rem;
  padding: 0.28rem 0.5rem;
}
.group {
  margin: 0.85rem 0 1.1rem;
  border: 1px solid var(--line-strong);
  background: var(--panel-2);
}
.group.group-youtube {
  border-color: color-mix(in srgb, var(--youtube) 35%, var(--line-strong));
}
.group.group-youtube .group-head {
  border-left: 3px solid var(--youtube);
}
.group-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
  padding: 0.65rem 0.75rem;
  background: var(--paper-2);
  border-bottom: 1px solid var(--line);
}
.group-head h2 {
  font-size: 0.95rem;
  margin: 0;
  flex: 1 1 auto;
  font-weight: 700;
}
.group-meta { font-size: 0.75rem; color: var(--muted); font-family: var(--mono); }
.group-actions { display: flex; flex-wrap: wrap; gap: 0.35rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
th, td {
  border-bottom: 1px solid var(--line);
  padding: 0.45rem 0.55rem;
  text-align: left;
  vertical-align: top;
}
th {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  font-weight: 700;
  background: var(--panel);
}
.badge {
  font-size: 0.7rem;
  font-family: var(--mono);
  padding: 0.1rem 0.35rem;
  border: 1px solid var(--line-strong);
  background: var(--panel);
}
.ep { font-family: var(--mono); font-weight: 700; color: var(--blue); }
.row-id { color: var(--faint); font-size: 0.78rem; font-family: var(--mono); }
.muted { color: var(--muted); font-size: 0.88rem; }
.faint { color: var(--faint); font-size: 0.8rem; }
.empty-q {
  padding: 1.25rem 0.5rem;
  text-align: center;
  color: var(--muted);
  font-size: 0.9rem;
  border: 1px dashed var(--line-strong);
  background: var(--panel-2);
}

/* Recent Tadoku logs (local pushed) */
.fold-recent > summary { background: #2a3a2e; }
.fold-recent > summary .count-badge { background: var(--green); }
.fold-recent > summary .count-badge.zero { background: #3a453c; }
.recent-table-wrap { overflow-x: auto; }
.recent-table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
.recent-table th, .recent-table td {
  border-bottom: 1px solid var(--line);
  padding: 0.4rem 0.5rem;
  text-align: left;
  vertical-align: top;
}
.recent-table th {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  font-weight: 700;
  background: var(--panel);
}
.recent-table .sent-at { font-family: var(--mono); font-size: 0.8rem; color: var(--green); }
.recent-table .remote-id {
  font-family: var(--mono);
  font-size: 0.72rem;
  color: var(--faint);
  max-width: 7rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* Clickable recent rows → tadoku.app/logs/{remote_id} */
.recent-table tr.recent-row.is-link {
  cursor: pointer;
}
.recent-table tr.recent-row.is-link:hover td {
  background: var(--paper-2);
}
.recent-table tr.recent-row.is-link:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.recent-table a.tadoku-log-link {
  color: var(--ink);
  text-decoration: none;
  font-weight: 650;
}
.recent-table tr.recent-row.is-link:hover a.tadoku-log-link,
.recent-table a.tadoku-log-link:hover {
  color: var(--accent);
  text-decoration: underline;
}
.recent-table a.tadoku-log-link.remote-id {
  display: inline-block;
  color: var(--muted);
  font-weight: 600;
}

/* Secondary zones */
.rail {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 0.85rem;
  margin-top: 0.25rem;
}
@media (max-width: 780px) { .rail { grid-template-columns: 1fr; } }
.block {
  border: 1px solid var(--line-strong);
  background: var(--panel);
  padding: 0.85rem 0.95rem;
}
.block h2 {
  margin: 0 0 0.55rem;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  border-bottom: 1px solid var(--line);
  padding-bottom: 0.4rem;
}
.tool-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 0.45rem;
}
.tool-tile {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.55rem;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--ink);
  text-decoration: none;
  font-size: 0.82rem;
  font-weight: 650;
}
.tool-tile:hover {
  border-color: var(--ink);
  background: var(--paper-2);
  text-decoration: none;
}
.tool-tile .ico {
  width: 28px; height: 28px;
  display: grid; place-items: center;
  flex-shrink: 0;
  border: 1px solid var(--line);
  background: #fff;
}
.tool-tile .ico svg { width: 16px; height: 16px; }
.tool-tile.plex .ico { background: var(--plex); border-color: #b87e08; color: #111; }
.tool-tile.tautulli .ico { color: var(--tautulli); }
.tool-tile.sheets .ico { color: var(--sheets); }
.tool-tile.tadoku .ico { color: var(--tadoku); }
.tool-tile.youtube .ico { color: var(--youtube); }
.tool-tile .go { margin-left: auto; color: var(--faint); font-size: 0.75rem; font-weight: 500; }
.tips { margin: 0; padding-left: 1.1rem; color: var(--muted); font-size: 0.84rem; }
.tips li { margin: 0.3rem 0; }
.chip-row { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.chip {
  display: inline-block;
  padding: 0.28rem 0.55rem;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--ink-soft);
  font-size: 0.75rem;
  font-weight: 600;
  font-family: var(--mono);
  text-decoration: none;
}
a.chip:hover { border-color: var(--ink); color: var(--ink); text-decoration: none; }
.footer-note {
  margin-top: 1.5rem;
  padding-top: 0.65rem;
  border-top: 1px solid var(--line);
  font-size: 0.75rem;
  color: var(--faint);
  font-family: var(--mono);
}

/* Forms (catalog) */
.card-form {
  border: 1px solid var(--line-strong);
  background: var(--panel);
  padding: 0.9rem 1rem;
  margin: 0.85rem 0;
}
.card-h {
  margin: 0 0 0.35rem;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
}
label {
  display: block;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
  margin: 0.5rem 0 0.2rem;
}
input, select, textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 0.45rem 0.55rem;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  /* explicit colors — Windows native <select> dark-mode contrast bug */
  background-color: #fff;
  color: var(--ink);
  font-family: inherit;
  font-size: var(--control-fs);
  min-height: 2.25rem;
}
input::placeholder, textarea::placeholder {
  color: var(--faint);
  opacity: 1;
}
input:hover, select:hover, textarea:hover { border-color: var(--ink-soft); }
input:focus, select:focus, textarea:focus { outline: none; }
input:focus-visible, select:focus-visible, textarea:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 0;
  border-color: var(--accent);
}
.row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.65rem; }
@media (max-width: 700px) { .row { grid-template-columns: 1fr; } }

/* Quick log catalog typeahead */
.ql-suggest {
  position: absolute;
  z-index: 40;
  left: 0; right: 0;
  top: calc(100% - 0.1rem);
  max-height: 16rem;
  overflow: auto;
  border: 1px solid var(--line-strong);
  background: #fff;
  box-shadow: 0 6px 18px rgba(0,0,0,0.08);
}
.ql-opt {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.1rem;
  width: 100%;
  text-align: left;
  border: 0;
  border-bottom: 1px solid var(--line);
  background: transparent;
  padding: 0.45rem 0.6rem;
  cursor: pointer;
  font: inherit;
  color: inherit;
}
.ql-opt:last-child { border-bottom: 0; }
.ql-opt:hover, .ql-opt.is-active { background: var(--blue-bg, #eef5ff); }
.ql-opt-title { font-weight: 600; font-size: 0.9rem; }
.ql-opt-sub { font-size: 0.72rem; color: var(--muted); font-family: var(--mono); }

/* Catalog page */
.page-catalog .mast { margin-bottom: 0.65rem; }
.how-card {
  border: 1px solid var(--line-strong);
  border-left: 3px solid var(--blue);
  background: var(--blue-bg);
  padding: 0.75rem 0.95rem;
  margin: 0.5rem 0 0.85rem;
}
.how-card h2 {
  margin: 0 0 0.4rem;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--blue);
}
.how-steps {
  margin: 0;
  padding-left: 1.2rem;
  color: var(--ink-soft);
  font-size: 0.86rem;
}
.how-steps li { margin: 0.22rem 0; }
.field-hint {
  margin: 0.2rem 0 0;
  font-size: 0.75rem;
  color: var(--faint);
  line-height: 1.35;
}
.form-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem 1rem;
  margin-top: 0.85rem;
  padding-top: 0.7rem;
  border-top: 1px solid var(--line);
}
.check-label {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  margin: 0;
  font-size: 0.84rem;
  font-weight: 600;
  text-transform: none;
  letter-spacing: 0;
  color: var(--ink-soft);
  cursor: pointer;
}
.check-label input[type="checkbox"] {
  width: auto;
  margin: 0;
  accent-color: var(--accent);
}
.btn-row { display: flex; flex-wrap: wrap; gap: 0.45rem; margin-left: auto; }
.form-msg {
  min-height: 1.2em;
  margin-top: 0.55rem;
  font-size: 0.82rem;
  color: var(--muted);
  font-family: var(--mono);
}
.form-msg.ok {
  color: var(--green);
  background: var(--green-bg);
  border: 1px solid #b7d4ba;
  padding: 0.4rem 0.55rem;
}
.form-msg.err {
  color: var(--red);
  background: var(--red-bg);
  border: 1px solid #e0b8b4;
  padding: 0.4rem 0.55rem;
}
.catalog-list-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem 1.25rem;
  margin-bottom: 0.65rem;
}
.catalog-filter-wrap {
  min-width: min(100%, 220px);
  flex: 0 1 240px;
}
.catalog-filter-wrap label { margin-top: 0; }
.catalog-table-wrap { overflow-x: auto; margin: 0 -0.15rem; max-height: min(70vh, 720px); }
.catalog-table { min-width: 720px; }
.catalog-table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--panel);
  box-shadow: 0 1px 0 var(--line);
}
.catalog-table .col-key { max-width: 11rem; word-break: break-all; }
.catalog-table .col-title { min-width: 8rem; }
.catalog-table .col-aliases { min-width: 12rem; }
.catalog-table .col-tadoku { min-width: 6.5rem; }
.catalog-table .col-actions {
  white-space: nowrap;
  vertical-align: middle;
}
.catalog-table .col-actions button {
  margin: 0.1rem 0.15rem 0.1rem 0;
}
.catalog-table td input,
.catalog-table td select {
  font-size: 0.84rem;
  padding: 0.35rem 0.4rem;
}
/* Sortable data table headers (catalog, logs, queue) */
table.data-table th[data-sort],
table.catalog-table th[data-sort] {
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
table.data-table th[data-sort]:hover,
table.catalog-table th[data-sort]:hover { color: var(--ink); }
table.data-table th.sorted,
table.catalog-table th.sorted { color: var(--accent); }
table.data-table th .sort-ind,
table.catalog-table th .sort-ind {
  font-family: var(--mono);
  font-size: 0.65rem;
  opacity: 0.75;
  margin-left: 0.15rem;
}
/* Queue status/mode dropdowns */
.badge-select {
  font-family: var(--mono);
  font-size: 0.72rem;
  font-weight: 600;
  padding: 0.22rem 0.3rem;
  border: 1px solid var(--line-strong);
  border-radius: 2px;
  background: var(--panel);
  color: var(--ink);
  max-width: 7.5rem;
  cursor: pointer;
}
.badge-select:focus { outline: none; }
.badge-select:focus-visible { outline: 2px solid var(--accent); outline-offset: 0; }
.badge-select:disabled { opacity: 0.55; cursor: wait; }
.status-select.status-pending { background: var(--amber-bg); border-color: #d4b86a; }
.status-select.status-ready { background: var(--blue-bg); border-color: #8aadc8; }
.status-select.status-failed { background: var(--red-bg); border-color: #d4a09a; }
.status-select.status-pushed { background: var(--green-bg); border-color: #8fbf95; }
.queue-table .col-status,
.queue-table .col-mode { white-space: nowrap; }
.queue-table .col-actions-q { white-space: nowrap; }
.queue-table .col-actions-q button {
  margin: 0.08rem 0.08rem;
  padding: 0.28rem 0.45rem;
  font-size: 0.75rem;
}
.mono { font-family: var(--mono); }

/* ── IA: Dashboard CTA + Inbox sections ── */
.dash-cta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.55rem 0.75rem;
  margin: 0 0 var(--sp-4);
  padding: 0.75rem 0.9rem;
  border: 2px solid var(--ink);
  background: var(--amber-bg);
  box-shadow: 2px 2px 0 rgba(20, 17, 14, 0.08);
}
a.dash-cta-btn,
a.primary.dash-cta-btn {
  display: inline-flex;
  align-items: center;
  min-height: 2.25rem;
  padding: 0.45rem 1rem;
  background: var(--accent);
  color: var(--accent-ink) !important;
  border: 1px solid #8f3f14;
  font-weight: 700;
  font-size: 0.9rem;
  text-decoration: none !important;
  border-radius: 2px;
}
a.dash-cta-btn:hover {
  background: var(--accent-hover);
  color: var(--accent-ink) !important;
}
.dash-cta-hint {
  font-family: var(--mono);
  font-size: var(--text-xs);
  color: var(--ink-soft);
  flex: 1 1 12rem;
}
.inbox-lede {
  margin: -0.15rem 0 0.85rem;
  font-size: var(--text-sm);
  color: var(--ink-soft);
  line-height: 1.45;
}
.inbox-section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.35rem 1rem;
  margin-bottom: 0.55rem;
  padding-bottom: 0.45rem;
  border-bottom: 1px solid var(--line-strong);
}
.inbox-h {
  margin: 0;
  font-family: var(--display);
  font-size: var(--text-md);
  font-weight: 600;
}
.inbox-section-meta {
  margin: 0;
  font-family: var(--mono);
  font-size: var(--text-xs);
}
.row-review {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.3rem;
}
.row-config {
  position: relative;
}
.row-config > summary {
  list-style: none;
  cursor: pointer;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.28rem 0.45rem;
  border: 1px solid var(--line-strong);
  background: var(--panel-2);
  color: var(--muted);
  min-height: 2rem;
  display: inline-flex;
  align-items: center;
}
.row-config > summary::-webkit-details-marker { display: none; }
.row-config[open] > summary {
  color: var(--ink);
  border-color: var(--ink);
}
.row-config-body {
  position: absolute;
  right: 0;
  top: calc(100% + 2px);
  z-index: 8;
  min-width: 9.5rem;
  padding: 0.45rem;
  border: 2px solid var(--ink);
  background: var(--panel);
  box-shadow: 0 8px 20px rgba(20, 17, 14, 0.16);
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.row-config-body label {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
}
.page-reading .reading-msg {
  min-height: 1.1rem;
  font-family: var(--mono);
  font-size: 0.82rem;
  margin: 0.25rem 0 0.5rem;
}
.page-reading .reading-msg.ok { color: var(--green); }
.page-reading .reading-msg.err { color: var(--red); }
.hidden-by-tab { display: none !important; }

/* Quick-log FAB + dialog (all pages) */
.fab-log {
  position: fixed;
  right: 1rem;
  bottom: 1rem;
  z-index: 80;
  width: 3.25rem;
  height: 3.25rem;
  border-radius: 999px;
  border: 2px solid var(--ink);
  background: var(--accent);
  color: var(--accent-ink);
  font-size: 1.75rem;
  font-weight: 700;
  line-height: 1;
  box-shadow: 0 6px 18px rgba(20, 17, 14, 0.22);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  min-height: 0;
}
.fab-log:hover { background: var(--accent-hover); }
.nav-more-menu .nav-more-btn {
  display: block;
  width: 100%;
  text-align: left;
  border: 0;
  background: transparent;
  font: inherit;
  font-weight: 650;
  color: var(--ink);
  padding: 0.45rem 0.75rem;
  cursor: pointer;
  min-height: 2.25rem;
}
.nav-more-menu .nav-more-btn:hover { background: var(--paper-2); }
.fab-log-dialog {
  border: 2px solid var(--ink);
  border-radius: var(--radius);
  padding: 0;
  background: var(--panel);
  color: var(--ink);
  max-width: 22rem;
  width: calc(100vw - 2rem);
  box-shadow: var(--sheet-shadow);
}
.fab-log-dialog::backdrop {
  background: rgba(20, 17, 14, 0.45);
}
.fab-log-dialog .fab-log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid var(--line-strong);
  background: var(--panel-2);
  font-family: var(--display);
  font-weight: 600;
}
.fab-log-dialog .fab-log-body {
  padding: 0.85rem;
  display: grid;
  gap: 0.55rem;
}
.fab-log-dialog label {
  display: grid;
  gap: 0.2rem;
  font-size: var(--text-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
}
.fab-log-dialog input,
.fab-log-dialog select {
  font: inherit;
  font-size: var(--text-md);
  font-weight: 600;
  text-transform: none;
  letter-spacing: 0;
  color: var(--ink);
  border: 1px solid var(--line-strong);
  background: var(--panel);
  padding: 0.45rem 0.55rem;
  min-height: 2.5rem;
  width: 100%;
}
.fab-log-dialog .fab-log-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 0.25rem;
}
.fab-log-dialog .fab-log-actions button {
  flex: 1 1 auto;
  min-height: 2.75rem;
}
.global-toast {
  position: fixed;
  left: 50%;
  bottom: 5rem;
  transform: translateX(-50%);
  z-index: 90;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
  max-width: min(28rem, calc(100vw - 1.5rem));
  padding: 0.65rem 0.85rem;
  border: 2px solid var(--ink);
  background: var(--panel);
  box-shadow: var(--sheet-shadow);
  font-size: var(--text-sm);
  font-weight: 650;
}
.global-toast.hidden { display: none !important; }
.global-toast .toast-msg { flex: 1 1 10rem; }
.global-toast button {
  min-height: 2.4rem;
  padding: 0.35rem 0.7rem;
}

/* Mobile queue: card rows + fat approve/skip targets */
@media (max-width: 700px) {
  .queue-table thead { display: none; }
  .queue-table,
  .queue-table tbody {
    display: block;
    width: 100%;
  }
  .queue-table tr {
    display: block;
    margin: 0.55rem 0.5rem;
    padding: 0.7rem 0.75rem 0.8rem;
    border: 1px solid var(--line-strong);
    background: var(--panel);
  }
  .queue-table td {
    display: block;
    border: 0;
    padding: 0.12rem 0;
    width: 100%;
  }
  .queue-table td.row-id {
    font-size: 0.72rem;
    color: var(--faint);
  }
  .queue-table td.ep {
    font-size: 0.9rem;
  }
  .queue-table td.col-actions-q {
    margin-top: 0.55rem;
    padding-top: 0.45rem;
    border-top: 1px dashed var(--line);
  }
  .queue-table .col-actions-q button {
    margin: 0;
    padding: 0.55rem 0.65rem;
    font-size: 0.95rem;
  }
  .row-review {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
  }
  .row-review > button.approve,
  .row-review > button.skip {
    flex: 1 1 42%;
    min-height: 3rem;
  }
  .row-review .row-config {
    flex: 1 1 100%;
  }
  .row-review .row-config > summary {
    min-height: 2.5rem;
    display: flex;
    align-items: center;
    padding: 0.35rem 0.5rem;
    border: 1px solid var(--line-strong);
    background: var(--panel-2);
    font-weight: 700;
  }
  .group-actions {
    width: 100%;
    display: flex;
    gap: 0.45rem;
  }
  .group-actions button {
    flex: 1 1 40%;
    min-height: 3rem;
    font-size: 0.95rem;
  }
  .fold-toolbar .process-cluster,
  .fold-toolbar .btn-row {
    width: 100%;
  }
  .fold-toolbar button.process,
  .fold-toolbar button.primary {
    min-height: 3rem;
    width: 100%;
  }
  .fab-log {
    right: max(0.85rem, env(safe-area-inset-right, 0px));
    bottom: max(0.85rem, env(safe-area-inset-bottom, 0px));
    width: 3.5rem;
    height: 3.5rem;
  }
  /* iOS: ≥16px inputs avoid focus zoom; ≥44px primary hits */
  input, select, textarea {
    font-size: 16px;
    min-height: var(--hit);
  }
  button, .topbar-nav > a, .topbar-nav > .nav-more > summary, .tool-btn {
    min-height: var(--hit);
  }
}

/* Large lists — paint offscreen rows lazily (Web Interface Guidelines) */
.queue-table tbody tr,
.logs-table tbody tr,
.prog-row {
  content-visibility: auto;
  contain-intrinsic-size: auto 3.25rem;
}

/* Sticky chrome clears notch */
.topbar {
  padding-top: env(safe-area-inset-top, 0px);
}

/* Google font load is optional; system fallbacks already set */
"""


def nav_html(
    active: str = "",
    *,
    tautulli: str = "http://127.0.0.1:8181",
    tadoku: str = "https://tadoku.app",
    sheets: str = "",
    plex: str = "http://127.0.0.1:32400/web",
) -> str:
    def cls(name: str) -> str:
        return ' class="active"' if active == name else ""

    # Job-shaped nav: Inbox · Logs · Race · More (Progress at /progress, hidden from topbar)
    more_names = {"reading", "catalog", "home"}
    more_cls = ' class="nav-more active"' if active in more_names else ' class="nav-more"'

    sheets_btn = ""
    if sheets:
        sheets_btn = f"""
    <a class="tool-btn sheets" href="{sheets}" target="_blank" rel="noopener" title="Google Sheets">
      <span class="ico">{icon("sheets")}</span><span class="tool-label">Sheets</span>
    </a>"""

    # Brand lands on Inbox (daily ops); dashboard remains at /
    brand_cls = ' class="topbar-brand active"' if active in ("queue", "inbox") else ' class="topbar-brand"'

    def current(name: str) -> str:
        return ' aria-current="page"' if active == name else ""

    queue_active = active in ("queue", "inbox")
    queue_cls = ' class="active"' if queue_active else ""
    queue_cur = ' aria-current="page"' if queue_active else ""

    return f"""
<a class="skip-link" href="#main">Skip to content</a>
<header class="topbar">
  <a{brand_cls} href="/queue" title="Lucid Immersion Tracker — Inbox">
    <span class="mark" aria-hidden="true">
      <img src="/static/brand/icon-64.png" width="34" height="34" alt="" decoding="async"/>
    </span>
    <span class="brand-text">
      <strong>Lucid Immersion</strong>
      <span>Tracker</span>
    </span>
  </a>
  <nav class="topbar-nav" aria-label="App">
    <a href="/queue"{queue_cls}{queue_cur}>Inbox</a>
    <a href="/logs"{cls("logs")}{current("logs")}>Logs</a>
    <a href="/race"{cls("race")}{current("race")}>Race</a>
    <details{more_cls}>
      <summary>More</summary>
      <div class="nav-more-menu" role="menu">
        <a href="/"{cls("home")} role="menuitem">Dashboard</a>
        <a href="/reading"{cls("reading")} role="menuitem">Reading</a>
        <a href="/catalog"{cls("catalog")} role="menuitem">Catalog</a>
        <a href="/api/backup" role="menuitem" download>Backup DB</a>
        <a href="/docs" target="_blank" rel="noopener" role="menuitem">API docs ↗</a>
      </div>
    </details>
  </nav>
  <nav class="topbar-tools" aria-label="External tools">
    <a class="tool-btn plex" href="{plex}" target="_blank" rel="noopener" title="Plex Web">
      <span class="ico">{icon("plex")}</span><span class="tool-label">Plex</span>
    </a>
    <a class="tool-btn tautulli" href="{tautulli}" target="_blank" rel="noopener" title="Tautulli">
      <span class="ico">{icon("tautulli")}</span><span class="tool-label">Tautulli</span>
    </a>
    <a class="tool-btn tadoku" href="{tadoku}" target="_blank" rel="noopener" title="Tadoku">
      <span class="ico">{icon("tadoku")}</span><span class="tool-label">Tadoku</span>
    </a>
    {sheets_btn}
    <span class="health-chip ok" id="shell-health" role="status" aria-live="polite" title="Server health">
      <span class="status-dot" id="shell-health-dot"></span>
      <span id="shell-health-text">…</span>
    </span>
  </nav>
</header>
<button type="button" class="fab-log" id="fab-log" title="Quick log" aria-label="Quick log">+</button>
<dialog class="fab-log-dialog" id="fab-log-dialog" aria-label="Quick log">
  <div class="fab-log-head">
    <span>Quick log</span>
    <button type="button" class="secondary" id="fab-ql-close" aria-label="Close">×</button>
  </div>
  <div class="fab-log-body">
    <label>Title
      <input id="fab-ql-title" type="text" autocomplete="off" placeholder="Work title"/>
    </label>
    <label>Type
      <select id="fab-ql-type">
        <option value="anime">anime</option>
        <option value="show">show</option>
        <option value="book">book</option>
        <option value="manga">manga</option>
        <option value="visual_novel">visual_novel</option>
        <option value="youtube">youtube</option>
        <option value="podcast">podcast</option>
        <option value="game">game</option>
        <option value="study">study</option>
      </select>
    </label>
    <label>Amount
      <input id="fab-ql-amount" type="number" step="any" min="0" placeholder="24"/>
    </label>
    <label>Unit
      <select id="fab-ql-unit">
        <option value="minutes">minutes</option>
        <option value="characters">characters</option>
        <option value="pages">pages</option>
        <option value="comic_pages">comic_pages</option>
        <option value="sentences">sentences</option>
      </select>
    </label>
    <div class="fab-log-actions">
      <button type="button" class="primary" id="fab-ql-submit">Log &amp; submit</button>
      <button type="button" class="secondary" id="fab-ql-queue">Queue only</button>
    </div>
  </div>
</dialog>
<div class="global-toast hidden" id="global-toast" role="status" aria-live="polite">
  <span class="toast-msg"></span>
  <button type="button" class="skip toast-undo">Undo</button>
  <button type="button" class="secondary toast-dismiss" aria-label="Dismiss">×</button>
</div>
<script>
(function(){{
  /* Shell health chip (error-only) */
  const chip = document.getElementById('shell-health');
  const dot = document.getElementById('shell-health-dot');
  const text = document.getElementById('shell-health-text');
  if (chip && dot && text) {{
    async function ping() {{
      try {{
        const r = await fetch('/api/health', {{ cache: 'no-store' }});
        if (r.ok) {{
          chip.className = 'health-chip ok';
          chip.setAttribute('aria-hidden', 'true');
          text.textContent = 'online';
        }} else {{
          chip.className = 'health-chip warn';
          chip.removeAttribute('aria-hidden');
          text.textContent = 'degraded';
        }}
      }} catch (e) {{
        chip.className = 'health-chip bad';
        chip.removeAttribute('aria-hidden');
        text.textContent = 'offline';
      }}
    }}
    ping();
    setInterval(ping, 60000);
  }}
  /* More menu: close on outside click / Escape */
  document.querySelectorAll('details.nav-more').forEach((d) => {{
    document.addEventListener('click', (ev) => {{
      if (!d.open) return;
      if (!d.contains(ev.target)) d.open = false;
    }});
    d.addEventListener('keydown', (ev) => {{
      if (ev.key === 'Escape') {{
        d.open = false;
        const s = d.querySelector('summary');
        if (s) s.focus();
      }}
    }});
  }});

  /* Global toast + undo */
  let _toastTimer = null;
  window.showAppToast = function(msg, opts) {{
    opts = opts || {{}};
    const el = document.getElementById('global-toast');
    if (!el) return;
    const text = el.querySelector('.toast-msg');
    const undoBtn = el.querySelector('.toast-undo');
    if (text) text.textContent = msg || '';
    el.dataset.logId = opts.logId != null ? String(opts.logId) : '';
    if (undoBtn) undoBtn.hidden = !opts.logId;
    el.classList.remove('hidden');
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => el.classList.add('hidden'), opts.ms || 12000);
  }};
  window.undoLogById = async function(id) {{
    if (!id) return;
    try {{
      const r = await fetch('/api/logs/' + id, {{ method: 'DELETE' }});
      if (!r.ok) {{
        window.showAppToast('Undo failed', {{ ms: 4000 }});
        return;
      }}
      window.showAppToast('Undid #' + id, {{ ms: 4000 }});
      if (typeof loadQueue === 'function') loadQueue();
      if (typeof loadRecentLogs === 'function') loadRecentLogs();
      if (typeof refreshMetrics === 'function') refreshMetrics();
      if (typeof loadLogs === 'function') loadLogs();
    }} catch (e) {{
      window.showAppToast('Undo failed (network)', {{ ms: 4000 }});
    }}
  }};
  window.undoLastLog = async function() {{
    try {{
      const r = await fetch('/api/logs/undo-last', {{ method: 'POST' }});
      let j = null; try {{ j = await r.json(); }} catch (e) {{}}
      if (!r.ok) {{
        window.showAppToast((j && j.detail) ? String(j.detail) : 'Nothing to undo', {{ ms: 4000 }});
        return;
      }}
      const d = j.deleted || {{}};
      window.showAppToast('Undid #' + (d.id || '') + (d.title ? (' · ' + d.title) : ''), {{ ms: 5000 }});
      if (typeof loadQueue === 'function') loadQueue();
      if (typeof loadRecentLogs === 'function') loadRecentLogs();
      if (typeof refreshMetrics === 'function') refreshMetrics();
      if (typeof loadLogs === 'function') loadLogs();
    }} catch (e) {{
      window.showAppToast('Undo failed (network)', {{ ms: 4000 }});
    }}
  }};
  const toast = document.getElementById('global-toast');
  if (toast) {{
    const undoBtn = toast.querySelector('.toast-undo');
    const dismiss = toast.querySelector('.toast-dismiss');
    if (undoBtn) undoBtn.addEventListener('click', () => {{
      const id = toast.dataset.logId;
      toast.classList.add('hidden');
      if (id) window.undoLogById(id);
    }});
    if (dismiss) dismiss.addEventListener('click', () => toast.classList.add('hidden'));
  }}
  /* Quick log FAB */
  const fab = document.getElementById('fab-log');
  const dlg = document.getElementById('fab-log-dialog');
  if (fab && dlg) {{
    const titleEl = document.getElementById('fab-ql-title');
    const typeEl = document.getElementById('fab-ql-type');
    const amountEl = document.getElementById('fab-ql-amount');
    const unitEl = document.getElementById('fab-ql-unit');
    const UNIT_BY_TYPE = {{
      book: 'characters', manga: 'characters', visual_novel: 'characters',
      anime: 'minutes', show: 'minutes', movie: 'minutes', youtube: 'minutes',
      podcast: 'minutes', game: 'minutes', study: 'minutes', audiobook: 'minutes_high_density'
    }};
    function openFab() {{
      /* Prefer full quick-log fold on inbox/home when present */
      const fold = document.getElementById('quick-log-fold');
      if (fold) {{
        fold.open = true;
        fold.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
        const t = document.getElementById('ql-title');
        if (t) setTimeout(() => t.focus(), 200);
        return;
      }}
      if (typeof dlg.showModal === 'function') dlg.showModal();
      else dlg.setAttribute('open', '');
      if (titleEl) setTimeout(() => titleEl.focus(), 50);
    }}
    fab.addEventListener('click', openFab);
    if (typeEl && unitEl) {{
      typeEl.addEventListener('change', () => {{
        const u = UNIT_BY_TYPE[typeEl.value];
        if (u) unitEl.value = u;
      }});
    }}
    const closeBtn = document.getElementById('fab-ql-close');
    if (closeBtn) closeBtn.addEventListener('click', () => dlg.close());
    async function fabSubmit(andApprove) {{
      const title = (titleEl && titleEl.value || '').trim();
      const amount = Number(amountEl && amountEl.value);
      if (!title) {{ window.showAppToast('Title required', {{ ms: 3000 }}); return; }}
      if (!(amount > 0)) {{ window.showAppToast('Amount must be > 0', {{ ms: 3000 }}); return; }}
      const body = {{
        content_type: (typeEl && typeEl.value) || 'anime',
        title,
        amount,
        unit: (unitEl && unitEl.value) || 'minutes',
        source: 'manual',
        tadoku_mode: andApprove ? 'auto' : 'pending',
      }};
      try {{
        const r = await fetch('/api/logs', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(body),
        }});
        let j = null; try {{ j = await r.json(); }} catch (e) {{}}
        if (!r.ok) {{
          window.showAppToast((j && j.detail) ? JSON.stringify(j.detail) : 'Log failed', {{ ms: 5000 }});
          return;
        }}
        if (andApprove && j.id) {{
          await fetch('/api/logs/' + j.id + '/approve', {{ method: 'POST' }});
        }}
        if (amountEl) amountEl.value = '';
        dlg.close();
        window.showAppToast((andApprove ? 'Submitted #' : 'Queued #') + j.id + ' · ' + title, {{ logId: j.id }});
        if (typeof loadQueue === 'function') loadQueue();
        if (typeof loadRecentLogs === 'function') loadRecentLogs();
        if (typeof refreshMetrics === 'function') refreshMetrics();
      }} catch (e) {{
        window.showAppToast('Log failed (network)', {{ ms: 4000 }});
      }}
    }}
    const qOnly = document.getElementById('fab-ql-queue');
    const qSub = document.getElementById('fab-ql-submit');
    if (qOnly) qOnly.addEventListener('click', () => fabSubmit(false));
    if (qSub) qSub.addEventListener('click', () => fabSubmit(true));
  }}
}})();
</script>
"""
