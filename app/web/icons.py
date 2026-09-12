"""Brand-recognizable SVG icons (inline, no CDN)."""

# Filled brand marks — sized for 18–22px viewBox 0 0 24 24 unless noted.


def icon(name: str) -> str:
    icons = {
        # Plex double-chevron (official-style mark)
        "plex": """<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M4.07 0 0 12.02 4.07 24h4.73L4.74 12.02 8.8 0H4.07zm7.56 0-4.07 12.02L11.63 24h4.73l-4.06-11.98L16.36 0h-4.73zm7.57 0-4.07 12.02L19.2 24H24L19.93 12.02 24 0h-4.8z"/></svg>""",
        # Tautulli-style: circular monitor / history mark (purple brand)
        "tautulli": """<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/><path fill="currentColor" d="M12 6.5a1 1 0 0 1 1 1V12l3.2 1.9a1 1 0 1 1-1 1.7l-3.7-2.2A1 1 0 0 1 11 12.5v-5a1 1 0 0 1 1-1z"/><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" d="M18.5 7.2A8 8 0 0 0 7.2 5.5"/></svg>""",
        # Google Sheets green grid
        "sheets": """<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#0F9D58" d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><path fill="#87CEAC" d="M14 2.5V8h5.5L14 2.5z"/><path fill="#fff" d="M7.5 11h9v8h-9z"/><path fill="#0F9D58" d="M7.5 11h9v1.2h-9zm0 3.4h9v1.2h-9zm0 3.4h9V20h-9zM10.3 11v8h1.2v-8zm3.4 0v8h1.2v-8z"/></svg>""",
        # Tadoku / reading — stamp-like 読 circle (distinct, not generic book)
        "tadoku": """<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10.5" fill="currentColor"/><text x="12" y="16.2" text-anchor="middle" font-size="11" font-weight="700" font-family="serif" fill="#fff">読</text></svg>""",
        # YouTube play
        "youtube": """<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#FF0000" d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.5 12 3.5 12 3.5s-7.5 0-9.4.6A3 3 0 0 0 .5 6.2 31.5 31.5 0 0 0 0 12a31.5 31.5 0 0 0 .5 5.8 3 3 0 0 0 2.1 2.1c1.9.6 9.4.6 9.4.6s7.5 0 9.4-.6a3 3 0 0 0 2.1-2.1A31.5 31.5 0 0 0 24 12a31.5 31.5 0 0 0-.5-5.8z"/><path fill="#fff" d="M9.75 15.5v-7l6 3.5-6 3.5z"/></svg>""",
        # Catalog / alias linking
        "catalog": """<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M8 6h11M8 12h11M8 18h11"/><circle cx="4.5" cy="6" r="1.2" fill="currentColor" stroke="none"/><circle cx="4.5" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="4.5" cy="18" r="1.2" fill="currentColor" stroke="none"/></svg>""",
        # Queue check
        "queue": """<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h12M4 12h16M4 17h10"/><path d="m15 15 2.2 2.2L22 12.5"/></svg>""",
        # API
        "api": """<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M8 8 4 12l4 4M16 8l4 4-4 4M13 5l-2 14"/></svg>""",
        # Plus / manual
        "manual": """<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>""",
        # Contest medal
        "contest": """<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="9" r="4.5"/><path d="M8.5 12.5 7 21l5-2.5L17 21l-1.5-8.5" stroke-linejoin="round"/></svg>""",
        # Lucid Immersion Tracker — LiT monogram (fallback SVG; PNG brand mark preferred in UI)
        "brand": """<svg viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="5" fill="#0b1220"/><text x="12" y="16.2" text-anchor="middle" font-size="9.5" font-weight="800" font-family="Segoe UI, system-ui, sans-serif" fill="#fff" letter-spacing="-0.5">LiT</text><path d="M4 18c3-4 6-5 8-3 2 2 4 1 8-2" fill="none" stroke="#2dd4bf" stroke-width="1.4" stroke-linecap="round"/></svg>""",
    }
    return icons.get(name, icons["brand"])
