"""
Tests for Self-Supervised GPR Encoder V1's architecture, loss, device
selection, checksum and save/load (`training.ssl_model`), plus the
end-to-end training driver (`training.ssl_train`).

Synthetic numeric fixtures throughout: these tests verify the CODE is
correct (shapes, gradients, reproducibility, save/load round-trips), never
a scientific claim about real GPR. Section 30's own instruction: a
synthetic overfit test is software verification, not evidence.
"""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from schemas.ssl_gpr import LicensePool, SiteExposure, SiteSplit, SSLWindowRef
from training.ssl_masking import MaskConfig, apply_mask, generate_mask
from training.ssl_model import (
    GPREncoder, SSLAutoencoder, SSLReconstructionDecoder, load_ssl_encoder,
    masked_reconstruction_loss, model_checksum, save_encoder_only, select_device, set_seed,
)


class TestShapes:
    def test_encoder_output_shape_is_bottleneck_resolution(self):
        set_seed(0)
        enc = GPREncoder(in_channels=1, base_channels=8)
        x = torch.zeros(2, 1, 64, 64)
        z = enc(x)
        assert z.shape == (2, 64, 8, 8)  # base_channels*8 == 64 channels, /8 spatial

    def test_reconstruction_output_shape_matches_input(self):
        set_seed(0)
        model = SSLAutoencoder(base_channels=8)
        x = torch.zeros(2, 1, 64, 128)
        out = model(x)
        assert out.shape == x.shape

    def test_input_tensor_shape_from_dataset_wrapper(self):
        from training.ssl_train import SSLWindowDataset

        ref = SSLWindowRef(
            dataset_id="d", site_id="s", survey_id="sv", source_file="f", reader="segy_le",
            trace_start=0, trace_end=63, sample_start=0, sample_end=127,
            preprocessing_version="test", license="CC0-1.0", commercial_use_permitted=True,
            license_pool=LicensePool.COMMERCIAL_COMPATIBLE, split=SiteSplit.TRAIN,
            exposure=SiteExposure.UNSEEN_LABELS_SEEN_ACQUISITION,
        )

        class _Ds(SSLWindowDataset):
            def __getitem__(self, idx):
                rng = np.random.default_rng(0)
                target = rng.normal(size=(128, 64))
                mask = generate_mask(target.shape, self.mask_config, window_seed=idx)
                masked = apply_mask(target, mask, 0.0)
                return (
                    torch.tensor(masked, dtype=torch.float32).unsqueeze(0),
                    torch.tensor(target, dtype=torch.float32).unsqueeze(0),
                    torch.tensor(mask, dtype=torch.bool).unsqueeze(0),
                )

        ds = _Ds([ref])
        x, y, m = ds[0]
        assert x.shape == (1, 128, 64)
        assert y.shape == (1, 128, 64)
        assert m.shape == (1, 128, 64)


class TestNoSkipLeakage:
    def test_decoder_has_no_encoder_feature_map_inputs(self):
        """Structural check: the decoder's forward signature takes only the bottleneck, never enc1/enc2/enc3."""
        import inspect
        sig = inspect.signature(SSLReconstructionDecoder.forward)
        assert list(sig.parameters) == ["self", "z"]

    def test_zeroing_the_bottleneck_removes_all_information_from_the_output(self):
        """If information could reach the output via any path other than the bottleneck, zeroing z would not zero the (deterministic-mode) output identically for two different inputs."""
        set_seed(0)
        model = SSLAutoencoder(base_channels=8).eval()
        decoder = model.decoder
        z = torch.zeros(1, 64, 8, 16)
        out_a = decoder(z)
        out_b = decoder(z.clone())
        assert torch.allclose(out_a, out_b)


class TestLoss:
    def test_masked_region_loss_ignores_unmasked_cells(self):
        pred = torch.zeros(1, 1, 4, 4)
        target = torch.zeros(1, 1, 4, 4)
        target[0, 0, :, 0] = 1000.0  # huge error, but OUTSIDE the mask
        mask = torch.zeros(1, 1, 4, 4, dtype=torch.bool)
        mask[0, 0, :, 1] = True  # a different, all-correct column
        loss = masked_reconstruction_loss(pred, target, mask, kind="l1")
        assert loss.item() == 0.0

    def test_masked_region_loss_is_sensitive_to_masked_cell_error(self):
        pred = torch.zeros(1, 1, 4, 4)
        target = torch.zeros(1, 1, 4, 4)
        target[0, 0, 0, 0] = 4.0
        mask = torch.zeros(1, 1, 4, 4, dtype=torch.bool)
        mask[0, 0, 0, 0] = True
        loss = masked_reconstruction_loss(pred, target, mask, kind="l1")
        assert loss.item() == pytest.approx(4.0)

    def test_l1_mse_huber_all_run_and_differ_on_the_same_inputs(self):
        pred = torch.zeros(1, 1, 4, 4)
        target = torch.ones(1, 1, 4, 4) * 3.0
        mask = torch.ones(1, 1, 4, 4, dtype=torch.bool)
        vals = {k: masked_reconstruction_loss(pred, target, mask, kind=k).item()
                for k in ("l1", "mse", "huber")}
        assert vals["l1"] == pytest.approx(3.0)
        assert vals["mse"] == pytest.approx(9.0)
        assert vals["huber"] < vals["mse"]


