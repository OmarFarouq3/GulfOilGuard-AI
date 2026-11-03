"""Plotly charts styled to the dark ocean theme (transparent, no default chrome)."""

from __future__ import annotations

import plotly.graph_objects as go

import config

METRIC_LABELS = {"dice": "Dice", "iou": "IoU", "precision": "Precision", "recall": "Recall"}
METRIC_HINTS = {
    "dice": "Overlap between detected and true oil",
    "iou": "Shared area over combined area",
    "precision": "Flagged pixels that really are oil",
    "recall": "Real oil pixels that were found",
}
# Colour follows the entity: oil is always amber, everything else is cool.
CLASS_COLORS = {"oil": config.AMBER, "background": "#3b6e86"}
OTHER_CLASS_COLORS = ("#22d3ee", "#a78bfa", "#34d399", "#60a5fa")

CHART_CONFIG = {"displayModeBar": False, "responsive": True}


def _style(fig: go.Figure, height: int = 300) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=4, r=4, t=36, b=4),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", color=config.TEXT_MUTED, size=13),
        bargap=0.5,
        bargroupgap=0.12,
        showlegend=len(fig.data) > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=config.TEXT)),
        hoverlabel=dict(bgcolor=config.SURFACE, bordercolor=config.TEAL, font=dict(color=config.TEXT)),
    )
    fig.update_yaxes(range=[0, 1.08], gridcolor=config.GRID, zeroline=False, tickformat=".1f", fixedrange=True)
    fig.update_xaxes(showgrid=False, linecolor=config.GRID, tickfont=dict(color=config.TEXT), fixedrange=True)
    return fig


def metrics_bar(metrics: dict[str, float]) -> go.Figure:
    """Single-series bar chart of segmentation metrics (0-1)."""
    keys = [k for k in METRIC_LABELS if k in metrics]
    fig = go.Figure(go.Bar(
        x=[METRIC_LABELS[k] for k in keys],
        y=[metrics[k] for k in keys],
        marker=dict(color=config.TEAL, cornerradius=6),
        text=[f"{metrics[k]:.2f}" for k in keys],
        textposition="outside",
        textfont=dict(color=config.TEXT),
        hovertemplate="%{x}: %{y:.3f}<extra></extra>",
    ))
    return _style(fig)


def per_class_bar(per_class: dict[str, dict[str, float]]) -> go.Figure:
    """Grouped bars, one series per class, metrics on the x axis."""
    fig = go.Figure()
    others = iter(OTHER_CLASS_COLORS * 3)
    for name, values in per_class.items():
        keys = [k for k in METRIC_LABELS if k in values]
        color = CLASS_COLORS.get(name.lower()) or next(others)
        fig.add_bar(
            name=name.capitalize(),
            x=[METRIC_LABELS[k] for k in keys],
            y=[values[k] for k in keys],
            marker=dict(color=color, cornerradius=6),
            hovertemplate=f"{name} · %{{x}}: %{{y:.3f}}<extra></extra>",
        )
    fig.update_layout(barmode="group")
    return _style(fig)
