"""Race / momentum page — CSS + client JS (inline, no build step)."""

MOMENTUM_CSS = """

/* ═══ Race scoreboard redesign (visible) ═══ */
.race-stamp {
  border: 3px solid var(--ink);
  background: var(--panel);
  margin: 0 0 0.85rem;
  box-shadow: 4px 4px 0 rgba(20,17,14,0.12);
  position: relative;
}
.race-stamp::before {
  content: "";
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 6px;
  background: var(--accent);
}
.race-stamp-top {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 0.75rem 1.25rem;
  padding: 0.85rem 1rem 0.65rem 1.15rem;
  align-items: flex-start;
}
.race-stamp-kicker {
  margin: 0 0 0.2rem;
  font-family: var(--mono);
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--accent);
}
.race-stamp h1 {
  font-family: var(--display);
  font-weight: 650;
  font-size: clamp(1.4rem, 2.6vw, 1.85rem);
  margin: 0 0 0.25rem;
  letter-spacing: -0.02em;
  line-height: 1.15;
}
.race-stamp .race-sub {
  margin: 0;
  font-size: 0.85rem;
  color: var(--muted);
  font-family: var(--mono);
}
.race-stamp-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 1.15rem;
  padding: 0.55rem 1rem 0.65rem 1.15rem;
  border-top: 1px solid var(--line-strong);
  background: var(--panel-2);
  font-family: var(--mono);
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--ink-soft);
}
.race-stamp-meta b { color: var(--ink); font-size: 1rem; }
.race-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  align-items: center;
}
.race-actions .btn-refresh,
.race-actions button.primary {
  appearance: none;
  border: 1px solid #8f3f14;
  background: var(--accent);
  color: var(--accent-ink);
  font-family: var(--font);
  font-weight: 700;
  font-size: 0.88rem;
  padding: 0.5rem 1.05rem;
  min-height: 2.4rem;
  cursor: pointer;
  border-radius: 2px;
  box-shadow: 2px 2px 0 rgba(20,17,14,0.12);
}
.race-actions .btn-refresh:hover { background: var(--accent-hover); }
.race-actions .btn-refresh:disabled { opacity: 0.55; cursor: wait; }
.race-actions .cache-meta {
  font-family: var(--mono);
  font-size: 0.72rem;
  color: var(--muted);
}
.race-actions a.quiet {
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--blue);
}
.race-scoreboard {
  border: 3px solid var(--ink);
  background: var(--panel);
  margin-bottom: 0.85rem;
  box-shadow: 0 10px 28px rgba(20,17,14,0.12);
}
.race-scoreboard-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.4rem 1rem;
  padding: 0.6rem 0.95rem;
  background: var(--ink);
  color: var(--panel);
}
.race-scoreboard-head h2 {
  margin: 0;
  font-family: var(--display);
  font-size: 1rem;
  font-weight: 600;
}
.race-scoreboard-head .hint {
  font-family: var(--mono);
  font-size: 0.7rem;
  opacity: 0.75;
  font-weight: 600;
}
.race-scoreboard-body { padding: 0.15rem 0; }
.sb-row {
  display: grid;
  grid-template-columns: 2.6rem minmax(0, 1fr) auto;
  gap: 0.55rem 0.85rem;
  align-items: center;
  padding: 0.6rem 0.95rem;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
}
.sb-row:last-child { border-bottom: 0; }
.sb-row:hover, .sb-row.hl { background: var(--paper-2); }
.sb-row.is-me {
  background: linear-gradient(90deg, rgba(184,78,31,0.14), transparent 60%);
  box-shadow: inset 5px 0 0 var(--accent);
}
.sb-rank {
  font-family: var(--mono);
  font-weight: 700;
  font-size: 1.2rem;
  letter-spacing: -0.03em;
}
.sb-row.is-me .sb-rank { color: var(--accent); }
.sb-main { min-width: 0; }
.sb-name {
  font-weight: 700;
  font-size: 0.98rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sb-you {
  font-family: var(--mono);
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  background: var(--accent);
  color: var(--accent-ink);
  padding: 0.12rem 0.32rem;
  border: 1px solid var(--ink);
  flex-shrink: 0;
}
.sb-bar-wrap {
  height: 9px;
  background: var(--paper-2);
  border: 1px solid var(--line-strong);
  margin-top: 0.35rem;
  overflow: hidden;
}
.sb-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), #d97706);
  min-width: 3px;
}
.sb-meta {
  font-family: var(--mono);
  font-size: 0.7rem;
  color: var(--muted);
  margin-top: 0.15rem;
}
.sb-side { text-align: right; font-family: var(--mono); }
.sb-score {
  font-weight: 700;
  font-size: 1.2rem;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}
.sb-pace {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--muted);
  margin-top: 0.1rem;
}
.sb-pill {
  display: inline-block;
  font-size: 0.62rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.1rem 0.32rem;
  border: 1px solid var(--line-strong);
  margin-top: 0.2rem;
}
.sb-pill.heating { background: var(--green-bg); color: var(--green); border-color: var(--green); }
.sb-pill.catching { background: var(--blue-bg); color: var(--blue); border-color: var(--blue); }
.sb-pill.cooling, .sb-pill.idle { background: var(--red-bg); color: var(--red); border-color: var(--red); }
.sb-pill.steady { background: var(--panel-2); color: var(--muted); }
.race-you-line {
  padding: 0.6rem 0.95rem;
  border-top: 2px solid var(--ink);
  background: var(--amber-bg);
  font-family: var(--mono);
  font-size: 0.84rem;
  font-weight: 600;
}
.race-you-line[hidden] { display: none !important; }
.band-grid-compact {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0.65rem;
  margin-bottom: 0.85rem;
}
@media (max-width: 960px) {
  .band-grid-compact { grid-template-columns: 1fr; }
}
.band-grid-compact .band {
  border: 2.5px solid var(--ink);
  min-height: 0;
}
.band-grid-compact .band-head { padding: 0.45rem 0.65rem; }
.band-grid-compact .band-head h2 { font-size: 0.75rem; letter-spacing: 0.06em; }
.band-grid-compact .person-row { padding: 0.28rem 0.25rem; gap: 0.4rem; }
.band-grid-compact .person-row .av { width: 28px; height: 28px; border-radius: 4px; }
.band-grid-compact .person-row .name { font-size: 0.82rem; }
.band-grid-compact .person-row .meta { font-size: 0.65rem; }
.band-grid-compact .person-row .metric { font-size: 0.85rem; }
.person-row.is-me {
  box-shadow: inset 3px 0 0 var(--accent);
  background: rgba(184,78,31,0.08);
}
.race-skeleton {
  border: 2.5px solid var(--ink);
  background: var(--panel);
  padding: 0.85rem 1rem 1rem;
  margin-bottom: 0.85rem;
}
.race-skeleton .sk-row {
  height: 2.5rem;
  margin-bottom: 0.45rem;
  background: linear-gradient(90deg, var(--paper-2) 25%, var(--panel-2) 50%, var(--paper-2) 75%);
  background-size: 200% 100%;
  animation: sk-shimmer 1.2s ease infinite;
  border: 1px solid var(--line);
}
.race-skeleton .sk-label {
  margin: 0.65rem 0 0;
  text-align: center;
  font-family: var(--mono);
  font-size: 0.8rem;
  color: var(--muted);
  font-weight: 600;
}
@keyframes sk-shimmer {
  0% { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .race-skeleton .sk-row { animation: none; }
}
.race-panel-fold {
  border: 2.5px solid var(--ink);
  background: var(--panel);
  margin-bottom: 0.85rem;
}
.race-panel-fold > summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem 0.75rem;
  padding: 0.65rem 0.9rem;
  font-family: var(--display);
  font-weight: 600;
  font-size: 0.95rem;
  background: var(--panel-2);
  user-select: none;
}
.race-panel-fold > summary::-webkit-details-marker { display: none; }
.race-panel-fold[open] > summary { border-bottom: 1px solid var(--line); }
.race-panel-fold > summary .hint {
  margin-left: auto;
  font-family: var(--mono);
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--muted);
}
.chart-wrap {
  height: min(36vh, 320px) !important;
  min-height: 240px !important;
}
.race-error {
  border: 2px solid var(--red);
  background: var(--red-bg);
  color: var(--red);
  padding: 0.85rem 1rem;
  margin-bottom: 1rem;
  font-weight: 600;
}
.race-loading .spin {
  display: inline-block;
  width: 1rem; height: 1rem;
  border: 2px solid var(--line-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: race-spin 0.7s linear infinite;
  vertical-align: -0.15rem;
  margin-right: 0.4rem;
}
@keyframes race-spin { to { transform: rotate(360deg); } }


/* ── Race / momentum page ── */
.page-race { max-width: 1280px; }
.race-page-mast { margin-bottom: 0.75rem; }
.race-lede {
  margin: -0.15rem 0 0.85rem;
  font-size: 0.88rem;
  color: var(--ink-soft);
  line-height: 1.45;
}
.race-panel-fold {
  border: 2px solid var(--ink);
  background: var(--panel);
  margin-bottom: 1rem;
}
.race-panel-fold > summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem 0.75rem;
  padding: 0.6rem 0.85rem;
  font-family: var(--display);
  font-weight: 600;
  font-size: 0.95rem;
  background: var(--panel-2);
  border-bottom: 1px solid transparent;
  user-select: none;
}
.race-panel-fold > summary::-webkit-details-marker { display: none; }
.race-panel-fold[open] > summary { border-bottom-color: var(--line); }
.race-panel-fold > summary .hint {
  margin-left: auto;
  font-family: var(--mono);
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--muted);
}
.race-panel-fold .fold-inner { padding: 0; }
table.race-table .col-adv { }
@media (max-width: 900px) {
  /* Score then, 30d, Catch-up, spark — keep Now / Runner / Score / 7d / Accel / Band */
  table.race-table th:nth-child(6),
  table.race-table td:nth-child(6),
  table.race-table th:nth-child(8),
  table.race-table td:nth-child(8),
  table.race-table th:nth-child(12),
  table.race-table td:nth-child(12),
  table.race-table th:nth-child(13),
  table.race-table td:nth-child(13) { display: none; }
}
.person-row { cursor: pointer; }
.person-row .metric .unit { color: var(--muted); }
.person-row.idle .metric { color: var(--amber) !important; }


.race-hero {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 1rem;
  margin-bottom: 1rem;
}
@media (max-width: 900px) {
  .race-hero { grid-template-columns: 1fr; }
}

.race-title-block {
  border: 2px solid var(--ink);
  background: var(--panel);
  padding: 1rem 1.15rem 1.1rem;
  position: relative;
  overflow: hidden;
}
.race-title-block::before {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 5px;
  background: linear-gradient(180deg, var(--accent), var(--tadoku));
}
.race-kicker { display: none; } /* job lives in mast / sub */
.race-title-block h1 {
  font-family: var(--display);
  font-weight: 600;
  font-size: clamp(1.45rem, 2.6vw, 1.9rem);
  margin: 0 0 0.35rem;
  letter-spacing: -0.02em;
  line-height: 1.2;
}
.race-sub {
  color: var(--muted);
  font-size: 0.88rem;
  margin: 0;
  max-width: 42em;
}
.race-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-top: 0.85rem;
}
.race-actions .btn-refresh,
.race-actions button.primary {
  appearance: none;
  border: 1px solid #8f3f14;
  background: var(--accent);
  color: var(--accent-ink);
  font-family: var(--font);
  font-weight: 700;
  font-size: 0.82rem;
  padding: 0.45rem 0.85rem;
  min-height: 2rem;
  cursor: pointer;
  border-radius: var(--radius);
}
.race-actions .btn-refresh:hover,
.race-actions button.primary:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
.race-actions .btn-refresh:disabled,
.race-actions button.primary:disabled { opacity: 0.55; cursor: wait; }
.race-actions .cache-meta {
  font-family: var(--mono);
  font-size: 0.75rem;
  color: var(--muted);
}
.race-actions a.quiet {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--blue);
}

.race-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border: 2px solid var(--ink);
  background: var(--panel);
}
.race-stat {
  padding: 0.85rem 1rem;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.race-stat:nth-child(2n) { border-right: 0; }
.race-stat:nth-last-child(-n+2) { border-bottom: 0; }
.race-stat .k {
  font-size: 0.66rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
}
.race-stat .v {
  font-family: var(--mono);
  font-size: 1.55rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  margin-top: 0.15rem;
  font-variant-numeric: tabular-nums;
}
.race-stat .s { font-size: 0.72rem; color: var(--faint); margin-top: 0.1rem; }

/* Momentum columns */
.band-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0.75rem;
  margin-bottom: 1rem;
}
@media (max-width: 960px) {
  .band-grid { grid-template-columns: 1fr; }
}
.band {
  border: 2px solid var(--ink);
  background: var(--panel);
  min-height: 8rem;
}
.band-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid var(--line);
  background: var(--panel-2);
}
.band-head h2 {
  margin: 0;
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.band.heating .band-head { background: var(--green-bg); }
.band.cooling .band-head { background: var(--red-bg); }
.band.catching .band-head { background: var(--blue-bg); }
.band-head .hint {
  font-size: 0.7rem;
  color: var(--muted);
  font-weight: 600;
}
.band-body { padding: 0.4rem 0.5rem 0.55rem; }
.band-empty {
  padding: 1rem 0.75rem;
  color: var(--faint);
  font-size: 0.85rem;
  text-align: center;
}

.person-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.55rem;
  align-items: center;
  padding: 0.4rem 0.35rem;
  border-radius: 3px;
  cursor: pointer;
  transition: background 0.12s ease;
}
.person-row:hover, .person-row.hl {
  background: var(--paper-2);
}
.person-row .av {
  width: 36px; height: 36px;
  border-radius: 8px;
  border: 1px solid var(--line-strong);
  object-fit: cover;
  background: var(--paper-2);
}
.person-row .who {
  min-width: 0;
}
.person-row .name {
  font-weight: 700;
  font-size: 0.88rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.person-row .meta {
  font-size: 0.72rem;
  color: var(--muted);
  font-family: var(--mono);
}
.person-row .metric {
  text-align: right;
  font-family: var(--mono);
  font-weight: 700;
  font-size: 0.95rem;
  font-variant-numeric: tabular-nums;
}
.person-row .metric.pos { color: var(--green); }
.person-row .metric.neg { color: var(--red); }
.person-row .metric .unit {
  display: block;
  font-size: 0.65rem;
  font-weight: 600;
  color: var(--faint);
}

/* Chart panel */
.chart-panel {
  border: 2px solid var(--ink);
  background: var(--panel);
  margin-bottom: 1rem;
}
.chart-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.55rem 1rem;
  padding: 0.6rem 0.85rem;
  border-bottom: 1px solid var(--line);
  background: var(--panel-2);
}
.chart-toolbar h2 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  font-family: var(--display);
}
.chart-toolbar .spacer { flex: 1; }
.chart-toolbar label {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--ink-soft);
  cursor: pointer;
  user-select: none;
}
.chart-toolbar select {
  font-family: var(--font);
  font-size: 0.8rem;
  font-weight: 600;
  border: 1px solid var(--line-strong);
  background: var(--panel);
  padding: 0.28rem 0.45rem;
  border-radius: 3px;
  color: var(--ink);
}
.chart-wrap {
  position: relative;
  height: min(52vh, 460px);
  min-height: 300px;
  padding: 0.5rem 0.75rem 0.75rem;
}
.chart-wrap canvas {
  width: 100% !important;
  height: 100% !important;
  display: block;
  cursor: crosshair;
}
.chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.55rem;
  padding: 0 0.85rem 0.75rem;
  max-height: 5.5rem;
  overflow-y: auto;
}
.legend-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.2rem 0.45rem 0.2rem 0.25rem;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--panel-2);
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  color: var(--ink-soft);
  max-width: 11rem;
}
.legend-chip img {
  width: 18px; height: 18px;
  border-radius: 50%;
  border: 1px solid var(--line);
}
.legend-chip .dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.legend-chip.on {
  border-color: var(--ink);
  color: var(--ink);
  background: var(--paper);
  box-shadow: inset 0 0 0 1px var(--ink);
}
.legend-chip.off { opacity: 0.4; }
.legend-chip .nm {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chart-tip {
  position: absolute;
  pointer-events: none;
  z-index: 5;
  background: var(--ink);
  color: var(--accent-ink);
  font-size: 0.75rem;
  padding: 0.45rem 0.6rem;
  border-radius: 4px;
  box-shadow: 0 6px 20px rgba(28,25,20,0.25);
  max-width: 220px;
  display: none;
  line-height: 1.35;
}
.chart-tip strong { display: block; margin-bottom: 0.15rem; }
.chart-tip .row { font-family: var(--mono); font-size: 0.72rem; opacity: 0.92; }

/* Standings table */
.table-panel {
  border: 2px solid var(--ink);
  background: var(--panel);
  margin-bottom: 1.25rem;
  overflow: hidden;
}
.table-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 1rem;
  padding: 0.6rem 0.85rem;
  border-bottom: 1px solid var(--line);
  background: var(--panel-2);
}
.table-toolbar h2 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  font-family: var(--display);
}
.table-toolbar input[type="search"] {
  font-family: var(--font);
  font-size: 0.82rem;
  border: 1px solid var(--line-strong);
  background: var(--panel);
  padding: 0.35rem 0.55rem;
  border-radius: 3px;
  min-width: 10rem;
  color: var(--ink);
}
.table-scroll { overflow-x: auto; }
table.race-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.86rem;
}
table.race-table th {
  text-align: left;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  padding: 0.55rem 0.65rem;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
  background: var(--panel);
  position: sticky;
  top: 0;
  cursor: pointer;
  user-select: none;
}
table.race-table th[title] {
  cursor: help;
  border-bottom: 1px dotted var(--muted);
  border-bottom-style: dotted;
}
table.race-table th[title]:hover {
  color: var(--ink);
  border-bottom-color: var(--ink);
}
table.race-table th:hover { color: var(--ink); }
table.race-table th.sorted { color: var(--accent); }
table.race-table th .th-sub {
  display: block;
  font-size: 0.62rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: none;
  color: var(--faint);
  margin-top: 0.12rem;
  font-family: var(--mono);
}
table.race-table td {
  padding: 0.5rem 0.65rem;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
  font-variant-numeric: tabular-nums;
}
table.race-table tr:last-child td { border-bottom: 0; }
table.race-table tr {
  cursor: pointer;
  transition: background 0.1s ease;
}
table.race-table tr:hover, table.race-table tr.hl {
  background: var(--paper-2);
}
table.race-table tr.hl td:first-child {
  box-shadow: inset 3px 0 0 var(--accent);
}
.cell-user {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  min-width: 10rem;
}
.cell-user img {
  width: 32px; height: 32px;
  border-radius: 7px;
  border: 1px solid var(--line-strong);
  flex-shrink: 0;
}
.cell-user .nm { font-weight: 700; }
.cell-user .id {
  font-size: 0.68rem;
  color: var(--faint);
  font-family: var(--mono);
}
.mono { font-family: var(--mono); }
.pos { color: var(--green); font-weight: 700; }
.neg { color: var(--red); font-weight: 700; }
.muted-cell { color: var(--muted); }

.pill {
  display: inline-block;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 0.15rem 0.4rem;
  border-radius: 3px;
  border: 1px solid var(--line);
}
.pill.heating { background: var(--green-bg); color: var(--green); border-color: #b5d4b8; }
.pill.cooling { background: var(--red-bg); color: var(--red); border-color: #e0c0bc; }
.pill.steady { background: var(--paper-2); color: var(--muted); }
.pill.idle { background: var(--amber-bg); color: var(--amber); border-color: #e0d0a0; }

.spark {
  display: block;
  width: 88px;
  height: 28px;
}
.spark path {
  fill: none;
  stroke-width: 1.6;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.spark .fill {
  stroke: none;
  opacity: 0.15;
}

.race-foot {
  font-size: 0.78rem;
  color: var(--faint);
  margin: 0.5rem 0 0;
  line-height: 1.5;
}
.race-foot code { font-size: 0.85em; }

/* Projection panel */
.project-panel {
  border: 2px solid var(--ink);
  background: var(--panel);
  margin-bottom: 1rem;
  overflow: hidden;
}
.project-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.55rem 1rem;
  padding: 0.65rem 0.85rem;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(90deg, var(--blue-bg), var(--panel-2));
}
.project-toolbar h2 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  font-family: var(--display);
}
.project-toolbar label {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--ink-soft);
  user-select: none;
}
.project-toolbar select,
.project-toolbar input[type="number"] {
  font-family: var(--font);
  font-size: 0.8rem;
  font-weight: 600;
  border: 1px solid var(--line-strong);
  background: var(--panel);
  padding: 0.28rem 0.45rem;
  border-radius: 3px;
  color: var(--ink);
}
.project-toolbar input[type="number"] {
  width: 4.2rem;
  font-family: var(--mono);
}
.project-toolbar .proj-summary {
  font-family: var(--mono);
  font-size: 0.75rem;
  color: var(--muted);
  margin-left: auto;
}
.project-body {
  display: grid;
  grid-template-columns: 1fr 1.1fr;
  gap: 0;
}
@media (max-width: 900px) {
  .project-body { grid-template-columns: 1fr; }
}
.project-podium {
  padding: 0.55rem 0.65rem 0.7rem;
  border-right: 1px solid var(--line);
}
@media (max-width: 900px) {
  .project-podium { border-right: 0; border-bottom: 1px solid var(--line); }
}
.project-podium .podium-head {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin: 0 0 0.4rem;
}
.project-movers {
  padding: 0.55rem 0.65rem 0.7rem;
  max-height: 14rem;
  overflow-y: auto;
}
.delta-up { color: var(--green); font-weight: 700; }
.delta-down { color: var(--red); font-weight: 700; }
.delta-flat { color: var(--muted); }
.proj-rank {
  font-family: var(--mono);
  font-weight: 700;
}
table.race-table th.proj-col,
table.race-table td.proj-col {
  background: color-mix(in srgb, var(--blue-bg) 55%, transparent);
}
.chart-sep-line {
  /* drawn on canvas — class reserved */
}

.race-error {
  border: 2px solid var(--red);
  background: var(--red-bg);
  color: var(--red);
  padding: 0.85rem 1rem;
  margin-bottom: 1rem;
  font-weight: 600;
}
.race-loading {
  padding: 2.5rem 1rem;
  text-align: center;
  color: var(--muted);
  font-weight: 600;
  border: 1px dashed var(--line-strong);
  background: var(--panel-2);
  margin: 0.75rem 0;
}
.race-loading .spin {
  display: inline-block;
  width: 1.1rem; height: 1.1rem;
  border: 2px solid var(--line-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: race-spin 0.7s linear infinite;
  vertical-align: -0.2rem;
  margin-right: 0.45rem;
}
@keyframes race-spin { to { transform: rotate(360deg); } }
"""

