# GulfOilGuard-AI

AI-Powered Oil Spill Detection, Drift Prediction & Cleanup Optimization

GulfOilGuard-AI is an AI-powered marine pollution response system designed to detect oil spills from satellite imagery, predict their movement using oceanographic and weather data, and optimize cleanup operations.

The project focuses on protecting marine ecosystems in the Gulf region through machine learning, environmental simulation, and optimization.

Project Objectives

Oil Spill Detection: Identify and segment oil spills in satellite imagery using deep learning models such as U-Net.

Oil Drift Prediction: Simulate oil movement using ocean currents, wind conditions, and environmental data.

Cleanup Optimization: Optimize cleanup vessel routes and resource allocation to support efficient response operations.

Visualization: Develop an interactive dashboard displaying detected spills, predicted trajectories, and recommended response plans.

System Architecture

The project consists of three main stages:

Stage 1: Oil Spill Detection

Input: Satellite radar imagery (SAR).

Model: Deep learning-based image segmentation.

Output: Predicted oil-spill masks and locations.

Stage 2: Oil Drift Prediction

Input: Geolocated oil spills, wind data, and ocean currents.

Tools: OpenDrift, ERA5, and Copernicus Marine.

Output: Simulated oil trajectories over time.

Stage 3: Cleanup Optimization

Input: Predicted oil locations, available vessels, and operational constraints.

Methods: Mathematical optimization and vehicle routing algorithms.

Output: Recommended cleanup routes and response priorities.

The three stages are integrated in an interactive decision-support dashboard (see Running the dashboard).

📊 Datasets and Resources

Oil Spill Detection

Refined Deep-SAR Oil Spill Dataset

M4D Oil Spill Detection Dataset

MADOS Dataset

Copernicus Data Space

Environmental Data and Simulation

ERA5 Weather Data

Copernicus Marine Service

OpenDrift

Optimization

Google OR-Tools

Dataset access and usage conditions depend on the original providers. Raw datasets are not stored in this repository.

🛠️ Technology Stack

Programming: Python

Deep Learning: PyTorch, U-Net

Data Processing: NumPy, Pandas

Computer Vision: OpenCV, Pillow

Ocean Simulation: OpenDrift

Optimization: Google OR-Tools

Visualization: Matplotlib, Streamlit, Plotly

Collaboration: Git and GitHub

The technology stack may evolve during development.

Project Structure:

```text
GulfOilGuard-AI/
├── dashboard/        Streamlit app (entry point dashboard/app.py): Overview, Detect, Predict, Respond
├── detection/        U-Net: data preparation, training, evaluation, predict_cli (run by Detect)
├── drift/            OpenDrift runs with ERA5 wind and Copernicus Marine currents
├── optimization/     OR-Tools cleanup routing on the drift output, plus validation
├── shared/           data contracts shared by all modules (schemas.py, detection_cli.py)
├── tests/            pytest / unittest suites and output contract checks
├── docs/             design notes, model card, audits and test reports
├── assets/icon/      the app icon (assets/images/ is a local, untracked image folder)
├── .streamlit/       dashboard theme (launch from the repository root)
├── requirements.txt  full pipeline + dashboard (includes dashboard/requirements.txt)
└── README.md

In the repository: outputs/ (real S1-S4 results) and checkpoints/unet_best.pth.
Not in the repository (local only): data/, assets/images/ (except ten sample images),
runs/, .env, and backups inside outputs/
```

Team Collaboration

The project is developed by a team of 10 members working across:

Satellite data processing and oil-spill detection

Deep learning model development and evaluation

Weather and oceanographic data collection

Oil drift simulation

Cleanup route optimization

Dashboard development and system integration

Research, documentation, and testing

Contributors should use separate feature branches and submit pull requests for review before merging changes into main.

Current Progress

Detection: U-Net trained and evaluated on the Refined Deep-SAR dataset (6,455 training, 1,615 validation pairs). Done

Drift prediction: 24-hour OpenDrift runs for four demo sites (S1–S4) from hypothetical release points, on ERA5 wind and Copernicus Marine currents. Done

Cleanup optimization: OR-Tools routing on each site's drift output, with a nearest-target baseline and validation. Done