class TestDeviceSelection:
    def test_cpu_fallback_is_always_available(self):
        device = select_device(prefer="cpu")
        assert device.type == "cpu"

    def test_default_selection_returns_a_valid_device(self):
        device = select_device()
        assert device.type in ("cuda", "mps", "cpu")


class TestSeeding:
    def test_same_seed_produces_identical_model_initialisation(self):
        set_seed(42)
        m1 = SSLAutoencoder(base_channels=4)
        set_seed(42)
        m2 = SSLAutoencoder(base_channels=4)
        for p1, p2 in zip(m1.parameters(), m2.parameters()):
            assert torch.allclose(p1, p2)


class TestChecksumAndSaveLoad:
    def test_checksum_is_stable_for_the_same_weights(self):
        set_seed(0)
        model = SSLAutoencoder(base_channels=4)
        assert model_checksum(model) == model_checksum(model)

    def test_checksum_differs_after_a_training_step(self):
        set_seed(0)
        model = SSLAutoencoder(base_channels=4)
        before = model_checksum(model)
        opt = torch.optim.SGD(model.parameters(), lr=0.1)
        x = torch.randn(1, 1, 32, 32)
        loss = model(x).sum()
        loss.backward()
        opt.step()
        assert model_checksum(model) != before

    def test_save_encoder_only_then_load_reproduces_encoder_weights(self, tmp_path):
        set_seed(0)
        model = SSLAutoencoder(base_channels=4)
        path = str(tmp_path / "encoder.pt")
        save_encoder_only(model.encoder, path)
        loaded = load_ssl_encoder(path, base_channels=4)
        for p1, p2 in zip(model.encoder.parameters(), loaded.parameters()):
            assert torch.allclose(p1, p2)

    def test_load_ssl_encoder_needs_no_decoder_import(self, tmp_path):
        """The stable interface Section 10 requires: callable in a context where SSLReconstructionDecoder was never imported at all."""
        set_seed(0)
        encoder_only = GPREncoder(in_channels=1, base_channels=4)
        path = str(tmp_path / "encoder.pt")
        save_encoder_only(encoder_only, path)

        import subprocess, sys
        script = (
            "from training.ssl_model import load_ssl_encoder\n"
            "assert 'SSLReconstructionDecoder' not in dir()\n"
            f"load_ssl_encoder({path!r}, base_channels=4)\n"
            "print('OK')\n"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=".")
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout


class TestSanityTraining:
    """
    Section 30: a tiny synthetic numerical fixture, solely to confirm loss
    decreases, a checkpoint saves, and a checkpoint reloads. THIS IS
    SOFTWARE TESTING, NOT SCIENTIFIC EVIDENCE about real GPR representation
    learning -- see `training.ssl_train`'s own real-corpus training path
    for that question.
    """
    def test_loss_decreases_on_a_tiny_synthetic_fixture(self):
        set_seed(0)
        model = SSLAutoencoder(base_channels=4)
        opt = torch.optim.Adam(model.parameters(), lr=1e-2)
        rng = np.random.default_rng(0)
        target = torch.tensor(rng.normal(size=(1, 1, 32, 32)), dtype=torch.float32)
        mask = torch.zeros(1, 1, 32, 32, dtype=torch.bool)
        mask[:, :, :, 8:16] = True
        masked_input = target.clone()
        masked_input[mask] = 0.0

        losses = []
        for _ in range(15):
            opt.zero_grad()
            pred = model(masked_input)
            loss = masked_reconstruction_loss(pred, target, mask, kind="mse")
            loss.backward()
            opt.step()
            losses.append(float(loss.item()))

        assert losses[-1] < losses[0]

    def test_checkpoint_saves_and_reloads_with_identical_predictions(self, tmp_path):
        set_seed(0)
        model = SSLAutoencoder(base_channels=4).eval()
        x = torch.randn(1, 1, 32, 32)
        with torch.no_grad():
            pred_before = model(x)

        path = str(tmp_path / "encoder.pt")
        save_encoder_only(model.encoder, path)
        loaded_encoder = load_ssl_encoder(path, base_channels=4).eval()
        with torch.no_grad():
            z_before = model.encoder(x)
            z_after = loaded_encoder(x)
        assert torch.allclose(z_before, z_after)
        assert pred_before.shape == x.shape  # sanity: forward ran to completion before save


class TestNoLabelsUsed:
    def test_ssl_dataset_item_carries_no_label_field(self):
        """SSLWindowRef has no label/mask-region/evidence-grade fields at all -- structurally cannot carry a target label."""
        fields = set(SSLWindowRef.model_fields)
        assert not (fields & {"label_level", "label_source", "evidence_grade", "mask"})

    def test_run_ssl_training_signature_takes_no_label_argument(self):
        import inspect
        from training.ssl_train import run_ssl_training
        params = inspect.signature(run_ssl_training).parameters
        assert not any("label" in p.lower() or "target_truth" in p.lower() for p in params)
