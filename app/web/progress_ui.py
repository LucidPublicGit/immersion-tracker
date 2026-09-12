"""Content progress page — list/grid of works with Tadoku pull + metadata cache."""

from __future__ import annotations

from html import escape

from app import __version__
from app.web.styles import SHARED_CSS, nav_html

PROGRESS_CSS = """
/* ═══ Library Shelf — bold OPERATE redesign ═══ */
.page-progress { max-width: 1280px; }
.page-progress .mast { margin-bottom: 0.4rem; }
.page-progress .mast h1 {
  font-size: 1.55rem;
  letter-spacing: -0.02em;
}

/* LIBRARY PULSE — same ticket language as Queue ledger */
.prog-pulse {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0;
  border: 3px solid var(--ink);
  background: var(--panel);
  margin: 0 0 0.85rem;
  box-shadow: 4px 4px 0 rgba(20, 17, 14, 0.1);
  position: relative;
}
.prog-pulse::before {
  content: "LIBRARY";
  position: absolute;
  top: -0.55rem;
  left: 0.75rem;
  font-family: var(--mono);
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  background: var(--ink);
  color: var(--panel);
  padding: 0.1rem 0.45rem;
  line-height: 1.3;
}
.prog-pulse-cell {
  padding: 0.75rem 0.9rem 0.7rem;
  border-right: 1px solid var(--line-strong);
  min-width: 0;
}
.prog-pulse-cell:last-child { border-right: 0; }
.prog-pulse-cell .k {
  font-family: var(--mono);
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  margin-bottom: 0.2rem;
}
.prog-pulse-cell .v {
  font-family: var(--mono);
  font-size: 1.85rem;
  font-weight: 700;
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
  line-height: 1;
  color: var(--ink);
}
.prog-pulse-cell.has-work.st-active {
  background: var(--blue-bg);
}
.prog-pulse-cell.has-work.st-active .v { color: var(--blue); }
.prog-pulse-cell.has-work.st-finished {
  background: var(--green-bg);
}
.prog-pulse-cell.has-work.st-finished .v { color: var(--green); }
.prog-pulse-cell.has-work.st-dropped {
  background: var(--red-bg);
}
.prog-pulse-cell.has-work.st-dropped .v { color: var(--red); }
.prog-pulse-cell.has-work.st-ignored {
  background: var(--paper-2);
}
.prog-pulse-cell.has-work.st-ignored .v { color: var(--muted); }
.prog-pulse-cell.is-selected {
  outline: 2px solid var(--ink);
  outline-offset: -2px;
  box-shadow: inset 0 0 0 1px var(--panel);
}
.prog-pulse-cell.is-selected.st-active { background: var(--blue-bg); }
.prog-pulse-cell.is-selected.st-finished { background: var(--green-bg); }
.prog-pulse-cell.is-selected.st-dropped { background: var(--red-bg); }
.prog-pulse-cell.is-selected.st-ignored { background: var(--paper-2); }
.prog-pulse-cell .s {
  font-family: var(--mono);
  font-size: 0.68rem;
  color: var(--faint);
  margin-top: 0.2rem;
}
@media (max-width: 520px) {
  .prog-pulse { grid-template-columns: 1fr; }
  .prog-pulse-cell { border-right: 0; border-bottom: 1px solid var(--line); }
  .prog-pulse-cell:last-child { border-bottom: 0; }
  .prog-pulse-cell .v { font-size: 1.55rem; }
}

/* Command bar — ink work frame */
.prog-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.65rem 1rem;
  margin-bottom: 0;
  padding: 0.75rem 0.9rem;
  border: 2.5px solid var(--ink);
  border-bottom: none;
  background: var(--panel);
  justify-content: space-between;
}
.prog-toolbar-view {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 0.55rem 0.85rem;
  flex: 1 1 16rem;
}
.prog-toolbar-ops {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
  margin-left: auto;
}
.prog-toolbar .field { min-width: 7rem; flex: 1 1 8rem; }
.prog-toolbar .field.grow { flex: 2 1 14rem; }
.prog-toolbar label {
  display: block;
  margin: 0 0 0.2rem;
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--muted);
  font-family: var(--mono);
}
.prog-toolbar input, .prog-toolbar select {
  width: 100%;
  font: inherit;
  font-size: 0.92rem;
  padding: 0.45rem 0.55rem;
  border: 1px solid var(--ink);
  background: #fff;
  color: var(--ink);
  border-radius: 2px;
  min-height: 2.25rem;
}
.prog-toolbar button, .mode-toggle button {
  appearance: none;
  font: inherit;
  font-size: 0.82rem;
  font-weight: 700;
  padding: 0.48rem 0.8rem;
  min-height: 2.25rem;
  border: 1px solid var(--ink);
  background: var(--panel-2);
  color: var(--ink);
  cursor: pointer;
  border-radius: 2px;
}
.prog-toolbar button.primary {
  background: var(--accent);
  border-color: #8f3f14;
  color: var(--accent-ink);
  padding: 0.48rem 1.1rem;
  letter-spacing: 0.01em;
  box-shadow: 2px 2px 0 rgba(20,17,14,0.12);
}
.prog-toolbar button.primary:hover { background: var(--accent-hover); }
.prog-toolbar button:hover { background: var(--paper-2); }
.prog-toolbar button.primary:hover { background: var(--accent-hover); color: var(--accent-ink); }
.prog-toolbar button:disabled { opacity: 0.55; cursor: wait; }
.mode-toggle {
  display: inline-flex;
  border: 1.5px solid var(--ink);
  background: var(--panel-2);
  overflow: hidden;
}
.mode-toggle button {
  border: none;
  border-radius: 0;
  border-right: 1px solid var(--line-strong);
  background: transparent;
  min-height: 2.25rem;
}
.mode-toggle button:last-child { border-right: 0; }
.mode-toggle button.active {
  background: var(--ink);
  color: var(--panel);
  box-shadow: none;
}
.prog-overflow { position: relative; }
.prog-overflow > summary {
  list-style: none;
  cursor: pointer;
  font: inherit;
  font-size: 0.82rem;
  font-weight: 700;
  padding: 0.48rem 0.75rem;
  border: 1px solid var(--ink);
  background: var(--panel);
  min-height: 2.25rem;
  display: inline-flex;
  align-items: center;
}
.prog-overflow > summary::-webkit-details-marker { display: none; }
.prog-overflow-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 3px);
  z-index: 12;
  min-width: 13rem;
  border: 2px solid var(--ink);
  background: var(--panel);
  padding: 0.35rem;
  box-shadow: 0 10px 24px rgba(20,17,14,0.16);
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.prog-overflow-menu button { width: 100%; text-align: left; }

/* Filter rail — ink shelf labels */
.prog-filter-band {
  border: 2.5px solid var(--ink);
  background: var(--paper-2);
  margin-bottom: 0.65rem;
}
.prog-filter-note {
  margin: 0;
  padding: 0.4rem 0.75rem 0.55rem;
  font-family: var(--mono);
  font-size: 0.72rem;
  color: var(--muted);
  border-top: 1px solid var(--line);
  background: var(--panel);
}
.prog-filter-note[hidden] { display: none; }
.page-progress .prog-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  margin: 0;
  border: none;
  border-bottom: 2px solid var(--ink);
  background: var(--paper-2);
  overflow-x: auto;
}
.page-progress .prog-tab {
  appearance: none;
  border: none;
  border-right: 1px solid var(--line-strong);
  background: transparent;
  color: var(--ink-soft);
  font: inherit;
  font-size: 0.82rem;
  font-weight: 700;
  padding: 0.6rem 0.9rem;
  cursor: pointer;
  white-space: nowrap;
  min-height: 2.4rem;
}
.page-progress .prog-tab:hover { background: var(--paper); color: var(--ink); }
.page-progress .prog-tab.active {
  background: var(--panel);
  color: var(--ink);
  box-shadow: inset 0 -3px 0 var(--accent);
}
.page-progress .prog-tab .tab-count {
  font-family: var(--mono);
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--muted);
  margin-left: 0.35rem;
  background: var(--panel);
  border: 1px solid var(--line-strong);
  padding: 0.05rem 0.3rem;
  border-radius: 2px;
}
.page-progress .prog-tab.active .tab-count {
  background: var(--ink);
  color: var(--panel);
  border-color: var(--ink);
}
.status-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 0;
  padding: 0.5rem 0.7rem;
  align-items: center;
  background: var(--panel);
}
.status-filters .sf-label {
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  font-family: var(--mono);
  margin-right: 0.2rem;
}
.status-chip {
  appearance: none;
  font: inherit;
  font-size: 0.8rem;
  font-weight: 700;
  padding: 0.35rem 0.65rem;
  min-height: 2rem;
  border: 1.5px solid var(--line-strong);
  background: var(--panel-2);
  color: var(--ink-soft);
  cursor: pointer;
  border-radius: 2px;
}
.status-chip:hover { background: var(--paper-2); color: var(--ink); border-color: var(--ink); }
.status-chip.on {
  border-color: var(--ink);
  color: var(--ink);
  background: var(--panel);
  box-shadow: 2px 2px 0 rgba(20,17,14,0.08);
}
.status-chip.on.st-active { background: var(--blue-bg); border-color: var(--blue); color: var(--blue); }
.status-chip.on.st-finished { background: var(--green-bg); border-color: var(--green); color: var(--green); }
.status-chip.on.st-dropped { background: var(--red-bg); border-color: var(--red); color: var(--red); }
.status-chip.on.st-ignored { background: var(--paper-2); border-color: var(--muted); color: var(--muted); }
.status-chip .n {
  font-family: var(--mono);
  font-size: 0.7rem;
  font-weight: 700;
  margin-left: 0.3rem;
  opacity: 0.85;
}

.prog-lib-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.85rem;
  margin: 0 0 0.75rem;
  font-family: var(--mono);
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--ink-soft);
}
.prog-lib-meta #prog-count {
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--ink);
}
.prog-lib-meta .prog-msg {
  margin: 0;
  flex: 1 1 10rem;
  min-height: 0;
  font-size: 0.8rem;
  color: var(--muted);
}
.prog-msg.err { color: var(--red); }
.prog-msg.ok { color: var(--green); }
.prog-help-inline { margin: 0; border: none; background: transparent; }
.prog-help-inline > summary {
  padding: 0.15rem 0;
  font-size: 0.72rem;
  letter-spacing: 0.04em;
  color: var(--muted);
}

/* Book shelf grid */
.prog-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 1rem;
}
.prog-card {
  border: 2.5px solid var(--ink);
  background: var(--panel);
  display: flex;
  flex-direction: column;
  min-height: 100%;
  overflow: hidden;
  box-shadow: 3px 3px 0 rgba(20, 17, 14, 0.1);
  position: relative;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.prog-card:hover {
  transform: translate(-1px, -1px);
  box-shadow: 4px 4px 0 rgba(20, 17, 14, 0.14);
}
.prog-card::before {
  content: "";
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 4px;
  background: var(--line-strong);
  z-index: 3;
}
.prog-card.status-active::before { background: var(--blue); width: 5px; }
.prog-card.status-finished::before { background: var(--green); width: 5px; }
.prog-card.status-dropped::before { background: var(--red); width: 5px; }
.prog-card.status-ignored::before { background: var(--muted); width: 5px; }
.prog-card.status-ignored { opacity: 0.78; }
.prog-card .cover-wrap {
  aspect-ratio: 2 / 3;
  background: var(--paper-2);
  border-bottom: 2px solid var(--ink);
  position: relative;
  overflow: hidden;
  cursor: default;
}
.prog-card .cover-wrap img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.prog-card .cover-wrap .ph {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 0.5rem;
  text-align: center;
  font-family: var(--mono);
  background:
    repeating-linear-gradient(0deg, transparent, transparent 11px, rgba(80,60,30,0.04) 12px);
}
.prog-card .pct-badge {
  position: absolute;
  top: 0.4rem;
  right: 0.4rem;
  background: var(--accent);
  color: var(--accent-ink);
  font-family: var(--mono);
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.18rem 0.4rem;
  border: 1.5px solid var(--ink);
  border-radius: 2px;
  z-index: 2;
}
.prog-card .status-stamp {
  position: absolute;
  bottom: 0.4rem;
  left: 0.4rem;
  font-family: var(--mono);
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 0.15rem 0.35rem;
  border: 1.5px solid var(--ink);
  background: var(--panel);
  z-index: 2;
}
.prog-card.status-active .status-stamp { background: var(--blue-bg); color: var(--blue); }
.prog-card.status-finished .status-stamp { background: var(--green-bg); color: var(--green); }
.prog-card.status-dropped .status-stamp { background: var(--red-bg); color: var(--red); }
.prog-card.status-ignored .status-stamp { background: var(--paper-2); color: var(--muted); }
.prog-card .body {
  padding: 0.55rem 0.6rem 0.6rem;
  /*
   * Three fixed bands from the top so season rails align across cards:
   * head (title/pos/total) · season chips · footer (status/type/logs)
   */
  display: grid;
  grid-template-rows: 4.7rem 3.1rem auto;
  gap: 0.35rem;
  flex: 1 1 auto;
  border-left: 4px solid transparent;
  margin-left: 0;
  min-height: 0;
}
.prog-card .card-head {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}
.prog-card .ctitle, .prog-title {
  font-weight: 700;
  font-size: 0.9rem;
  line-height: 1.25;
  color: var(--ink);
  cursor: text;
  border-radius: 2px;
  padding: 0.05rem 0.1rem;
  margin: 0;
  height: calc(1.25em * 2);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  word-break: break-word;
}
.prog-title { font-size: 1.05rem; margin-bottom: 0.15rem; }
.prog-card .ctitle:hover, .prog-title:hover {
  background: var(--paper-2);
  outline: 1px dashed var(--line-strong);
}
.prog-title-input, .prog-card .prog-title-input {
  width: 100%;
  font: inherit;
  font-weight: 700;
  font-size: inherit;
  line-height: 1.25;
  color: var(--ink);
  border: 1px solid var(--accent);
  background: #fff;
  border-radius: 2px;
  padding: 0.15rem 0.3rem;
  margin: 0 0 0.15rem;
}
.prog-card .cpos {
  font-family: var(--mono);
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--accent);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.2;
  min-height: 1.2em;
  font-variant-numeric: tabular-nums;
}
.prog-card .ctotal {
  font-size: 0.7rem;
  color: var(--muted);
  font-family: var(--mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.2;
  min-height: 1.2em;
  font-variant-numeric: tabular-nums;
}
.prog-card .ctotal:empty {
  visibility: hidden;
}
/* Footer: two tidy rows — never mash selects + links into one overflow line */
.prog-card .cmeta {
  font-size: 0.68rem;
  color: var(--faint);
  margin-top: 0;
  padding-top: 0.35rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  border-top: 1px solid var(--line);
  min-width: 0;
}
.prog-card .cmeta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.3rem;
  min-width: 0;
}
.prog-card .cmeta .clog {
  font-family: var(--mono);
  font-weight: 700;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.prog-card .cmeta .prog-status-select,
.prog-card .cmeta .prog-type-select {
  flex: 1 1 auto;
  max-width: none;
  min-width: 0;
  width: auto;
  font-size: 0.65rem;
  padding: 0.2rem 1.1rem 0.2rem 0.3rem;
  min-height: 1.7rem;
}
.prog-card .btn-resync-tadoku {
  flex: 0 0 auto;
  min-width: 1.7rem;
  padding: 0.2rem 0.4rem;
  font-size: 0.72rem;
  line-height: 1;
  margin: 0;
}
.prog-card .btn-fix-meta {
  width: auto;
  margin: 0;
  padding: 0.2rem 0.4rem;
  font-size: 0.65rem;
}

/* List as dense shelf ledger */
.prog-list {
  border: 2.5px solid var(--ink);
  background: var(--panel);
  box-shadow: 3px 3px 0 rgba(20,17,14,0.08);
}
.prog-row {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr) minmax(11rem, 13rem);
  gap: 0.85rem;
  align-items: start;
  padding: 0.7rem 0.9rem 0.7rem 1rem;
  border-bottom: 1px solid var(--line);
  position: relative;
  cursor: default;
  border-left: 5px solid var(--line-strong);
}
.prog-row:last-child { border-bottom: 0; }
.prog-row:hover { background: var(--paper-2); }
.prog-row.status-active { border-left-color: var(--blue); }
.prog-row.status-finished { border-left-color: var(--green); }
.prog-row.status-dropped { border-left-color: var(--red); }
.prog-row.status-ignored { border-left-color: var(--muted); opacity: 0.78; }
.prog-thumb {
  width: 56px;
  height: 78px;
  border: 2px solid var(--ink);
  background: var(--paper-2);
  object-fit: cover;
  display: block;
}
.prog-thumb.placeholder {
  display: grid;
  place-items: center;
  font-size: 0.62rem;
  font-weight: 700;
  color: var(--muted);
  text-align: center;
  padding: 0.2rem;
  text-transform: uppercase;
  font-family: var(--mono);
}
.prog-main { min-width: 0; }
.prog-meta {
  font-size: 0.78rem;
  color: var(--muted);
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem 0.65rem;
  align-items: center;
}
.prog-side {
  text-align: right;
  min-width: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.2rem;
}
.prog-current {
  font-family: var(--mono);
  font-weight: 700;
  font-size: 1.05rem;
  color: var(--ink);
}
.prog-total {
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 0;
  font-family: var(--mono);
}
.prog-bar {
  margin-top: 0.15rem;
  height: 5px;
  background: var(--line);
  border-radius: 1px;
  overflow: hidden;
  max-width: none;
  width: 100%;
  margin-left: 0;
  border: 1px solid var(--line-strong);
}
.prog-bar > i {
  display: block;
  height: 100%;
  background: var(--accent);
}
.prog-links {
  margin-top: 0.3rem;
  font-size: 0.72rem;
}
.prog-links a { margin-left: 0.4rem; }

.prog-type-select {
  appearance: none;
  font: inherit;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--blue);
  background: var(--blue-bg);
  border: 1px solid var(--line-strong);
  border-radius: 2px;
  padding: 0.15rem 1.15rem 0.15rem 0.35rem;
  cursor: pointer;
  background-image: linear-gradient(45deg, transparent 50%, var(--blue) 50%),
    linear-gradient(135deg, var(--blue) 50%, transparent 50%);
  background-position: calc(100% - 8px) 55%, calc(100% - 4px) 55%;
  background-size: 4px 4px, 4px 4px;
  background-repeat: no-repeat;
  max-width: 7.5rem;
}
.prog-type-select:hover { border-color: var(--blue); }
.prog-type-select:focus { outline: none; }
.prog-type-select:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.prog-status-select {
  appearance: none;
  font: inherit;
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  border: 1.5px solid var(--ink);
  border-radius: 2px;
  padding: 0.15rem 1.15rem 0.15rem 0.35rem;
  cursor: pointer;
  background-color: var(--panel);
  background-image: linear-gradient(45deg, transparent 50%, var(--muted) 50%),
    linear-gradient(135deg, var(--muted) 50%, transparent 50%);
  background-position: calc(100% - 8px) 55%, calc(100% - 4px) 55%;
  background-size: 4px 4px, 4px 4px;
  background-repeat: no-repeat;
  max-width: 6.5rem;
  color: var(--ink);
}
.prog-status-select.status-active {
  color: var(--blue);
  background-color: var(--blue-bg);
  border-color: var(--blue);
}
.prog-status-select.status-finished {
  color: var(--green);
  background-color: var(--green-bg);
  border-color: var(--green);
}
.prog-status-select.status-dropped {
  color: var(--red);
  background-color: var(--red-bg);
  border-color: var(--red);
}
.prog-status-select.status-ignored {
  color: var(--muted);
  background-color: var(--paper-2);
  border-color: var(--muted);
}

/* Selection / merge mode */
.prog-row.selected, .prog-card.selected {
  outline: 3px solid var(--accent);
  outline-offset: 2px;
  background: #fff6ef;
  z-index: 1;
}
.page-progress.merge-mode .prog-card:not(.selected),
.page-progress.merge-mode .prog-row:not(.selected) {
  opacity: 0.55;
}
.page-progress.merge-mode .prog-card.selected,
.page-progress.merge-mode .prog-row.selected {
  opacity: 1;
}
.prog-check {
  position: absolute;
  top: 0.4rem;
  left: 0.55rem;
  z-index: 4;
  width: 1.15rem;
  height: 1.15rem;
  accent-color: var(--accent);
  cursor: pointer;
}
.prog-row .prog-check { top: 0.55rem; left: 0.55rem; }
.btn-merge-into {
  appearance: none;
  font: inherit;
  font-size: 0.75rem;
  font-weight: 700;
  padding: 0.35rem 0.55rem;
  border: 2px solid var(--ink);
  background: var(--blue);
  color: #fff;
  cursor: pointer;
  border-radius: 2px;
  margin-top: 0.4rem;
  width: 100%;
  min-height: 2rem;
}
.btn-merge-into:hover { filter: brightness(1.08); }
.btn-merge-into:disabled { opacity: 0.5; cursor: not-allowed; }
.prog-row .btn-merge-into {
  width: auto;
  margin-top: 0;
  margin-left: 0.35rem;
}

/* Toast */
.sel-toast {
  position: fixed;
  left: 50%;
  bottom: 1.15rem;
  transform: translateX(-50%);
  z-index: 40;
  display: none;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem 0.75rem;
  max-width: min(760px, calc(100vw - 1.5rem));
  padding: 0.75rem 1rem;
  border: 3px solid var(--ink);
  border-top: 4px solid var(--accent);
  background: var(--panel);
  box-shadow: 0 12px 32px rgba(20, 17, 14, 0.22);
}
.sel-toast.open { display: flex; }
.sel-toast .sel-count {
  font-family: var(--mono);
  font-weight: 700;
  font-size: 1.05rem;
  color: var(--ink);
}
.sel-toast .hint {
  font-size: 0.82rem;
  color: var(--ink-soft);
  flex: 1 1 12rem;
  font-weight: 600;
}
.sel-toast button {
  appearance: none;
  font: inherit;
  font-size: 0.8rem;
  font-weight: 700;
  padding: 0.4rem 0.65rem;
  min-height: 2rem;
  border: 1px solid var(--ink);
  background: var(--panel-2);
  color: var(--ink);
  cursor: pointer;
  border-radius: 2px;
}
.sel-toast button:disabled { opacity: 0.55; cursor: wait; }
.sel-toast button.primary {
  background: var(--blue);
  border-color: var(--ink);
  color: #fff;
}

.prog-empty {
  padding: 2.5rem 1.25rem;
  text-align: center;
  border: 2.5px dashed var(--ink);
  color: var(--ink-soft);
  background: var(--panel);
  font-size: 0.95rem;
  box-shadow: 3px 3px 0 rgba(20,17,14,0.06);
}
.prog-empty b { color: var(--ink); font-size: 1.05rem; }
.prog-empty-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  justify-content: center;
  margin-top: 1rem;
}
.prog-empty-actions button.primary {
  background: var(--accent);
  color: var(--accent-ink);
  border: 1px solid #8f3f14;
  font-weight: 700;
  padding: 0.5rem 1rem;
  min-height: 2.25rem;
  cursor: pointer;
}

/* Bulk status in selection toast */
.sel-toast .bulk-status {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  align-items: center;
}
.sel-toast .bulk-status .bulk-label {
  font-family: var(--mono);
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin-right: 0.15rem;
}
.sel-toast button.st-active {
  background: var(--blue-bg);
  color: var(--blue);
  border-color: var(--blue);
}
.sel-toast button.st-finished {
  background: var(--green-bg);
  color: var(--green);
  border-color: var(--green);
}
.sel-toast button.st-dropped {
  background: var(--red-bg);
  color: var(--red);
  border-color: var(--red);
}
.sel-toast button.st-ignored {
  background: var(--paper-2);
  color: var(--muted);
  border-color: var(--muted);
}
.prog-card .cmeta a.logs-link {
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--blue);
  text-decoration: none;
  margin-left: 0.15rem;
}
.prog-card .cmeta a.logs-link:hover { text-decoration: underline; }

/* ── Needs user input (manual cover / length) ── */
.prog-needs {
  margin: 0 0 0.85rem;
  border: 2.5px solid var(--ink);
  background: var(--panel);
  box-shadow: 3px 3px 0 rgba(20, 17, 14, 0.08);
}
.prog-needs[hidden] { display: none !important; }
.prog-needs > summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.75rem;
  padding: 0.65rem 0.9rem;
  font-family: var(--mono);
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  background: var(--panel-2);
  border-bottom: 1px solid transparent;
  user-select: none;
}
.prog-needs > summary::-webkit-details-marker { display: none; }
.prog-needs[open] > summary {
  border-bottom: 1px solid var(--line-strong);
}
.prog-needs .needs-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.5rem;
  padding: 0.05rem 0.4rem;
  background: var(--accent);
  color: var(--accent-ink);
  border: 1px solid #8f3f14;
  font-size: 0.75rem;
}
.prog-needs .needs-sub {
  font-weight: 600;
  text-transform: none;
  letter-spacing: 0;
  color: var(--muted);
  font-family: var(--sans);
  font-size: 0.82rem;
}
.prog-needs-body {
  padding: 0.65rem 0.85rem 0.85rem;
}
.prog-needs-intro {
  margin: 0 0 0.65rem;
  font-size: 0.84rem;
  color: var(--ink-soft);
  line-height: 1.45;
}
.prog-needs-list {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.needs-card {
  border: 1.5px solid var(--line-strong);
  background: var(--panel);
  padding: 0.55rem 0.65rem;
}
.needs-card.is-open {
  border-color: var(--ink);
  box-shadow: 2px 2px 0 rgba(20, 17, 14, 0.08);
}
.needs-head {
  display: grid;
  grid-template-columns: 40px 1fr auto;
  gap: 0.55rem;
  align-items: center;
}
.needs-thumb {
  width: 40px;
  height: 56px;
  object-fit: cover;
  border: 1px solid var(--ink);
  background: var(--panel-2);
}
.needs-thumb.ph {
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--mono);
  font-size: 0.55rem;
  font-weight: 700;
  text-align: center;
  color: var(--muted);
  padding: 0.15rem;
  line-height: 1.15;
}
.needs-title {
  font-weight: 700;
  font-size: 0.95rem;
  color: var(--ink);
  line-height: 1.25;
}
.needs-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-top: 0.2rem;
}
.needs-tag {
  font-family: var(--mono);
  font-size: 0.62rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.1rem 0.35rem;
  border: 1px solid var(--line-strong);
  color: var(--muted);
  background: var(--panel-2);
}
.needs-tag.bad {
  color: var(--red);
  border-color: var(--red);
  background: var(--red-bg);
}
.needs-meta-line {
  font-size: 0.72rem;
  color: var(--faint);
  margin-top: 0.15rem;
  font-family: var(--mono);
}
.needs-actions {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  align-items: stretch;
}
.needs-actions button {
  appearance: none;
  font: inherit;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.35rem 0.5rem;
  min-height: 1.85rem;
  border: 1.5px solid var(--ink);
  background: var(--panel-2);
  color: var(--ink);
  cursor: pointer;
  border-radius: 2px;
  white-space: nowrap;
}
.needs-actions button.primary {
  background: var(--blue);
  color: #fff;
}
.needs-actions button:disabled { opacity: 0.5; cursor: wait; }
.needs-form {
  margin-top: 0.65rem;
  padding-top: 0.65rem;
  border-top: 1px dashed var(--line-strong);
  display: none;
}
.needs-card.is-open .needs-form { display: block; }
.needs-form .hints {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin: 0 0 0.55rem;
}
.needs-form .hints a {
  font-family: var(--mono);
  font-size: 0.68rem;
  font-weight: 700;
  padding: 0.2rem 0.45rem;
  border: 1px solid var(--line-strong);
  color: var(--blue);
  text-decoration: none;
  background: var(--panel-2);
}
.needs-form .hints a:hover { border-color: var(--blue); }
.needs-form .row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.45rem;
  margin-bottom: 0.45rem;
}
@media (min-width: 640px) {
  .needs-form .row.two { grid-template-columns: 1fr 1fr; }
  .needs-form .row.three { grid-template-columns: 1fr 1fr 1fr; }
}
.needs-form label {
  display: block;
  font-family: var(--mono);
  font-size: 0.62rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin-bottom: 0.15rem;
}
.needs-form input, .needs-form select {
  width: 100%;
  font: inherit;
  font-size: 0.85rem;
  padding: 0.4rem 0.5rem;
  border: 1.5px solid var(--ink);
  background: var(--panel);
  color: var(--ink);
  border-radius: 2px;
  min-height: 2.1rem;
}
.needs-form .form-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.35rem;
  align-items: center;
}
.needs-form .form-actions button.primary {
  background: var(--accent);
  color: var(--accent-ink);
  border: 1px solid #8f3f14;
  font-weight: 700;
  padding: 0.45rem 0.85rem;
  min-height: 2.15rem;
  cursor: pointer;
}
.needs-form .form-hint {
  font-size: 0.75rem;
  color: var(--faint);
  flex: 1 1 12rem;
}
.needs-form .form-msg {
  font-size: 0.8rem;
  font-weight: 600;
  min-height: 1.2em;
  margin-top: 0.35rem;
}
.needs-form .form-msg.ok { color: var(--green); }
.needs-form .form-msg.err { color: var(--red); }
.btn-resync-tadoku {
  appearance: none;
  font: inherit;
  font-size: 0.68rem;
  font-weight: 700;
  padding: 0.2rem 0.45rem;
  border: 1.5px solid var(--ink);
  background: var(--panel-2);
  color: var(--ink);
  cursor: pointer;
  border-radius: 2px;
  font-family: var(--mono);
  letter-spacing: 0.02em;
}
.btn-resync-tadoku:hover { background: var(--paper-2); }
.prog-card .btn-resync-tadoku {
  margin-left: 0.25rem;
  padding: 0.12rem 0.35rem;
  font-size: 0.62rem;
}
.prog-card .btn-fix-meta,
.prog-row .btn-fix-meta {
  appearance: none;
  font: inherit;
  font-size: 0.68rem;
  font-weight: 700;
  padding: 0.2rem 0.4rem;
  border: 1px solid var(--accent);
  background: var(--accent);
  color: var(--accent-ink);
  cursor: pointer;
  border-radius: 2px;
  margin-left: 0.25rem;
}
/* Season progress chips — compact by default (list + card) */
.season-rail {
  display: flex;
  flex-wrap: wrap;
  gap: 0.28rem;
  width: 100%;
  margin-top: 0.35rem;
  align-items: flex-start;
  min-width: 0;
}
.season-chip {
  display: inline-flex;
  flex-direction: column;
  gap: 0.1rem;
  flex: 0 0 auto;
  width: auto;
  min-width: 3.4rem;
  max-width: 5.5rem;
  height: auto;
  padding: 0.28rem 0.35rem 0.3rem;
  border: 2px solid var(--ink);
  background: var(--panel);
  font-family: var(--mono);
  line-height: 1.1;
  box-shadow: 2px 2px 0 rgba(20, 17, 14, 0.08);
  box-sizing: border-box;
}
.season-chip .sl {
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--muted);
  white-space: nowrap;
}
.season-chip .sv {
  font-size: 0.72rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--ink);
  white-space: nowrap;
}
.season-chip .sbar {
  height: 3px;
  background: var(--line-strong);
  border-radius: 1px;
  overflow: hidden;
  margin-top: 0.06rem;
  flex-shrink: 0;
}
.season-chip .sbar > i {
  display: block;
  height: 100%;
  background: var(--blue);
  min-width: 0;
}
.season-chip.is-done {
  border-color: var(--green);
  background: var(--green-bg);
}
.season-chip.is-done .sv { color: var(--green); }
.season-chip.is-done .sl { color: var(--green); }
.season-chip.is-done .sbar > i { background: var(--green); }
.season-chip.is-current:not(.is-done) {
  border-color: var(--ink);
  box-shadow: 1px 1px 0 rgba(20,17,14,0.12);
}
.season-chip.is-empty {
  opacity: 0.55;
  border-style: dashed;
}
.season-chip.is-more {
  align-items: center;
  justify-content: center;
  text-align: center;
  border-style: dashed;
  opacity: 0.85;
  min-width: 2.6rem;
}
.season-slot {
  display: block;
  width: 100%;
  min-width: 0;
}
.prog-row .season-slot:empty { display: none; }
.prog-row .season-rail { margin-top: 0.35rem; }

/* Card: one fixed-height season band; chips share width in a single row */
.prog-card .season-slot {
  margin: 0;
  height: 3.1rem;
  min-height: 3.1rem;
  max-height: 3.1rem;
  overflow: hidden;
  box-sizing: border-box;
}
.prog-card .season-slot.is-empty {
  visibility: hidden;
}
.prog-card .season-rail {
  display: flex;
  flex-wrap: nowrap;
  align-items: stretch;
  gap: 0.2rem;
  margin: 0;
  height: 100%;
  width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
  -webkit-overflow-scrolling: touch;
}
.prog-card .season-rail::-webkit-scrollbar { height: 3px; }
.prog-card .season-rail::-webkit-scrollbar-thumb {
  background: var(--line-strong);
  border-radius: 2px;
}
.prog-card .season-chip {
  flex: 1 1 0;
  min-width: 2.5rem;
  max-width: none;
  height: 100%;
  max-height: 100%;
  width: auto;
  padding: 0.2rem 0.22rem 0.22rem;
  justify-content: space-between;
}
.prog-card .season-rail.is-crowded .season-chip {
  flex: 1 0 2.45rem;
  min-width: 2.45rem;
}
.prog-card .season-chip .sl { font-size: 0.55rem; }
.prog-card .season-chip .sv { font-size: 0.68rem; }
.prog-card .season-chip .sbar { margin-top: auto; }
.season-hint {
  font-size: 0.65rem;
  color: var(--muted);
  margin-top: 0;
  font-family: var(--mono);
  font-weight: 600;
  line-height: 1.2;
}
.prog-row .prog-thumb,
.prog-row .prog-thumb.placeholder {
  align-self: center;
}
.prog-side .season-rail {
  margin-left: 0;
  width: 100%;
}
@media (max-width: 640px) {
  .prog-side { text-align: left; }
}

@media (max-width: 640px) {
  .prog-row { grid-template-columns: 48px 1fr; }
  .prog-side { grid-column: 2; text-align: left; }
  .prog-bar { margin-left: 0; }
  .prog-thumb { width: 48px; height: 68px; }
  .prog-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 0.75rem; }
  .needs-head { grid-template-columns: 40px 1fr; }
  .needs-actions { grid-column: 1 / -1; flex-direction: row; }
}
"""