Dashboard: Detect → Predict → Respond for each site, with every simulated or assumed part labelled. Done

Open: georeferenced detections (the SAR scenes have no map location, so they are not linked to a site), and validation against observed spills.

Sustainability Impact

GulfOilGuard-AI aims to support:

Faster identification of marine oil pollution.

Improved planning of oil-spill response operations.

More efficient use of cleanup vessels and resources.

Protection of Gulf marine ecosystems and coastal environments.

Data-driven environmental decision-making.

The environmental and operational benefits will be evaluated through experiments and simulated response scenarios.

⚠️ Project Scope

This project is currently a research prototype. Oil detection, drift simulation, and cleanup optimization require separate validation before the complete system can be considered operational.

Satellite image segmentation datasets may not include the geolocation information required for oil-drift modeling. Georeferenced imagery and appropriate environmental data will be incorporated during integration.

Developed for the Ericsson Sustainability Challenge 2026.


## Status

- **Detection:** a PyTorch U-Net with training, checkpoint saving/resuming, validation metrics and mask prediction. The baseline reached 0.8689 Dice and 0.7682 oil-class IoU on the 1,615 Refined SOS validation pairs (validation scores; that split also chose the checkpoint). See [the model card](docs/detection_model_card.md) and [the training guide](docs/detection_training.md).
- **Drift prediction:** implemented (`drift/`, see [drift/README.md](drift/README.md)). The four demo sites are separate, precomputed OpenDrift runs from hypothetical release points; see [the provenance audit](docs/dashboard_provenance_audit.md).
- **Cleanup optimization:** implemented (`optimization/`, see [optimization/README.md](optimization/README.md)).
- **Dashboard:** implemented (`dashboard/`, see [dashboard/README.md](dashboard/README.md)). It shows saved results and never re-runs OpenDrift or the optimiser; only Detect runs the U-Net on the selected image.

Start with [architecture](docs/architecture.md), [integration plan](docs/integration_plan.md), [data resources](docs/datasets.md), and [shared contracts](shared/README.md). Component responsibilities are in each module README.

## Running the dashboard

1. Create an environment and install everything (the root requirements include the dashboard's own, `dashboard/requirements.txt`). Check platform compatibility first, especially for OpenDrift and PyTorch:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

2. Data. **`outputs/` is included in the repository**, so a fresh clone shows the real results for the four sites S1–S4: `outputs/sites/S1…S4/` (each site's drift run, routing plan and validation), `outputs/fleet/`, `outputs/detection/`, `outputs/report/` and `outputs/drift/` (backups and incoming copies inside `outputs/` stay local). The file contract is in [dashboard/README.md](dashboard/README.md); to regenerate the results, see [drift/README.md](drift/README.md) and [optimization/README.md](optimization/README.md).
   - `checkpoints/unet_best.pth`, the trained U-Net for **Run detection**, is included too. Without it, Detect offers a simulated detection, labelled as such.
   - Radar images: `assets/images/` is local (ten sample images are committed under `assets/images/train/`). Settings go in a `.env` file; copy [.env.example](.env.example). **Without a `.env` the app scans all of `assets/images/`** (about 12 s on the first load with the full dataset, and again after a minute); `GOG_IMAGE_DIR=assets/images/val` in `.env` makes it about 1 s.
   - **No data at all?** Write a complete sample scenario and point the dashboard at it. Every sample file is marked `"synthetic": true`, so the pages are labelled **Simulated scenario**:

     ```powershell
     python dashboard/make_sample_outputs.py sample_outputs
     $env:GULFOILGUARD_OUTPUTS = "sample_outputs"
     ```

     The **Demo scenario** switch in the options panel (or `?demo=1`) shows a simulated incident on every page, labelled as simulated.

3. Launch it **from the repository root** (so `.streamlit/config.toml` and its theme are used):

   ```powershell
   streamlit run dashboard/app.py
   ```

Keep imagery, masks and checkpoints in the ignored local folders and do not add datasets to Git. `detection/visualization.py` is the original inspection script; `detection/visualize_data.py` is a compatibility launcher for it.

Use one feature branch per task and pull requests reviewed before merging. Validate interfaces and clearly label synthetic examples. See [tests](tests/README.md) for how to run the checks.
