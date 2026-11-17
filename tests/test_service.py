"""The workflow layer, called the way the desktop window will call it."""

import os
import re

import pytest

import sanitizer_core as sc
import sanitizer_service as service
from sanitizer_core import GlinerDetector

TEXT = (
    "John A. Smith sued Acme Corporation. Smith's SSN is 123-45-6789. "
    "The American Arbitration Association heard it. Gerry testified for Acme."
)
PASSPHRASE = "correct horse battery"


class FakeModel:
    def __init__(self, known):
        self.known, self.calls = known, 0

    def predict_entities(self, text, labels, threshold=0.5):
        self.calls += 1
        return [
            {"start": m.start(), "end": m.end(), "label": label}
            for name, label in self.known.items()
            for m in re.finditer(re.escape(name), text)
        ]


@pytest.fixture(autouse=True)
def detector(monkeypatch):
    fake = GlinerDetector(
        model=FakeModel({"John A. Smith": "person", "Acme Corporation": "company",
                         "American Arbitration Association": "company"}),
        window_words=8, overlap_words=2,
    )  # fmt: skip
    monkeypatch.setattr(sc, "_default_detector", fake)
    return fake


@pytest.fixture
def case(tmp_path):
    doc = tmp_path / "case.txt"
    doc.write_text(TEXT)
    return str(doc), str(tmp_path / "matter.vault")


def test_service_has_no_terminal_or_gui_in_it():
    source = open(service.__file__, encoding="utf-8").read()
    assert not re.search(r"\bprint\(|\binput\(|getpass|PySide|argparse", source)


def test_scan_returns_review_rows_and_changes_nothing(case):
    doc, vault_path = case
    vault = service.open_matter(vault_path, PASSPHRASE)
    scan = service.scan_document(doc, vault)
    rows = {i.value: i for i in scan.items}
    assert rows["John A. Smith"].type == "person" and rows["John A. Smith"].times == 1
    assert rows["Smith"].source == "propagated" and rows["Smith"].entity_hint == "John A. Smith"
    assert rows["Acme"].entity_hint == "Acme Corporation" and rows["Acme Corporation"].entity_hint == ""
    assert rows["123-45-6789"].source == "regex"
    assert scan.already_known == 0 and vault == sc.new_vault()
    assert os.listdir(os.path.dirname(doc)) == ["case.txt"]


def test_progress_is_reported_and_cancel_stops_the_scan(case, detector):
    doc, vault_path = case
    vault = service.open_matter(vault_path, PASSPHRASE)
    seen = []
    service.scan_document(doc, vault, progress=lambda done, total: seen.append((done, total)))
    total = seen[0][1]
    assert total > 2 and seen[0] == (0, total) and seen[-1] == (total, total)
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)

    calls_before = detector.model.calls
    with pytest.raises(sc.ScanCancelled):
        service.scan_document(doc, vault, cancelled=lambda: detector.model.calls >= calls_before + 2)
    assert detector.model.calls == calls_before + 2
    assert os.listdir(os.path.dirname(doc)) == ["case.txt"]


def test_review_helpers(case):
    doc, vault_path = case
    scan = service.scan_document(doc, service.open_matter(vault_path, PASSPHRASE))
    spans = service.occurrences(scan.text, "Acme")
    assert [scan.text[a:b] for a, b in spans] == ["Acme", "Acme"]
    assert "«Acme»" in service.context(scan.text, *spans[1]) and "Gerry testified" in service.context(scan.text, *spans[1])
    assert service.validate_edit(scan, "Gerry") is None
    assert "does not appear" in service.validate_edit(scan, "Nobody Here")
    assert service.validate_edit(scan, "  ") is not None
    assert service.make_item(scan, "person", "Gerry") == service.Item("person", "Gerry", "manual", 1)


def test_commit_with_reviewed_decisions(case):
    doc, vault_path = case
    scan = service.scan_document(doc, service.open_matter(vault_path, PASSPHRASE))
    accepted = [i for i in scan.items if "Arbitration" not in i.value]
    accepted.append(service.make_item(scan, "person", "Gerry"))
    result = service.commit(scan, accepted, ["American Arbitration Association"], True, vault_path, PASSPHRASE)

    safe = open(result.output_path, encoding="utf-8").read()
    for leak in ("Smith", "Acme", "123-45-6789", "Gerry"):
        assert leak not in safe
    assert "American Arbitration Association" in safe
    assert result.added == len(accepted) and result.declined == 1 and result.reviewed
    assert result.replaced == len(sc.find_vault_spans(TEXT, result.vault))

    reopened = service.open_matter(vault_path, PASSPHRASE)
    assert reopened == result.vault and reopened["declined"] == ["American Arbitration Association"]
    assert all(e["reviewed"] is True for e in reopened["mappings"].values())
    assert sc.rehydrate_text(safe, reopened) == TEXT
    # a second scan of the same document proposes nothing new
    again = service.scan_document(doc, reopened)
    assert again.items == [] and again.already_known == len(reopened["mappings"])


