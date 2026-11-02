# Team B – Environmental data sources

Downloaded by Joud, 1 Nov 2026. Raw files are stored locally in data/raw/ and
clean OpenDrift-ready files are written to data/processed/ (neither is in Git).

## Region and time
- Area (WGS84): North 27.0, South 24.75, West 55.0, East 57.0 (northern UAE coast)
- Time: 2026-10-19 00:00 to 2026-10-26 23:00 UTC, hourly
- Reason: the real oil slick from the Strait of Hormuz reached this coast in late October 2026
- Synthetic test start point (NOT a detection result): 25.85 N, 55.65 E

## Wind: ERA5
- Source: ERA5 hourly data on single levels (Copernicus Climate Data Store), reanalysis
- Variables: u10, v10 (10 m wind, m/s), 0.25° grid
- File: era5_wind_gulf_2026-10-19_26.nc
- Licence: CC-BY (credit Copernicus Climate Change Service)
- Notes: time variable is `valid_time`; recent days are preliminary (ERA5T)

## Ocean currents: Copernicus Marine
- Source: GLOBAL_ANALYSISFORECAST_PHY_001_024,
  dataset cmems_mod_glo_phy_anfc_merged-uv_PT1H-i (surface, hourly)
- Variables (m/s): uo, vo (currents), utide, vtide (tides),
  vsdx, vsdy (wave drift), utotal, vtotal (all combined), 1/12° grid, depth 0.49 m
- File: cmems_currents_gulf_2026-10-19_26.nc
- Licence: Copernicus Marine Service (credit "E.U. Copernicus Marine Service Information")
- Note: utotal/vtotal already include wave drift, so don't add wave drift again in OpenDrift
