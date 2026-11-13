"""One-time download of the GLiNER ONNX model into ./models/gliner.

This is the only part of the project that touches the network, and it only
downloads. Run it once on a connected machine; after that, sanitizer_core
loads the model from disk with the Hugging Face libraries in offline mode.

    python scripts/fetch_model.py [--repo REPO] [--dest DIR]
"""

import argparse
import os

DEFAULT_REPO = "onnx-community/gliner_small-v2.1"
DEFAULT_DEST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "gliner"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--dest", default=DEFAULT_DEST)
    args = parser.parse_args()

    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    from huggingface_hub import snapshot_download

    snapshot_download(
        args.repo,
        local_dir=args.dest,
        # Full-precision ONNX weights plus config and tokenizer; skip other variants.
        allow_patterns=["*.json", "*.txt", "*.model", "onnx/model.onnx", "model.onnx"],
    )
    print(f"Model saved to {args.dest}")


if __name__ == "__main__":
    main()
