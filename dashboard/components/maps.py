"""Folium map helpers. All inputs are GeoJSON features in WGS84 [lon, lat]."""

from __future__ import annotations

import folium
from streamlit_folium import st_folium

import config
from services.files import iter_positions
from services.geo import bounds

# Keyless Esri tiles (CartoDB now requires an API key).
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
ESRI_ATTR = "Esri, HERE, Garmin, © OpenStreetMap contributors"
POINT_TYPES = {"Point", "MultiPoint"}

MAP_CSS = """
<style>
  .leaflet-container { background: #0a2a40; font-family: Inter, system-ui, sans-serif; }
  .leaflet-tooltip { background: #0c2232; color: #e2eef3; border: 1px solid rgba(94,234,212,.3);
                     border-radius: 8px; box-shadow: 0 6px 18px rgba(0,0,0,.4); }
  .leaflet-tooltip-top:before { border-top-color: #0c2232; }
  .leaflet-control-layers, .leaflet-bar a { background: #0c2232; color: #e2eef3; border-color: #1b3a4d; }
  .leaflet-control-layers-expanded { color: #e2eef3; }
  .leaflet-control-attribution { background: rgba(6,21,33,.7) !important; color: #8fa9b8; }
  .leaflet-control-attribution a { color: #5eead4; }
  .leaflet-control-scale-line { background: rgba(6,21,33,.6); color: #e2eef3; border-color: #8fa9b8; }
  @media (max-width: 520px) { .leaflet-control-scale { display: none; } }
</style>
"""


def base_map() -> folium.Map:
    """Dark ocean basemap centred on the Gulf demo area, with labels and a satellite option."""
    m = folium.Map(location=config.MAP_CENTER, zoom_start=config.MAP_ZOOM, tiles=None, control_scale=True)
    folium.TileLayer(ESRI.format("Canvas/World_Dark_Gray_Base"), attr=ESRI_ATTR, name="Ocean",
                     max_zoom=16, opacity=0.62).add_to(m)  # navy map background shows through the sea
    folium.TileLayer(ESRI.format("World_Imagery"), attr="Esri World Imagery", name="Satellite",
                     show=False).add_to(m)
    folium.TileLayer(ESRI.format("Canvas/World_Dark_Gray_Reference"), attr=ESRI_ATTR, name="Place names",
                     overlay=True, control=True, max_zoom=16).add_to(m)
    m.get_root().header.add_child(folium.Element(MAP_CSS))
    return m


def _tooltip_fields(features: list[dict], wanted: tuple[str, ...]) -> list[str]:
    """Fields present on every feature (GeoJsonTooltip fails on missing keys)."""
    return [f for f in wanted if all(f in feat.get("properties", {}) for feat in features)]


def add_features(
    target: folium.Map | folium.FeatureGroup,
    features: list[dict],
    color: str,
    *,
    outline: str | None = None,
    fill_opacity: float = 0.35,
    weight: float = 2,
    point_radius: float = 3,
    tooltip: dict[str, str] | None = None,
) -> None:
    """Draw polygons/lines as GeoJSON and points as small glowing circle markers.

    ``tooltip`` maps property names to friendly labels.
    """
    shapes = [f for f in features if f["geometry"]["type"] not in POINT_TYPES]
    points = [f for f in features if f["geometry"]["type"] in POINT_TYPES]

    if shapes:
        fields = _tooltip_fields(shapes, tuple(tooltip or {}))
        folium.GeoJson(
            {"type": "FeatureCollection", "features": shapes},
            style_function=lambda _f: {
                "color": outline or color, "weight": weight, "fillColor": color, "fillOpacity": fill_opacity,
            },
            tooltip=folium.GeoJsonTooltip(fields=fields, aliases=[tooltip[f] for f in fields]) if fields else None,
        ).add_to(target)

    for feature in points:
        for lon, lat, *_ in iter_positions(feature["geometry"]["coordinates"]):
            folium.CircleMarker(
                location=(lat, lon), radius=point_radius, color=color, weight=0,
                fill=True, fill_color=color, fill_opacity=0.85,
            ).add_to(target)


def render(m: folium.Map, fit_features: list[dict] | None, key: str, height: int = 520) -> None:
    """Fit the view to the given features, add a layer switcher and render the map."""
    view = bounds(fit_features or [])
    if view:
        (south, west), (north, east) = view
        m.location = [(south + north) / 2, (west + east) / 2]  # centred even before the fit runs
        m.fit_bounds(view, padding=(30, 30), max_zoom=12)  # keep coastline context for small slicks
    folium.LayerControl(collapsed=True).add_to(m)
    st_folium(m, height=height, use_container_width=True, returned_objects=[], key=key)
