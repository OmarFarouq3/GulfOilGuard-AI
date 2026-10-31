# Validation plan

Use standard-library `unittest` for lightweight contracts and adapters; add tools only when justified. No dataset, provider credentials, or training is required for unit checks.

Planned coverage: mask pairing/class encoding; metrics with empty and known masks; coordinate order and missing georeferencing; UTC and environmental coverage; 6/12/24-hour trajectories; vessel constraints and infeasible status; baseline fairness; dashboard empty/error states. Use tiny, explicitly synthetic inputs authored for tests, never copied satellite images.

No algorithm tests exist yet because the algorithm interfaces are unfinished. Scaffold verification uses AST syntax checks without importing existing scripts that load data. Later run discovered tests with `python -m unittest discover -s tests`.
