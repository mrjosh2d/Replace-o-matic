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
        ("ITIN 900-41-7782 applies", "financial_id", "900-41-7782"),
        ("your account at Golden Valley Credit Union, number 4402981156?", "financial_id", "4402981156"),
        ("a personal operating account, no. 6150219983, at", "financial_id", "6150219983"),
        ("the savings account ending in 4410, and", "financial_id", "4410"),
        ("SSN: 900-77-1204\nMRN: HM-0066412\n", "financial_id", "HM-0066412"),
        ("Member ID GCM 884-20-1167.", "financial_id", "GCM 884-20-1167"),
        ("lives in Tucson, Arizona 85712.", "address", "Tucson, Arizona 85712"),
        ("office in New York, New York 10018", "address", "New York, New York 10018"),
        ("Vancouver, BC V6B 1A1, Canada", "address", "Vancouver, BC V6B 1A1"),
        ("by Oyelaran, Schmidt & Lindqvist PC today", "company", "Oyelaran, Schmidt & Lindqvist PC"),
        ("HARROWGATE & VOSS, P.A.\n", "company", "HARROWGATE & VOSS, P.A."),
        ("LAW OFFICES\n#1 OLD CAPITAL SQUARE\nSPRINGFIELD, ILLINOIS 00000\n", "address", "#1 OLD CAPITAL SQUARE"),
        ("LAW OFFICES\n#1 OLD CAPITAL SQUARE\nSPRINGFIELD, ILLINOIS 00000\n", "address", "SPRINGFIELD, ILLINOIS 00000"),
        ("offices at 4120 Harbor View Drive, Suite 300, Tacoma", "address", "4120 Harbor View Drive, Suite 300"),
        ("mail to P.O. Box 71188 today", "address", "P.O. Box 71188"),
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
        "under the Delaware General Corporation Law",
        "the Arizona Revised Limited Liability Company Act",
        "Section 5 applies and 30 days later the road closed",
        "Section 14.05       No Court Proceedings ........ 14-3",
        "the account was opened. In 2019 the number 12345678 appeared",
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


def test_first_name_alone_is_caught_and_linked():
    text = "Maria Q. Delgado signed. Maria agrees. Ms. Delgado's copy. Mariana did not."
    proposal = scan_text(text, ner=fake_ner(person=["Maria Q. Delgado"]))
    assert values(proposal) == {
        "[PERSON_1]": "Maria Q. Delgado",
        "[PERSON_1_ALIAS_1]": "Maria",
        "[PERSON_1_ALIAS_2]": "Delgado",
    }
    vault = merge_vault(None, proposal["proposed"])
    assert apply_vault(text, vault) == (
        "[PERSON_1] signed. [PERSON_1_ALIAS_1] agrees. Ms. [PERSON_1_ALIAS_2]'s copy. Mariana did not."
    )


def test_surname_with_particles_is_caught_whole():
    text = "Pieter van der Meer signed. Mr. van der Meer left. Ana de la Cruz stayed; de la Cruz agreed."
    proposal = scan_text(text, ner=fake_ner(person=["Pieter van der Meer", "Ana de la Cruz"]))
    found = {e["value"] for e in proposal["proposed"].values()}
    assert {"van der Meer", "de la Cruz"} <= found
    vault = merge_vault(None, proposal["proposed"])
    safe = apply_vault(text, vault)
    assert "van der" not in safe and "de la" not in safe
    assert rehydrate_text(safe, vault) == text


def test_firm_list_does_not_swallow_the_lawyer_named_before_it():
    text = "represented by Priya Venkat, Esq., Oyelaran, Schmidt & Lindqvist PC, 410 Fifth Avenue. Ms. Venkat will appear."
    proposal = scan_text(text, ner=fake_ner(person=["Priya Venkat"]))
    found = {e["value"]: e["type"] for e in proposal["proposed"].values()}
    assert found["Oyelaran, Schmidt & Lindqvist PC"] == "company"
    assert found["Priya Venkat"] == found["Venkat"] == "person"


def test_all_caps_name_propagates_its_title_case_short_form():
    text = "PINNACLE TITLE & ESCROW, INC.\n\nPinnacle will record the deed. KAREN VOSS signed; Ms. Voss left."
    proposal = scan_text(text, ner=fake_ner(person=["KAREN VOSS"]))
    by_value = {e["value"]: e["entity"] for e in proposal["proposed"].values()}
    assert by_value["Pinnacle"] == by_value["PINNACLE TITLE & ESCROW, INC."]
    assert by_value["Voss"] == by_value["KAREN VOSS"]


TRUST_TEXT = (
    "I, Ulysses S Grant, grant my Trustee the powers below. My Trustee may pay the Marital Share "
    "to my wife, Julia D. Grant. The Trust Protector may remove any Trustee. Each beneficiary "
    "of the trust takes a share. Thomas Banks is successor Trustee; Banks may resign. "
    "Gifts Limited to tuition are exempt. The Internal Revenue Code controls."
)


def test_role_words_and_defined_terms_are_not_names():
    generic = ["my Trustee", "My Trustee", "Trustee", "Marital Share", "my wife", "I", "trust",
               "beneficiary", "The Trust Protector", "Trust Protector", "Internal Revenue Code"]  # fmt: skip
    ner = fake_ner(person=["Ulysses S Grant", "Julia D. Grant", "Thomas Banks"] + generic[:8], company=generic[8:])
    found = {e["value"] for e in scan_text(TRUST_TEXT, ner=ner)["proposed"].values()}
    assert found == {"Ulysses S Grant", "Julia D. Grant", "Thomas Banks", "Banks"}


