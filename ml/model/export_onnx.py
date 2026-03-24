"""
ml/model/export_onnx.py

Exports a trained NextWordLSTM checkpoint to ONNX (float32) and INT8 quantized ONNX.

Outputs:
    ml/model/model.onnx       — float32 (~16 MB)
    ml/model/model_quant.onnx — INT8 dynamic quantization (~4-12 MB)

Input names:  token_ids [batch, seq_len], hidden_h [num_layers, batch, hidden], hidden_c [...]
Output names: logits [batch, vocab_size], out_hidden_h [...], out_hidden_c [...]
Dynamic axes on batch dimension. opset_version=17.

Usage:
    .venv/bin/python ml/model/export_onnx.py
    .venv/bin/python ml/model/export_onnx.py --checkpoint ml/training/warmstart_final.pt
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import torch

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from ml.model.lstm_model import NextWordLSTM
from ml.model.model_config import ModelConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parent
DEFAULT_CHECKPOINT = _REPO_ROOT / "ml" / "training" / "warmstart_final.pt"


def export_float32(model: NextWordLSTM, config: ModelConfig, output_path: Path) -> None:
    """Export PyTorch model to ONNX float32."""
    model.eval()
    batch = 1
    seq_len = config.seq_len
    num_layers = config.num_layers
    hidden_size = config.hidden_size

    # Dummy inputs
    token_ids = torch.randint(0, config.vocab_size, (batch, seq_len))
    hidden_h = torch.zeros(num_layers, batch, hidden_size)
    hidden_c = torch.zeros(num_layers, batch, hidden_size)

    dynamic_axes = {
        "token_ids": {0: "batch"},
        "hidden_h": {1: "batch"},
        "hidden_c": {1: "batch"},
        "logits": {0: "batch"},
        "out_hidden_h": {1: "batch"},
        "out_hidden_c": {1: "batch"},
    }

    torch.onnx.export(
        model,
        (token_ids, (hidden_h, hidden_c)),
        str(output_path),
        input_names=["token_ids", "hidden_h", "hidden_c"],
        output_names=["logits", "out_hidden_h", "out_hidden_c"],
        dynamic_axes=dynamic_axes,
        opset_version=17,
        do_constant_folding=True,
    )
    size_mb = output_path.stat().st_size / (1024 * 1024)
    log.info("Float32 ONNX exported: %s (%.1f MB)", output_path, size_mb)


def quantize_int8(input_path: Path, output_path: Path) -> None:
    """Apply INT8 dynamic quantization to an ONNX model."""
    from onnxruntime.quantization import QuantType, quantize_dynamic

    quantize_dynamic(
        model_input=str(input_path),
        model_output=str(output_path),
        weight_type=QuantType.QInt8,
    )
    size_mb = output_path.stat().st_size / (1024 * 1024)
    log.info("INT8 quantized ONNX exported: %s (%.1f MB)", output_path, size_mb)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export LSTM to ONNX")
    parser.add_argument("--checkpoint", type=str, default=str(DEFAULT_CHECKPOINT))
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR))
    args = parser.parse_args()

    ckpt_path = Path(args.checkpoint)
    out_dir = Path(args.output_dir)
    assert ckpt_path.exists(), f"Checkpoint not found: {ckpt_path}"

    # Load checkpoint
    log.info("Loading checkpoint: %s", ckpt_path)
    checkpoint = torch.load(ckpt_path, map_location="cpu", weights_only=False)

    # Reconstruct model from saved config (or defaults)
    if "model_config" in checkpoint:
        config = ModelConfig.from_dict(checkpoint["model_config"])
    else:
        config = ModelConfig()

    model = NextWordLSTM.from_config(config)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    log.info("Model loaded: %s params", f"{sum(p.numel() for p in model.parameters()):,}")

    # Export float32
    fp32_path = out_dir / "model.onnx"
    export_float32(model, config, fp32_path)

    # Quantize to INT8
    int8_path = out_dir / "model_quant.onnx"
    quantize_int8(fp32_path, int8_path)

    log.info("Done.")


if __name__ == "__main__":
    main()
