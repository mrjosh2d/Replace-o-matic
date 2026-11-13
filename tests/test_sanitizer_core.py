import copy
import json
import re
import stat

import pytest

from sanitizer_core import (
    Detection,
    apply_vault,
    detect_regex,
    load_vault,
    merge_vault,
    new_vault,
    rehydrate_text,
    save_vault,
    scan_text,
)


def fake_ner(**by_type):
    """NER stub: fake_ner(person=["John Smith"], company=["Acme"]) tags every
    whole-word occurrence of those strings. Keeps tests model-free and exact."""

    def detect(text):
        found = []
        for etype, names in by_type.items():
            for name in names:
                for m in re.finditer(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text):
                    found.append(Detection(m.start(), m.end(), etype))
        return found

    return detect


def build_vault(text, vault=None, **by_type):
    return merge_vault(vault, scan_text(text, vault, ner=fake_ner(**by_type))["proposed"])


def values(proposal):
    return {p: e["value"] for p, e in proposal["proposed"].items()}


# ---------------------------------------------------------------- regex


@pytest.mark.parametrize(
    "text, expected_type, expected_value",
    [
        ("SSN 123-45-6789 on file.", "financial_id", "123-45-6789"),
        ("EIN: 12-3456789.", "financial_id", "12-3456789"),
        ("wire to Account No. 000123456789 today", "financial_id", "000123456789"),
        ("Routing #: 021000021", "financial_id", "021000021"),
        ("acct 1234 5678 9012", "financial_id", "1234 5678 9012"),
        ("IBAN GB29 NWBK 6016 1331 9268 19 applies", "financial_id", "GB29 NWBK 6016 1331 9268 19"),
        ("Contact j.smith+legal@acme-corp.com.", "email", "j.smith+legal@acme-corp.com"),
        ("Call (212) 555-0147 now", "phone", "(212) 555-0147"),
        ("Call +1 212.555.0147 now", "phone", "+1 212.555.0147"),
        ("Call 212-555-0147.", "phone", "212-555-0147"),
    ],
)
def test_regex_detects(text, expected_type, expected_value):
    hits = [(d.type, text[d.start : d.end]) for d in detect_regex(text)]
    assert (expected_type, expected_value) in hits


@pytest.mark.parametrize(
    "text",
    [
        "Section 12-345 of the Code",
        "dated 2024-01-15",
        "invoice 1234-56-78901",
        "000-12-3456",  # invalid SSN area
        "the account was closed in 2019",
        "see page 212 and 555",
    ],
)
def test_regex_ignores_lookalikes(text):
    assert detect_regex(text) == []


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Counsel Mary Smithson of Smithson & Johnson LLP appeared.", "Smithson & Johnson LLP"),
        ("ACME CORPORATION and Beta Holdings LLC agree.", "ACME CORPORATION"),
        ("ACME CORPORATION and Beta Holdings LLC agree.", "Beta Holdings LLC"),
        ("Payment to Acme, Inc. is due.", "Acme, Inc."),
        ("Notices go to First Bank, N.A. promptly.", "First Bank, N.A."),
    ],
)
def test_regex_detects_companies_by_legal_suffix(text, expected):
    hits = [text[d.start : d.end] for d in detect_regex(text) if d.type == "company"]
    assert expected in hits


def test_bare_surname_and_short_company_name_are_caught_without_the_model_seeing_them():
    text = "John A. Smith sued Acme Corporation. Later Smith settled; Acme's insurer paid. Smithfield and Acmeville were not involved."
    proposal = scan_text(text, ner=fake_ner(person=["John A. Smith"]))
    assert values(proposal) == {
        "[PERSON_1]": "John A. Smith",
        "[COMPANY_1]": "Acme Corporation",
        "[PERSON_1_ALIAS_1]": "Smith",
        "[COMPANY_1_ALIAS_1]": "Acme",
    }
    vault = merge_vault(None, proposal["proposed"])
    safe = apply_vault(text, vault)
    assert safe.endswith("Smithfield and Acmeville were not involved.")
    assert rehydrate_text(safe, vault) == text


