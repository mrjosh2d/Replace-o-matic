import json
import re
import zipfile

import pytest

import sanitizer_cli as cli
import sanitizer_core as sc
from sanitizer_core import Detection

TEXT = (
    "John A. Smith sued Acme Corporation. Smith's SSN is 123-45-6789. "
    "The American Arbitration Association heard it. Gerry testified for Acme."
)
PASSPHRASE = "correct horse battery"


@pytest.fixture(autouse=True)
def stub_model(monkeypatch):
    """Replace the GLiNER model with a fixed detector and supply the passphrase."""

    def detector(text):
        found = []
        for etype, names in {
            "person": ["John A. Smith"],
            "company": ["Acme Corporation", "American Arbitration Association"],
        }.items():
            for name in names:
                found += [Detection(m.start(), m.end(), etype) for m in re.finditer(re.escape(name), text)]
        return found

    monkeypatch.setattr(sc, "_default_detector", detector)
    monkeypatch.setenv(cli.PASSPHRASE_ENV, PASSPHRASE)


def run(argv, answers=()):
    answers = iter(answers)
    printed = []
    code = cli.main(argv, ask=lambda prompt: next(answers), out=printed.append)
    return code, "\n".join(printed)


# ---------------------------------------------------------------- encryption


def test_encrypted_vault_round_trip_and_no_plaintext_on_disk(tmp_path):
    vault = sc.merge_vault(None, sc.scan_text(TEXT)["proposed"])
    path = tmp_path / "matter.vault"
    sc.save_vault(vault, path, passphrase=PASSPHRASE)
    raw = path.read_text()
    assert "Smith" not in raw and "Acme" not in raw and "123-45-6789" not in raw
    assert sc.is_encrypted_vault(path)
    assert sc.load_vault(path, passphrase=PASSPHRASE) == vault


def test_wrong_or_missing_passphrase_is_refused(tmp_path):
    path = tmp_path / "matter.vault"
    sc.save_vault(sc.new_vault(), path, passphrase=PASSPHRASE)
    with pytest.raises(sc.VaultError):
        sc.load_vault(path, passphrase="not the passphrase")
    with pytest.raises(sc.VaultError):
        sc.load_vault(path)


def test_tampered_vault_is_refused(tmp_path):
    path = tmp_path / "matter.vault"
    sc.save_vault(sc.new_vault(), path, passphrase=PASSPHRASE)
    envelope = json.loads(path.read_text())
    envelope["ciphertext"] = envelope["ciphertext"][:-4] + "AAAA"
    path.write_text(json.dumps(envelope))
    with pytest.raises(sc.VaultError):
        sc.load_vault(path, passphrase=PASSPHRASE)


