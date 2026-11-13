"""Score the tool against a reviewed label sheet for real documents.

    python scripts/evaluate_labels.py labels.csv "Will Compendia (docx)=/path/will.docx" ...

The sheet is a CSV with the columns ``document``, ``sensitive (yes/no)``,
``type`` and ``text`` (others are ignored). Each ``NAME=path`` argument ties a
value of the ``document`` column to its file. Only rows marked yes are scored.
A label counts as leaked if any of its characters survive redaction.

Real documents and their label sheets stay out of the repository.
"""

import csv
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit("/", 2)[0])

import sanitizer_core as sc  # noqa: E402
import sanitizer_cli as cli  # noqa: E402


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    paths = dict(arg.split("=", 1) for arg in argv[1:])
    labels = defaultdict(list)
    with open(argv[0], encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["sensitive (yes/no)"].strip().lower().startswith("y") and row["text"].strip():
                labels[row["document"]].append((row["type"].strip(), row["text"].strip()))

    total = hit = 0
    for name, path in paths.items():
        text = cli.read_document(path)
        vault = sc.merge_vault(None, sc.scan_text(text)["proposed"])
        redacted = bytearray(len(text))
        for start, end, _ in sc.find_vault_spans(text, vault):
            redacted[start:end] = b"\x01" * (end - start)
        seen = bytearray(len(text))
        outcome, doc_total, doc_hit, leaks = Counter(), 0, 0, []
        for etype, value in sorted(labels[name], key=lambda item: -len(item[1])):
            pattern = r"(?<!\w)" + r"\s+".join(map(re.escape, value.split())) + r"(?!\w)"
            chars = [
                i
                for m in re.finditer(pattern, text)
                for i in range(m.start(), m.end())
                if not text[i].isspace() and not seen[i]
            ]
            for i in chars:
                seen[i] = 1
            if not chars:
                outcome["not found in document"] += 1
                continue
            covered = sum(redacted[i] for i in chars)
            doc_total += len(chars)
            doc_hit += covered
            result = "caught" if covered == len(chars) else "missed" if not covered else "partly"
            outcome[result] += 1
            if result != "caught":
                leaks.append(f"    {result:7} {etype:13} {value!r}")
        total += doc_total
        hit += doc_hit
        print(f"\n{name}: {len(labels[name])} labels, {dict(outcome)}")
        print(f"  sensitive characters redacted: {doc_hit / max(doc_total, 1):.1%}")
        print("\n".join(leaks))
    print(f"\nAll documents: {hit / max(total, 1):.1%} of sensitive characters redacted")


if __name__ == "__main__":
    main(sys.argv[1:])