def test_surname_of_a_person_already_in_the_vault_is_caught_in_a_new_document():
    vault = build_vault("Jane Q. Doe", person=["Jane Q. Doe"])
    proposal = scan_text("Doe did not appear.", vault, ner=False)
    assert values(proposal) == {"[PERSON_1_ALIAS_1]": "Doe"}


def test_adjacent_address_parts_merge_into_one_address():
    text = "residing at 742 Evergreen Terrace, Springfield, IL 62704, and"
    proposal = scan_text(text, ner=fake_ner(address=["742 Evergreen Terrace", "Springfield, IL 62704"]))
    assert values(proposal) == {"[ADDRESS_1]": "742 Evergreen Terrace, Springfield, IL 62704"}


def test_ssn_and_ein_with_the_same_digits_are_different_ids():
    proposal = scan_text("EIN 12-3456789 and SSN 123-45-6789", ner=False)
    assert set(proposal["proposed"]) == {"[FINANCIAL_ID_1]", "[FINANCIAL_ID_2]"}


def test_ssn_is_not_also_a_phone_or_ein():
    proposal = scan_text("SSN 123-45-6789", ner=False)
    assert values(proposal) == {"[FINANCIAL_ID_1]": "123-45-6789"}


# ---------------------------------------------------------------- scan_text


def test_scan_does_not_alter_text_or_vault():
    text = "John Smith, SSN 123-45-6789."
    vault = build_vault("Jane Doe", person=["Jane Doe"])
    before = copy.deepcopy(vault)
    scan_text(text, vault, ner=fake_ner(person=["John Smith"]))
    assert vault == before
    assert text == "John Smith, SSN 123-45-6789."


def test_scan_numbers_by_first_appearance_and_is_deterministic():
    text = "Zed Young met Amy Brown. Amy Brown paid Zed Young."
    ner = fake_ner(person=["Amy Brown", "Zed Young"])
    first = scan_text(text, ner=ner)
    assert values(first) == {"[PERSON_1]": "Zed Young", "[PERSON_2]": "Amy Brown"}
    assert scan_text(text, ner=ner) == first


def test_scan_reuses_existing_vault_and_continues_numbering():
    vault = build_vault("John Smith", person=["John Smith"])
    proposal = scan_text(
        "John Smith and Jane Doe", vault, ner=fake_ner(person=["John Smith", "Jane Doe"])
    )
    assert values(proposal) == {"[PERSON_2]": "Jane Doe"}
    assert proposal["matched"] == ["[PERSON_1]"]


def test_scan_alias_numbering_continues_from_vault():
    vault = build_vault("Acme Corporation and Acme Corp.", company=["Acme Corporation", "Acme Corp."])
    proposal = scan_text("ACME CORPORATION", vault, ner=fake_ner(company=["ACME CORPORATION"]))
    assert values(proposal) == {"[COMPANY_1_ALIAS_2]": "ACME CORPORATION"}


def test_regex_wins_over_ner_inside_an_email():
    text = "Email john.smith@acme.com"
    proposal = scan_text(text, ner=fake_ner(person=["john.smith"], company=["acme"]))
    assert values(proposal) == {"[EMAIL_1]": "john.smith@acme.com"}


def test_longer_ner_span_wins_overlap():
    text = "at Smith Barney LLC"
    proposal = scan_text(text, ner=fake_ner(person=["Smith"], company=["Smith Barney LLC"]))
    assert values(proposal) == {"[COMPANY_1]": "Smith Barney LLC"}


def test_possessive_is_trimmed_from_ner_span():
    text = "per Acme's records"
    ner = lambda t: [Detection(4, 10, "company")]  # "Acme's"
    assert values(scan_text(text, ner=ner)) == {"[COMPANY_1]": "Acme"}


def test_scan_warns_about_preexisting_placeholder_tokens():
    proposal = scan_text("The template says [PERSON_7] signs here.", ner=False)
    assert proposal["proposed"] == {}
    assert "[PERSON_7]" in proposal["warnings"][0]


