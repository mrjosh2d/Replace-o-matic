import os
import re

import pytest

import sanitizer_core
from sanitizer_core import (
    DEFAULT_MODEL_DIR,
    GlinerDetector,
    ModelNotFoundError,
    apply_vault,
    merge_vault,
    rehydrate_text,
    scan_text,
)


class FakeModel:
    """Stands in for GLiNER: tags known strings and, like the real model,
    ignores everything past its input limit."""

    def __init__(self, known, limit_words=10**9):
        self.known, self.limit_words, self.calls = known, limit_words, []

    def predict_entities(self, text, labels, threshold=0.5):
        self.calls.append(text)
        visible_end = ([m.end() for m in re.finditer(r"\S+", text)][: self.limit_words] or [0])[-1]
        return [
            {"start": m.start(), "end": m.end(), "text": name, "label": label, "score": 0.9}
            for name, label in self.known.items()
            if label in labels
            for m in re.finditer(re.escape(name), text)
            if m.end() <= visible_end
        ]


def test_labels_map_to_entity_types_and_offsets_are_document_relative():
    text = "Filler. " * 5 + "Jane Doe of Acme Corp lives at 1 Main St."
    model = FakeModel({"Jane Doe": "person", "Acme Corp": "organization", "1 Main St": "address"})
    found = {(text[d.start : d.end], d.type) for d in GlinerDetector(model=model)(text)}
    assert found == {("Jane Doe", "person"), ("Acme Corp", "company"), ("1 Main St", "address")}


def test_long_document_is_windowed_so_late_entities_are_not_lost():
    text = "word " * 1000 + "Jane Doe signed. " + "word " * 1000 + "Then Bob Ray left."
    model = FakeModel({"Jane Doe": "person", "Bob Ray": "person"}, limit_words=250)
    detector = GlinerDetector(model=model, window_words=200, overlap_words=40)
    assert {text[d.start : d.end] for d in detector(text)} == {"Jane Doe", "Bob Ray"}
    assert len(model.calls) > 10
    assert all(len(chunk.split()) <= 200 for chunk in model.calls)


def test_entity_straddling_a_window_edge_is_caught_by_the_overlap():
    words = ["w"] * 199 + ["Jane", "Doe"] + ["w"] * 158 + ["Bob", "Ray"] + ["w"] * 50
    text = " ".join(words)  # both names straddle the end of a 200-word window
    model = FakeModel({"Jane Doe": "person", "Bob Ray": "person"})
    detector = GlinerDetector(model=model, window_words=200, overlap_words=40)
    proposal = scan_text(text, ner=detector)
    assert {e["value"] for e in proposal["proposed"].values()} == {"Jane Doe", "Bob Ray"}
    assert model.calls[0].endswith("Jane")  # the first window really did cut the name


def window_texts(text, **kw):
    detector = GlinerDetector(model=FakeModel({}), **kw)
    return [text[a:b] for a, b in detector._windows(text)]


def test_windows_prefer_paragraph_breaks_then_sentence_ends():
    para = "one two three four five six seven. eight nine ten"
    text = para + "\n\n" + "alpha beta gamma delta epsilon zeta eta theta. iota kappa lambda mu nu xi"
    chunks = window_texts(text, window_words=12, overlap_words=2)
    assert chunks[0] == para  # cut at the blank line, not mid-sentence at word 12
    assert chunks[1].startswith("nine ten")  # overlap is kept
    assert chunks[1].endswith("theta.")  # no paragraph break in range: cut at sentence end


def test_windows_cover_every_word_and_never_exceed_the_limit():
    import random

    rng = random.Random(7)
    words = [rng.choice(["Mr.", "x", "end.", "word", "a;", "b\n\nc", "d\ne"]) for _ in range(3000)]
    text = " ".join(words)
    detector = GlinerDetector(model=FakeModel({}), window_words=50, overlap_words=10)
    covered = set()
    previous_end = 0
    for a, b in detector._windows(text):
        assert len(text[a:b].split()) <= 50
        assert a <= previous_end  # no gap between consecutive windows
        covered.update(range(a, b))
        previous_end = b
    assert all(i in covered for i, ch in enumerate(text) if not ch.isspace())


def test_overlap_must_leave_room_to_advance():
    with pytest.raises(ValueError):
        GlinerDetector(model=FakeModel({}), window_words=10, overlap_words=5)


def test_empty_and_whitespace_text():
    detector = GlinerDetector(model=FakeModel({}))
    assert detector("") == [] and detector("  \n ") == []


def test_missing_model_fails_loudly_instead_of_skipping_names(tmp_path, monkeypatch):
    with pytest.raises(ModelNotFoundError):
        GlinerDetector(model_dir=tmp_path)
    monkeypatch.setattr(sanitizer_core, "_default_detector", None)
    monkeypatch.setattr(sanitizer_core, "DEFAULT_MODEL_DIR", str(tmp_path))
    with pytest.raises(ModelNotFoundError):
        scan_text("John Smith signed.")
    assert scan_text("John Smith signed.", ner=False)["proposed"] == {}


# ---- real model; skipped until scripts/fetch_model.py has been run ----

needs_model = pytest.mark.skipif(
    not any(
        os.path.isfile(os.path.join(DEFAULT_MODEL_DIR, f))
        for f in ("onnx/model.onnx", "model.onnx")
    ),
    reason="GLiNER model not downloaded (run scripts/fetch_model.py)",
)


@pytest.mark.model
@needs_model
def test_real_model_end_to_end_without_network(monkeypatch):
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    from test_sanitizer_core import DOCUMENT

    proposal = scan_text(DOCUMENT)
    vault = merge_vault(None, proposal["proposed"])
    safe = apply_vault(DOCUMENT, vault)
    for leak in ("Smith", "Johnson", "Acme", "ACME", "Evergreen", "Springfield", "6789", "555-0147", "021000021", "@"):
        assert leak not in safe, leak
    assert rehydrate_text(safe, vault) == DOCUMENT

    entity_of = {e["value"]: e["entity"] for e in vault["mappings"].values()}
    assert entity_of["John A. Smith"] == entity_of["Smith"]
    assert entity_of["Mary Smithson"] != entity_of["Smith"]
    assert entity_of["Acme Corporation"] == entity_of["Acme"]
    assert entity_of["Acme Holdings LLC"] != entity_of["Acme Corporation"]


def load_eval(name):
    import json

    path = os.path.join(os.path.dirname(__file__), "eval", name)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize("name", ["passages.json", "holdout.json"])
def test_eval_labels_occur_in_their_passages(name):
    for passage in load_eval(name):
        for entity in passage["entities"]:
            assert entity["text"] in passage["text"], (passage["id"], entity["text"])
            assert entity["type"] in sanitizer_core.ENTITY_TYPES


@pytest.mark.model
@needs_model
def test_recall_on_labelled_passages_does_not_regress():
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    from evaluate import evaluate

    stats, leaks, extras = evaluate(load_eval("passages.json"), sanitizer_core.default_detector())
    assert stats["hit_chars"] / stats["gold_chars"] >= 0.99, leaks
    assert len(extras) <= 3, extras