PROGRESS_JS = r"""
const MODE_KEY = 'progress.displayMode';
// YouTube stays on its own tab; never mixed into All
const EXCLUDE_FROM_ALL = new Set(['youtube']);
const CONTENT_TYPES = [
  'anime','show','manga','book','audiobook','visual_novel','game','movie','podcast','youtube','study','other'
];
const STATUS_KEY = 'progress.statusFilter';
const SORT_KEY = 'progress.sort';
const PROGRESS_STATUSES = [
  { key: 'active', label: 'Active' },
  { key: 'finished', label: 'Finished' },
  { key: 'dropped', label: 'Dropped' },
  { key: 'ignored', label: 'Ignored' },
];
const state = {
  items: [],
  contentTypes: {},
  statusCounts: { active: 0, finished: 0, dropped: 0, ignored: 0 },
  filter: '',
  statusFilter: (function(){
    try {
      const u = new URL(window.location.href);
      if (u.searchParams.has('status')) return u.searchParams.get('status') || '';
    } catch(e) {}
    const saved = localStorage.getItem(STATUS_KEY);
    if (saved !== null) return saved;
    return '__auto_active__'; // resolve after first load
  })(),
  q: '',
  sort: (function(){
    const s = localStorage.getItem(SORT_KEY) || 'last_logged';
    return (s === 'title') ? 'title' : 'last_logged';
  })(),
  mode: localStorage.getItem(MODE_KEY) || 'grid',
  bust: Date.now(),
  busy: false,
  selected: new Set(),
  needsOpenKey: '',
};

function $(id) { return document.getElementById(id); }

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

function setMsg(text, kind) {
  const el = $('prog-msg');
  if (!el) return;
  el.textContent = text || '';
  el.className = 'prog-msg' + (kind ? ' ' + kind : '');
}

function setBusy(on) {
  state.busy = !!on;
  [
    'btn-pull', 'btn-enrich', 'btn-enrich-all', 'btn-normalize', 'btn-recover',
    'btn-toast-cover', 'btn-toast-clear', 'btn-toast-select-visible',
    'btn-toast-active', 'btn-toast-finished', 'btn-toast-dropped', 'btn-toast-ignored',
    'prog-sort',
  ].forEach(id => {
    const b = $(id);
    if (b) b.disabled = !!on;
  });
  document.querySelectorAll('.btn-merge-into').forEach(b => { b.disabled = !!on; });
  // Lock facets during network ops so filters/edits don't race a re-render
  const q = $('prog-q');
  if (q) q.disabled = !!on;
  document.querySelectorAll('.prog-tab, .status-chip, .mode-toggle button, .prog-pulse-cell').forEach(el => {
    if (on) el.setAttribute('aria-disabled', 'true');
    else el.removeAttribute('aria-disabled');
  });
  document.querySelectorAll('.prog-type-select, .prog-status-select, .prog-check').forEach(el => {
    el.disabled = !!on;
  });
}

/** Apply a /api/progress (or nested progress) payload and re-render in place. */
function applyProgress(data, { quiet, keepSelection } = {}) {
  if (!data) return;
  state.items = data.items || [];
  state.contentTypes = data.content_types || {};
  state.statusCounts = data.status_counts || { active: 0, finished: 0, dropped: 0, ignored: 0 };
  state.bust = Date.now();
  if (!keepSelection) {
    const valid = new Set(state.items.map(i => i.series_key));
    for (const k of [...state.selected]) {
      if (!valid.has(k)) state.selected.delete(k);
    }
  }
  // Smart default: Active shelf when library has active works (first load only)
  if (state.statusFilter === '__auto_active__') {
    const ac = state.statusCounts.active || 0;
    state.statusFilter = ac > 0 ? 'active' : '';
    try { localStorage.setItem(STATUS_KEY, state.statusFilter); } catch (e) {}
  }
  renderPulse();
  renderTabs();
  renderStatusFilters();
  renderNeeds();
  renderItems();
  if (!quiet) {
    const n = filteredItems().length;
    setMsg(`${n} work${n === 1 ? '' : 's'} shown`, 'ok');
  }
}
function renderPulse() {
  const host = document.getElementById('prog-pulse');
  if (!host) return;
  // Same scope as status chips (type-filtered, YouTube excluded from All)
  const sc = statusCountsForType();
  const scope = state.filter
    ? typeLabel(state.filter)
    : 'all types (excl. YouTube)';
  const cells = [
    { key: 'active', label: 'Active', n: sc.active || 0, sub: scope },
    { key: 'finished', label: 'Finished', n: sc.finished || 0, sub: scope },
    { key: 'dropped', label: 'Dropped', n: sc.dropped || 0, sub: scope },
  ];
  host.innerHTML = cells.map(c => {
    const on = c.n > 0 ? ' has-work' : '';
    const sel = state.statusFilter === c.key ? ' is-selected' : '';
    const pressed = state.statusFilter === c.key ? 'true' : 'false';
    return `<div class="prog-pulse-cell st-${c.key}${on}${sel}" data-pulse="${c.key}" role="button" tabindex="0" aria-pressed="${pressed}" title="Filter: ${c.label} · ${scope}">
      <div class="k">${c.label}</div>
      <div class="v">${c.n}</div>
      <div class="s">${c.sub}</div>
    </div>`;
  }).join('');
  host.querySelectorAll('.prog-pulse-cell').forEach(el => {
    const go = () => {
      if (state.busy) return;
      const key = el.getAttribute('data-pulse') || '';
      // Toggle off if already selected (same as re-clicking an on chip)
      state.statusFilter = state.statusFilter === key ? '' : key;
      try { localStorage.setItem(STATUS_KEY, state.statusFilter); } catch (e) {}
      syncUrl();
      renderPulse();
      renderStatusFilters();
      renderItems();
    };
    el.addEventListener('click', go);
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
    });
  });
}

function coverSrc(item) {
  const m = item.metadata || {};
  const raw = m.cover_local || m.cover_url || '';
  if (!raw) return '';
  // Bust browser cache after enrich so new local covers appear immediately
  const sep = raw.includes('?') ? '&' : '?';
  return raw + sep + 'v=' + state.bust;
}

function typeLabel(ct) {
  const map = {
    anime: 'Anime', show: 'Show', manga: 'Manga', book: 'Book',
    audiobook: 'Audiobook', visual_novel: 'VN', vn: 'VN', youtube: 'YouTube',
    game: 'Game', podcast: 'Podcast', study: 'Study', other: 'Other', movie: 'Movie',
  };
  return map[ct] || (ct || 'other');
}

function statusLabel(st) {
  const map = {
    active: 'Active', finished: 'Finished', dropped: 'Dropped', ignored: 'Ignored',
  };
  return map[st] || 'Active';
}

function normStatus(st) {
  const s = (st || 'active').toLowerCase();
  if (s === 'unfinished' || s === 'watching') return 'active';
  if (s === 'ignore' || s === 'hidden' || s === 'hide') return 'ignored';
  if (['active', 'finished', 'dropped', 'ignored'].includes(s)) return s;
  return 'active';
}

function allCount(types) {
  return Object.entries(types || {})
    .filter(([k]) => !EXCLUDE_FROM_ALL.has(k))
    .reduce((s, [, n]) => s + n, 0);
}

function renderTabs() {
  const host = $('prog-tabs');
  if (!host) return;
  const types = state.contentTypes || {};
  const keys = Object.keys(types).sort((a, b) => types[b] - types[a] || a.localeCompare(b));
  let html = `<button type="button" role="tab" class="prog-tab ${!state.filter ? 'active' : ''}" data-ct="" aria-selected="${!state.filter ? 'true' : 'false'}">All<span class="tab-count">${allCount(types)}</span></button>`;
  for (const ct of keys) {
    const on = state.filter === ct;
    html += `<button type="button" role="tab" class="prog-tab ${on ? 'active' : ''}" data-ct="${esc(ct)}" aria-selected="${on ? 'true' : 'false'}">${esc(typeLabel(ct))}<span class="tab-count">${types[ct]}</span></button>`;
  }
  host.innerHTML = html;
  host.querySelectorAll('.prog-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      if (state.busy) return;
      state.filter = btn.dataset.ct || '';
      syncUrl();
      renderPulse();
      renderTabs();
      renderStatusFilters();
      renderFilterNote();
      renderItems();
    });
  });
  renderFilterNote();
}

function renderFilterNote() {
  const note = $('prog-filter-note');
  if (!note) return;
  // Explain YouTube exclusion when viewing All (not the YouTube tab)
  if (!state.filter) {
    const ytN = (state.contentTypes || {}).youtube || 0;
    if (ytN > 0) {
      note.hidden = false;
      note.textContent = `YouTube (${ytN}) is under its own tab — not included in All.`;
      return;
    }
  }
  note.hidden = true;
  note.textContent = '';
}

function filteredItems() {
  let items = state.items.slice();
  if (state.filter) {
    items = items.filter(i => (i.content_type || '') === state.filter);
  } else {
    items = items.filter(i => !EXCLUDE_FROM_ALL.has(i.content_type || ''));
  }
  if (state.statusFilter) {
    const want = normStatus(state.statusFilter);
    items = items.filter(i => normStatus(i.progress_status) === want);
  } else {
    // "All" = library shelf only — ignored works stay hidden until filtered
    items = items.filter(i => normStatus(i.progress_status) !== 'ignored');
  }
  const q = (state.q || '').trim().toLowerCase();
  if (q) {
    items = items.filter(i =>
      (i.title || '').toLowerCase().includes(q) ||
      (i.series_key || '').toLowerCase().includes(q)
    );
  }
  // Server order is last_logged desc; re-sort client-side when needed
  if (state.sort === 'title') {
    items.sort((a, b) =>
      String(a.title || '').localeCompare(String(b.title || ''), undefined, {
        sensitivity: 'base',
      })
    );
  } else {
    // last_logged desc (stable with title tiebreak)
    items.sort((a, b) => {
      const la = a.last_logged || '';
      const lb = b.last_logged || '';
      if (la !== lb) return la < lb ? 1 : -1;
      return String(a.title || '').localeCompare(String(b.title || ''), undefined, {
        sensitivity: 'base',
      });
    });
  }
  return items;
}

/** Works the auto pipeline cannot finish (cover / length). */
function needsUserItems() {
  return (state.items || []).filter(i => {
    if (EXCLUDE_FROM_ALL.has(i.content_type || '')) return false;
    if (normStatus(i.progress_status) === 'ignored') return false;
    return !!i.needs_user_input;
  });
}

function issueLabels(issues) {
  const map = {
    no_cover: 'No cover',
    no_length: 'No total length',
    lookup_failed: 'Auto lookup failed',
    no_season_totals: 'Season totals needed',
  };
  return (issues || []).map(k => map[k] || k);
}

const UNIT_LABEL_OPTS = [
  'episodes', 'volumes', 'chapters', 'parts', 'routes', 'minutes', 'characters', 'pages',
];

function formatSeasonTotalsInput(item) {
  const st = item.season_totals || (item.metadata && item.metadata.season_totals) || {};
  const keys = Object.keys(st).sort((a, b) => Number(a) - Number(b));
  if (!keys.length) return '';
  return keys.map(k => `${k}:${st[k]}`).join(', ');
}

function seasonDetailHtml(item) {
  const seasons = item.seasons || [];
  if (!seasons.length) return '';
  const rows = seasons.map(r => {
    const tot = r.total_episodes != null ? r.total_episodes : '—';
    const done = r.progress_episodes || r.episodes_logged || 0;
    const pct = r.percent_complete != null ? Math.round(r.percent_complete) + '%' : '—';
    return `<tr>
      <td>${esc(r.label)}</td>
      <td class="mono">${done}</td>
      <td class="mono">${tot}</td>
      <td class="mono">${r.max_episode != null ? r.max_episode : '—'}</td>
      <td class="mono">${pct}</td>
      <td class="mono">${r.log_count || 0}</td>
    </tr>`;
  }).join('');
  return `<div class="row" style="margin-top:0.35rem">
    <div>
      <label>Logged seasons</label>
      <div style="overflow:auto;border:1px solid var(--line-strong)">
        <table style="width:100%;border-collapse:collapse;font-size:0.78rem">
          <thead><tr style="text-align:left;font-family:var(--mono);font-size:0.62rem;text-transform:uppercase;color:var(--muted)">
            <th style="padding:0.3rem 0.4rem">Season</th>
            <th style="padding:0.3rem 0.4rem">Done</th>
            <th style="padding:0.3rem 0.4rem">Total</th>
            <th style="padding:0.3rem 0.4rem">Max ep</th>
            <th style="padding:0.3rem 0.4rem">%</th>
            <th style="padding:0.3rem 0.4rem">Logs</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  </div>`;
}

function needsFormHtml(item) {
  const m = item.metadata || {};
  const unitOpts = UNIT_LABEL_OPTS.map(u =>
    `<option value="${u}"${(m.total_units_label || item.total_units_label || '') === u ? ' selected' : ''}>${u}</option>`
  ).join('');
  const hints = (item.provider_hints || []).map(h =>
    `<a href="${esc(h.url)}" target="_blank" rel="noopener" title="Search ${esc(h.label)}">${esc(h.label)}</a>`
  ).join('');
  return `
    <div class="needs-form" data-needs-form="${esc(item.series_key)}">
      <p class="form-hint" style="margin:0 0 0.4rem">Paste a page from a provider below (or a direct image URL), then adjust totals if needed.</p>
      <div class="hints">${hints || '<span class="form-hint">No provider shortcuts for this type.</span>'}</div>
      <div class="row">
        <div>
          <label for="imp-${esc(item.series_key)}">Provider or image URL</label>
          <input id="imp-${esc(item.series_key)}" type="url" name="import_url" placeholder="https://anilist.co/anime/… · steam · tvmaze · mal · jiten · vndb…" value="${esc(m.external_url || '')}" autocomplete="off"/>
        </div>
      </div>
      <div class="row two">
        <div>
          <label>Cover image URL (optional override)</label>
          <input type="url" name="cover_url" placeholder="https://…/cover.jpg" value="" autocomplete="off"/>
        </div>
        <div>
          <label>Display title (optional)</label>
          <input type="text" name="title" placeholder="${esc(item.title || '')}" value="" autocomplete="off"/>
        </div>
      </div>
      <div class="row three">
        <div>
          <label>Total units (eps / vols)</label>
          <input type="number" name="total_units" min="0" step="1" placeholder="${m.total_units != null ? m.total_units : 'e.g. 12'}" value="${m.total_units != null ? m.total_units : ''}"/>
        </div>
        <div>
          <label>Unit type</label>
          <select name="total_units_label">${unitOpts}</select>
        </div>
        <div>
          <label>Total minutes</label>
          <input type="number" name="total_minutes" min="0" step="1" placeholder="${m.total_minutes != null ? m.total_minutes : 'runtime'}" value="${m.total_minutes != null ? m.total_minutes : ''}"/>
        </div>
      </div>
      <div class="row two">
        <div>
          <label>Total characters</label>
          <input type="number" name="total_characters" min="0" step="1" placeholder="${m.total_characters != null ? m.total_characters : 'for books / VN'}" value="${m.total_characters != null ? m.total_characters : ''}"/>
        </div>
        <div>
          <label>Category</label>
          <select name="content_type">${CONTENT_TYPES.map(ct =>
            `<option value="${ct}"${ct === (item.content_type || '') ? ' selected' : ''}>${esc(typeLabel(ct))}</option>`
          ).join('')}</select>
        </div>
      </div>
      <div class="row">
        <div>
          <label>Season episode counts (multi-season)</label>
          <input type="text" name="season_totals" placeholder="1:12, 2:13, 3:12" value="${esc(formatSeasonTotalsInput(item))}" autocomplete="off"/>
          <span class="form-hint" style="display:block;margin-top:0.2rem">Format <b>S#:eps</b> e.g. <code>1:12, 2:13</code>. Used for franchise % when flat totals are wrong. TVMaze import fills this automatically.</span>
        </div>
      </div>
      ${seasonDetailHtml(item)}
      <div class="form-actions">
        <button type="button" class="primary" data-needs-save="${esc(item.series_key)}">Save metadata</button>
        <button type="button" data-needs-import="${esc(item.series_key)}">Import URL only</button>
        <button type="button" data-needs-cancel="${esc(item.series_key)}">Close</button>
        <span class="form-hint">Supported: AniList, MAL, jiten, Steam, VNDB, TVMaze, TMDB, Open Library, Wikipedia, direct image</span>
      </div>
      <div class="form-msg" data-needs-msg="${esc(item.series_key)}" role="status"></div>
    </div>`;
}

function renderNeeds() {
  const host = $('prog-needs');
  if (!host) return;
  const items = needsUserItems();
  if (!items.length) {
    host.hidden = true;
    host.innerHTML = '';
    return;
  }
  host.hidden = false;
  const wasOpen = host.open;
  const openKey = state.needsOpenKey || '';
  host.innerHTML = `
    <summary>
      <span>Needs your input</span>
      <span class="needs-count">${items.length}</span>
      <span class="needs-sub">Missing cover or total length — paste a provider link or set fields manually</span>
    </summary>
    <div class="needs-body prog-needs-body">
      <p class="prog-needs-intro">Auto lookup could not finish these works. Open a provider search, copy the title’s page URL, paste it here — or type episode/volume/minute totals and a cover URL yourself.</p>
      <div class="prog-needs-list">${items.map(item => {
        const src = coverSrc(item);
        const thumb = src
          ? `<img class="needs-thumb" src="${esc(src)}" alt="" loading="lazy" referrerpolicy="no-referrer"/>`
          : `<div class="needs-thumb ph">${esc(typeLabel(item.content_type))}</div>`;
        const tags = issueLabels(item.meta_issues).map(t =>
          `<span class="needs-tag bad">${esc(t)}</span>`
        ).join('');
        const open = openKey === item.series_key ? ' is-open' : '';
        return `<div class="needs-card${open}" data-needs-key="${esc(item.series_key)}">
          <div class="needs-head">
            ${thumb}
            <div>
              <div class="needs-title">${esc(item.title)}</div>
              <div class="needs-tags">
                <span class="needs-tag">${esc(typeLabel(item.content_type))}</span>
                ${tags}
              </div>
              <div class="needs-meta-line">${esc(item.series_key)} · ${item.log_count} log${item.log_count === 1 ? '' : 's'}${item.current_display ? ' · ' + esc(item.current_display) : ''}</div>
            </div>
            <div class="needs-actions">
              <button type="button" class="primary" data-needs-toggle="${esc(item.series_key)}">${openKey === item.series_key ? 'Hide form' : 'Fix…'}</button>
              <button type="button" data-needs-refetch="${esc(item.series_key)}">Retry auto</button>
            </div>
          </div>
          ${needsFormHtml(item)}
        </div>`;
      }).join('')}</div>
    </div>`;
  // Keep expanded if user was working, or if few items
  host.open = wasOpen || items.length <= 6 || !!openKey;
  bindNeeds(host);
}

function bindNeeds(root) {
  root.querySelectorAll('[data-needs-toggle]').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.getAttribute('data-needs-toggle');
      state.needsOpenKey = state.needsOpenKey === key ? '' : key;
      renderNeeds();
    });
  });
  root.querySelectorAll('[data-needs-cancel]').forEach(btn => {
    btn.addEventListener('click', () => {
      state.needsOpenKey = '';
      renderNeeds();
    });
  });
  root.querySelectorAll('[data-needs-refetch]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const key = btn.getAttribute('data-needs-refetch');
      if (!key || state.busy) return;
      setBusy(true);
      setMsg('Retrying auto lookup…');
      try {
        await inlineFixup('refetch_cover', { series_keys: [key] });
        state.needsOpenKey = key;
        renderNeeds();
      } finally {
        setBusy(false);
      }
    });
  });
  root.querySelectorAll('[data-needs-save], [data-needs-import]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const key = btn.getAttribute('data-needs-save') || btn.getAttribute('data-needs-import');
      const importOnly = btn.hasAttribute('data-needs-import');
      if (!key || state.busy) return;
      const card = root.querySelector(`.needs-card[data-needs-key="${CSS.escape(key)}"]`);
      const form = card && card.querySelector('[data-needs-form]');
      const msg = root.querySelector(`[data-needs-msg="${CSS.escape(key)}"]`);
      if (!form) return;
      const val = (name) => {
        const el = form.querySelector(`[name="${name}"]`);
        return el ? (el.value || '').trim() : '';
      };
      const numOrNull = (name) => {
        const s = val(name);
        if (s === '') return null;
        const n = Number(s);
        return Number.isFinite(n) ? Math.round(n) : null;
      };
      const body = {
        action: 'set_metadata',
        series_keys: [key],
        content_type: val('content_type') || undefined,
      };
      const imp = val('import_url');
      if (imp) body.import_url = imp;
      if (!importOnly) {
        const cov = val('cover_url');
        if (cov) body.cover_url = cov;
        const title = val('title');
        if (title) body.title = title;
        const tu = numOrNull('total_units');
        if (tu != null) body.total_units = tu;
        const label = val('total_units_label');
        if (label) body.total_units_label = label;
        const tm = numOrNull('total_minutes');
        if (tm != null) body.total_minutes = tm;
        const tc = numOrNull('total_characters');
        if (tc != null) body.total_characters = tc;
        const st = val('season_totals');
        if (st) body.season_totals = st;
      }
      if (importOnly && !imp) {
        if (msg) { msg.textContent = 'Paste a provider URL first.'; msg.className = 'form-msg err'; }
        return;
      }
      if (!importOnly && !imp && !val('cover_url') && numOrNull('total_units') == null
          && numOrNull('total_minutes') == null && numOrNull('total_characters') == null
          && !val('title') && !val('season_totals')) {
        if (msg) { msg.textContent = 'Enter a URL and/or at least one field to save.'; msg.className = 'form-msg err'; }
        return;
      }
      setBusy(true);
      if (msg) { msg.textContent = importOnly ? 'Importing…' : 'Saving…'; msg.className = 'form-msg'; }
      try {
        const r = await fetch('/api/progress/fixup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok || data.ok === false) {
          const err = data.detail || data.error || ('HTTP ' + r.status);
          if (msg) { msg.textContent = typeof err === 'string' ? err : JSON.stringify(err); msg.className = 'form-msg err'; }
          setMsg('Metadata save failed', 'err');
          return;
        }
        if (data.progress) applyProgress(data.progress, { quiet: true, keepSelection: true });
        else await loadProgress({ quiet: true });
        const still = (state.items || []).find(i => i.series_key === key);
        if (still && still.needs_user_input) {
          state.needsOpenKey = key;
          if (msg) {
            msg.textContent = 'Saved — still missing ' + issueLabels(still.meta_issues).join(', ').toLowerCase() + '.';
            msg.className = 'form-msg ok';
          }
          renderNeeds();
        } else {
          state.needsOpenKey = '';
          setMsg('Metadata saved for ' + key, 'ok');
          renderNeeds();
        }
      } catch (e) {
        if (msg) { msg.textContent = e.message || String(e); msg.className = 'form-msg err'; }
        setMsg('Metadata save failed: ' + e.message, 'err');
      } finally {
        setBusy(false);
      }
    });
  });
}

function openNeedsFor(key) {
  state.needsOpenKey = key || '';
  const host = $('prog-needs');
  if (host) {
    host.hidden = false;
    host.open = true;
    renderNeeds();
    host.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

function logsHref(item) {
  const key = item.series_key || '';
  if (!key) return '/logs';
  return '/logs?series_key=' + encodeURIComponent(key);
}

function statusCountsForType() {
  /* Counts match the current type filter (not whole library) so chips stay honest */
  let items = state.items || [];
  if (state.filter) {
    items = items.filter(i => (i.content_type || '') === state.filter);
  } else {
    items = items.filter(i => !EXCLUDE_FROM_ALL.has(i.content_type || ''));
  }
  const counts = { active: 0, finished: 0, dropped: 0, ignored: 0 };
  for (const i of items) {
    const st = normStatus(i.progress_status);
    if (counts[st] != null) counts[st]++;
  }
  return counts;
}
function renderStatusFilters() {
  const host = $('status-filters');
  if (!host) return;
  const counts = statusCountsForType();
  // "All" is the library shelf (excludes ignored)
  const allN = (counts.active || 0) + (counts.finished || 0) + (counts.dropped || 0);
  const chips = [
    { key: '', label: 'All', cls: '', n: allN },
    { key: 'active', label: 'Active', cls: 'st-active', n: counts.active || 0 },
    { key: 'finished', label: 'Finished', cls: 'st-finished', n: counts.finished || 0 },
    { key: 'dropped', label: 'Dropped', cls: 'st-dropped', n: counts.dropped || 0 },
    { key: 'ignored', label: 'Ignored', cls: 'st-ignored', n: counts.ignored || 0 },
  ];
  host.innerHTML = `<span class="sf-label">Status</span>` + chips.map(c => {
    const on = state.statusFilter === c.key;
    return `<button type="button" class="status-chip ${c.cls}${on ? ' on' : ''}" data-st="${c.key}" aria-pressed="${on ? 'true' : 'false'}">${c.label}<span class="n">${c.n}</span></button>`;
  }).join('');
  host.querySelectorAll('.status-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      if (state.busy) return;
      state.statusFilter = btn.dataset.st || '';
      try { localStorage.setItem(STATUS_KEY, state.statusFilter); } catch (e) {}
      syncUrl();
      renderPulse();
      renderStatusFilters();
      renderItems();
    });
  });
}
function syncUrl() {
  try {
    const u = new URL(window.location.href);
    if (state.filter) u.searchParams.set('type', state.filter);
    else u.searchParams.delete('type');
    if (state.statusFilter) u.searchParams.set('status', state.statusFilter);
    else u.searchParams.delete('status');
    history.replaceState(null, '', u.pathname + u.search + u.hash);
  } catch (e) {}
}
function readUrlFilters() {
  try {
    const u = new URL(window.location.href);
    const t = u.searchParams.get('type');
    const s = u.searchParams.get('status');
    if (t) state.filter = t;
    if (s === 'active' || s === 'finished' || s === 'dropped' || s === '') {
      state.statusFilter = s || '';
    }
  } catch (e) {}
}

function progressBar(pct) {
  if (pct == null || isNaN(pct)) return '';
  const w = Math.max(0, Math.min(100, Number(pct)));
  return `<div class="prog-bar" title="${w}%"><i style="width:${w}%"></i></div>`;
}

/**
 * Short shelf labels — prefer structured fields over bloated display strings.
 * Season chips already show S1/S2 fill; don't repeat that in the position line.
 */
function cardPosition(item) {
  if (item.progress_label) return item.progress_label;
  let cur = (item.current_display || '').trim();
  if (!cur) return '—';
  // Drop legacy "S01E03 · S1 3/12 · S2 …" tails if any still arrive
  if (item.is_multi_season && cur.includes(' · S')) {
    cur = cur.split(' · ')[0];
  }
  return cur;
}

function cardTotal(item) {
  const td = (item.total_display || '').trim();
  if (!td) return ''; // omit "Total · ?" — unknown length is noise
  return td;
}

function cardTotalTitle(item) {
  return (item.total_display_detail || item.total_display || item.seasons_summary || '').trim();
}

function lastLoggedLabel(item) {
  const raw = item && item.last_logged;
  if (raw == null || raw === '') return '';
  const s = String(raw);
  // ISO-ish → YYYY-MM-DD
  const m = s.match(/(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : s.slice(0, 10);
}
function lastLoggedHtml(item, cls) {
  const d = lastLoggedLabel(item);
  if (!d) return '';
  return `<span class="mono faint ${cls || ''}">Last · ${esc(d)}</span>`;
}
function cardMetaHtml(item) {
  // Two rows: controls, then links — never one crushed nowrap line
  const needs = item.needs_user_input
    ? `<button type="button" class="btn-fix-meta" data-fix-meta="${esc(item.series_key)}">Fix</button>`
    : '';
  const last = lastLoggedHtml(item, 'clast');
  return `<div class="cmeta-row cmeta-controls">
      ${statusSelectHtml(item)}
      ${typeSelectHtml(item)}
    </div>
    <div class="cmeta-row cmeta-links">
      <span class="clog">${item.log_count} log${item.log_count === 1 ? '' : 's'}</span>
      ${last}
      <a class="logs-link" href="${esc(logsHref(item))}">logs</a>
      <button type="button" class="btn-resync-tadoku" data-resync="${esc(item.series_key)}" data-title="${esc(item.title || '')}" title="Resync this title from Tadoku">Resync</button>
      ${needs}
      <button type="button" class="btn-merge-into" data-merge-into="${esc(item.series_key)}" hidden>Merge into this</button>
    </div>`;
}

/**
 * Always returns exactly one `.season-slot` (possibly empty).
 * Empty slots still reserve height so grid cards align season bands.
 */
function seasonRailHtml(item) {
  const wrap = (inner, empty) =>
    `<div class="season-slot${empty ? ' is-empty' : ''}"${empty ? ' aria-hidden="true"' : ''}>${inner || ''}</div>`;

  let seasons = (item.seasons || []).slice();
  const mode = item.season_mode || '';
  const ct = (item.content_type || '');

  const chipBar = (pct) => {
    const w = pct != null && !isNaN(pct) ? Math.max(0, Math.min(100, Number(pct))) : 0;
    const title = pct != null && !isNaN(pct) ? Math.round(pct) + '%' : '';
    return `<span class="sbar"${title ? ` title="${title}"` : ''}><i style="width:${w}%"></i></span>`;
  };

  // Movies: single film chip
  if (ct === 'movie') {
    const pct = item.percent_complete;
    const done = pct != null && pct >= 99.5;
    const val = pct != null ? (Math.round(pct) + '%') : 'Film';
    return wrap(`<div class="season-rail" aria-label="Movie progress">
      <span class="season-chip${done ? ' is-done' : ' is-current'}" title="Movie · ${esc(val)}">
        <span class="sl">Film</span>
        <span class="sv">${esc(val)}</span>
        ${chipBar(pct)}
      </span>
    </div>`);
  }

  // Manga / book volume chip
  if (['manga', 'book'].includes(ct)) {
    const vol = item.progress_episode;
    const tot = (item.total_units_label === 'volumes' || item.total_units_label === 'chapters')
      ? item.total_units : null;
    if (vol == null && !tot) return wrap('', true);
    const done = vol != null ? vol : (item.episodes_logged || 0);
    const val = tot != null ? `${done}/${tot}` : `Vol ${done}`;
    const pct = tot ? Math.min(100, (100 * done) / tot) : null;
    return wrap(`<div class="season-rail" aria-label="Volume progress">
      <span class="season-chip${tot && done >= tot ? ' is-done' : ''} is-current" title="${esc(val)}">
        <span class="sl">Vol</span>
        <span class="sv">${esc(val)}</span>
        ${chipBar(pct)}
      </span>
    </div>`);
  }

  // Non-episode media: reserve empty slot for grid alignment
  if (['game', 'visual_novel', 'study', 'youtube', 'podcast'].includes(ct)) {
    return wrap('', true);
  }

  // Synthesize a chip when API seasons[] is empty but we have flat episode totals
  const flatEps = (item.total_units_label === 'episodes' || item.total_units_label === 'parts')
    ? item.total_units : null;
  if (!seasons.length && (item.progress_label || flatEps || item.episodes_logged)) {
    const done = item.episodes_logged
      || (item.progress_episode != null ? item.progress_episode : 0)
      || 0;
    if (done || flatEps) {
      seasons = [{
        season: item.progress_season,
        label: item.progress_season != null ? ('S' + item.progress_season) : 'Eps',
        progress_episodes: done,
        episodes_logged: item.episodes_logged || 0,
        total_episodes: flatEps,
        percent_complete: item.percent_complete,
        max_episode: item.progress_episode,
      }];
    }
  }

  const hasNumbered = seasons.some(r => r.season != null);
  let rows = seasons.filter(r => {
    if (r.season == null && hasNumbered) {
      return (r.episodes_logged || r.progress_episodes || 0) > 0;
    }
    return r.season != null
      || (r.episodes_logged || r.progress_episodes || r.total_episodes || r.max_episode);
  });
  rows.sort((a, b) => {
    const as = a.season == null ? 999 : a.season;
    const bs = b.season == null ? 999 : b.season;
    return as - bs;
  });
  if (!rows.length) return wrap('', true);

  const curS = item.progress_season;
  // Keep every season chip in the rail (S3 must not disappear). Cards use a
  // single flex row + equal chip share; 5+ seasons scroll horizontally.
  const MAX_INLINE = 6;
  const shown = rows.slice(0, MAX_INLINE);
  const hidden = rows.slice(MAX_INLINE);

  const chipFor = (r) => {
    const tot = r.total_episodes != null ? r.total_episodes : (
      (mode === 'single' || (rows.length === 1 && !item.is_multi_season)) && flatEps ? flatEps : null
    );
    let done = r.progress_episodes || r.episodes_logged || 0;
    if ((mode === 'single' || rows.length === 1) && r.max_episode != null) {
      done = Math.max(done, r.max_episode);
    }
    if (tot != null && done > tot) done = tot;
    const pct = r.percent_complete != null
      ? r.percent_complete
      : (tot ? Math.min(100, (100 * done) / tot) : null);
    const isDone = r.is_done || (tot != null && done >= tot);
    const doneCls = isDone ? ' is-done' : '';
    const emptyCls = (!done && !isDone && tot) ? ' is-empty' : '';
    const curCls = !isDone && ((curS != null && r.season === curS) || (rows.length === 1))
      ? ' is-current' : '';
    // Compact values for narrow multi-season chips: "3/12" not "3 ep"
    const val = tot != null ? `${done}/${tot}` : (done ? String(done) : '—');
    const tip = `${r.label}: ${tot != null ? done + '/' + tot : done + ' ep'}${pct != null ? ' · ' + Math.round(pct) + '%' : ''}`;
    return `<span class="season-chip${doneCls}${curCls}${emptyCls}" title="${esc(tip)}">
      <span class="sl">${esc(r.label)}</span>
      <span class="sv">${esc(val)}</span>
      ${chipBar(pct)}
    </span>`;
  };

  let chips = shown.map(chipFor).join('');
  if (hidden.length) {
    const tip = hidden.map(r => {
      const tot = r.total_episodes;
      const done = r.progress_episodes || r.episodes_logged || 0;
      return `${r.label} ${tot != null ? done + '/' + tot : done}`;
    }).join(' · ');
    chips += `<span class="season-chip is-more" title="${esc(tip)}">
      <span class="sl">more</span>
      <span class="sv">+${hidden.length}</span>
      ${chipBar(null)}
    </span>`;
  }
  if (!chips) return wrap('', true);
  const crowded = rows.length >= 4 ? ' is-crowded' : '';
  // Single child only — no external hints that steal vertical space / clip S3
  return wrap(
    `<div class="season-rail${crowded}" aria-label="Season progress (${rows.length} seasons)">${chips}</div>`
  );
}

function isSelected(key) {
  return state.selected.has(key);
}

function toggleSelect(key, on) {
  if (on == null) {
    if (state.selected.has(key)) state.selected.delete(key);
    else state.selected.add(key);
  } else if (on) state.selected.add(key);
  else state.selected.delete(key);
  syncSelectionUI();
}

function clearSelection() {
  state.selected.clear();
  syncSelectionUI();
}

function selectedItems() {
  return state.items.filter(i => state.selected.has(i.series_key));
}

function canOfferMergeInto(targetKey) {
  // Need at least one selected work that is not the target
  if (!state.selected.size) return false;
  if (state.selected.size === 1 && state.selected.has(targetKey)) return false;
  return true;
}

function syncSelectionUI() {
  document.querySelectorAll('[data-key]').forEach(el => {
    const key = el.getAttribute('data-key');
    const on = state.selected.has(key);
    el.classList.toggle('selected', on);
    const cb = el.querySelector('.prog-check');
    if (cb) cb.checked = on;
    const mergeBtn = el.querySelector('.btn-merge-into');
    if (mergeBtn) {
      mergeBtn.hidden = !canOfferMergeInto(key);
    }
  });
  const n = state.selected.size;
  const main = document.getElementById('main');
  if (main) main.classList.toggle('merge-mode', n > 0);
  const toast = $('sel-toast');
  if (toast) {
    toast.classList.toggle('open', n > 0);
    toast.setAttribute('aria-hidden', n > 0 ? 'false' : 'true');
    const c = $('toast-count');
    if (c) c.textContent = n + ' selected';
    const hint = $('toast-hint');
    if (hint) {
      if (n >= 2) {
        hint.textContent = 'Merge: click “Merge into this” on the work that should remain.';
      } else if (n === 1) {
        hint.textContent = 'Check another work to merge, or clear selection.';
      } else {
        hint.textContent = '';
      }
    }
  }
}

function typeSelectHtml(item) {
  const cur = item.content_type || 'other';
  const opts = CONTENT_TYPES.map(ct =>
    `<option value="${ct}"${ct === cur ? ' selected' : ''}>${esc(typeLabel(ct))}</option>`
  ).join('');
  return `<select class="prog-type-select" data-key="${esc(item.series_key)}" title="Change category" aria-label="Category for ${esc(item.title)}">${opts}</select>`;
}

function statusSelectHtml(item) {
  const cur = normStatus(item.progress_status);
  const opts = PROGRESS_STATUSES.map(s =>
    `<option value="${s.key}"${s.key === cur ? ' selected' : ''}>${s.label}</option>`
  ).join('');
  return `<select class="prog-status-select status-${cur}" data-key="${esc(item.series_key)}" title="Active / Finished / Dropped / Ignored (hide from shelf)" aria-label="Status for ${esc(item.title)}">${opts}</select>`;
}

function emptyLibraryHtml() {
  const hasAny = (state.items || []).length > 0;
  if (!hasAny) {
    return `<div class="prog-empty">
      <p><b>No works yet.</b> Pull logs from Tadoku or clear the Inbox so watches land here.</p>
      <div class="prog-empty-actions">
        <button type="button" class="primary" id="empty-pull">Pull from Tadoku</button>
        <a class="chip" href="/queue">Inbox</a>
        <a class="chip" href="/logs">Logs</a>
      </div>
    </div>`;
  }
  return `<div class="prog-empty">
    <p><b>Nothing matches these filters.</b></p>
    <div class="prog-empty-actions">
      <button type="button" class="secondary" id="empty-clear-filters">Show all status</button>
      <button type="button" class="secondary" id="empty-clear-type">All types</button>
    </div>
  </div>`;
}
function bindEmptyActions(root) {
  root.querySelector('#empty-pull')?.addEventListener('click', () => pullTadoku());
  root.querySelector('#empty-clear-filters')?.addEventListener('click', () => {
    state.statusFilter = '';
    try { localStorage.setItem(STATUS_KEY, ''); } catch (e) {}
    syncUrl();
    renderPulse();
    renderStatusFilters();
    renderItems();
  });
  root.querySelector('#empty-clear-type')?.addEventListener('click', () => {
    state.filter = '';
    syncUrl();
    renderPulse();
    renderTabs();
    renderStatusFilters();
    renderFilterNote();
    renderItems();
  });
}
function renderList(items) {
  if (!items.length) {
    return emptyLibraryHtml();
  }
  return `<div class="prog-list">${items.map(item => {
    const src = coverSrc(item);
    const thumb = src
      ? `<img class="prog-thumb" src="${esc(src)}" alt="" loading="lazy" referrerpolicy="no-referrer"/>`
      : `<div class="prog-thumb placeholder">${esc(typeLabel(item.content_type))}</div>`;
    const meta = item.metadata || {};
    const ext = meta.external_url
      ? `<a href="${esc(meta.external_url)}" target="_blank" rel="noopener">source</a>`
      : '';
    const logs = `<a href="${esc(logsHref(item))}">logs</a> · <span class="mono" style="font-size:0.7rem;color:var(--faint)">${esc(item.series_key)}</span>`;
    const sel = isSelected(item.series_key) ? ' selected' : '';
    const checked = isSelected(item.series_key) ? ' checked' : '';
    const st = normStatus(item.progress_status);
    return `<div class="prog-row${sel} status-${st}" data-key="${esc(item.series_key)}">
      <input type="checkbox" class="prog-check" data-key="${esc(item.series_key)}"${checked} aria-label="Select ${esc(item.title)}"/>
      ${thumb}
      <div class="prog-main">
        <div class="prog-title" data-edit-title="${esc(item.series_key)}" title="Click to rename">${esc(item.title)}</div>
        <div class="prog-meta">
          ${statusSelectHtml(item)}
          ${typeSelectHtml(item)}
          <span>${item.log_count} log${item.log_count === 1 ? '' : 's'}</span>
          ${lastLoggedHtml(item)}
          <span>${esc((item.sources || []).join(', '))}</span>
          ${item.score_estimate ? `<span>~${Number(item.score_estimate).toLocaleString(undefined,{maximumFractionDigits:1})} pts</span>` : ''}
        </div>
        <div class="prog-links">${logs}${ext ? ' · ' + ext : ''}
          <button type="button" class="btn-resync-tadoku" data-resync="${esc(item.series_key)}" data-title="${esc(item.title || '')}" title="Import missing Tadoku logs for this title">Resync Tadoku</button>
          ${item.needs_user_input ? `<button type="button" class="btn-fix-meta" data-fix-meta="${esc(item.series_key)}">Fix metadata</button>` : ''}
          <button type="button" class="btn-merge-into" data-merge-into="${esc(item.series_key)}" hidden>Merge into this</button>
        </div>
      </div>
      <div class="prog-side">
        <div class="prog-current">${esc(cardPosition(item))}</div>
        <div class="prog-total" title="${esc(cardTotalTitle(item))}">${cardTotal(item) ? 'of ' + esc(cardTotal(item)) : ''}</div>
        ${progressBar(item.percent_complete)}
        ${seasonRailHtml(item)}
      </div>
    </div>`;
  }).join('')}</div>`;
}

function renderGrid(items) {
  if (!items.length) {
    return emptyLibraryHtml();
  }
  return `<div class="prog-grid">${items.map(item => {
    const src = coverSrc(item);
    const cover = src
      ? `<img src="${esc(src)}" alt="" loading="lazy" referrerpolicy="no-referrer"/>`
      : `<div class="ph">${esc(typeLabel(item.content_type))}</div>`;
    const pct = item.percent_complete != null
      ? `<span class="pct-badge">${Math.round(item.percent_complete)}%</span>`
      : '';
    const sel = isSelected(item.series_key) ? ' selected' : '';
    const checked = isSelected(item.series_key) ? ' checked' : '';
    const st = normStatus(item.progress_status);
    return `<article class="prog-card${sel} status-${st}" data-key="${esc(item.series_key)}" title="${esc(item.series_key)}">
      <input type="checkbox" class="prog-check" data-key="${esc(item.series_key)}"${checked} aria-label="Select ${esc(item.title)}"/>
      <div class="cover-wrap">${cover}${pct}<span class="status-stamp">${esc(statusLabel(st))}</span></div>
      <div class="body">
        <div class="card-head">
          <div class="ctitle" data-edit-title="${esc(item.series_key)}" title="${esc(item.title)} · click to rename">${esc(item.title)}</div>
          <div class="cpos" title="${esc(item.current_display || item.progress_label || '')}">${esc(cardPosition(item))}</div>
          <div class="ctotal" title="${esc(cardTotalTitle(item))}">${cardTotal(item) ? esc(cardTotal(item)) : ''}</div>
        </div>
        ${seasonRailHtml(item)}
        <div class="cmeta">${cardMetaHtml(item)}</div>
      </div>
    </article>`;
  }).join('')}</div>`;
}

function bindItemClicks() {
  // Event delegation — one listener on the items host (survives re-render when rebound)
  const host = $('prog-items');
  if (!host || host.dataset.bound === '1') {
    // Still wire per-render for checkboxes after innerHTML replace
  }
  // Selection is checkbox-only (no cover/row click) so browsing never accidental-selects
  document.querySelectorAll('.prog-check').forEach(cb => {
    cb.addEventListener('click', (e) => e.stopPropagation());
    cb.addEventListener('change', (e) => {
      if (state.busy) {
        e.target.checked = !e.target.checked;
        return;
      }
      const key = e.target.getAttribute('data-key');
      toggleSelect(key, e.target.checked);
    });
  });
  document.querySelectorAll('.prog-type-select').forEach(sel => {
    sel.addEventListener('click', (e) => e.stopPropagation());
    sel.addEventListener('change', async (e) => {
      if (state.busy) return;
      const key = e.target.getAttribute('data-key');
      const ct = e.target.value;
      const prevFilter = state.filter;
      setMsg(`Category → ${typeLabel(ct)} · refreshing cover & totals…`);
      await inlineFixup('set_type', {
        series_keys: [key],
        content_type: ct,
        refetch_meta: true,
      });
      if (prevFilter && prevFilter !== ct) {
        setMsg(`Category → ${typeLabel(ct)} (moved to ${typeLabel(ct)} tab; metadata refreshed)`, 'ok');
      }
    });
  });
  document.querySelectorAll('.prog-status-select').forEach(sel => {
    sel.addEventListener('click', (e) => e.stopPropagation());
    sel.addEventListener('change', async (e) => {
      if (state.busy) return;
      const key = e.target.getAttribute('data-key');
      const st = e.target.value;
      await inlineFixup('set_status', { series_keys: [key], progress_status: st });
    });
  });
  document.querySelectorAll('[data-edit-title]').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      if (state.busy) return;
      beginTitleEdit(el);
    });
  });
  document.querySelectorAll('[data-merge-into]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const target = btn.getAttribute('data-merge-into');
      if (target) mergeIntoTarget(target);
    });
  });
  document.querySelectorAll('[data-resync]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (state.busy) return;
      const key = btn.getAttribute('data-resync') || '';
      const title = btn.getAttribute('data-title') || '';
      pullTadoku({ seriesKey: key, title: title });
    });
  });
}

async function mergeIntoTarget(targetKey) {
  if (state.busy) return;
  const target = state.items.find(i => i.series_key === targetKey);
  if (!target) {
    setMsg('Target work not found', 'err');
    return;
  }
  const sources = [...state.selected].filter(k => k !== targetKey);
  if (!sources.length) {
    setMsg('Select other works first, then click Merge into this on the target', 'err');
    return;
  }
  const sourceItems = state.items.filter(i => sources.includes(i.series_key));
  const preview = sourceItems.slice(0, 14).map(i =>
    `• ${i.title} (${i.series_key}, ${i.log_count} log${i.log_count === 1 ? '' : 's'})`
  ).join('\n');
  const more = sourceItems.length > 14 ? `\n… +${sourceItems.length - 14} more` : '';
  if (!confirm(
    `Merge ${sources.length} work(s) INTO:\n\n` +
    `  “${target.title}”\n` +
    `  ${target.series_key} · ${typeLabel(target.content_type)}\n\n` +
    `These will be absorbed (target keeps its name / category / key):\n${preview}${more}\n\nContinue?`
  )) return;

  setBusy(true);
  setMsg(`Merging ${sources.length} into “${target.title}”…`);
  try {
    const r = await fetch('/api/progress/fixup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'merge',
        series_keys: [...sources, targetKey],
        title: target.title,
        content_type: target.content_type || 'anime',
        target_series_key: targetKey,
        parse_episodes: true,
        refetch_meta: true,
      }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) {
      setMsg(String(data.detail || data.error || ('HTTP ' + r.status)), 'err');
      return;
    }
    state.selected.clear();
    if (data.progress) applyProgress(data.progress, { quiet: true });
    else await loadProgress({ quiet: true });
    // Keep target selected so user sees the survivor
    if (data.target_series_key) state.selected.add(data.target_series_key);
    syncSelectionUI();
    setMsg(
      `Merged ${sources.length} → ${data.target_series_key || targetKey}` +
        (data.updated_logs != null ? ` · ${data.updated_logs} logs` : '') +
        (data.metadata && data.metadata.has_cover ? ' · cover ok' : ''),
      'ok'
    );
  } catch (e) {
    setMsg('Merge failed: ' + e.message, 'err');
  } finally {
    setBusy(false);
  }
}

function beginTitleEdit(el) {
  if (el.dataset.editing === '1' || state.busy) return;
  const key = el.getAttribute('data-edit-title');
  const item = state.items.find(i => i.series_key === key);
  if (!item) return;
  el.dataset.editing = '1';
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'prog-title-input';
  input.value = item.title || '';
  input.setAttribute('aria-label', 'Edit title');
  const parent = el.parentNode;
  const original = el;
  parent.replaceChild(input, el);
  input.focus();
  input.select();
  let done = false;
  const restoreNode = () => {
    original.dataset.editing = '';
    original.textContent = item.title || '';
    if (input.parentNode) parent.replaceChild(original, input);
  };
  const finish = async (save) => {
    if (done) return;
    done = true;
    const next = input.value.trim();
    if (save && next && next !== item.title) {
      await inlineFixup('rename', { series_keys: [key], title: next });
      return; // re-render replaces input
    }
    // Cancel or unchanged — restore the title node in place (no full reload)
    restoreNode();
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  });
  input.addEventListener('blur', () => {
    // Only save on blur when the title actually changed
    const next = input.value.trim();
    if (next && next !== item.title) finish(true);
    else finish(false);
  });
}

async function inlineFixup(action, fields) {
  if (state.busy) return;
  setBusy(true);
  try {
    const body = {
      action,
      series_keys: fields.series_keys,
      parse_episodes: true,
      refetch_meta: false,
      ...fields,
    };
    const r = await fetch('/api/progress/fixup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) {
      setMsg(String(data.detail || data.error || ('HTTP ' + r.status)), 'err');
      await loadProgress({ quiet: true });
      return;
    }
    if (data.progress) applyProgress(data.progress, { quiet: true, keepSelection: true });
    else await loadProgress({ quiet: true });
    if (action === 'set_type') {
      const rewrites = (data && data.key_rewrites) || {};
      const nMeta = ((data && data.metadata) || []).filter(m => m && !m.error).length;
      const bits = [`Category → ${typeLabel(fields.content_type || '')}`];
      if (Object.keys(rewrites).length) bits.push('key updated');
      if (nMeta) bits.push('cover/totals refreshed');
      setMsg(bits.join(' · '), 'ok');
    } else if (action === 'set_status') {
      const n = (fields.series_keys || []).length;
      const who = n > 1 ? `${n} works` : '1 work';
      setMsg(`Status → ${statusLabel(fields.progress_status)} · ${who}`, 'ok');
    } else if (action === 'rename') {
      setMsg(`Renamed to “${fields.title}”`, 'ok');
    }
  } catch (e) {
    setMsg('Update failed: ' + e.message, 'err');
  } finally {
    setBusy(false);
  }
}

async function bulkSetStatus(st) {
  if (state.busy) return;
  const keys = [...state.selected];
  if (!keys.length) {
    setMsg('Select works first', 'err');
    return;
  }
  await inlineFixup('set_status', { series_keys: keys, progress_status: st });
  // Keep selection so user can bulk again or merge; filters may hide some
  syncSelectionUI();
}

function renderItems() {
  const host = $('prog-items');
  if (!host) return;
  const items = filteredItems();
  // Drop selections no longer visible in full list (merged away)
  const valid = new Set(state.items.map(i => i.series_key));
  for (const k of [...state.selected]) {
    if (!valid.has(k)) state.selected.delete(k);
  }
  {
    const parts = [items.length + ' shown'];
    if (state.statusFilter && state.statusFilter !== '__auto_active__') {
      parts.push(statusLabel(state.statusFilter));
    }
    if (state.filter) parts.push(typeLabel(state.filter));
    const total = (state.items || []).length;
    if (items.length !== total) parts.push('of ' + total);
    const needN = needsUserItems().length;
    if (needN) parts.push(needN + ' need input');
    $('prog-count').textContent = parts.join(' · ');
  }
  host.innerHTML = state.mode === 'list' ? renderList(items) : renderGrid(items);
  bindEmptyActions(host);
  bindItemClicks();
  host.querySelectorAll('[data-fix-meta]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      openNeedsFor(btn.getAttribute('data-fix-meta'));
    });
  });
  syncSelectionUI();
}

function setMode(mode) {
  state.mode = mode === 'list' ? 'list' : 'grid';
  try { localStorage.setItem(MODE_KEY, state.mode); } catch (e) {}
  document.querySelectorAll('.mode-toggle button').forEach(b => {
    const on = b.dataset.mode === state.mode;
    b.classList.toggle('active', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  renderItems();
}

function needsEnrich() {
  return state.items.some(i =>
    (i.content_type || '') !== 'youtube' && (!i.has_metadata || !i.has_cover)
  );
}

async function loadProgress({ quiet, autoEnrich } = {}) {
  if (!quiet) setMsg('Loading…');
  try {
    const r = await fetch('/api/progress');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    applyProgress(data, { quiet: true });
    if (!quiet) {
      const n = filteredItems().length;
      setMsg(`${n} work${n === 1 ? '' : 's'} · local database`);
    }
    // Background fill for missing covers (no second click needed)
    if (autoEnrich && needsEnrich()) {
      enrichMeta({ background: true });
    }
  } catch (e) {
    setMsg('Failed to load progress: ' + e.message, 'err');
  }
}

async function pullTadoku({ seriesKey, title } = {}) {
  if (state.busy) return;
  setBusy(true);
  const scoped = !!(seriesKey || title);
  setMsg(scoped
    ? `Resyncing “${title || seriesKey}” from Tadoku…`
    : 'Pulling from Tadoku and updating covers…');
  try {
    const params = new URLSearchParams({
      enrich: 'true',
      enrich_limit: scoped ? '5' : '50',
    });
    if (seriesKey) params.set('series_key', seriesKey);
    if (title) params.set('q', title);
    const r = await fetch('/api/progress/pull-tadoku?' + params.toString(), {
      method: 'POST',
    });
    const data = await r.json();
    if (!data.ok) {
      setMsg(data.error || 'Pull failed', 'err');
      return;
    }
    if (data.progress) {
      applyProgress(data.progress, { quiet: true });
    } else {
      await loadProgress({ quiet: true });
    }
    if (scoped) {
      const matched = data.matched != null ? data.matched : '—';
      const local = data.already_local != null ? data.already_local : 0;
      const samples = (data.matched_samples || []).slice(0, 3).join(' · ');
      setMsg(
        `Resync “${data.query || title || seriesKey}”: ${data.imported} imported, ${local} already local, ${matched} matched of ${data.remote_total} remote` +
          (samples ? ` · e.g. ${samples}` : ''),
        'ok'
      );
    } else {
      setMsg(
        `Tadoku: imported ${data.imported}, skipped ${data.skipped} of ${data.remote_total} remote · list updated`,
        'ok'
      );
    }
  } catch (e) {
    setMsg('Pull failed: ' + e.message, 'err');
  } finally {
    setBusy(false);
  }
}

async function enrichMeta({ background, limit, retryNone } = {}) {
  if (state.busy && !background) return;
  if (!background) setBusy(true);
  // Small batches keep the single-worker server responsive (healthcheck + UI)
  const batchSize = background ? 15 : 25;
  const target = limit != null ? limit : (background ? 30 : 100);
  if (!background) setMsg('Fetching covers & totals (multi-source)…');
  else setMsg('Filling missing covers in the background…');
  let looked = 0, matched = 0, skipped = 0, errN = 0;
  try {
    let remaining = target;
    while (remaining > 0) {
      const lim = Math.min(batchSize, remaining);
      const r = await fetch('/api/progress/enrich', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          force: false,
          limit: lim,
          only_missing: true,
          retry_none: !!retryNone,
        }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok || data.ok === false) {
        if (!background) setMsg(data.error || 'Enrich failed', 'err');
        break;
      }
      if (data.progress) applyProgress(data.progress, { quiet: true });
      looked += data.enriched || 0;
      matched += data.matched != null ? data.matched : (data.enriched || 0);
      skipped += data.skipped || 0;
      errN += (data.errors || []).length;
      remaining -= lim;
      // Stop if nothing left to do
      if ((data.enriched || 0) === 0) break;
      if (!background) {
        setMsg(`Covers/totals… ${looked} looked up, ${matched} matched…`, 'ok');
      }
    }
    if (!background || looked > 0) {
      setMsg(
        `Covers/totals: looked up ${looked}, matched ${matched}, skipped ${skipped}` +
          (errN ? `, ${errN} error(s)` : '') +
          ' · cached locally',
        errN ? '' : 'ok'
      );
    } else if (background) {
      setMsg(`${filteredItems().length} works · local database`);
    }
  } catch (e) {
    if (!background) setMsg('Enrich failed: ' + e.message, 'err');
  } finally {
    if (!background) setBusy(false);
  }
}

async function runNormalizeLibrary() {
  if (state.busy) return;
  if (!confirm(
    'Heal library?\n\n' +
    '• Collapse volume/episode fragments (One Piece 18/19 → One Piece)\n' +
    '• Move Anki / Bunpro / Italki to study (off this shelf)\n' +
    '• Clean work titles (no page counts / log notes)\n\n' +
    'Safe for logs: rewrites series_key + title only.'
  )) return;
  setBusy(true);
  setMsg('Healing library…');
  try {
    const r = await fetch('/api/progress/fixup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'normalize_library', series_keys: [] }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) {
      setMsg(String(data.detail || data.error || ('HTTP ' + r.status)), 'err');
      return;
    }
    if (data.progress) applyProgress(data.progress, { quiet: true });
    else await loadProgress({ quiet: true });
    setMsg(
      `Library healed · ${data.updated_logs || 0} logs` +
        (data.study_reclassified ? ` · ${data.study_reclassified} study` : '') +
        (data.targets ? ` · ${data.targets} works` : ''),
      'ok'
    );
  } catch (e) {
    setMsg('Heal failed: ' + e.message, 'err');
  } finally {
    setBusy(false);
  }
}

async function runFixup(action) {
  if (state.busy) return;
  const keys = [...state.selected];

  const body = {
    action,
    series_keys: keys,
    parse_episodes: true,
    refetch_meta: true,
  };

  if (action === 'refetch_cover') {
    if (!keys.length) { setMsg('Select works first', 'err'); return; }
  } else if (action === 'recover_notes') {
    const scope = keys.length
      ? `selected series (${keys.length})`
      : 'logs that look wrongly merged (unknown / mismatched notes)';
    if (!confirm(
      `Recover works from Tadoku import notes (${scope})?\n\n` +
      `Uses original descriptions still stored in notes to undo bad merges.`
    )) return;
  } else {
    setMsg('Unknown action', 'err');
    return;
  }

  setBusy(true);
  setMsg(action === 'refetch_cover' ? 'Fetching covers…' : 'Recovering from notes…');
  try {
    const r = await fetch('/api/progress/fixup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) {
      setMsg(String(data.detail || data.error || ('HTTP ' + r.status)), 'err');
      return;
    }
    if (data.progress) applyProgress(data.progress, { quiet: true });
    else await loadProgress({ quiet: true });

    if (action === 'refetch_cover') {
      const okN = (data.results || []).filter(x => x.has_cover).length;
      setMsg(`Cover lookup · ${okN}/${keys.length} with art`, 'ok');
    } else if (action === 'recover_notes') {
      const targets = Object.entries(data.by_target || {})
        .map(([k, n]) => `${k}(${n})`)
        .slice(0, 8)
        .join(', ');
      setMsg(
        `Recovered ${data.recovered || 0} log(s)` + (targets ? ` → ${targets}` : ''),
        'ok'
      );
      state.selected.clear();
      syncSelectionUI();
    }
  } catch (e) {
    setMsg('Action failed: ' + e.message, 'err');
  } finally {
    setBusy(false);
  }
}

function init() {
  readUrlFilters();
  setMode(state.mode);
  const sortEl = $('prog-sort');
  if (sortEl) sortEl.value = state.sort === 'title' ? 'title' : 'last_logged';
  $('btn-pull')?.addEventListener('click', pullTadoku);
  $('btn-enrich')?.addEventListener('click', () => enrichMeta({ limit: 120 }));
  $('btn-enrich-all')?.addEventListener('click', () =>
    enrichMeta({ limit: 200, retryNone: true })
  );
  $('btn-normalize')?.addEventListener('click', () => runNormalizeLibrary());
  $('btn-recover')?.addEventListener('click', () => runFixup('recover_notes'));
  $('btn-toast-cover')?.addEventListener('click', () => runFixup('refetch_cover'));
  $('btn-toast-clear')?.addEventListener('click', clearSelection);
  $('btn-toast-select-visible')?.addEventListener('click', () => {
    filteredItems().forEach(i => state.selected.add(i.series_key));
    syncSelectionUI();
  });
  $('btn-toast-active')?.addEventListener('click', () => bulkSetStatus('active'));
  $('btn-toast-finished')?.addEventListener('click', () => bulkSetStatus('finished'));
  $('btn-toast-dropped')?.addEventListener('click', () => bulkSetStatus('dropped'));
  $('btn-toast-ignored')?.addEventListener('click', () => bulkSetStatus('ignored'));
  sortEl?.addEventListener('change', (e) => {
    state.sort = e.target.value === 'title' ? 'title' : 'last_logged';
    try { localStorage.setItem(SORT_KEY, state.sort); } catch (err) {}
    renderItems();
  });
  document.querySelectorAll('.mode-toggle button').forEach(b => {
    b.addEventListener('click', () => {
      if (state.busy) return;
      setMode(b.dataset.mode);
    });
  });
  let t = null;
  $('prog-q')?.addEventListener('input', (e) => {
    clearTimeout(t);
    t = setTimeout(() => {
      state.q = e.target.value || '';
      renderItems();
    }, 120);
  });
  // Esc clears selection when not editing a title
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (document.activeElement && document.activeElement.classList.contains('prog-title-input')) return;
    if (state.selected.size) {
      e.preventDefault();
      clearSelection();
    }
  });
  loadProgress({ autoEnrich: true });
}
document.addEventListener('DOMContentLoaded', init);
"""


