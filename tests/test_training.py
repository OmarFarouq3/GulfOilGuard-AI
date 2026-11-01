"""Dataset, metric, checkpoint, resume and prediction checks on tiny synthetic PNGs."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
import torch

from detection.dataset import OilSpillDataset
from detection.evaluate import evaluate, predict
from detection.metrics import confusion_counts, metrics_from_counts
from detection.train import train


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous_threads = torch.get_num_threads()
        for split in ("train", "val"):
            for kind in ("images", "masks"):
                (self.root / kind / split).mkdir(parents=True)
            for index in range(2):
                labels = np.zeros((20, 24), dtype=np.uint8)
                labels[4:15, 5 + index:18] = 255
                Image.fromarray(labels).save(self.root / "masks" / split / f"{index}.png")
                Image.fromarray(np.repeat(labels[..., None], 3, axis=2)).save(
                    self.root / "images" / split / f"{index}.png")

    def tearDown(self):
        torch.set_num_threads(self.previous_threads)
        self.temporary.cleanup()

    def dataset(self, **kwargs):
        return OilSpillDataset(self.root / "images/train", self.root / "masks/train", **kwargs)

    def test_transforms_keep_images_and_labels_aligned(self):
        dataset = self.dataset(augment=True)
        torch.manual_seed(42)
        for _ in range(6):
            image, mask = dataset[0]
            torch.testing.assert_close(image[0], mask[0])
            self.assertEqual(mask.dtype, torch.float32)
        image, mask = self.dataset(image_size=16)[0]
        self.assertEqual(image.shape, (3, 16, 16))
        self.assertEqual(mask.shape, (1, 16, 16))
        self.assertEqual(set(torch.unique(mask).tolist()), {0.0, 1.0})

    def test_threshold_boundary(self):
        pixels = np.tile(np.array([0, 127, 128, 255], dtype=np.uint8), (20, 6))
        Image.fromarray(pixels).save(self.root / "masks/train/0.png")
        _, mask = self.dataset()[0]
        self.assertEqual(mask[0, 0, :4].tolist(), [0.0, 0.0, 1.0, 1.0])

    def test_unmatched_and_misaligned_pairs_are_rejected(self):
        (self.root / "masks/train/0.png").unlink()
        with self.assertRaisesRegex(ValueError, "Unmatched"):
            self.dataset()
        Image.new("L", (8, 8)).save(self.root / "masks/train/0.png")
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            self.dataset()[0]

    def test_known_and_empty_metrics(self):
        logits = torch.tensor([10.0, 10.0, -10.0, -10.0]).reshape(1, 1, 2, 2)
        masks = torch.tensor([1.0, 0.0, 1.0, 0.0]).reshape(1, 1, 2, 2)
        counts = confusion_counts(logits, masks).tolist()
        self.assertEqual(counts, [1, 1, 1, 1])
        metrics = metrics_from_counts(counts)
        self.assertEqual(metrics["dice"], 0.5)
        self.assertAlmostEqual(metrics["iou"], 1 / 3)
        self.assertEqual(metrics["precision"], 0.5)
        self.assertEqual(metrics["recall"], 0.5)
        self.assertTrue(all(v == 1.0 for v in metrics_from_counts([0, 0, 0, 4]).values()))
        self.assertTrue(all(v == 0.0 for v in metrics_from_counts([0, 0, 4, 0]).values()))

    def test_training_resume_evaluation_and_prediction(self):
        output = self.root / "run"
        arguments = dict(image_dir=self.root / "images/train", mask_dir=self.root / "masks/train",
                         val_image_dir=self.root / "images/val", val_mask_dir=self.root / "masks/val",
                         output_dir=output, image_size=16, base_channels=2, batch_size=2,
                         workers=0, device="cpu")
        best = train(**arguments, epochs=1)
        self.assertTrue(best.is_file())
        with self.assertRaisesRegex(ValueError, "not empty"):
            train(**arguments, epochs=1)
        with self.assertRaisesRegex(ValueError, "must exceed saved epoch"):
            train(**arguments, epochs=1, resume=output / "last.pth")
        with self.assertRaisesRegex(ValueError, "Resume configuration mismatch: learning_rate"):
            train(**arguments, epochs=2, learning_rate=1e-2, resume=output / "last.pth")
        train(**arguments, epochs=2, resume=output / "last.pth")
        history = json.loads((output / "history.json").read_text())
        self.assertEqual([row["epoch"] for row in history], [1, 2])
        checkpoint = torch.load(best, map_location="cpu", weights_only=True)
        metrics = evaluate(best, self.root / "images/val", self.root / "masks/val",
                           device="cpu", output_dir=self.root / "evaluation")
        for key, value in metrics.items():
            self.assertAlmostEqual(value, checkpoint["validation"][key])
        result = predict(best, self.root / "images/val/0.png", self.root / "prediction", device="cpu")
        with Image.open(result.mask_path) as mask:
            self.assertEqual(mask.size, (24, 20))
            self.assertTrue(set(np.unique(mask)).issubset({0, 255}))
        self.assertIsNone(result.oil_coordinates)
        self.assertIsNone(result.confidence)


if __name__ == "__main__":
    unittest.main()
