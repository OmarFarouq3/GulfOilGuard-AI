"""Presentation building blocks: page heading, chips, stat tiles, empty states, legend, footer.

All text shown here is audience-facing. Technical details (paths, file names, loader
warnings) belong only in the developer panel (components/nav.py).
"""

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from components import illustrations
from components.data import Stage
from components.labels import STAGE_STATUS
from services.files import display_text

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
EMPTY_VALUE = "—"

STATUS_CHIPS = {status: (css, label) for status, (css, label, _help) in STAGE_STATUS.items()}


def esc(value: object) -> str:
    """HTML-escape anything that may come from data files."""
    return html.escape(str(value))


def load_styles() -> None:
    """Inject the dashboard stylesheet (sent to the event container, takes no space)."""
    st.html(ASSETS_DIR / "styles.css")


def chip(status: str) -> str:
    css, label = STATUS_CHIPS[status]
    return f'<span class="gog-chip {css}"><span class="gog-dot"></span>{label}</span>'


def page_heading(eyebrow: str, title: str, subtitle: str, stage: Stage | None = None) -> None:
    """Large page heading with an optional status chip ("Simulated scenario", "Real detection, ...")."""
    status = chip(stage.status) if stage and stage.status != "empty" else ""
    st.html(
        f"""<div class="gog-heading">
              <div class="gog-eyebrow">{esc(eyebrow)}</div>
              <div class="gog-heading-row"><h1>{esc(title)}</h1>{status}</div>
              <p class="gog-subtitle">{esc(subtitle)}</p>
            </div>"""
    )
    if stage and stage.has_issue:
        result_unavailable()


def section(title: str, caption: str | None = None) -> None:
    """Section header with a short teal accent bar."""
    cap = f'<p class="gog-section-caption">{esc(caption)}</p>' if caption else ""
    st.html(f'<div class="gog-section"><h3>{esc(title)}</h3>{cap}</div>')


def stat_tiles(tiles: list[tuple]) -> None:
    """Row of glass KPI tiles: (label, value or None, unit, hint[, secondary]). None renders as an elegant dash.

    ``secondary`` is an optional small line under the hint (e.g. "Overall 0.87"); left out when None.
    """
    cells = []
    for label, value, unit, hint, *rest in tiles:
        secondary = rest[0] if rest else None
        extra = f'<div class="gog-stat-secondary">{esc(secondary)}</div>' if secondary else ""
        if value is None:
            number = f'<span class="gog-stat-value gog-stat-empty">{EMPTY_VALUE}</span>'
        else:
            unit_html = f'<span class="gog-stat-unit">{esc(unit)}</span>' if unit else ""
            number = f'<span class="gog-stat-value">{esc(value)}</span>{unit_html}'
        cells.append(
            f"""<div class="gog-stat">
                  <div class="gog-stat-label">{esc(label)}</div>
                  <div class="gog-stat-number">{number}</div>
                  <div class="gog-stat-hint">{esc(hint)}</div>{extra}
                </div>"""
        )
    st.html(f'<div class="gog-stats">{"".join(cells)}</div>')


EMPTY_ART = {
    "detect": (illustrations.SATELLITE, "Satellite scanning the sea"),
    "predict": (illustrations.DRIFT, "Oil slick drifting over time"),
    "respond": (illustrations.ROUTES, "Vessels routed to oil patches"),
}


def empty_state(kind: str, title: str, body: str, features: list[str]) -> None:
    """Friendly empty-state card with an illustration and what the section will show."""
    items = "".join(f"<li>{esc(f)}</li>" for f in features)
    svg, alt = EMPTY_ART[kind]
    st.html(
        f"""<div class="gog-empty">
              <div class="gog-empty-art">{illustrations.img(svg, "gog-illus", alt)}</div>
              <div class="gog-empty-text">
                <h3>{esc(title)}</h3>
                <p>{esc(body)}</p>
                <ul class="gog-empty-list">{items}</ul>
                <p class="gog-empty-tip">Presenting? A simulated Gulf scenario is available from the options menu (⚙).</p>
              </div>
            </div>"""
    )


def inline_empty(message: str) -> None:
    """Small muted placeholder for one missing piece inside an otherwise populated page."""
    st.html(f'<div class="gog-inline-empty">{esc(message)}</div>')


def result_unavailable() -> None:
    """Generic, audience-safe notice when some inputs could not be read."""
    st.html(
        '<div class="gog-notice">Part of this result couldn\'t be displayed. '
        "The rest of the analysis is shown below.</div>"
    )


def legend(items: list[tuple[str, str, str]]) -> None:
    """Map legend: (colour, label, shape) where shape is 'fill', 'line', 'dash' or 'dot'."""
    entries = "".join(
        f'<span class="gog-legend-item"><span class="gog-swatch gog-swatch-{shape}" '
        f'style="--c:{esc(color)}"></span>{esc(label)}</span>'
        for color, label, shape in items
    )
    st.html(f'<div class="gog-legend">{entries}</div>')


def table(headers: list[str], rows: list[list | tuple], numeric: tuple[int, ...] = (), key: str = "",
          scroll_hint: bool = False) -> None:
    """Plain table whose cells wrap, so it stays readable on a phone; numeric columns align right.

    A table still too wide scrolls sideways; ``scroll_hint`` then says so on narrow screens.
    """
    def cell(tag: str, i: int, value: object) -> str:
        return f'<{tag} class="{"gog-num" if i in numeric else ""}">{esc(value)}</{tag}>'

    head = "".join(cell("th", i, h) for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(cell("td", i, v) for i, v in enumerate(row)) + "</tr>" for row in rows)
    hint = '<p class="gog-scroll-hint">Scroll sideways to see all columns →</p>' if scroll_hint else ""
    st.html(f'{hint}<div class="gog-table-wrap {esc(key)}"><table class="gog-table"><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def details_table(rows: dict[str, object]) -> None:
    """Compact two-column key/value list for model details."""
    body = "".join(f"<dt>{esc(k)}</dt><dd>{esc(display_text(v) if isinstance(v, str) else v)}</dd>"
                   for k, v in rows.items())
    st.html(f'<dl class="gog-details">{body}</dl>')


def footer() -> None:
    st.html('<footer class="gog-footer"><span>GulfOilGuard-AI</span><span>Hack for Earth 2026</span></footer>')


def coordinates(latitude: float, longitude: float) -> str:
    """'25.850° N, 55.650° E'."""
    return (f"{abs(latitude):.3f}° {'N' if latitude >= 0 else 'S'}, "
            f"{abs(longitude):.3f}° {'E' if longitude >= 0 else 'W'}")


def fmt(value: float | None, digits: int = 1) -> str | None:
    """Format a number for a tile, or None when unknown (tile shows a dash)."""
    return None if value is None else f"{value:,.{digits}f}"
