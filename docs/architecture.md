# Architecture

GulfOilGuard-AI is a university research prototype for the Ericsson Sustainability Challenge 2026. Detection now implements a basic U-Net, training, validation, and mask export. Drift simulation, routing, and the complete integrated pipeline remain planned.

```text
SAR imagery + masks -> detection -> predicted mask
                                      |
                         source metadata + georeferencing
                                      |
                         WGS84 oil location + release time
                                      |
ERA5 winds + Copernicus currents -> OpenDrift -> timestamped trajectories
                                                       |
                               target aggregation + vessel constraints
                                                       |
                                               OR-Tools routes
                                                       |
                                      Streamlit / Plotly dashboard
```

Detection owns preprocessing, U-Net and held-out metrics. Drift owns provider normalization, oil configuration and trajectory export. Optimization owns target assignment, navigation costs, operational constraints and baseline evaluation. The dashboard coordinates explicit requests and renders outputs; it must show missing inputs and errors rather than fabricate results.

Shared dataclasses in `shared/schemas.py` define handoffs. Georeferencing is a required integration gate: PNG/JPEG pixel indices cannot be interpreted as latitude/longitude. Missing source metadata prevents automatic detection-to-drift integration. Simulations also require a verified UTC release time and environmental coverage.

Raw data, checkpoints, secrets, logs and generated artifacts remain local and ignored. No real-world response or sustainability performance is claimed before validation.
