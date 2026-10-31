"""Interface for the planned binary U-Net segmentation model."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from torch.nn import Module


def build_model(in_channels: int = 3, out_channels: int = 1) -> "Module":
    """Build a U-Net returning binary segmentation logits."""
    raise NotImplementedError("The detection team must implement U-Net.")