MOMENTUM_JS = r"""
(function () {
  const state = {
    data: null,
    sortKey: 'rank',
    sortDir: 1,
    filter: '',
    chartMode: 'top5', // top12 | all | heating
    hidden: new Set(),
    hlUser: null,
    // Projection: "what place if current pace holds for N days"
    projectDays: 30,
    projectModel: 'velocity', // velocity | baseline | accel
    projectHorizon: '30', // preset key; 'custom' uses projectDays
    projected: null, // list from projectStandings()
  };

  const $ = (id) => document.getElementById(id);

  function fmt(n, d = 1) {
    if (n == null || Number.isNaN(n)) return '—';
    return Number(n).toLocaleString(undefined, { maximumFractionDigits: d });
  }
  function fmtAge(sec) {
    if (sec == null) return 'never';
    if (sec < 60) return sec + 's ago';
    if (sec < 3600) return Math.round(sec / 60) + 'm ago';
    if (sec < 86400) return Math.round(sec / 3600) + 'h ago';
    return Math.round(sec / 86400) + 'd ago';
  }
  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }
  function parseISODate(s) {
    if (!s) return null;
    const p = String(s).slice(0, 10).split('-').map(Number);
    if (p.length < 3 || p.some(n => Number.isNaN(n))) return null;
    return new Date(Date.UTC(p[0], p[1] - 1, p[2]));
  }
  function addDaysISO(iso, days) {
    const d = parseISODate(iso);
    if (!d) return iso;
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  }
  function daysBetween(aIso, bIso) {
    const a = parseISODate(aIso);
    const b = parseISODate(bIso);
    if (!a || !b) return 0;
    return Math.max(0, Math.round((b - a) / 86400000));
  }

  function dailyRateFor(u, model) {
    const v7 = Number(u.velocity_7d) || 0;
    const v30 = Number(u.velocity_30d) || 0;
    const acc = Number(u.acceleration) || 0;
    if (model === 'baseline') return Math.max(0, v30);
    if (model === 'accel') {
      const endPace = Math.max(0, v7 + acc);
      return Math.max(0, (v7 + endPace) / 2);
    }
    return Math.max(0, v7);
  }

  function resolveProjectDays() {
    const c = (state.data && state.data.contest) || {};
    const asOf = (state.data && state.data.summary && state.data.summary.as_of) || null;
    const end = c.end || null;
    const key = state.projectHorizon;
    if (key === 'end' && asOf && end) return daysBetween(asOf, end);
    if (key === 'custom') return Math.max(0, Number(state.projectDays) || 0);
    const n = parseInt(key, 10);
    return Number.isFinite(n) ? Math.max(0, n) : 30;
  }

  function projectStandings(users, days, model) {
    const list = (users || []).map(u => {
      const rate = dailyRateFor(u, model);
      const pscore = (Number(u.score) || 0) + rate * days;
      return Object.assign({}, u, {
        projected_score: Math.round(pscore * 100) / 100,
        projected_daily_rate: Math.round(rate * 100) / 100,
        project_days: days,
        project_model: model,
      });
    });
    list.sort((a, b) => {
      if (b.projected_score !== a.projected_score) return b.projected_score - a.projected_score;
      return (a.rank || 9999) - (b.rank || 9999);
    });
    list.forEach((row, i) => {
      row.projected_rank = i + 1;
      row.rank_delta = (row.rank || i + 1) - row.projected_rank;
    });
    return list;
  }

  function recomputeProjection() {
    if (!state.data) {
      state.projected = null;
      return;
    }
    const days = resolveProjectDays();
    state.projectDays = days;
    state.projected = projectStandings(state.data.users || [], days, state.projectModel);
  }

  function projectedById() {
    const map = new Map();
    (state.projected || []).forEach(u => map.set(u.user_id, u));
    return map;
  }

  function fmtDelta(d) {
    if (d == null || d === 0) return '<span class="delta-flat">—</span>';
    if (d > 0) return `<span class="delta-up">↑${d}</span>`;
    return `<span class="delta-down">↓${Math.abs(d)}</span>`;
  }

  function sparkSVG(values, color) {
    const w = 88, h = 28, pad = 2;
    const vals = values || [];
    if (!vals.length) return '';
    const max = Math.max(...vals, 0.01);
    const step = (w - pad * 2) / Math.max(vals.length - 1, 1);
    const pts = vals.map((v, i) => {
      const x = pad + i * step;
      const y = h - pad - (v / max) * (h - pad * 2);
      return [x, y];
    });
    const line = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
    const fill = line + ` L${pts[pts.length - 1][0].toFixed(1)},${h - pad} L${pts[0][0].toFixed(1)},${h - pad} Z`;
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true">
      <path class="fill" d="${fill}" fill="${esc(color)}"/>
      <path d="${line}" stroke="${esc(color)}"/>
    </svg>`;
  }


  function resolveMeUserId(users) {
    try {
      const forced = localStorage.getItem('race.meUserId');
      if (forced) return forced;
    } catch (e) {}
    const me = (window.RACE_ME && window.RACE_ME.username) || '';
    if (!me) return null;
    const m = me.toLowerCase().trim();
    for (const u of users || []) {
      const names = [u.display_name, u.username, u.user_id].filter(Boolean).map(x => String(x).toLowerCase());
      if (names.some(n => n === m || n.includes(m) || m.includes(n))) return u.user_id;
    }
    return null;
  }

  function renderScoreboard() {
    const host = $('race-scoreboard');
    if (!host || !state.data) return;
    const users = (state.data.users || []).slice().sort((a, b) => (a.rank || 999) - (b.rank || 999));
    const meId = resolveMeUserId(users);
    if (meId && !state._pinnedHl) {
      state.hlUser = meId;
      state._pinnedHl = true;
    }
    let rows = users.filter(u => (u.rank || 99) <= 5).slice(0, 5);
    if (meId) {
      const me = users.find(u => u.user_id === meId);
      if (me && !rows.some(u => u.user_id === meId)) rows = rows.concat([me]);
    }
    const leaderScore = Math.max(1, Number((users[0] && (users[0].score ?? users[0].total_score)) || 1));
    host.innerHTML = rows.map(u => {
      const score = Number(u.score ?? u.total_score) || 0;
      const pct = Math.max(3, Math.min(100, 100 * score / leaderScore));
      const isMe = meId && u.user_id === meId;
      const mom = (u.momentum || 'steady').toLowerCase();
      const pace = u.velocity_7d != null ? fmt(u.velocity_7d, 1) + '/d' : '—';
      const uid = esc(u.user_id);
      return `<div class="sb-row${isMe ? ' is-me' : ''}${state.hlUser === u.user_id ? ' hl' : ''}" data-uid="${uid}" data-rank="${u.rank || ''}" onclick="Race.hl('${uid}')">
        <div class="sb-rank">#${u.rank || '—'}</div>
        <div class="sb-main">
          <div class="sb-name">${esc(u.display_name || u.username || '—')}${isMe ? '<span class="sb-you">YOU</span>' : ''}</div>
          <div class="sb-bar-wrap"><div class="sb-bar" style="width:${pct}%"></div></div>
          <div class="sb-meta">${esc(mom)}</div>
        </div>
        <div class="sb-side">
          <div class="sb-score">${fmt(score, 0)}</div>
          <div class="sb-pace">${pace}</div>
          <span class="sb-pill ${esc(mom)}">${esc(mom)}</span>
        </div>
      </div>`;
    }).join('') || '<div class="band-empty" style="padding:1rem;text-align:center">No runners yet</div>';

    const youLine = $('race-you-line');
    if (youLine && meId) {
      const me = users.find(u => u.user_id === meId);
      if (me) {
        youLine.hidden = false;
        const gap = me.gap_above != null ? ' · gap ↑ ' + fmt(me.gap_above, 0) : '';
        const catchd = me.days_to_catch != null ? ' · catch ~' + fmt(me.days_to_catch, 0) + 'd' : '';
        youLine.innerHTML = `<b>YOU</b> · #${me.rank || '—'} · ${fmt(me.score ?? me.total_score, 0)} pts · 7d ${fmt(me.velocity_7d, 1)}/d${gap}${catchd}`;
      } else youLine.hidden = true;
    } else if (youLine) youLine.hidden = true;
  }

  function personRow(u, metricHtml, opts) {
    opts = opts || {};
    const meId = resolveMeUserId((state.data && state.data.users) || []);
    const isMe = meId && u.user_id === meId;
    return `<div class="person-row${isMe ? ' is-me' : ''}${state.hlUser === u.user_id ? ' hl' : ''}" data-uid="${esc(u.user_id)}" onclick="Race.hl('${esc(u.user_id)}')">
      <img class="av" src="${esc(u.avatar_url)}" alt="" width="36" height="36" loading="lazy"/>
      <div class="who">
        <div class="name">${esc(u.display_name)}</div>
        <div class="meta">#${u.rank} · ${fmt(u.score, 0)} pts</div>
      </div>
      <div class="metric">${metricHtml}</div>
    </div>`;
  }

  function renderHighlights(h) {
    const heat = (h.heating || []);
    const cool = (h.cooling || []);
    const catchu = (h.catching_up || []);

    const CAP = 4;
    const heatS = heat.slice(0, CAP);
    const coolS = cool.slice(0, CAP);
    const catchS = catchu.slice(0, CAP);
    $('band-heating').innerHTML = heatS.length
      ? heatS.map(u => personRow(u,
          `<span class="pos">+${fmt(u.acceleration)}</span><span class="unit">accel · ${fmt(u.velocity_7d)}/d</span>`
        )).join('') + (heat.length > CAP ? `<div class="band-empty">+${heat.length - CAP} more in standings</div>` : '')
      : '<div class="band-empty">No one heating up right now</div>';

    $('band-cooling').innerHTML = coolS.length
      ? coolS.map(u => personRow(u,
          `<span class="neg">${fmt(u.acceleration)}</span><span class="unit">${u.momentum === 'idle' ? 'idle ' + (u.inactive_days || 0) + 'd' : fmt(u.velocity_7d) + '/d'}</span>`
        )).join('') + (cool.length > CAP ? `<div class="band-empty">+${cool.length - CAP} more in standings</div>` : '')
      : '<div class="band-empty">No one cooling off</div>';

    $('band-catching').innerHTML = catchS.length
      ? catchS.map(u => personRow(u,
          `<span class="pos">${fmt(u.days_to_catch, 0)}d</span><span class="unit">gap ${fmt(u.gap_above, 0)}</span>`
        )).join('')
      : '<div class="band-empty">Nobody currently outpacing the rank above</div>';
  }

  function selectedChartUsers() {
    const users = (state.data.users || []).slice();
    let list;
    if (state.chartMode === 'all') {
      list = users.filter(u => u.score > 0);
    } else if (state.chartMode === 'heating') {
      list = users.filter(u => u.momentum === 'heating' || (u.acceleration > 0 && u.velocity_7d > 5));
      if (list.length < 3) list = users.slice().sort((a, b) => b.acceleration - a.acceleration).slice(0, 8);
    } else {
      list = users.filter(u => u.score > 0).slice().sort((a, b) => a.rank - b.rank).slice(0, state.chartMode === 'top5' ? 5 : 12);
    }
    return list.filter(u => !state.hidden.has(u.user_id));
  }

  function chartSeriesFor(uid) {
    const c = (state.data.chart || []).find(x => x.user_id === uid);
    return c ? c.series : [];
  }

  function renderLegend(pool) {
    const el = $('chart-legend');
    // pool includes hidden for toggle UI
    const all = (state.data.users || []).filter(u => {
      if (state.chartMode === 'all') return u.score > 0;
      if (state.chartMode === 'heating') return true;
      return u.score > 0 && u.rank <= 12;
    }).slice(0, state.chartMode === 'all' ? 40 : 20);

    let source = all;
    if (state.chartMode === 'heating') {
      source = (state.data.users || []).slice().sort((a, b) => b.acceleration - a.acceleration).slice(0, 12);
    } else if (state.chartMode === 'top12') {
      source = (state.data.users || []).filter(u => u.score > 0).sort((a, b) => a.rank - b.rank).slice(0, 12);
    } else {
      source = (state.data.users || []).filter(u => u.score > 0).sort((a, b) => a.rank - b.rank);
    }

    el.innerHTML = source.map(u => {
      const off = state.hidden.has(u.user_id) ? 'off' : 'on';
      return `<button type="button" class="legend-chip ${off}" data-uid="${esc(u.user_id)}" title="${esc(u.display_name)}">
        <img src="${esc(u.avatar_url)}" alt=""/>
        <span class="dot" style="background:${esc(u.color)}"></span>
        <span class="nm">#${u.rank} ${esc(u.display_name)}</span>
      </button>`;
    }).join('');

    el.querySelectorAll('.legend-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-uid');
        if (state.hidden.has(id)) state.hidden.delete(id);
        else state.hidden.add(id);
        drawChart();
        renderLegend();
      });
      btn.addEventListener('mouseenter', () => Race.hl(btn.getAttribute('data-uid'), false));
    });
  }

  function buildProjectedTail(u, histPts) {
    const days = Math.floor(resolveProjectDays());
    if (days <= 0 || !histPts.length) return [];
    const last = histPts[histPts.length - 1];
    const rate = dailyRateFor(u, state.projectModel);
    const tail = [];
    let running = Number(last.cumulative) || 0;
    for (let i = 1; i <= days; i++) {
      running += rate;
      tail.push({
        date: addDaysISO(last.date, i),
        cumulative: Math.round(running * 100) / 100,
        projected: true,
      });
    }
    return tail;
  }

  function drawChart() {
    const canvas = $('race-canvas');
    if (!canvas || !state.data) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    const W = Math.max(320, rect.width);
    const H = Math.max(280, rect.height);
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const pad = { t: 16, r: 18, b: 36, l: 58 };
    const plotW = W - pad.l - pad.r;
    const plotH = H - pad.t - pad.b;

    ctx.clearRect(0, 0, W, H);

    // paper grid
    ctx.fillStyle = '#fffaf0';
    ctx.fillRect(0, 0, W, H);

    const projDays = Math.floor(resolveProjectDays());
    const users = selectedChartUsers();
    const seriesList = users.map(u => {
      const hist = chartSeriesFor(u.user_id);
      const proj = buildProjectedTail(u, hist);
      return { u, pts: hist, proj };
    }).filter(s => s.pts.length);

    if (!seriesList.length) {
      ctx.fillStyle = '#9a9182';
      ctx.font = '600 14px IBM Plex Sans, system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('No series to plot — try showing more runners', W / 2, H / 2);
      return;
    }

    // Axis dates: longest historical series + projection horizon
    let histDates = seriesList.reduce((a, s) => s.pts.length > a.length ? s.pts.map(p => p.date) : a, []);
    const lastHist = histDates[histDates.length - 1];
    const dates = histDates.slice();
    if (projDays > 0 && lastHist) {
      for (let i = 1; i <= projDays; i++) dates.push(addDaysISO(lastHist, i));
    }
    const histEndIdx = histDates.length - 1;

    let maxY = 0;
    seriesList.forEach(s => {
      s.pts.forEach(p => { if (p.cumulative > maxY) maxY = p.cumulative; });
      s.proj.forEach(p => { if (p.cumulative > maxY) maxY = p.cumulative; });
    });
    maxY = Math.max(maxY * 1.05, 10);

    const xAt = (i) => pad.l + (i / Math.max(dates.length - 1, 1)) * plotW;
    const yAt = (v) => pad.t + plotH - (v / maxY) * plotH;

    // gridlines
    ctx.strokeStyle = 'rgba(180,168,140,0.35)';
    ctx.lineWidth = 1;
    ctx.font = '600 10px IBM Plex Mono, monospace';
    ctx.fillStyle = '#9a9182';
    ctx.textAlign = 'right';
    for (let g = 0; g <= 5; g++) {
      const v = (maxY / 5) * g;
      const y = yAt(v);
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(pad.l + plotW, y);
      ctx.stroke();
      ctx.fillText(fmt(v, 0), pad.l - 8, y + 3);
    }

    // projection band
    if (projDays > 0 && histEndIdx >= 0 && dates.length > histEndIdx + 1) {
      const x0 = xAt(histEndIdx);
      const x1 = xAt(dates.length - 1);
      ctx.fillStyle = 'rgba(42, 82, 120, 0.06)';
      ctx.fillRect(x0, pad.t, x1 - x0, plotH);
      ctx.strokeStyle = 'rgba(42, 82, 120, 0.35)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x0, pad.t);
      ctx.lineTo(x0, pad.t + plotH);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#2a5278';
      ctx.font = '700 10px IBM Plex Sans, system-ui, sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText('projected →', x0 + 6, pad.t + 12);
    }

    // x labels
    ctx.textAlign = 'center';
    ctx.fillStyle = '#9a9182';
    ctx.font = '600 10px IBM Plex Mono, monospace';
    const labelEvery = Math.max(1, Math.floor(dates.length / 6));
    dates.forEach((d, i) => {
      if (i % labelEvery !== 0 && i !== dates.length - 1) return;
      const x = xAt(i);
      ctx.fillStyle = i > histEndIdx ? '#2a5278' : '#9a9182';
      ctx.fillText(d.slice(5), x, H - 12);
    });

    // axes
    ctx.strokeStyle = '#1c1914';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, pad.t + plotH);
    ctx.lineTo(pad.l + plotW, pad.t + plotH);
    ctx.stroke();

    const dateIndex = new Map(dates.map((d, i) => [d, i]));

    const ordered = seriesList.slice().sort((a, b) => {
      const ah = a.u.user_id === state.hlUser ? 1 : 0;
      const bh = b.u.user_id === state.hlUser ? 1 : 0;
      return ah - bh;
    });

    function pathFor(pts, dash) {
      ctx.setLineDash(dash || []);
      ctx.beginPath();
      let started = false;
      pts.forEach((p) => {
        let i = dateIndex.get(p.date);
        if (i == null) {
          i = dates.findIndex(d => d >= p.date);
          if (i < 0) i = dates.length - 1;
        }
        const x = xAt(i);
        const y = yAt(p.cumulative);
        if (!started) { ctx.moveTo(x, y); started = true; }
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.setLineDash([]);
    }

    ordered.forEach(({ u, pts, proj }) => {
      const hl = state.hlUser === u.user_id;
      ctx.strokeStyle = u.color;
      ctx.lineWidth = hl ? 3.2 : 1.7;
      ctx.globalAlpha = state.hlUser && !hl ? 0.22 : 0.92;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';

      // historical solid
      pathFor(pts, []);

      // projected dashed, linked from last hist point
      if (proj && proj.length) {
        const bridge = [pts[pts.length - 1]].concat(proj);
        pathFor(bridge, [6, 5]);
      }

      const endPts = (proj && proj.length) ? proj : pts;
      if (endPts.length && (hl || u.rank <= 5 || seriesList.length <= 8)) {
        const last = endPts[endPts.length - 1];
        let i = dateIndex.get(last.date);
        if (i == null) i = dates.length - 1;
        const x = xAt(i);
        const y = yAt(last.cumulative);
        ctx.globalAlpha = state.hlUser && !hl ? 0.25 : 1;
        ctx.fillStyle = u.color;
        ctx.beginPath();
        ctx.arc(x, y, hl ? 5 : 3.5, 0, Math.PI * 2);
        ctx.fill();
        if (hl || u.rank <= 3) {
          ctx.font = '700 11px IBM Plex Sans, system-ui, sans-serif';
          ctx.textAlign = 'left';
          const pmap = projectedById();
          const pr = pmap.get(u.user_id);
          const label = pr
            ? `${u.display_name} →#${pr.projected_rank}`
            : u.display_name;
          ctx.fillText(label, Math.min(x + 8, W - 100), y - 6);
        }
      }
    });
    ctx.globalAlpha = 1;

    canvas._plot = {
      pad, plotW, plotH, maxY, dates, seriesList, W, H, xAt, yAt, dateIndex, histEndIdx, projDays,
    };
  }

  function bindChartHover() {
    const canvas = $('race-canvas');
    const tip = $('chart-tip');
    if (!canvas || canvas._bound) return;
    canvas._bound = true;

    canvas.addEventListener('mousemove', (ev) => {
      const plot = canvas._plot;
      if (!plot) return;
      const rect = canvas.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      const { pad, plotW, dates, seriesList, dateIndex, xAt, yAt } = plot;
      if (x < pad.l || x > pad.l + plotW) {
        tip.style.display = 'none';
        return;
      }
      const t = (x - pad.l) / plotW;
      const idx = Math.round(t * Math.max(dates.length - 1, 1));
      const date = dates[idx];

      // nearest series by y (historical + projected)
      let best = null;
      let bestDist = 1e9;
      seriesList.forEach(({ u, pts, proj }) => {
        const all = pts.concat(proj || []);
        let pt = all.find(p => p.date === date);
        if (!pt) {
          for (let i = all.length - 1; i >= 0; i--) {
            if (all[i].date <= date) { pt = all[i]; break; }
          }
        }
        if (!pt) return;
        const py = yAt(pt.cumulative);
        const dist = Math.abs(py - y);
        if (dist < bestDist) {
          bestDist = dist;
          best = { u, pt, date };
        }
      });

      if (!best || bestDist > 40) {
        tip.style.display = 'none';
        return;
      }
      const pmap = projectedById();
      const pr = pmap.get(best.u.user_id);
      const isProj = !!(best.pt && best.pt.projected);
      tip.style.display = 'block';
      tip.innerHTML = `<strong style="color:${esc(best.u.color)}">${esc(best.u.display_name)}</strong>
        <div class="row">${esc(best.date)}${isProj ? ' · projected' : ''}</div>
        <div class="row">${fmt(best.pt.cumulative, 1)} pts cumulative</div>
        <div class="row">now #${best.u.rank}${pr ? ' → proj #' + pr.projected_rank : ''}</div>`;
      const tw = tip.offsetWidth || 160;
      const th = tip.offsetHeight || 60;
      let left = ev.clientX - rect.left + 14;
      let top = ev.clientY - rect.top - th - 8;
      if (left + tw > rect.width) left = ev.clientX - rect.left - tw - 12;
      if (top < 0) top = ev.clientY - rect.top + 16;
      tip.style.left = left + 'px';
      tip.style.top = top + 'px';
    });
    canvas.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
  }

  function sortedUsers() {
    const q = state.filter.trim().toLowerCase();
    const pmap = projectedById();
    let list = (state.data.users || []).map(u => {
      const p = pmap.get(u.user_id);
      return p ? Object.assign({}, u, {
        projected_rank: p.projected_rank,
        projected_score: p.projected_score,
        rank_delta: p.rank_delta,
        projected_daily_rate: p.projected_daily_rate,
      }) : Object.assign({}, u);
    });
    if (q) list = list.filter(u => (u.display_name || '').toLowerCase().includes(q));
    const k = state.sortKey;
    const dir = state.sortDir;
    list.sort((a, b) => {
      let av = a[k], bv = b[k];
      if (av == null) av = dir > 0 ? Infinity : -Infinity;
      if (bv == null) bv = dir > 0 ? Infinity : -Infinity;
      if (typeof av === 'string') return av.localeCompare(bv) * dir;
      return (av - bv) * dir;
    });
    return list;
  }

  function renderProjection() {
    const days = resolveProjectDays();
    const model = state.projectModel;
    const modelLabel = {
      velocity: '7d pace',
      baseline: '30d pace',
      accel: 'accel trend',
    }[model] || model;

    const asOf = (state.data.summary && state.data.summary.as_of) || '';
    const target = asOf ? addDaysISO(asOf, days) : '';
    const sumEl = $('proj-summary');
    if (sumEl) {
      sumEl.textContent = days <= 0
        ? 'horizon 0d · no projection'
        : `+${days}d → ${target || '?'} · ${modelLabel}`;
    }

    // Live header labels: show *when* "Score then" / place projection is for
    const thScore = $('th-proj-score');
    const thPlace = $('th-proj-rank');
    const thDelta = $('th-rank-delta');
    if (thScore) {
      if (days <= 0) {
        thScore.innerHTML = 'Score then';
        thScore.title = 'Set a projection horizon above to estimate future scores.';
      } else {
        thScore.innerHTML = `Score then<span class="th-sub">@ ${esc(target || ('+' + days + 'd'))}</span>`;
        thScore.title =
          `Estimated total score on ${target || ('+' + days + ' days')}, ` +
          `if this runner keeps the “${modelLabel}” model for ${days} day(s). ` +
          `Does not account for rest days, burnout, or contest rule changes.`;
      }
    }
    if (thPlace) {
      if (days <= 0) {
        thPlace.innerHTML = 'Proj place';
        thPlace.title = 'Set a projection horizon above to estimate future rank.';
      } else {
        thPlace.innerHTML = `Proj place<span class="th-sub">@ ${esc(target || ('+' + days + 'd'))}</span>`;
        thPlace.title =
          `Projected contest rank on ${target || ('+' + days + ' days')} ` +
          `if everyone keeps their “${modelLabel}” for ${days} day(s). ` +
          `Everyone is re-ranked by projected score.`;
      }
    }
    if (thDelta) {
      thDelta.title =
        days <= 0
          ? 'Places gained (↑) or lost (↓) at the projection horizon versus current rank.'
          : `Places gained (↑) or lost (↓) by ${target || ('+' + days + 'd')} versus current rank. ` +
            `↑2 means two places higher; ↓1 means one place lower.`;
    }

    const customWrap = $('proj-custom-wrap');
    const customInput = $('proj-custom-days');
    if (customWrap) customWrap.style.display = state.projectHorizon === 'custom' ? '' : 'none';
    if (customInput && state.projectHorizon === 'custom' && document.activeElement !== customInput) {
      customInput.value = String(days);
    }

    const list = state.projected || [];
    const podium = list.slice(0, 5);
    const pod = $('proj-podium');
    if (pod) {
      if (!days) {
        pod.innerHTML = '<div class="band-empty">Set a horizon above to project places</div>';
      } else {
        pod.innerHTML = podium.map(u => personRow(u,
          `<span class="proj-rank">#${u.projected_rank}</span>` +
          `<span class="unit">${fmtDelta(u.rank_delta)} · ${fmt(u.projected_score, 0)} pts</span>`
        )).join('') || '<div class="band-empty">No runners</div>';
      }
    }

    const movers = list
      .filter(u => u.rank_delta !== 0)
      .slice()
      .sort((a, b) => Math.abs(b.rank_delta) - Math.abs(a.rank_delta))
      .slice(0, 8);
    const mov = $('proj-movers');
    if (mov) {
      if (!days) {
        mov.innerHTML = '<div class="band-empty">—</div>';
      } else if (!movers.length) {
        mov.innerHTML = '<div class="band-empty">No place changes at this pace</div>';
      } else {
        mov.innerHTML = movers.map(u => personRow(u,
          `${fmtDelta(u.rank_delta)}<span class="unit">#${u.rank} → #${u.projected_rank}</span>`
        )).join('');
      }
    }

    // sync horizon select
    const hSel = $('proj-horizon');
    if (hSel && hSel.value !== state.projectHorizon) hSel.value = state.projectHorizon;
    const mSel = $('proj-model');
    if (mSel && mSel.value !== state.projectModel) mSel.value = state.projectModel;
  }

  function renderTable() {
    const body = $('race-tbody');
    const list = sortedUsers();
    body.innerHTML = list.map(u => {
      const accelCls = u.acceleration > 1 ? 'pos' : u.acceleration < -1 ? 'neg' : 'muted-cell';
      const hl = state.hlUser === u.user_id ? 'hl' : '';
      const catchTxt = u.days_to_catch != null && u.days_to_catch > 0
        ? `${fmt(u.days_to_catch, 0)}d`
        : '—';
      const pRank = u.projected_rank != null ? u.projected_rank : '—';
      const pScore = u.projected_score != null ? fmt(u.projected_score, 0) : '—';
      return `<tr class="${hl}" data-uid="${esc(u.user_id)}" onclick="Race.hl('${esc(u.user_id)}')">
        <td class="mono">${u.rank}</td>
        <td class="mono proj-col proj-rank">${pRank}</td>
        <td class="mono proj-col">${fmtDelta(u.rank_delta)}</td>
        <td>
          <div class="cell-user">
            <img src="${esc(u.avatar_url)}" alt="" width="32" height="32" loading="lazy"/>
            <div>
              <div class="nm">${esc(u.display_name)}</div>
              <div class="id">${u.inactive_days > 3 ? u.inactive_days + 'd quiet' : (u.days_logged || 0) + ' days logged'}</div>
            </div>
          </div>
        </td>
        <td class="mono">${fmt(u.score, 1)}</td>
        <td class="mono proj-col">${pScore}</td>
        <td class="mono">${fmt(u.velocity_7d, 1)}</td>
        <td class="mono">${fmt(u.velocity_30d, 1)}</td>
        <td class="mono ${accelCls}">${u.acceleration > 0 ? '+' : ''}${fmt(u.acceleration, 1)}</td>
        <td><span class="pill ${esc(u.momentum)}">${esc(u.momentum)}</span></td>
        <td class="mono">${u.gap_above != null ? fmt(u.gap_above, 0) : '—'}</td>
        <td class="mono">${catchTxt}</td>
        <td>${sparkSVG(u.sparkline, u.color)}</td>
      </tr>`;
    }).join('');

    document.querySelectorAll('table.race-table th[data-sort]').forEach(th => {
      th.classList.toggle('sorted', th.getAttribute('data-sort') === state.sortKey);
    });
  }

  function renderAll() {
    const d = state.data;
    if (!d) return;
    const c = d.contest || {};
    const s = d.summary || {};
    const cache = d.cache || {};

    recomputeProjection();

    if ($('race-title')) $('race-title').textContent = c.title || 'Contest race';
    if ($('race-sub')) {
      $('race-sub').textContent = (c.start && c.end)
        ? `${c.start} → ${c.end}`
        : 'Contest standings';
    }

    const users = d.users || d.standings || [];
    const list = Array.isArray(users) ? users : [];
    let daysLeft = '—';
    if (c.end) {
      const end = parseISODate(c.end);
      const asof = parseISODate(s.as_of) || new Date();
      if (end) {
        const ms = end - asof;
        const days = Math.ceil(ms / 86400000);
        daysLeft = days < 0 ? 'ended' : String(days);
      }
    }
    if ($('stat-days')) $('stat-days').textContent = daysLeft;
    if ($('stat-runners')) $('stat-runners').textContent = fmt(s.participant_count, 0);
    if ($('stat-asof')) $('stat-asof').textContent = s.as_of || '—';
    const hot = (d.highlights && d.highlights.heating) ? d.highlights.heating.length : 0;
    const cold = (d.highlights && d.highlights.cooling) ? d.highlights.cooling.length : 0;
    const catchN = (d.highlights && (d.highlights.catching_up || d.highlights.catching))
      ? (d.highlights.catching_up || d.highlights.catching).length : 0;
    const pulse = $('race-pulse-line');
    if (pulse) pulse.textContent = `${hot} heating · ${catchN} catching · ${cold} cooling`;
    renderScoreboard();
    // keep legacy ids if present
    const leader = list.slice().sort((a, b) => (a.rank || 999) - (b.rank || 999))[0];
    if ($('stat-leader')) {
      $('stat-leader').textContent = leader
        ? ((leader.display_name || leader.username || '—').slice(0, 18))
        : '—';
    }
    const mom = $('stat-momentum');
    if (mom) mom.textContent = `${hot}↑ / ${cold}↓`;
    const momSub = $('stat-momentum-sub');
    if (momSub) momSub.textContent = 'heating / cooling';

    const age = cache.age_seconds;
    let cacheTxt = cache.hit
      ? `cached ${fmtAge(age)}`
      : `fresh · ${cache.activity_refreshed ?? '—'} updated`;
    if (cache.stale) cacheTxt += ' · offline stale';
    $('cache-meta').textContent = cacheTxt;

    renderHighlights(d.highlights || {});
    renderProjection();
    renderLegend();
    renderTable();
    drawChart();
    bindChartHover();
    applyHighlightDom();
  }

  function applyHighlightDom() {
    document.querySelectorAll('[data-uid]').forEach(el => {
      el.classList.toggle('hl', el.getAttribute('data-uid') === state.hlUser);
    });
  }

  async function load(force) {
    const err = $('race-error');
    const loading = $('race-loading');
    err.style.display = 'none';
    loading.style.display = 'block';
    const main = $('race-main');
    if (main && !state.data) main.style.display = 'none';
    $('btn-refresh').disabled = true;
    try {
      const url = force ? '/api/contest/momentum?force=1' : '/api/contest/momentum';
      const r = await fetch(url);
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t || ('HTTP ' + r.status));
      }
      state.data = await r.json();
      loading.style.display = 'none';
      $('race-main').style.display = 'block';
      renderAll();
    } catch (e) {
      loading.style.display = 'none';
      err.style.display = 'block';
      err.textContent = 'Could not load contest data: ' + (e.message || e);
    } finally {
      $('btn-refresh').disabled = false;
    }
  }

  window.Race = {
    hl(uid, scroll) {
      state.hlUser = state.hlUser === uid ? null : uid;
      applyHighlightDom();
      drawChart();
      if (scroll !== false && state.hlUser) {
        const row = document.querySelector(`tr[data-uid="${CSS.escape(uid)}"]`);
        if (row) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    },
    refresh() { load(true); },
    setMode(m) {
      state.chartMode = m;
      state.hidden.clear();
      renderLegend();
      drawChart();
    },
    setHorizon(key) {
      state.projectHorizon = key || '30';
      if (key === 'custom') {
        const n = Number(($('proj-custom-days') || {}).value);
        if (Number.isFinite(n) && n >= 0) state.projectDays = n;
      }
      recomputeProjection();
      renderProjection();
      renderTable();
      drawChart();
    },
    setModel(m) {
      state.projectModel = m || 'velocity';
      recomputeProjection();
      renderProjection();
      renderTable();
      drawChart();
    },
    setCustomDays(n) {
      state.projectHorizon = 'custom';
      state.projectDays = Math.max(0, Number(n) || 0);
      const hSel = $('proj-horizon');
      if (hSel) hSel.value = 'custom';
      recomputeProjection();
      renderProjection();
      renderTable();
      drawChart();
    },
    sort(key) {
      if (state.sortKey === key) state.sortDir *= -1;
      else {
        state.sortKey = key;
        // lower rank / projected_rank better; higher scores/vel better
        const ascKeys = new Set(['rank', 'projected_rank', 'display_name']);
        state.sortDir = ascKeys.has(key) ? 1 : -1;
      }
      renderTable();
    },
    filter(q) {
      state.filter = q;
      renderTable();
    },
  };

  window.addEventListener('resize', () => {
    if (state.data) drawChart();
  });

  // boot
  document.querySelectorAll('table.race-table th[data-sort]').forEach(th => {
    th.addEventListener('click', () => Race.sort(th.getAttribute('data-sort')));
  });
  const search = $('race-search');
  if (search) search.addEventListener('input', () => Race.filter(search.value));
  const mode = $('chart-mode');
  if (mode) mode.addEventListener('change', () => Race.setMode(mode.value));
  const horizon = $('proj-horizon');
  if (horizon) horizon.addEventListener('change', () => Race.setHorizon(horizon.value));
  const model = $('proj-model');
  if (model) model.addEventListener('change', () => Race.setModel(model.value));
  const customDays = $('proj-custom-days');
  if (customDays) {
    customDays.addEventListener('change', () => Race.setCustomDays(customDays.value));
    customDays.addEventListener('input', () => {
      if (state.projectHorizon === 'custom') Race.setCustomDays(customDays.value);
    });
  }
  $('btn-refresh').addEventListener('click', () => Race.refresh());

  load(false);
})();
"""
