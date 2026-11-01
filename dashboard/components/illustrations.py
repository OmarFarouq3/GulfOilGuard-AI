"""SVG illustrations (no external assets), embedded as data-URI images.

st.html sanitises inline <svg>, so each drawing is self-contained (its own <style>
for animations) and rendered through ``img()``.
"""

from __future__ import annotations

import base64

SVG_STYLE = """<style>
  .gog-pulse { animation: p 3.2s ease-in-out infinite; }
  .gog-dash { animation: d 2.4s linear infinite; }
  .gog-wave { animation: w 18s linear infinite; }
  .gog-wave-2 { animation-duration: 26s; animation-direction: reverse; }
  .gog-wave-3 { animation-duration: 34s; }
  .gog-slick { animation: s 7s ease-in-out infinite; transform-origin: 1040px 214px; }
  .gog-illus-label { fill: #8fa9b8; font: 600 8px Inter, system-ui, sans-serif; }
  @keyframes p { 0%, 100% { opacity: .45; } 50% { opacity: 1; } }
  @keyframes d { to { stroke-dashoffset: -18; } }
  @keyframes w { from { transform: translateX(0); } to { transform: translateX(-1440px); } }
  @keyframes s { 0%, 100% { opacity: .55; transform: scaleX(1); } 50% { opacity: .95; transform: scaleX(1.08); } }
  @media (prefers-reduced-motion: reduce) { * { animation: none !important; } }
</style>"""


def img(svg: str, css_class: str, alt: str = "") -> str:
    """Return an <img> tag embedding the SVG (adds the xmlns and shared animation styles)."""
    svg = svg.strip().replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    svg = svg.replace(">", ">" + SVG_STYLE, 1)
    data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f'<img class="{css_class}" src="data:image/svg+xml;base64,{data}" alt="{alt}">'

SATELLITE = """
<svg viewBox="0 0 160 120" role="img" aria-label="Satellite scanning the sea" class="gog-illus">
  <defs>
    <linearGradient id="beam" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#2dd4bf" stop-opacity=".45"/>
      <stop offset="1" stop-color="#2dd4bf" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <path d="M62 44 L30 104 H130 L98 44 Z" fill="url(#beam)" class="gog-pulse"/>
  <g transform="translate(80 30) rotate(-18)">
    <rect x="-9" y="-7" width="18" height="14" rx="3" fill="#0f2a3d" stroke="#5eead4" stroke-width="1.5"/>
    <rect x="-36" y="-5" width="22" height="10" rx="1.5" fill="#123247" stroke="#38bdf8" stroke-width="1.2"/>
    <rect x="14" y="-5" width="22" height="10" rx="1.5" fill="#123247" stroke="#38bdf8" stroke-width="1.2"/>
    <line x1="-14" y1="0" x2="-9" y2="0" stroke="#5eead4" stroke-width="1.5"/>
    <line x1="9" y1="0" x2="14" y2="0" stroke="#5eead4" stroke-width="1.5"/>
  </g>
  <path d="M10 104 q10 -5 20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0" fill="none" stroke="#1b3a4d" stroke-width="2"/>
  <path d="M10 112 q10 -5 20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0" fill="none" stroke="#123247" stroke-width="2"/>
  <ellipse cx="82" cy="101" rx="16" ry="3.5" fill="#f59e0b" opacity=".75"/>
</svg>
"""

DRIFT = """
<svg viewBox="0 0 160 120" role="img" aria-label="Oil slick drifting over time" class="gog-illus">
  <path d="M10 92 q10 -5 20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0" fill="none" stroke="#1b3a4d" stroke-width="2"/>
  <path d="M10 102 q10 -5 20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0" fill="none" stroke="#123247" stroke-width="2"/>
  <path d="M34 46 C60 40, 84 58, 128 70" fill="none" stroke="#8fa9b8" stroke-width="1.5" stroke-dasharray="4 5"/>
  <ellipse cx="34" cy="46" rx="11" ry="6" fill="#fcd34d"/>
  <ellipse cx="66" cy="50" rx="15" ry="8" fill="#f59e0b" opacity=".75"/>
  <ellipse cx="96" cy="60" rx="19" ry="10" fill="#ea580c" opacity=".55"/>
  <ellipse cx="128" cy="70" rx="23" ry="12" fill="#c2410c" opacity=".4" class="gog-pulse"/>
  <text x="34" y="30" text-anchor="middle" class="gog-illus-label">0h</text>
  <text x="66" y="34" text-anchor="middle" class="gog-illus-label">6h</text>
  <text x="96" y="42" text-anchor="middle" class="gog-illus-label">12h</text>
  <text x="128" y="50" text-anchor="middle" class="gog-illus-label">24h</text>
</svg>
"""