def test_unknown_entity_type_is_rejected():
    with pytest.raises(ValueError):
        scan_text("x", ner=lambda t: [Detection(0, 1, "martian")])


# ---------------------------------------------------------------- aliases


def test_company_aliases_share_an_entity_but_keep_distinct_placeholders():
    text = 'Acme Corporation ("Acme") sued. ACME CORPORATION, a.k.a. Acme Corp., lost. Acme paid.'
    names = ["Acme Corporation", "Acme", "ACME CORPORATION", "Acme Corp."]
    proposal = scan_text(text, ner=fake_ner(company=names))
    assert values(proposal) == {
        "[COMPANY_1]": "Acme Corporation",
        "[COMPANY_1_ALIAS_1]": "Acme",
        "[COMPANY_1_ALIAS_2]": "ACME CORPORATION",
        "[COMPANY_1_ALIAS_3]": "Acme Corp.",
    }
    assert {e["entity"] for e in proposal["proposed"].values()} == {"COMPANY_1"}

    vault = merge_vault(None, proposal["proposed"])
    safe = apply_vault(text, vault)
    assert safe == (
        '[COMPANY_1] ("[COMPANY_1_ALIAS_1]") sued. [COMPANY_1_ALIAS_2], a.k.a. '
        "[COMPANY_1_ALIAS_3], lost. [COMPANY_1_ALIAS_1] paid."
    )
    assert rehydrate_text(safe, vault) == text


def test_related_but_different_companies_stay_separate():
    text = "Acme Holdings LLC owns Acme Inc. and Acme Realty, L.L.C."
    names = ["Acme Holdings LLC", "Acme Inc.", "Acme Realty, L.L.C."]
    proposal = scan_text(text, ner=fake_ner(company=names))
    assert set(proposal["proposed"]) == {"[COMPANY_1]", "[COMPANY_2]", "[COMPANY_3]"}


def test_person_title_and_surname_link_to_the_full_name():
    text = "John Smith testified. Mr. Smith left. Smith returned. John Q. Smith signed."
    names = ["John Smith", "Mr. Smith", "Smith", "John Q. Smith"]
    proposal = scan_text(text, ner=fake_ner(person=names))
    assert {e["entity"] for e in proposal["proposed"].values()} == {"PERSON_1"}
    assert proposal["proposed"]["[PERSON_1]"]["value"] == "John Smith"


def test_ambiguous_surname_is_not_linked_to_either_person():
    text = "John Smith and Mary Smith disagreed. Smith then left."
    proposal = scan_text(text, ner=fake_ner(person=["John Smith", "Mary Smith", "Smith"]))
    assert values(proposal) == {
        "[PERSON_1]": "John Smith",
        "[PERSON_2]": "Mary Smith",
        "[PERSON_3]": "Smith",
    }


def test_surname_seen_first_does_not_merge_two_different_people():
    text = "Smith arrived. John Smith spoke. Mary Smith objected."
    proposal = scan_text(text, ner=fake_ner(person=["Smith", "John Smith", "Mary Smith"]))
    by_value = {e["value"]: e["entity"] for e in proposal["proposed"].values()}
    assert by_value["John Smith"] == by_value["Smith"] == "PERSON_1"
    assert by_value["Mary Smith"] == "PERSON_2"


def test_different_middle_initials_are_different_people():
    text = "John A. Smith and John B. Smith"
    proposal = scan_text(text, ner=fake_ner(person=["John A. Smith", "John B. Smith"]))
    assert set(proposal["proposed"]) == {"[PERSON_1]", "[PERSON_2]"}


def test_reformatted_identifiers_are_aliases():
    text = "Call (212) 555-0147 or 212-555-0147. Mail A@B.com or a@b.com."
    proposal = scan_text(text, ner=False)
    assert set(proposal["proposed"]) == {
        "[PHONE_1]", "[PHONE_1_ALIAS_1]", "[EMAIL_1]", "[EMAIL_1_ALIAS_1]"
    }  # fmt: skip


