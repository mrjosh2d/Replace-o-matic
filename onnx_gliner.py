"""Run a GLiNER ONNX model with onnxruntime and tokenizers only.

The ``gliner`` package needs PyTorch and transformers (several GB) even when
inference runs on ONNX. This module does the same pre- and post-processing for
span-mode GLiNER models directly, so a packaged app needs only ``onnxruntime``,
``tokenizers`` and ``numpy``. ``predict_entities`` matches ``gliner``'s method
of the same name; tests compare the two on the labelled passages.

Import ``sanitizer_core`` first: it switches off onnxruntime's telemetry.
"""

from __future__ import annotations

import json
import os
import re

import numpy as np

_WORD = re.compile(r"\w+(?:[-_]\w+)*|\S")  # gliner's whitespace word splitter


class OnnxGliner:
    def __init__(self, model_dir: str, onnx_file: str = "onnx/model.onnx"):
        import onnxruntime
        from tokenizers import Tokenizer

        with open(os.path.join(model_dir, "gliner_config.json"), encoding="utf-8") as fh:
            config = json.load(fh)
        if config.get("span_mode") != "markerV0" or config.get("subtoken_pooling", "first") != "first":
            raise ValueError("Only span-mode GLiNER models (markerV0, first-subtoken pooling) are supported.")
        self.max_width = config["max_width"]
        self.max_len = config["max_len"]
        self.ent_token = config["ent_token"]
        self.sep_token = config["sep_token"]
        self.tokenizer = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tokenizer.no_padding()
        self.tokenizer.no_truncation()
        options = onnxruntime.SessionOptions()
        options.log_severity_level = 3
        self.session = onnxruntime.InferenceSession(
            os.path.join(model_dir, onnx_file), options, providers=["CPUExecutionProvider"]
        )

    def predict_entities(self, text: str, labels: list[str], threshold: float = 0.5) -> list[dict]:
        """Non-overlapping entities: dicts with start, end, text, label, score."""
        words = [(m.start(), m.end()) for m in _WORD.finditer(text)][: self.max_len]
        if not words:
            return []
        n = len(words)

        # Prompt "<<ENT>> label ... <<SEP>>" followed by the text, one word per item.
        prompt = [token for label in labels for token in (self.ent_token, label)] + [self.sep_token]
        encoding = self.tokenizer.encode(prompt + [text[a:b] for a, b in words], is_pretokenized=True)
        words_mask = np.zeros(len(encoding.ids), dtype=np.int64)
        previous = None
        for position, word_id in enumerate(encoding.word_ids):
            if word_id is not None and word_id != previous and word_id >= len(prompt):
                words_mask[position] = word_id - len(prompt) + 1  # first sub-token of each text word
            previous = word_id

        starts = np.repeat(np.arange(n), self.max_width)
        ends = starts + np.tile(np.arange(self.max_width), n)
        logits = self.session.run(
            ["logits"],
            {
                "input_ids": np.array([encoding.ids], dtype=np.int64),
                "attention_mask": np.ones((1, len(encoding.ids)), dtype=np.int64),
                "words_mask": words_mask[None, :],
                "text_lengths": np.array([[n]], dtype=np.int64),
                "span_idx": np.stack([starts, ends], axis=1)[None, :, :],
                "span_mask": (ends < n)[None, :],
            },
        )[0][0]  # (words, max_width, labels)
        scores = 1.0 / (1.0 + np.exp(-logits[:n]))

        candidates = [
            (float(scores[i, w, c]), int(i), int(i + w), int(c))
            for i, w, c in zip(*np.nonzero(scores > threshold))
            if i + w < n
        ]
        # Greedy: best score first, dropping anything that overlaps a kept span.
        kept: list[tuple] = []
        for candidate in sorted(candidates, key=lambda item: -item[0]):
            _, start, end, _ = candidate
            if all(end < k[1] or start > k[2] for k in kept):
                kept.append(candidate)
        return [
            {
                "start": words[start][0],
                "end": words[end][1],
                "text": text[words[start][0] : words[end][1]],
                "label": labels[label],
                "score": score,
            }
            for score, start, end, label in sorted(kept, key=lambda item: item[1])
        ]
