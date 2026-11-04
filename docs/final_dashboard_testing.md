# Detection Dashboard Testing Report

## 1. Objective

Test the updated dashboard to verify that SAR images, predicted oil masks, and overlays display correctly, remain aligned, and update when switching between incidents.


## 2. Tests Performed

| Test | Result |
|---|---|
| Dashboard launches successfully | PASS |
| Real U-Net detection runs | PASS |
| SAR images display correctly | PASS |
| Predicted oil masks display correctly | PASS |
| Mask and overlay appear visually aligned | PASS |
| Switching incidents updates the detection images | PASS |
| No broken detection images observed | PASS |
| Predict page loads and displays forecast results | PASS |
| Forecast controls update the displayed results | PASS |
| Respond page displays vessel routes and assignments | PASS |
| Switching incidents resets previous Predict/Respond results | PASS |

## 3. Observations

The dashboard successfully displayed SAR images alongside their predicted oil masks and overlays.

The white regions in the predicted masks visually matched the orange regions displayed in the overlays.

Switching between incidents updated the detection images without obvious alignment or display issues.

The Predict and Respond pages were also tested. Forecast visualizations and vessel routes displayed successfully.

## 4. Important Notes

- Detection uses real predictions from the trained U-Net model.
- Incident locations are simulated and are not geolocated to the SAR images.
- Drift forecasts currently use simulated scenarios rather than newly computed predictions for each incident.
- Vessel response plans are simulated and repositioned to the selected incident.

## 5. Conclusion

The updated dashboard passed the visual and functional checks performed during testing. No obvious broken images, incorrect overlays, or display failures were observed.

The dashboard is suitable for demonstrating the integrated workflow, provided that simulated components are clearly identified.
