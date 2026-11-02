"""Fit synthetic rectangles to check that U-Net can learn, without a dataset.

Run from the repository root: python -m detection.smoke_test
This checks model mechanics only; it does not measure oil-spill accuracy.
"""

import torch
from torch import nn

from detection.model import build_model


def main() -> None:
    torch.manual_seed(7)
    torch.set_num_threads(2)

    # Two deliberately simple labelled examples, generated entirely in memory.
    masks = torch.zeros(2, 1, 32, 32)
    masks[0, :, 6:24, 8:25] = 1
    masks[1, :, 10:28, 4:22] = 1
    images = (0.2 + 0.6 * masks.repeat(1, 3, 1, 1) + 0.05 * torch.rand(2, 3, 32, 32))

    model = build_model()
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    model.eval()
    with torch.no_grad():
        initial_loss = criterion(model(images), masks).item()

    model.train()
    for _ in range(60):
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(model(images), masks)
        if not torch.isfinite(loss).item():
            raise RuntimeError("Synthetic training produced a non-finite loss.")
        loss.backward()
        optimizer.step()

    model.eval()
    with torch.inference_mode():
        logits = model(images)
        final_loss = criterion(logits, masks).item()
        prediction = torch.sigmoid(logits) >= 0.5

    print("Synthetic rectangle check only -- not oil-spill validation.")
    print(f"Input shape: {tuple(images.shape)}")
    print(f"Output shape: {tuple(logits.shape)}")
    print(f"Trainable parameters: {sum(p.numel() for p in model.parameters()):,}")
    print(f"BCE loss: {initial_loss:.4f} -> {final_loss:.4f} after 60 steps")

    # Require both loss reduction and correct foreground/background recovery.
    # These checks keep an all-background prediction from passing the demo.
    oil_recovered = prediction[masks.bool()].float().mean().item()
    background_recovered = (~prediction[~masks.bool()]).float().mean().item()
    if not (final_loss < initial_loss * 0.5 and oil_recovered > 0.9 and background_recovered > 0.9):
        raise RuntimeError("Model did not sufficiently fit the synthetic examples.")
    print("PASS: loss decreased and both synthetic regions were recovered.")


if __name__ == "__main__":
    main()