def test_each_save_uses_a_fresh_salt_and_nonce(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    sc.save_vault(sc.new_vault(), a, passphrase=PASSPHRASE)
    sc.save_vault(sc.new_vault(), b, passphrase=PASSPHRASE)
    ea, eb = json.loads(a.read_text()), json.loads(b.read_text())
    assert ea["kdf"]["salt"] != eb["kdf"]["salt"] and ea["nonce"] != eb["nonce"]


def test_raw_key_can_replace_the_passphrase(tmp_path):
    # The seam a keychain would use later: same file format, no passphrase.
    key = bytes(range(32))
    path = tmp_path / "matter.vault"
    vault = sc.merge_vault(None, sc.scan_text(TEXT)["proposed"])
    sc.save_vault(vault, path, key=key)
    assert sc.load_vault(path, key=key) == vault


# ---------------------------------------------------------------- declines


def test_declined_values_are_remembered_and_not_proposed_again():
    proposal = sc.scan_text(TEXT)
    keep = {p: e for p, e in proposal["proposed"].items() if "Arbitration" not in e["value"]}
    vault = sc.merge_vault(None, keep, declined=["American Arbitration Association"])
    assert vault["declined"] == ["American Arbitration Association"]
    again = sc.scan_text(TEXT, vault)
    assert again["proposed"] == {}
    assert "American Arbitration Association" in sc.apply_vault(TEXT, vault)


def test_accepting_a_value_later_removes_it_from_declined():
    vault = sc.merge_vault(None, {}, declined=["Gerry"])
    proposed, _ = sc.propose_mappings([("person", "Gerry")], vault)
    assert "declined" not in sc.merge_vault(vault, proposed)


# ---------------------------------------------------------------- review


def test_review_accept_decline_edit_retype_and_add(tmp_path):
    doc = tmp_path / "case.txt"
    doc.write_text(TEXT)
    vault_path = tmp_path / "matter.vault"
    proposed = list(sc.scan_text(TEXT)["proposed"].values())
    answers = ["r"]
    for entry in proposed:
        if entry["value"] == "American Arbitration Association":
            answers.append("d")
        elif entry["value"] == "Acme":
            answers += ["t", "company", "a"]
        else:
            answers.append("a")
    answers += ["Gerry", "", "Nobody Here", ""]  # add a missed nickname; a typo is rejected
    code, printed = run(["sanitize", str(doc), "--vault", str(vault_path)], answers)
    assert code == 0
    assert "does not appear in the document" in printed

    safe = (tmp_path / "case.sanitized.txt").read_text()
    for leak in ("Smith", "Acme", "123-45-6789", "Gerry"):
        assert leak not in safe
    assert "American Arbitration Association" in safe

    vault = sc.load_vault(vault_path, passphrase=PASSPHRASE)
    assert vault["declined"] == ["American Arbitration Association"]
    assert all(e["reviewed"] is True for e in vault["mappings"].values())
    by_value = {e["value"]: e for e in vault["mappings"].values()}
    assert by_value["Gerry"]["source"] == "manual"
    assert sc.rehydrate_text(safe, vault) == TEXT


def test_review_edit_changes_the_text_to_redact(tmp_path):
    answers = ["r", "e", "John A. Smith sued", "a", "A"]
    accepted, declined, reviewed = cli.review(
        TEXT, sc.scan_text(TEXT)["proposed"], ask=lambda p, a=iter(answers + [""]): next(a), out=lambda s: None
    )
    assert accepted[0] == ("person", "John A. Smith sued", "manual")
    assert reviewed and not declined


def test_quit_saves_nothing(tmp_path):
    doc = tmp_path / "case.txt"
    doc.write_text(TEXT)
    code, printed = run(["sanitize", str(doc), "--vault", str(tmp_path / "v")], ["q"])
    assert code == 1
    assert not (tmp_path / "v").exists() and not (tmp_path / "case.sanitized.txt").exists()


@pytest.mark.parametrize("how", ["flag", "menu"])
def test_im_feeling_lucky_accepts_everything_and_marks_it_unreviewed(tmp_path, how):
    doc = tmp_path / "case.txt"
    doc.write_text(TEXT)
    argv = ["sanitize", str(doc), "--vault", str(tmp_path / "v")]
    code, printed = run(argv + ["--lucky"]) if how == "flag" else run(argv, ["l"])
    assert code == 0
    assert "UNREVIEWED" in printed
    vault = sc.load_vault(tmp_path / "v", passphrase=PASSPHRASE)
    assert vault["mappings"] and all(e["reviewed"] is False for e in vault["mappings"].values())
    assert "Smith" not in (tmp_path / "case.sanitized.txt").read_text()

    code, printed = run(["vault", "--vault", str(tmp_path / "v")])
    assert f"{len(vault['mappings'])} accepted without review" in printed
    assert "Smith" not in printed  # values are only shown on request


def test_second_document_reuses_the_vault_and_rehydrate_restores(tmp_path):
    vault_path = str(tmp_path / "v")
    first = tmp_path / "one.txt"
    first.write_text(TEXT)
    run(["sanitize", str(first), "--vault", vault_path, "--lucky"])
    before = sc.load_vault(vault_path, passphrase=PASSPHRASE)

    second = tmp_path / "two.txt"
    second.write_text("Smith and Acme Corporation settled. Jane Doe, SSN 222-33-4444, signed.")
    code, printed = run(["sanitize", str(second), "--vault", vault_path, "--lucky"])
    after = sc.load_vault(vault_path, passphrase=PASSPHRASE)
    assert {p: after["mappings"][p] for p in before["mappings"]} == before["mappings"]
    assert "2 item(s) in this document are already in the vault" in printed

    answer = tmp_path / "answer.txt"
    answer.write_text("Summary: [PERSON_1] lost to [COMPANY_1]; see [PERSON_99].")
    code, printed = run(["rehydrate", str(answer), "--vault", vault_path])
    restored = (tmp_path / "answer.rehydrated.txt").read_text()
    assert restored == "Summary: John A. Smith lost to Acme Corporation; see [PERSON_99]."
    assert "[PERSON_99]" in printed


def test_wrong_passphrase_stops_the_cli(tmp_path, monkeypatch):
    doc = tmp_path / "case.txt"
    doc.write_text(TEXT)
    run(["sanitize", str(doc), "--vault", str(tmp_path / "v"), "--lucky"])
    monkeypatch.setenv(cli.PASSPHRASE_ENV, "something else entirely")
    with pytest.raises(SystemExit, match="Wrong passphrase"):
        run(["sanitize", str(doc), "--vault", str(tmp_path / "v"), "--lucky"])


def test_plaintext_vault_is_refused_by_the_cli(tmp_path):
    doc = tmp_path / "case.txt"
    doc.write_text(TEXT)
    sc.save_vault(sc.new_vault(), tmp_path / "plain.json")
    with pytest.raises(SystemExit, match="not an encrypted vault"):
        run(["sanitize", str(doc), "--vault", str(tmp_path / "plain.json"), "--lucky"])


def test_residue_check_flags_other_letter_case():
    vault = sc.merge_vault(None, sc.propose_mappings([("company", "Acme Corporation")])[0])
    safe = sc.apply_vault("Acme Corporation and ACME CORPORATION agree.", vault)
    assert cli.find_residue(safe, vault) == [("Acme Corporation", 1)]


# ---------------------------------------------------------------- file formats


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"



def make_docx(path, body, extra=None):
    parts = {"word/document.xml": f'<w:document xmlns:w="{W_NS}" xmlns:mc="urn:x-mc"><w:body>{body}</w:body></w:document>'}
    for name, tag, inner in extra or []:
        parts[name] = f'<w:{tag} xmlns:w="{W_NS}">{inner}</w:{tag}>'
    parts["docProps/core.xml"] = (
        '<cp:coreProperties xmlns:cp="urn:cp" xmlns:dc="urn:dc">'
        "<dc:creator>John A. Smith</dc:creator><cp:lastModifiedBy>Paralegal Pat</cp:lastModifiedBy>"
        "<dc:title>Complaint</dc:title></cp:coreProperties>"
    )
    parts["word/styles.xml"] = f'<w:styles xmlns:w="{W_NS}"><w:style w:styleId="Bold"/></w:styles>'
    with zipfile.ZipFile(path, "w") as archive:
        for name, xml in parts.items():
            archive.writestr(name, xml)


def run_(text, bold=False):
    props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{props}<w:t xml:space="preserve">{text}</w:t></w:r>'


def test_reads_docx(tmp_path):
    body = (
        "<w:p>" + run_("John A. Smith") + "<w:r><w:tab/></w:r>" + run_(" sued") + "</w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Acme &amp; Sons</w:t><w:br/><w:t>Line two</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )
    path = tmp_path / "doc.docx"
    make_docx(path, body)
    assert cli.read_document(str(path)) == "John A. Smith\t sued\nAcme & Sons\nLine two"


DOCX_BODY = (
    # the name is split across three runs with different formatting
    "<w:p>" + run_("Plaintiff John ") + run_("A. Sm", bold=True) + run_("ith sued Acme Corporation.") + "</w:p>"
    "<w:p>" + run_("Smith's SSN is 123-45-6789.") + "</w:p>"
    '<w:p><w:del w:author="John A. Smith"><w:r><w:delText>Acme Corporation was struck.</w:delText></w:r></w:del></w:p>'
)
DOCX_EXTRA = [
    ("word/header1.xml", "hdr", "<w:p>" + run_("Smith v. Acme Corporation") + "</w:p>"),
    ("word/footer1.xml", "ftr", "<w:p>" + run_("Prepared for John A. Smith") + "</w:p>"),
    ("word/footnotes.xml", "footnotes", '<w:footnote w:id="1"><w:p>' + run_("See letter from Acme Corporation.") + "</w:p></w:footnote>"),
    ("word/endnotes.xml", "endnotes", '<w:endnote w:id="1"><w:p>' + run_("Smith, deposition.") + "</w:p></w:endnote>"),
    ("word/comments.xml", "comments", '<w:comment w:id="0" w:author="John A. Smith" w:initials="JAS"><w:p>' + run_("Ask Smith.") + "</w:p></w:comment>"),
]  # fmt: skip


def test_docx_text_includes_headers_footers_notes_comments_and_deletions(tmp_path):
    path = tmp_path / "case.docx"
    make_docx(path, DOCX_BODY, DOCX_EXTRA)
    text = cli.read_document(str(path))
    for expected in (
        "Plaintiff John A. Smith sued Acme Corporation.", "Acme Corporation was struck.",
        "Smith v. Acme Corporation", "Prepared for John A. Smith",
        "See letter from Acme Corporation.", "Smith, deposition.", "Ask Smith.",
    ):  # fmt: skip
        assert expected in text


def test_docx_in_docx_out_redacts_every_part_and_keeps_formatting(tmp_path):
    path = tmp_path / "case.docx"
    make_docx(path, DOCX_BODY, DOCX_EXTRA)
    original_text = cli.read_document(str(path))
    code, printed = run(["sanitize", str(path), "--vault", str(tmp_path / "v"), "--lucky"])
    assert code == 0
    out_path = tmp_path / "case.sanitized.docx"

    with zipfile.ZipFile(out_path) as archive:
        everything = "".join(archive.read(n).decode("utf-8") for n in archive.namelist())
        document = archive.read("word/document.xml").decode("utf-8")
        assert archive.read("word/styles.xml") == zipfile.ZipFile(path).read("word/styles.xml")
    for leak in ("Smith", "Acme", "123-45-6789", "Paralegal Pat", "JAS"):
        assert leak not in everything, leak
    assert "<w:b/>" in document and document.count("<w:r>") == DOCX_BODY.count("<w:r>")  # runs untouched
    assert "Complaint" in everything  # non-identifying metadata is kept

    # an LLM's answer, or the same file, comes back as a .docx and is restored
    code, printed = run(["rehydrate", str(out_path), "--vault", str(tmp_path / "v")])
    restored = cli.read_document(str(tmp_path / "case.sanitized.rehydrated.docx"))
    assert restored == original_text


def test_docx_can_still_be_written_as_plain_text(tmp_path):
    path = tmp_path / "case.docx"
    make_docx(path, DOCX_BODY, DOCX_EXTRA)
    out_path = tmp_path / "plain.txt"
    run(["sanitize", str(path), "--vault", str(tmp_path / "v"), "--lucky", "-o", str(out_path)])
    assert "Smith" not in out_path.read_text() and "[PERSON_1]" in out_path.read_text()


def test_reads_pdf(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject(
        {NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
         NameObject("/BaseFont"): NameObject("/Helvetica")}
    )  # fmt: skip
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 100 Td (John A. Smith sued Acme) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    path = tmp_path / "doc.pdf"
    with open(path, "wb") as fh:
        writer.write(fh)
    assert "John A. Smith sued Acme" in cli.read_document(str(path))


def test_empty_document_is_reported(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("  \n")
    with pytest.raises(SystemExit, match="No text found"):
        cli.read_document(str(path))
