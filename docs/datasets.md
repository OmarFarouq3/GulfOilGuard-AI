# Data and tool resources

These are candidate resources, not bundled datasets. Check licenses, access terms, citations, mask encoding, sensor type and geographic/time coverage before use. No downloads are performed by the scaffold.

| Resource | Purpose | Access and integration limitations |
| --- | --- | --- |
| [Refined Deep-SAR](https://zenodo.org/records/15298010) | SAR segmentation with revised annotations; primary detection candidate. | Separate image/mask archives. Inspect source metadata and crop transforms before assuming geographic coordinates survive image export. |
| [M4D](https://m4d.iti.gr/oil-spill-detection-dataset/) | Sentinel-1 SAR image patches and multiclass masks, including oil and look-alikes. | Provider-specific terms and access procedure apply. Map classes explicitly to binary oil labels; source-event coordinates do not guarantee each JPEG crop has an affine transform. |
| [MADOS](https://zenodo.org/records/10664073) | Sentinel-2 optical marine pollution segmentation with sparse annotations. | Optical, not SAR: requires a separate preprocessing/model plan. Respect sparse/ignored labels and inspect scene/crop metadata for georeferencing. |
| [ERA5 / Climate Data Store](https://cds.climate.copernicus.eu/) | Historical wind forcing for drift scenarios. | Review account/API credentials and selected product terms. Match UTC windows, units, temporal resolution and spatial coverage. Reanalysis is not a live forecast. |
| [Copernicus Marine](https://marine.copernicus.eu/) | Ocean current forcing. | Select a suitable regional/global product and inspect its access terms, depth, grid, time resolution and coverage. Configure any required credentials locally. The main site returned HTTP 403 during scaffold source review; product access was not verified. |
| [OpenDrift](https://github.com/OpenDrift/opendrift) | Framework for trajectory and oil drift simulation. | A simulator, not a source of observations. Needs appropriate readers, forcing fields, release parameters and oil properties. Check platform/native dependency setup before manual installation. |
| [Google OR-Tools](https://developers.google.com/optimization) | Vehicle routing and constrained optimization. | A solver, not vessel, bathymetry or navigation data. Supply validated travel costs and operational constraints; routing feasibility depends on these inputs. |

Store provider files under ignored `data/` or `datasets/`; existing detection scripts use ignored `detection/images/` and `detection/masks/`. Keep credentials and large archives outside Git. Document selected versions, licenses, attribution, splits and provenance before experiments.

For detection-to-drift integration retain original scene identifiers, acquisition UTC time, CRS, affine transform and crop offsets. Transform oil mask regions into WGS84; do not substitute pixel row/column values. If unavailable, use explicitly synthetic geographic fixtures for independent development and label them accordingly. They cannot demonstrate end-to-end accuracy.