# ---------------------------------------------------------------- apply / rehydrate


def test_overlapping_names_never_collide():
    text = "John Smith, John Smithson, Johnson and John met. Smith's car; Smithson's van."
    vault = build_vault(text, person=["John Smith", "John Smithson", "Johnson", "John", "Smith", "Smithson"])
    safe = apply_vault(text, vault)
    for name in ("John", "Smith", "Johnson", "Smithson"):
        assert name not in safe
    assert not re.search(r"\]\w|\w\[", safe)  # no half-replaced words like "[PERSON_1]son"
    assert rehydrate_text(safe, vault) == text


def test_short_name_does_not_fire_inside_other_words():
    text = "Ann signed the Annual report; Annette and JoAnn did not. Ann's copy."
    vault = build_vault(text, person=["Ann"])
    assert apply_vault(text, vault) == (
        "[PERSON_1] signed the Annual report; Annette and JoAnn did not. [PERSON_1]'s copy."
    )


def test_longest_value_wins_regardless_of_vault_order():
    vault = new_vault()
    vault["mappings"] = {
        "[COMPANY_1]": {"type": "company", "value": "Acme", "entity": "COMPANY_1"},
        "[COMPANY_2]": {"type": "company", "value": "Acme Holdings LLC", "entity": "COMPANY_2"},
    }
    assert apply_vault("Acme Holdings LLC and Acme.", vault) == "[COMPANY_2] and [COMPANY_1]."


def test_value_with_punctuation_at_the_edges():
    text = "Payment to Acme, Inc. is due. (Acme, Inc.) agrees."
    vault = build_vault(text, company=["Acme, Inc."])
    safe = apply_vault(text, vault)
    assert safe == "Payment to [COMPANY_1] is due. ([COMPANY_1]) agrees."
    assert rehydrate_text(safe, vault) == text


def test_apply_is_idempotent_and_leaves_placeholders_alone():
    # A person literally named "Alias" must not corrupt [PERSON_1_ALIAS_1].
    text = "John Smith, Smith and Alias Person"
    vault = build_vault(text, person=["John Smith", "Smith", "Alias", "Person"])
    once = apply_vault(text, vault)
    assert apply_vault(once, vault) == once
    assert rehydrate_text(once, vault) == text


def test_rehydrate_does_not_rescan_restored_values():
    vault = new_vault()
    vault["mappings"] = {
        "[COMPANY_1]": {"type": "company", "value": "[PERSON_1] Fan Club", "entity": "COMPANY_1"},
        "[PERSON_1]": {"type": "person", "value": "Bob", "entity": "PERSON_1"},
    }
    assert rehydrate_text("[COMPANY_1] hired [PERSON_1]", vault) == "[PERSON_1] Fan Club hired Bob"


def test_placeholder_numbers_do_not_prefix_collide():
    people = [f"Person{chr(65 + i)} Test{chr(65 + i)}" for i in range(12)]
    text = "; ".join(people)
    vault = build_vault(text, person=people)
    safe = apply_vault(text, vault)
    assert "[PERSON_1]" in safe and "[PERSON_12]" in safe
    assert rehydrate_text(safe, vault) == text


def test_rehydrate_keeps_unknown_placeholders_and_llm_added_text():
    vault = build_vault("John Smith", person=["John Smith"])
    out = rehydrate_text("Summary: [PERSON_1]'s claim against [PERSON_9] fails.", vault)
    assert out == "Summary: John Smith's claim against [PERSON_9] fails."


def test_unicode_names_round_trip():
    text = "José Álvarez-Ruiz y Zoë O’Brien firmaron. José no."
    vault = build_vault(text, person=["José Álvarez-Ruiz", "Zoë O’Brien", "José"])
    safe = apply_vault(text, vault)
    assert "José" not in safe and "Brien" not in safe
    assert rehydrate_text(safe, vault) == text