ROUTES = """
<svg viewBox="0 0 160 120" role="img" aria-label="Vessels routed to oil patches" class="gog-illus">
  <path d="M0 96 C30 90, 40 112, 70 110 L0 120 Z" fill="#123247"/>
  <ellipse cx="104" cy="44" rx="26" ry="11" fill="#f59e0b" opacity=".3"/>
  <circle cx="92" cy="42" r="3.5" fill="#f59e0b"/><circle cx="106" cy="46" r="3.5" fill="#f59e0b"/>
  <circle cx="118" cy="42" r="3.5" fill="#f59e0b"/>
  <path d="M22 98 C40 70, 64 50, 92 42" fill="none" stroke="#22d3ee" stroke-width="2" stroke-dasharray="5 4" class="gog-dash"/>
  <path d="M40 106 C70 96, 100 70, 106 46" fill="none" stroke="#34d399" stroke-width="2" stroke-dasharray="5 4" class="gog-dash"/>
  <path d="M150 96 C140 76, 128 60, 118 42" fill="none" stroke="#a78bfa" stroke-width="2" stroke-dasharray="5 4" class="gog-dash"/>
  <path d="M14 98 h16 l-3 5 h-10 z" fill="#5eead4"/><path d="M32 106 h16 l-3 5 h-10 z" fill="#5eead4"/>
  <path d="M142 96 h16 l-3 5 h-10 z" fill="#5eead4"/>
</svg>
"""

HERO_WAVES = """
<svg class="gog-hero-waves" viewBox="0 0 1440 320" preserveAspectRatio="none" aria-hidden="true">
  <defs>
    <linearGradient id="sheen" x1="0" x2="1">
      <stop offset="0" stop-color="#fcd34d" stop-opacity="0"/>
      <stop offset=".45" stop-color="#f59e0b" stop-opacity=".55"/>
      <stop offset=".7" stop-color="#a78bfa" stop-opacity=".35"/>
      <stop offset="1" stop-color="#2dd4bf" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <g class="gog-wave gog-wave-1"><path d="M0 200 C240 160 480 240 720 200 C960 160 1200 240 1440 200 C1680 160 1920 240 2160 200 C2400 160 2640 240 2880 200 V320 H0 Z" fill="#0c2a3c"/></g>
  <g class="gog-wave gog-wave-2"><path d="M0 230 C240 200 480 260 720 230 C960 200 1200 260 1440 230 C1680 200 1920 260 2160 230 C2400 200 2640 260 2880 230 V320 H0 Z" fill="#0a2333"/></g>
  <ellipse class="gog-slick" cx="1040" cy="214" rx="210" ry="16" fill="url(#sheen)"/>
  <g class="gog-wave gog-wave-3"><path d="M0 262 C240 240 480 290 720 262 C960 240 1200 290 1440 262 C1680 240 1920 290 2160 262 C2400 240 2640 290 2880 262 V320 H0 Z" fill="#071a28"/></g>
</svg>
"""

LOGO = """
<svg viewBox="0 0 32 32" class="gog-logo" aria-hidden="true">
  <path d="M16 3 C16 3 6 14 6 20 a10 10 0 0 0 20 0 C26 14 16 3 16 3 Z" fill="#0f2a3d" stroke="#2dd4bf" stroke-width="2"/>
  <path d="M10 21 q3 -2.5 6 0 t6 0" fill="none" stroke="#34d399" stroke-width="2" stroke-linecap="round"/>
  <ellipse cx="16" cy="15" rx="3.2" ry="1.6" fill="#f59e0b"/>
</svg>
"""
