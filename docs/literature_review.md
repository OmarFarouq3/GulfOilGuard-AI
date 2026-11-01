# Literature review: oil spill detection, drift and response

Prepared for GulfOilGuard-AI (Hack for Earth, Ericsson Sustainability Challenge 2026). This review lists the references each team can cite, the numbers we should compare against, and the claims we can and cannot make in the pitch. Reference numbers in brackets point to the list at the end.

## 1. Why this matters in the Gulf

The UAE depends on seawater desalination for drinking water, and its large plants sit on the coast. A UAE University modelling study focused on five coastal desalination plants that produce more than 90% of the country's desalinated water. It mapped, for each plant, the wind direction that pushes oil toward it and the shortest time a slick needs to reach it [11]. An earlier study from the same group coupled a 3-D Gulf circulation model with an oil spill model and checked the drift against the historical Al-Ahmadi spill [10].

Spills on the UAE coast are recurring, not hypothetical. In October 2024 oil reached beaches near Snoopy Island in Fujairah, and the Fujairah Environment Authority sent an anti-pollution crew to contain it [16]. In 2013 a spill from a ship off Fujairah damaged about 2 km of beach and was reported as a possible risk to the Qidfa desalination plant [17].

**Pitch angle.** Our pipeline can answer the operational question raised in [11]: if oil is detected here now, how many hours until it reaches a desalination intake, and which vessels should go where first.

## 2. Detection (Team A)

**Why SAR.** Synthetic aperture radar works day and night and through cloud. Oil damps small surface waves, so slicks appear dark. The main difficulty is look-alikes: low-wind areas and natural films also appear dark [5], [6]. Optical imagery adds spectral detail but suffers from clouds and sun glint, and thermal infrared works for thick oil but not thin films [6].

**Datasets and reported results.**

| Dataset | Sensor | Size | Labels | Reported results |
|---|---|---|---|---|
| M4D [1] | Sentinel-1, VV | 1,112 crops (1,002 train / 110 test) | 5 classes: oil, look-alike, ship, land, sea | Best mIoU 65.06% (DeepLabv3+). Oil-class IoU: U-Net 53.79%, DeepLabv3+ 53.38% |
| SOS [2] | ALOS PALSAR and Sentinel-1A | 8,070 crops of 256x256 px from 21 scenes | Binary oil / background | mIoU about 85% for DeepLabV3+ on the Sentinel split [15] |
| Refined SOS [3] | Same as SOS | Same as SOS | Binary, with about 38% of training and 50% of validation masks corrected | No benchmark on the record page; CC BY 4.0 |
| Eastern Mediterranean set [4] | Sentinel-1, VV | 1,365 oil patches, 640x640 JPG | Bounding boxes, plus a separate look-alike set | Useful for testing false alarms on look-alikes |

**What this means for us.**

1. U-Net is a reasonable baseline. On M4D its oil-class IoU matched DeepLabv3+ [1].
2. Numbers from different datasets cannot be compared directly. SOS is binary and has larger oil regions; M4D includes look-alikes. Team A should report oil-class Dice and IoU on a held-out split and state which dataset they come from.
3. All these datasets are image crops (JPG or PNG). They do not keep the geographic transform, so pixel positions cannot be converted to latitude and longitude. This confirms the georeferencing gate in `docs/architecture.md`. For a real end-to-end demo we need either a georeferenced Sentinel-1 GeoTIFF scene, or a clearly labelled synthetic release point.
4. Before claiming Gulf coverage, check the original SOS paper [2] for the scene locations. Do not assume them.

## 3. Drift prediction (Team B)

**OpenDrift.** OpenDrift is an open-source Python framework for Lagrangian particle tracking, with modules for oil, search and rescue, and larval drift [7]. Its oil module was extended with wave entrainment, droplet size spectra and turbulent mixing, and checked against airborne observations of a real slick. That work found that vertical mixing and weathering must be modelled to get horizontal spreading right, and that drift differs by oil type and weather [8].

**Gulf circulation.** The Gulf is shallow and its circulation is driven by wind and buoyancy. Lower-salinity water enters through the Strait of Hormuz, and tidal currents are strong near the Strait [9]. A Met Office model of the Gulf runs at about 1.8 km resolution. Its authors note that higher resolution does not always give better drift tracks, because small position errors in eddies can make trajectories diverge [9].

**What this means for us.**

1. Wind forcing (ERA5) and current forcing (Copernicus Marine) must cover the full simulation window in UTC.
2. Run ensembles of particles, not one track, so the dashboard can show a spread instead of a single line. The current `DriftOutput` has one track; this needs agreement with Omar before extending it.
3. ERA5 is a reanalysis. A hindcast demo is honest; calling it a live forecast is not.
4. Validation idea: compare one simulated trajectory with a documented past event, as [10] did with Al-Ahmadi.

## 4. Response optimization (Team C)

Most early work on spill logistics scheduled resources once, at the start. Zhang et al. argue this misses how risk shifts as the slick moves, and propose a dynamic multi-objective location-routing model solved with a hybrid heuristic [12]. A 2026 preprint models cleanup with towed-boom vessel pairs as a risk-weighted minimum-latency routing problem: each spill has a risk weight, and damage grows the longer it waits. Mixed-integer programming with a warm start gave near-optimal plans for tens of spills within minutes [13].

**What this means for us.**