DOCUMENT = """\
SETTLEMENT AGREEMENT

This Agreement is entered into by John A. Smith ("Smith"), residing at
742 Evergreen Terrace, Springfield, IL 62704, and Acme Holdings LLC ("Acme Holdings"),
a subsidiary of Acme Corporation ("Acme"), EIN 12-3456789.

1. Mr. Smith (SSN 123-45-6789) shall receive payment to Account No. 000123456789,
   routing number 021000021. Smith's counsel, Mary Smithson of Smithson & Johnson LLP,
   may be reached at (212) 555-0147 or msmithson@smithsonjohnson.com.
2. ACME CORPORATION and Acme Holdings LLC release all claims. Acme's obligations
   survive. Notices to Acme Corp. go to 742 Evergreen Terrace, Springfield, IL 62704.
"""

DOCUMENT_NER = dict(
    person=["John A. Smith", "Smith", "Mr. Smith", "Mary Smithson"],
    company=[
        "Acme Holdings LLC", "Acme Holdings", "Acme Corporation", "Acme",
        "ACME CORPORATION", "Acme Corp.", "Smithson & Johnson LLP",
    ],  # fmt: skip
    address=["742 Evergreen Terrace, Springfield, IL 62704"],
)


def test_full_document_round_trip():
    vault = build_vault(DOCUMENT, **DOCUMENT_NER)
    safe = apply_vault(DOCUMENT, vault)

    for entry in vault["mappings"].values():
        assert entry["value"] not in safe, entry["value"]
    for leak in ("Smith", "Acme", "Evergreen", "6789", "555-0147", "021000021"):
        assert leak not in safe
    assert rehydrate_text(safe, vault) == DOCUMENT

    entity_of = {e["value"]: e["entity"] for e in vault["mappings"].values()}
    assert entity_of["John A. Smith"] == entity_of["Smith"] == entity_of["Mr. Smith"]
    assert entity_of["Mary Smithson"] != entity_of["Smith"]
    assert entity_of["Acme Holdings LLC"] == entity_of["Acme Holdings"]
    assert entity_of["Acme Corporation"] == entity_of["Acme"] == entity_of["Acme Corp."]
    assert entity_of["Acme Holdings LLC"] != entity_of["Acme"]


def test_incremental_scan_of_a_second_document_keeps_old_placeholders_stable():
    vault = build_vault(DOCUMENT, **DOCUMENT_NER)
    second = "Jane Doe emailed Mr. Smith and Acme Corp. about SSN 123-45-6789."
    grown = build_vault(second, vault, person=["Jane Doe", "Mr. Smith"], company=["Acme Corp."])
    assert {p: grown["mappings"][p] for p in vault["mappings"]} == vault["mappings"]
    assert len(grown["mappings"]) == len(vault["mappings"]) + 1
    assert rehydrate_text(apply_vault(second, grown), grown) == second


# ---------------------------------------------------------------- vault


def test_vault_save_load_round_trip(tmp_path):
    vault = build_vault(DOCUMENT, **DOCUMENT_NER)
    path = tmp_path / "vault.json"
    save_vault(vault, path)
    assert load_vault(path) == vault
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_merge_rejects_remapping_a_placeholder():
    vault = build_vault("John Smith", person=["John Smith"])
    clash = {"[PERSON_1]": {"type": "person", "value": "Jane Doe", "entity": "PERSON_1"}}
    with pytest.raises(ValueError):
        merge_vault(vault, clash)


def test_merge_rejects_one_value_under_two_placeholders():
    vault = build_vault("John Smith", person=["John Smith"])
    dup = {"[PERSON_2]": {"type": "person", "value": "John Smith", "entity": "PERSON_2"}}
    with pytest.raises(ValueError):
        merge_vault(vault, dup)


def test_merge_does_not_mutate_inputs():
    vault = build_vault("John Smith", person=["John Smith"])
    before = copy.deepcopy(vault)
    merge_vault(vault, {"[PERSON_2]": {"type": "person", "value": "Jane Doe", "entity": "PERSON_2"}})
    assert vault == before
