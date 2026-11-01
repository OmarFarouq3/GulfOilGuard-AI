"""Model contract checks using synthetic tensors; no satellite data required."""

import io
import unittest

import torch
from torch import nn

from detection.model import build_model


class UNetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Small CPU tests are faster with a limited thread count.
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(2)

    @classmethod
    def tearDownClass(cls) -> None:
        torch.set_num_threads(cls.previous_threads)

    def setUp(self) -> None:
        torch.manual_seed(7)

    def test_default_model_preserves_batch_and_spatial_shape(self) -> None:
        model = build_model().eval()
        for shape in ((4, 3, 64, 64), (1, 3, 65, 97), (1, 3, 16, 16)):
            with self.subTest(shape=shape), torch.inference_mode():
                logits = model(torch.rand(shape))
                self.assertEqual(logits.shape, (shape[0], 1, shape[2], shape[3]))
                self.assertTrue(torch.isfinite(logits).all().item())

    def test_custom_channel_counts(self) -> None:
        model = build_model(in_channels=1, out_channels=2, base_channels=4)
        with torch.inference_mode():
            self.assertEqual(model(torch.rand(2, 1, 32, 48)).shape, (2, 2, 32, 48))

    def test_binary_loss_backpropagates_and_updates_weights(self) -> None:
        model = build_model()
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        images = torch.rand(2, 3, 32, 48)
        masks = torch.randint(0, 2, (2, 1, 32, 48)).float()
        first_weight = next(model.parameters())
        previous_weight = first_weight.detach().clone()

        optimizer.zero_grad(set_to_none=True)
        loss = nn.BCEWithLogitsLoss()(model(images), masks)
        self.assertTrue(torch.isfinite(loss).item())
        loss.backward()
        for name, parameter in model.named_parameters():
            with self.subTest(parameter=name):
                self.assertIsNotNone(parameter.grad)
                self.assertTrue(torch.isfinite(parameter.grad).all().item())
        optimizer.step()
        self.assertFalse(torch.equal(first_weight, previous_weight))

    def test_checkpoint_round_trip_preserves_predictions(self) -> None:
        model = build_model(base_channels=4).eval()
        images = torch.rand(1, 3, 33, 49)
        checkpoint = io.BytesIO()
        torch.save(model.state_dict(), checkpoint)
        checkpoint.seek(0)
        restored = build_model(base_channels=4).eval()
        restored.load_state_dict(torch.load(checkpoint, weights_only=True))
        with torch.inference_mode():
            torch.testing.assert_close(model(images), restored(images), rtol=0, atol=0)

    def test_invalid_inputs_have_clear_errors(self) -> None:
        model = build_model(base_channels=4)
        cases = (
            (torch.rand(3, 32, 32), "Expected input shape"),
            (torch.rand(1, 1, 32, 32), "Expected 3 input channels"),
            (torch.rand(1, 3, 15, 32), "at least 16"),
            (torch.rand(1, 3, 32, 15), "at least 16"),
        )
        for images, message in cases:
            with self.subTest(shape=images.shape):
                with self.assertRaisesRegex(ValueError, message):
                    model(images)

    def test_rejects_nonpositive_channels(self) -> None:
        for settings in ({"in_channels": 0}, {"out_channels": 0}, {"base_channels": 0}):
            with self.subTest(settings=settings):
                with self.assertRaisesRegex(ValueError, "positive"):
                    build_model(**settings)


if __name__ == "__main__":
    unittest.main()
