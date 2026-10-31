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

The three stages will eventually be integrated into an interactive decision-support dashboard.

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

Planned Project Structure:

GulfOilGuard-AI/
│
├── detection/
│   ├── dataset.py
│   ├── model.py
│   ├── train.py
│   └── evaluate.py
│
├── drift/
│
├── optimization/
│
├── dashboard/
│
├── tests/
│
├── docs/
│
├── data/
│
├── models/
│
├── requirements.txt
├── .gitignore
└── README.md

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

Selected the project concept. Done 

Identified potential datasets and simulation tools. Done

Downloaded and extracted the Refined Deep-SAR dataset. Done
 
Verified 6,455 training and 1,615 validation image-mask pairs. Done

Implemented initial PyTorch data loading. Done

Train and evaluate the baseline U-Net model.

Integrate georeferenced oil-spill information.

Implement oil drift simulation.

Develop cleanup optimization algorithms.

Build the interactive dashboard.

Integrate and evaluate the complete system.

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

This project is currently a research prototype. Oil detection, drift simulation, and cleanup optimization require separate validation before the complete system can be considered operational.

Satellite image segmentation datasets may not include the geolocation information required for oil-drift modeling. Georeferenced imagery and appropriate environmental data will be incorporated during integration.

Developed for the Ericsson Sustainability Challenge 2026.


## Collaborative scaffold

The project now has starter interfaces for the ten-member team. Segmentation training, evaluation, drift simulation and route optimization remain unimplemented and raise `NotImplementedError`. The dashboard displays scaffold status only. Existing progress statements above are retained from the original README and were not revalidated during setup.

Start with [architecture](docs/architecture.md), [team assignments](docs/team_tasks.md), [integration plan](docs/integration_plan.md), [data resources](docs/datasets.md), and [shared contracts](shared/README.md). Component responsibilities are in each module README.

Create a local environment manually with `python -m venv .venv`, activate it on Windows with `.venv\Scripts\Activate.ps1`, then install the planned stack with `python -m pip install -r requirements.txt` after reviewing platform compatibility, especially OpenDrift. Nothing is installed automatically; versions remain unpinned until tested. Launch the status dashboard from the repository root with `streamlit run dashboard/app.py`.

Existing `detection/visualization.py` is preserved; `detection/visualize_data.py` is a compatibility launcher. Existing scripts may read local data immediately when run or imported. Keep imagery/masks in ignored local directories and do not add datasets to Git.

Use one feature branch per task and pull requests reviewed by the lead and affected component owners. Validate interfaces and clearly label synthetic examples. See [tests](tests/README.md) for the planned checks.
