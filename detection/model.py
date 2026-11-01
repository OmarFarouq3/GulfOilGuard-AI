"""A basic U-Net for oil-spill segmentation, implemented using only PyTorch."""

import torch
from torch import nn
from torch.nn import functional as F


class DoubleConv(nn.Sequential):
    """Learn spatial features while preserving height and width."""

    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__(
            nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
        )


class Up(nn.Module):
    """Upsample, concatenate an encoder skip connection, then learn features."""

    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__()
        self.conv = DoubleConv(in_channels, out_channels)

    def forward(self, x: torch.Tensor, skip: torch.Tensor) -> torch.Tensor:
        # Matching the skip size also supports odd image dimensions.
        x = F.interpolate(x, size=skip.shape[-2:], mode="bilinear", align_corners=False)
        return self.conv(torch.cat((skip, x), dim=1))


class UNet(nn.Module):
    """Four-level U-Net with a same-size output and unnormalised logits.

    Input: floating-point tensor [batch, in_channels, height, width].
    Output: logits [batch, out_channels, height, width].
    Both spatial dimensions must be at least 16 for four pooling operations.

    Defaults match OilSpillDataset: three input channels and one oil channel.
    For binary training, pass logits directly to nn.BCEWithLogitsLoss with
    float masks containing 0 and 1. Apply sigmoid only when probabilities are
    needed. No data is loaded and no pretrained weights are downloaded here.
    """

    def __init__(
        self, in_channels: int = 3, out_channels: int = 1, *, base_channels: int = 32
    ) -> None:
        super().__init__()
        if min(in_channels, out_channels, base_channels) < 1:
            raise ValueError("Channel counts must be positive.")

        self.in_channels = in_channels
        channels = base_channels
        self.pool = nn.MaxPool2d(kernel_size=2)

        self.encoder1 = DoubleConv(in_channels, channels)
        self.encoder2 = DoubleConv(channels, channels * 2)
        self.encoder3 = DoubleConv(channels * 2, channels * 4)
        self.encoder4 = DoubleConv(channels * 4, channels * 8)
        self.bottleneck = DoubleConv(channels * 8, channels * 16)

        self.decoder4 = Up(channels * 24, channels * 8)
        self.decoder3 = Up(channels * 12, channels * 4)
        self.decoder2 = Up(channels * 6, channels * 2)
        self.decoder1 = Up(channels * 3, channels)
        self.output = nn.Conv2d(channels, out_channels, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 4:
            raise ValueError("Expected input shape [batch, channels, height, width].")
        if x.shape[1] != self.in_channels:
            raise ValueError(f"Expected {self.in_channels} input channels, got {x.shape[1]}.")
        if min(x.shape[-2:]) < 16:
            raise ValueError("Input height and width must both be at least 16.")

        # Save encoder features so the decoder can recover fine boundaries.
        skip1 = self.encoder1(x)
        skip2 = self.encoder2(self.pool(skip1))
        skip3 = self.encoder3(self.pool(skip2))
        skip4 = self.encoder4(self.pool(skip3))
        x = self.bottleneck(self.pool(skip4))

        x = self.decoder4(x, skip4)
        x = self.decoder3(x, skip3)
        x = self.decoder2(x, skip2)
        x = self.decoder1(x, skip1)
        return self.output(x)


def build_model(
    in_channels: int = 3, out_channels: int = 1, *, base_channels: int = 32
) -> UNet:
    """Build an untrained U-Net; defaults preserve the existing model interface."""
    return UNet(in_channels, out_channels, base_channels=base_channels)
