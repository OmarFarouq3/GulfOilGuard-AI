# Individually assignable tasks

Member numbers are assignment slots for the ten-person team. All work uses separate branches and reviewed pull requests.

| Member | Responsibility | Required inputs | Expected deliverables | Dependencies | Acceptance criteria |
| --- | --- | --- | --- | --- | --- |
| 1 | SAR loading and preprocessing | Local approved image/mask pairs, provider label definitions | Documented preprocessing and split manifest | Dataset access | Pairing and class encoding verified; no scene leakage; existing scripts preserved unless separately reviewed |
| 2 | Binary U-Net and training | Member 1 loader/splits | Model builder, training entry point, local checkpoint procedure | 1; can start with synthetic tensors | Correct input/output shapes; training explicitly invoked; settings recorded; no checkpoints committed |
| 3 | Detection evaluation and mask export | Held-out labels, checkpoint, metadata | Dice/IoU/precision/recall and DetectionOutput adapter | 1, 2; start with known tiny masks | Known-mask metrics checked; empty-mask convention documented; absent georeferencing explicit |
| 4 | Environmental data | Region, UTC window, approved provider access | ERA5/current retrieval and normalized EnvironmentalData | Provider terms; independent geographic fixtures | Units, time, grid, depth and coverage documented; secrets local |
| 5 | Oil drift simulation | Initial WGS84 release, forcing, oil settings | OpenDrift runner and DriftOutput export | 4; 3 for real integrated releases | 6/12/24-hour exports; ordered UTC positions; reproducible configuration; uncertainty stated |
| 6 | Vessel and target routing | Vessel fleet, targets, navigation costs | OR-Tools route solver and status mapping | Shared contracts; 5 for real targets | Capacity/availability respected; IDs consistent; infeasibility explicit; target aggregation documented |
| 7 | Baselines and routing evaluation | Identical fleet/targets/costs | Simple baseline and comparison report | 6; independent synthetic cases first | Fair inputs; distance/time units explicit; coverage and feasibility compared without invented gains |
| 8 | Dashboard views | Shared contracts, labelled example inputs | Imagery/mask, trajectory-map and route views | View fixtures initially; 3, 5, 6 later | Empty/missing/error states visible; pixels and geographic maps separated; fixtures labelled |
| 9 | Integration adapters and testing | Team outputs and interface agreements | Orchestration, validation, contract and integration checks | 3-8; independent adapters first | Missing metadata blocks drift; UTC/units/IDs validated; no automatic downloads/training on import |
| 10 | Project lead | Team progress, PRs and validation evidence | Branch/review conventions, milestones, coordinated tests and presentation | All members | Reviews complete; interfaces agreed; claims backed by recorded evidence; no raw data/secrets in Git |