def test_commit_is_all_or_nothing(case, monkeypatch):
    doc, vault_path = case
    scan = service.scan_document(doc, service.open_matter(vault_path, PASSPHRASE))

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(sc, "save_vault", fail)
    with pytest.raises(OSError):
        service.commit(scan, scan.items, [], True, vault_path, PASSPHRASE)
    assert os.listdir(os.path.dirname(doc)) == ["case.txt"]  # no output, no vault, no temp file


def test_wrong_passphrase_and_plaintext_vault_are_service_errors(case, tmp_path):
    doc, vault_path = case
    scan = service.scan_document(doc, service.open_matter(vault_path, PASSPHRASE))
    service.commit(scan, scan.items, [], False, vault_path, PASSPHRASE)
    with pytest.raises(service.ServiceError, match="Wrong passphrase"):
        service.open_matter(vault_path, "not it")
    sc.save_vault(sc.new_vault(), tmp_path / "plain.json")
    with pytest.raises(service.ServiceError, match="not an encrypted vault"):
        service.open_matter(str(tmp_path / "plain.json"), PASSPHRASE)
    empty = tmp_path / "empty.txt"
    empty.write_text(" ")
    with pytest.raises(service.ServiceError, match="No text found"):
        service.read_document(str(empty))


def test_restore_and_keys(case, tmp_path):
    doc, vault_path = case
    scan = service.scan_document(doc, service.open_matter(vault_path, PASSPHRASE))
    result = service.commit(scan, scan.items, [], False, vault_path, PASSPHRASE)
    assert not result.reviewed and all(e["reviewed"] is False for e in result.vault["mappings"].values())

    answer = tmp_path / "answer.txt"
    answer.write_text("[person_1] beat [COMPANY_1]; see [PERSON_99].")
    restored = service.restore(str(answer), result.vault)
    assert open(restored.output_path).read() == "John A. Smith beat Acme Corporation; see [PERSON_99]."
    assert restored.restored == 2 and restored.altered == ["[person_1]"] and restored.unknown == ["[PERSON_99]"]
    strict = service.restore(str(answer), result.vault, tolerant=False)
    assert strict.restored == 1 and strict.altered == []

    keys = service.write_keys(result.vault, result.output_path, vault_path, fmt="txt")
    assert "John A. Smith" in open(keys.confidential_path).read()
    assert "Smith" not in open(keys.safe_path).read() and keys.count == len(result.vault["mappings"])
    only_safe = service.write_keys(result.vault, None, vault_path, fmt="csv", confidential=False)
    assert only_safe.confidential_path is None and os.path.exists(only_safe.safe_path)

    summary = service.vault_summary(result.vault)
    assert summary["unreviewed"] == summary["mappings"] == len(result.vault["mappings"])


def test_output_path_refuses_the_original_the_matter_and_wrong_formats(case, tmp_path):
    doc, vault_path = case
    vault = service.open_matter(vault_path, PASSPHRASE)
    scan = service.scan_document(doc, vault)
    items = scan.items
    for bad in (doc, vault_path, str(tmp_path / "out.docx"), str(tmp_path / "no-such-folder" / "out.txt")):
        with pytest.raises(service.ServiceError):
            service.commit(scan, items, [], True, vault_path, PASSPHRASE, output_path=bad)
    assert open(doc).read() == TEXT and not os.path.exists(vault_path)  # nothing written, original intact
    assert sorted(os.listdir(tmp_path)) == ["case.txt"]

    chosen = str(tmp_path / "for the analyst.md")  # any other extension is plain text
    result = service.commit(scan, items, [], True, vault_path, PASSPHRASE, output_path=chosen)
    assert result.output_path == chosen and "Smith" not in open(chosen).read()
    with pytest.raises(service.ServiceError):
        service.restore(chosen, result.vault, output_path=chosen)
    restored = service.restore(chosen, result.vault, output_path=str(tmp_path / "back.txt"))
    assert open(restored.output_path).read() == TEXT


def test_output_formats_follow_the_input():
    assert service.output_formats("a.docx", "sanitized") == [".docx", ".txt"]
    assert service.output_formats("a.txt", "sanitized") == [".txt"]
    assert service.output_formats("a.pdf", "rehydrated") == [".txt"]
    assert service.check_output_path("a.docx", "b.docx", "sanitized") is None
    assert "cannot be written" in service.check_output_path("a.txt", "b.pdf", "sanitized")
