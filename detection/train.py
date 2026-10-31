"""Training entry point; importing this module does not load data or train."""

from pathlib import Path


def train(image_dir: Path, mask_dir: Path, output_dir: Path, epochs: int = 1) -> Path:
    """Train on paired images and masks and return the saved checkpoint path."""
    raise NotImplementedError("Implement training and a separate validation split.")
