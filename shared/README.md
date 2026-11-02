# Shared contracts

`schemas.py` uses standard-library dataclasses and typed fields. All teams coordinate interface changes through reviewed pull requests.

- `DetectionOutput`: image identifier, local predicted-mask path, optional oil coordinates and confidence (0-1). `None` means unavailable, not zero confidence.
- `GeoCoordinate`: WGS84 latitude/longitude in decimal degrees, in that field order. Validate latitude [-90, 90], longitude [-180, 180], and finite numbers at ingestion.
- `EnvironmentalData`: local wind/current paths and timezone-aware UTC coverage.
- `DriftOutput`: simulation identifier, initial location, ordered timestamped positions and duration in hours. A first-stage single representative trajectory is supported; agree on a particle/ensemble extension before exporting multiple tracks.
- `Vessel` and `ResponseTarget`: speed in m/s, capacity/demand in cubic metres, availability in hours; IDs must be unique and measurements nonnegative (speed positive).
- `VesselRoute` and `OptimizationOutput`: target IDs, ordered coordinates, distance in km and/or travel time in hours, and explicit solver status. Do not report optimality unless established by the solver.

Dataclasses do not perform runtime validation. Integration adapters must validate timestamps, ranges, IDs, coverage, route estimates, confidence, and statuses before use. Paths stay local and are not portable dataset bundles. For future JSON adapters encode paths as strings and UTC timestamps as ISO 8601, and define a schema version.

Pixel coordinates are not geographic coordinates. Use original scene CRS, raster transform, crop offsets, and acquisition metadata to georeference masks, then transform to WGS84. If metadata is missing, leave geographic output absent and block automatic drift integration.

`detection_cli.py` is the contract between the dashboard's detection adapter and `detection/predict_cli.py` (module name, result line, exit codes, atomic file replacement). Standard library only, so the dashboard can import it without torch.
