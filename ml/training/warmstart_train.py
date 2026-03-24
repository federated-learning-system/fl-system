"""
ml/training/warmstart_train.py

Warm-start training for NextWordLSTM on Wikipedia Simple English.

Creates a sliding-window dataset: input = tokens[i:i+10], target = tokens[i+10].
Trains for 3 epochs with Adam (lr=1e-3), cross-entropy loss, batch size 128.
Saves checkpoints per epoch and a final model.

Usage:
    .venv/bin/python ml/training/warmstart_train.py                    # full training
    .venv/bin/python ml/training/warmstart_train.py --max-steps 1000 --smoke-test  # quick test
    .venv/bin/python ml/training/warmstart_train.py --epochs 5         # more epochs
    .venv/bin/python ml/training/warmstart_train.py --device cuda       # GPU if available

Environment:
    Runs on CPU by default. Set --device cuda for GTX 1650 acceleration.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset, random_split

# Repo root for imports
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from ml.model.lstm_model import NextWordLSTM
from ml.model.model_config import ModelConfig
from ml.tokenizer.tokenizer import FLTokenizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────────
TOKENIZER_MODEL = _REPO_ROOT / "ml" / "tokenizer" / "vocab_8192.model"
CHECKPOINT_DIR = Path(__file__).resolve().parent / "checkpoints"
FINAL_MODEL_PATH = Path(__file__).resolve().parent / "warmstart_final.pt"


# ── Dataset ─────────────────────────────────────────────────────────────────

class SlidingWindowDataset(Dataset):
    """
    Sliding window over a flat token array.
    input  = tokens[i : i+seq_len]     (10 tokens)
    target = tokens[i + seq_len]        (next token)
    """

    def __init__(self, token_ids: list[int], seq_len: int = 10) -> None:
        self.data = torch.tensor(token_ids, dtype=torch.long)
        self.seq_len = seq_len

    def __len__(self) -> int:
        return len(self.data) - self.seq_len

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        x = self.data[idx : idx + self.seq_len]
        y = self.data[idx + self.seq_len]
        return x, y


def build_corpus_tokens(tokenizer: FLTokenizer, max_articles: int | None = None) -> list[int]:
    """Load Wikipedia Simple English and tokenize all articles into a flat list."""
    from datasets import load_dataset

    log.info("Loading Wikipedia Simple English...")
    ds = load_dataset("wikimedia/wikipedia", "20231101.simple", split="train")

    all_tokens: list[int] = []
    n = len(ds) if max_articles is None else min(max_articles, len(ds))
    log.info("Tokenizing %d articles...", n)

    for i in range(n):
        text = ds[i]["text"].strip()
        if text:
            tokens = tokenizer.encode(text)
            all_tokens.extend(tokens)
        if (i + 1) % 20_000 == 0:
            log.info("  %d / %d articles tokenized (%d tokens so far)", i + 1, n, len(all_tokens))

    log.info("Total tokens: %d", len(all_tokens))
    return all_tokens


# ── Training loop ───────────────────────────────────────────────────────────

def train_epoch(
    model: NextWordLSTM,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    criterion: nn.Module,
    device: torch.device,
    max_steps: int | None = None,
) -> float:
    """Train one epoch. Returns average loss."""
    model.train()
    total_loss = 0.0
    n_batches = 0

    for step, (x, y) in enumerate(loader):
        if max_steps is not None and step >= max_steps:
            break

        x, y = x.to(device), y.to(device)
        optimizer.zero_grad()
        logits, _ = model(x)
        loss = criterion(logits, y)
        loss.backward()
        # Gradient clipping to stabilize training
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()

        total_loss += loss.item()
        n_batches += 1

        if (step + 1) % 500 == 0:
            avg = total_loss / n_batches
            log.info("  step %d  loss=%.4f  ppl=%.2f", step + 1, avg, math.exp(min(avg, 20)))

    return total_loss / max(n_batches, 1)


@torch.no_grad()
def evaluate(
    model: NextWordLSTM,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    max_steps: int | None = None,
) -> tuple[float, float]:
    """Evaluate on validation set. Returns (avg_loss, perplexity)."""
    model.eval()
    total_loss = 0.0
    n_batches = 0

    for step, (x, y) in enumerate(loader):
        if max_steps is not None and step >= max_steps:
            break
        x, y = x.to(device), y.to(device)
        logits, _ = model(x)
        loss = criterion(logits, y)
        total_loss += loss.item()
        n_batches += 1

    avg_loss = total_loss / max(n_batches, 1)
    perplexity = math.exp(min(avg_loss, 20))  # cap to avoid overflow
    return avg_loss, perplexity


def save_checkpoint(
    model: NextWordLSTM,
    optimizer: torch.optim.Optimizer,
    epoch: int,
    train_loss: float,
    val_loss: float,
    val_perplexity: float,
    config: ModelConfig,
    path: Path,
) -> None:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "epoch": epoch,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "train_loss": train_loss,
            "val_loss": val_loss,
            "val_perplexity": val_perplexity,
            "model_config": config.to_dict(),
        },
        path,
    )
    log.info("Checkpoint saved: %s", path)


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Warm-start LSTM training")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--seq-len", type=int, default=10)
    parser.add_argument("--device", type=str, default="cpu")
    parser.add_argument("--max-steps", type=int, default=None, help="Limit steps per epoch (for smoke test)")
    parser.add_argument("--max-articles", type=int, default=None, help="Limit articles to tokenize")
    parser.add_argument("--smoke-test", action="store_true", help="Quick smoke test mode")
    parser.add_argument("--workers", type=int, default=2, help="DataLoader workers")
    args = parser.parse_args()

    if args.smoke_test:
        if args.max_steps is None:
            args.max_steps = 1000
        if args.max_articles is None:
            args.max_articles = 5000
        args.epochs = min(args.epochs, 2)
        log.info("SMOKE TEST mode: max_steps=%d, max_articles=%d, epochs=%d",
                 args.max_steps, args.max_articles, args.epochs)

    device = torch.device(args.device)
    log.info("Device: %s", device)

    # Load tokenizer
    assert TOKENIZER_MODEL.exists(), f"Tokenizer not found: {TOKENIZER_MODEL}. Run train_tokenizer.py first."
    tokenizer = FLTokenizer(str(TOKENIZER_MODEL))
    log.info("Tokenizer loaded: vocab_size=%d", tokenizer.vocab_size())

    # Build token corpus
    all_tokens = build_corpus_tokens(tokenizer, max_articles=args.max_articles)

    # Create dataset and split 95/5
    full_ds = SlidingWindowDataset(all_tokens, seq_len=args.seq_len)
    val_size = max(1, int(len(full_ds) * 0.05))
    train_size = len(full_ds) - val_size
    train_ds, val_ds = random_split(
        full_ds, [train_size, val_size], generator=torch.Generator().manual_seed(42)
    )
    log.info("Dataset: %d train, %d val windows (from %d tokens)", train_size, val_size, len(all_tokens))

    train_loader = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True,
        num_workers=args.workers, pin_memory=(device.type == "cuda"),
    )
    val_loader = DataLoader(
        val_ds, batch_size=args.batch_size, shuffle=False,
        num_workers=args.workers, pin_memory=(device.type == "cuda"),
    )

    # Model
    config = ModelConfig(seq_len=args.seq_len)
    model = NextWordLSTM.from_config(config).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    log.info("Model: NextWordLSTM (%s params)", f"{n_params:,}")

    # Optimizer & loss
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.CrossEntropyLoss(ignore_index=0)  # ignore PAD

    # Training loop
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    best_val_ppl = float("inf")

    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        log.info("=== Epoch %d/%d ===", epoch, args.epochs)

        train_loss = train_epoch(model, train_loader, optimizer, criterion, device, max_steps=args.max_steps)
        val_loss, val_ppl = evaluate(model, val_loader, criterion, device,
                                     max_steps=args.max_steps // 5 if args.max_steps else None)

        elapsed = time.time() - t0
        log.info(
            "Epoch %d: train_loss=%.4f  val_loss=%.4f  val_ppl=%.2f  time=%.1fs",
            epoch, train_loss, val_loss, val_ppl, elapsed,
        )

        # Save epoch checkpoint
        ckpt_path = CHECKPOINT_DIR / f"warmstart_epoch_{epoch}.pt"
        save_checkpoint(model, optimizer, epoch, train_loss, val_loss, val_ppl, config, ckpt_path)

        if val_ppl < best_val_ppl:
            best_val_ppl = val_ppl

    # Save final model
    save_checkpoint(model, optimizer, args.epochs, train_loss, val_loss, val_ppl, config, FINAL_MODEL_PATH)
    log.info("Training complete. Best val perplexity: %.2f", best_val_ppl)
    log.info("Final model: %s", FINAL_MODEL_PATH)


if __name__ == "__main__":
    main()