def test_surname_that_is_also_a_word_survives_the_vocabulary_filter():
    # "grant" appears in lower case, yet the people named Grant are still caught,
    # and the bare surname "Banks" is propagated although "bank" is a common word.
    proposal = scan_text(TRUST_TEXT, ner=fake_ner(person=["Ulysses S Grant", "Julia D. Grant", "Thomas Banks"]))
    vault = merge_vault(None, proposal["proposed"])
    safe = apply_vault(TRUST_TEXT, vault)
    assert "Grant" not in safe and "Banks" not in safe
    assert "grant my Trustee" in safe and "Gifts Limited to tuition" in safe
    assert rehydrate_text(safe, vault) == TRUST_TEXT


def test_overlapping_address_pieces_are_joined():
    text = "lives at 88 Quarry Hill Road, Flagstaff, AZ 86001 now"
    proposal = scan_text(text, ner=fake_ner(address=["88 Quarry Hill Road, Flagstaff"]))
    assert values(proposal) == {"[ADDRESS_1]": "88 Quarry Hill Road, Flagstaff, AZ 86001"}


def test_model_addresses_without_substance_are_dropped():
    text = "The State of Arizona governs. See the address set forth in Section 17.12, or 84101."
    ner = fake_ner(address=["State of Arizona", "address set forth in Section 17.12", "84101"])
    assert scan_text(text, ner=ner)["proposed"] == {}


def test_entity_descriptions_are_not_companies():
    text = "Acme Works LLC, a Delaware corporation, and the Claimant agree."
    ner = fake_ner(company=["Delaware corporation", "Claimant"])
    assert values(scan_text(text, ner=ner)) == {"[COMPANY_1]": "Acme Works LLC"}


def test_shared_first_name_is_not_linked_to_either_person():
    text = "Anna Lee and Anna Ruiz met. Anna spoke."
    proposal = scan_text(text, ner=fake_ner(person=["Anna Lee", "Anna Ruiz"]))
    assert proposal["proposed"]["[PERSON_3]"]["value"] == "Anna"


def test_company_leading_words_are_caught_and_linked_to_the_full_name():
    text = "Cedar Ridge Properties LLC leases to Lumen Health. Cedar Ridge agrees. Cedar is a tree."
    proposal = scan_text(text, ner=fake_ner(company=["Lumen Health"]))
    by_value = {e["value"]: e["entity"] for e in proposal["proposed"].values()}
    assert by_value["Cedar Ridge"] == by_value["Cedar Ridge Properties LLC"]
    assert by_value["Cedar"] == by_value["Cedar Ridge Properties LLC"]
    assert by_value["Lumen Health"] != by_value["Cedar Ridge"]
    vault = merge_vault(None, proposal["proposed"])
    assert rehydrate_text(apply_vault(text, vault), vault) == text


def test_generic_leading_word_is_not_treated_as_the_company():
    text = "First Prairie Bank, N.A. holds the note. First, the parties agree."
    proposal = scan_text(text, ner=False)
    assert "First" not in {e["value"] for e in proposal["proposed"].values()}


def test_short_form_shared_by_two_companies_gets_its_own_entity():
    text = "Orion Tools Corp. and Orion Freight LLC merged. Orion survives."
    proposal = scan_text(text, ner=False)
    by_value = {e["value"]: e["entity"] for e in proposal["proposed"].values()}
    assert len({by_value["Orion Tools Corp."], by_value["Orion Freight LLC"], by_value["Orion"]}) == 3


@pytest.mark.parametrize("term", ["Employee", "the Borrower", "Landlord", "The Company"])
def test_defined_terms_are_not_treated_as_names(term):
    text = f"{term} shall notify Jane Doe."
    ner = fake_ner(person=[term, "Jane Doe"], company=[term])
    assert values(scan_text(text, ner=ner)) == {"[PERSON_1]": "Jane Doe"}


def test_courts_and_lowercase_entity_descriptions_are_not_companies():
    text = "Acme Works LLC, a Delaware limited liability company, sued in the Court of Common Pleas."
    proposal = scan_text(text, ner=fake_ner(company=["Court of Common Pleas"]))
    assert values(proposal) == {"[COMPANY_1]": "Acme Works LLC"}


def test_firm_names_without_a_legal_suffix():
    text = "Counsel at Zhang & Associates and Harlan Pryce Accounting Group replied."
    hits = [text[d.start : d.end] for d in detect_regex(text) if d.type == "company"]
    assert hits == ["Zhang & Associates", "Harlan Pryce Accounting Group"]


def test_city_state_zip_is_detected_and_joined_to_the_street():
    text = "Send to 500 Alder Avenue, Floor 9, Denver, CO 80202 or to Kansas City, MO 64106-1234."
    proposal = scan_text(text, ner=fake_ner(address=["500 Alder Avenue, Floor 9"]))
    assert values(proposal) == {
        "[ADDRESS_1]": "500 Alder Avenue, Floor 9, Denver, CO 80202",
        "[ADDRESS_2]": "Kansas City, MO 64106-1234",
    }


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