1. Ordering targets by risk is supported in the literature. A target near a desalination intake should carry a higher weight.
2. Compare OR-Tools [14] against a simple baseline, such as sending each vessel to its nearest unassigned target, under the same inputs. Report the difference; do not claim savings without that comparison.
3. Re-solving as drift updates arrive (every 6 hours, for example) matches the dynamic approach in [12].

## 5. Reliability: what the dashboard should show

1. Detection: oil-class IoU and Dice on held-out data, the dataset name, and a note that look-alikes cause false alarms.
2. Drift: the forcing sources and time window, the ensemble spread, and a label stating hindcast or synthetic.
3. Routing: solver status (`optimal`, `feasible`, `infeasible`) and the comparison with the baseline.
4. Every synthetic input must be labelled as synthetic on screen.

## 6. Claims we can and cannot make

We can say the pipeline uses established methods (U-Net on SAR, OpenDrift, vehicle routing), that each one is cited, and that we report measured metrics for each stage.

We cannot say the system detects spills in real time, gives operational forecasts, or reduces response time, unless we have measured it.

## References

[1] M. Krestenitis, G. Orfanidis, K. Ioannidis, K. Avgerinakis, S. Vrochidis, and I. Kompatsiaris, "Oil spill identification from satellite images using deep neural networks," *Remote Sensing*, vol. 11, no. 15, p. 1762, 2019, doi: 10.3390/rs11151762.

[2] Q. Zhu, Y. Zhang, Z. Li, X. Yan, Q. Guan, Y. Zhong, L. Zhang, and D. Li, "Oil spill contextual and boundary-supervised detection network based on marine SAR images," *IEEE Trans. Geosci. Remote Sens.*, 2021, doi: 10.1109/TGRS.2021.3115492.

[3] D. Zuenko and I. Khaidarova, "Refined Deep-SAR Oil Spill (SOS) dataset," Zenodo, Apr. 2025, doi: 10.5281/zenodo.15298010.

[4] Y.-J. Yang, S. Singha, R. Goldman, and F. Schütte, "Dataset of oil slicks, look-alikes and remarkable SAR signatures obtained from Sentinel-1 data in the Eastern Mediterranean Sea," *Earth Syst. Sci. Data*, vol. 17, pp. 6807–6837, 2025.

[5] R. Al-Ruzouq, M. B. A. Gibril, A. Shanableh, A. Kais, O. Hamed, S. Al-Mansoori, and M. A. Khalil, "Sensors, features, and machine learning for oil spill detection and monitoring: A review," *Remote Sensing*, vol. 12, no. 20, p. 3338, 2020, doi: 10.3390/rs12203338.

[6] S. Dong, J. Feng, Z. Gu, K. Yin, and Y. Long, "A review of artificial intelligence and remote sensing for marine oil spill detection, classification, and thickness estimation," *Remote Sensing*, vol. 17, no. 22, p. 3681, 2025.

[7] K.-F. Dagestad, J. Röhrs, Ø. Breivik, and B. Ådlandsvik, "OpenDrift v1.0: A generic framework for trajectory modelling," *Geosci. Model Dev.*, vol. 11, pp. 1405–1420, 2018, doi: 10.5194/gmd-11-1405-2018.

[8] J. Röhrs, K.-F. Dagestad, H. Asbjørnsen, T. Nordam, J. Skancke, C. E. Jones, and C. Brekke, "The effect of vertical mixing on the horizontal drift of oil spills," *Ocean Sci.*, vol. 14, pp. 1581–1601, 2018, doi: 10.5194/os-14-1581-2018.

[9] D. Bruciaferri, M. Tonani, I. Ascione, F. Al Senafi, E. O'Dea, H. T. Hewitt, and A. Saulter, "GULF18, a high-resolution NEMO-based tidal ocean model of the Arabian/Persian Gulf," *Geosci. Model Dev.*, vol. 15, pp. 8705–8730, 2022.

[10] A. A. Elhakeem, W. Elshorbagy, and R. Chebbi, "Oil spill simulation and validation in the Arabian (Persian) Gulf with special reference to the UAE coast," *Water Air Soil Pollut.*, vol. 184, pp. 243–254, 2007.

[11] W. Elshorbagy and A. Elhakeem, "Forecasting the oil spill impacts on coastal desalination plants in United Arab Emirates," in *Water Pollution XI*, WIT Trans. Ecol. Environ., vol. 164, pp. 263–274, 2012.

[12] L. Zhang, J. Lu, and Z. Yang, "Dynamic optimization of emergency resource scheduling in a large-scale maritime oil spill accident," *Comput. Ind. Eng.*, vol. 152, 2021.

[13] S. Carmeli, A. Morgan, and K. Solovey, "Routing and control for marine oil-spill cleanup with a boom-towing vessel fleet," arXiv:2603.16626, 2026.

[14] Google, "OR-Tools," [Online]. Available: https://developers.google.com/optimization

[15] "Diffusion-based data augmentation and knowledge distillation with generated soft labels solving data scarcity problems of SAR oil spill segmentation," arXiv:2412.08116, 2024. (Author list to be added.)

[16] "Investigation begins after oil spill cleared from Fujairah coastline," *The National*, Oct. 19, 2024.

[17] "U.A.E.: Oil spill damages Fujairah's beach, may affect desalination plant," *Business Insurance*, Jul. 15, 2013.