def progress_page(
    *,
    tautulli: str = "http://127.0.0.1:8181",
    tadoku: str = "https://tadoku.app",
    sheets: str = "",
    plex: str = "http://127.0.0.1:32400/web",
    contest_url: str = "https://tadoku.app",
) -> str:
    nav = nav_html(
        "progress",
        tautulli=tautulli,
        tadoku=tadoku,
        sheets=sheets,
        plex=plex,
    )
    fonts = (
        '<link rel="preconnect" href="https://fonts.googleapis.com"/>'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>'
        '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700'
        '&family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Serif:wght@500;600'
        '&display=swap" rel="stylesheet"/>'
    )
    body = f"""
<main id="main" class="page page-progress" tabindex="-1">
  <div class="mast">
    <h1>Progress</h1>
    <div class="meta">
      Library shelf ·
      <a href="/queue">Inbox</a> ·
      <a href="/logs">Logs</a> ·
      <a href="{escape(contest_url)}" target="_blank" rel="noopener">Contest</a>
    </div>
  </div>

  <div class="prog-pulse" id="prog-pulse" aria-label="Status counts for current type filter">
    <div class="prog-pulse-cell st-active"><div class="k">Active</div><div class="v">—</div><div class="s">loading</div></div>
    <div class="prog-pulse-cell st-finished"><div class="k">Finished</div><div class="v">—</div><div class="s">loading</div></div>
    <div class="prog-pulse-cell st-dropped"><div class="k">Dropped</div><div class="v">—</div><div class="s">loading</div></div>
  </div>

  <div class="prog-toolbar">
    <div class="prog-toolbar-view">
      <div class="field grow">
        <label for="prog-q">Search</label>
        <input id="prog-q" type="search" placeholder="Title or series key…" autocomplete="off"/>
      </div>
      <div class="field" style="flex:0 0 auto">
        <label for="prog-sort">Sort</label>
        <select id="prog-sort" aria-label="Sort works">
          <option value="last_logged">Last activity</option>
          <option value="title">Title</option>
        </select>
      </div>
      <div class="field" style="flex:0 0 auto">
        <span class="sf-label" id="prog-display-label" style="display:block;margin:0 0 0.2rem">Display</span>
        <div class="mode-toggle" role="group" aria-labelledby="prog-display-label">
          <button type="button" data-mode="grid" class="active" aria-pressed="true">Images</button>
          <button type="button" data-mode="list" aria-pressed="false">List</button>
        </div>
      </div>
    </div>
    <div class="actions prog-toolbar-ops">
      <button type="button" class="primary" id="btn-pull" title="Import missing Tadoku logs, then fill covers/totals">Pull from Tadoku</button>
      <details class="prog-overflow">
        <summary class="secondary">Maintain ▾</summary>
        <div class="prog-overflow-menu" role="menu">
          <button type="button" class="secondary" id="btn-enrich" title="Multi-source covers &amp; totals for missing works">Fetch covers / totals</button>
          <button type="button" class="secondary" id="btn-enrich-all" title="Re-try failures too (slower, up to 200 works)">Fill all missing (slow)</button>
          <button type="button" class="secondary" id="btn-normalize" title="Collapse One Piece 18/19… into works; move Anki/Bunpro off the shelf">Heal library</button>
          <button type="button" class="secondary" id="btn-recover" title="Undo bad merges using Tadoku import notes">Recover from notes</button>
        </div>
      </details>
    </div>
  </div>

  <div class="prog-filter-band">
    <div class="prog-tabs app-tabs" id="prog-tabs" role="tablist" aria-label="Content type"></div>
    <div class="status-filters" id="status-filters" aria-label="Progress status filter"></div>
    <p class="prog-filter-note" id="prog-filter-note" hidden></p>
  </div>
  <div class="prog-lib-meta">
    <span id="prog-count">0 works</span>
    <span class="prog-msg" id="prog-msg" role="status" aria-live="polite"></span>
    <details class="help-fold prog-help-inline">
      <summary>Merge &amp; rename</summary>
      <div class="help-body">
        <p class="faint" style="margin:0">Click <b>title</b> to rename · change <b>status</b> / <b>category</b> on each card.
        Open <b>logs</b> for that work’s entries. <b>Merge:</b> checkboxes → <b>Merge into this</b> on the keeper.
        Selection bar: bulk status, covers. Esc clears selection.
        <b>Ignore</b> hides stub/junk works from the shelf (logs stay; restore via Status → Ignored).
        Works missing a cover or total length appear under <b>Needs your input</b> — paste AniList/MAL/Steam/TVMaze/… links or set totals by hand.
        <b>Multi-season:</b> cards show S1/S2 fill chips; set <code>1:12, 2:13</code> season totals (or import TVMaze) so franchise % is correct — flat episode totals are often S1-only.</p>
      </div>
    </details>
  </div>
  <details class="prog-needs" id="prog-needs" hidden></details>
  <div id="prog-items"></div>

  <!-- Fixed selection bar — checkbox multi-select only -->
  <div class="sel-toast" id="sel-toast" role="region" aria-label="Selection actions" aria-hidden="true">
    <span class="sel-count" id="toast-count">0 selected</span>
    <span class="hint" id="toast-hint"></span>
    <span class="bulk-status">
      <span class="bulk-label">Status</span>
      <button type="button" class="st-active" id="btn-toast-active" title="Mark selected Active (locks auto-finish)">Active</button>
      <button type="button" class="st-finished" id="btn-toast-finished" title="Mark selected Finished">Finished</button>
      <button type="button" class="st-dropped" id="btn-toast-dropped" title="Mark selected Dropped">Dropped</button>
      <button type="button" class="st-ignored" id="btn-toast-ignored" title="Hide selected from Progress shelf (logs kept)">Ignore</button>
    </span>
    <button type="button" id="btn-toast-select-visible">Select visible</button>
    <button type="button" id="btn-toast-cover">Refetch covers</button>
    <button type="button" id="btn-toast-clear">Clear</button>
  </div>
</main>
<script>
{PROGRESS_JS}
</script>
"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta name="color-scheme" content="light"/>
  <meta name="theme-color" content="#cfc4ae"/>
  <title>Progress · Immersion Tracker</title>
  <link rel="icon" type="image/png" sizes="32x32" href="/static/brand/favicon-32.png"/>
  <link rel="icon" type="image/png" sizes="16x16" href="/static/brand/favicon-16.png"/>
  {fonts}
  <style>{SHARED_CSS}{PROGRESS_CSS}</style>
</head>
<body>
{nav}
{body}
</body>
</html>"""
