"""Measure what the detector misses on the labelled passages in tests/eval.

    python scripts/evaluate.py                    # default threshold
    python scripts/evaluate.py -t 0.2 0.3 0.4 0.5 # compare thresholds
    python scripts/evaluate.py -v                 # list every miss and extra
    python scripts/evaluate.py -f holdout.json    # the held-out set

A labelled string counts as *leaked* if any of its characters survive
redaction. Recall is the share of labelled characters that were redacted.
"Extra" redactions are spans that touch no labelled string (over-redaction).
"""

import argparse
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import sanitizer_core as sc  # noqa: E402

EVAL_DIR = os.path.join(ROOT, "tests", "eval")


def gold_spans(text, entities):
    """Every whole-word occurrence of every labelled string: (start, end, type, string)."""
    spans = []
    for entity in entities:
        value = entity["text"]
        left = r"(?<!\w)" if value[0].isalnum() else ""
        right = r"(?!\w)" if value[-1].isalnum() else ""
        for m in re.finditer(left + re.escape(value) + right, text):
            spans.append((m.start(), m.end(), entity["type"], value))
    return spans


def evaluate(passages, ner):
    stats = {"gold_chars": 0, "hit_chars": 0, "gold": Counter(), "leaked": Counter()}
    leaks, extras = [], []
    for passage in passages:
        text = passage["text"]
        proposal = sc.scan_text(text, ner=ner)
        vault = sc.merge_vault(None, proposal["proposed"])
        if sc.rehydrate_text(sc.apply_vault(text, vault), vault) != text:
            raise AssertionError(f"round-trip failed on {passage['id']}")

        redacted = [False] * len(text)
        spans = sc.find_vault_spans(text, vault)
        for start, end, _ in spans:
            redacted[start:end] = [True] * (end - start)

        gold = [False] * len(text)
        # Longest label first, so "Smith" inside "John Smith" is not double-counted.
        seen = [False] * len(text)
        for start, end, etype, value in sorted(
            gold_spans(text, passage["entities"]), key=lambda s: s[0] - s[1]
        ):
            gold[start:end] = [True] * (end - start)
            if any(seen[start:end]):
                continue
            seen[start:end] = [True] * (end - start)
            chars = [i for i in range(start, end) if not text[i].isspace()]
            missed = [i for i in chars if not redacted[i]]
            stats["gold"][etype] += 1
            stats["gold_chars"] += len(chars)
            stats["hit_chars"] += len(chars) - len(missed)
            if missed:
                stats["leaked"][etype] += 1
                left = "".join(text[i] if not redacted[i] else "#" for i in range(start, end))
                leaks.append((passage["id"], etype, value, left))

        for start, end, placeholder in spans:
            if not any(gold[start:end]):
                extras.append((passage["id"], placeholder, text[start:end]))
    return stats, leaks, extras


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-t", "--threshold", type=float, nargs="+", default=[None])
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-f", "--file", default="passages.json", help="file in tests/eval")
    parser.add_argument("--regex-only", action="store_true", help="skip the model")
    args = parser.parse_args()

    with open(os.path.join(EVAL_DIR, args.file), encoding="utf-8") as fh:
        passages = json.load(fh)
    detector = False if args.regex_only else sc.default_detector()

    for threshold in args.threshold:
        if detector and threshold is not None:
            detector.threshold = threshold
        stats, leaks, extras = evaluate(passages, detector)
        label = "regex only" if not detector else f"threshold {detector.threshold}"
        total, leaked = sum(stats["gold"].values()), sum(stats["leaked"].values())
        print(f"\n== {label}: {len(passages)} passages ==")
        print(f"character recall   {stats['hit_chars'] / max(stats['gold_chars'], 1):.1%}")
        print(f"labelled mentions  {total}, leaked (fully or partly) {leaked}")
        for etype in sc.ENTITY_TYPES:
            if stats["gold"][etype]:
                print(f"  {etype:13} {stats['leaked'][etype]:3} leaked of {stats['gold'][etype]}")
        print(f"extra redactions   {len(extras)}")
        if args.verbose:
            print("\nLeaks (# = redacted character):")
            for pid, etype, value, left in leaks:
                print(f"  {pid:18} {etype:13} {value!r} -> {left!r}")
            print("\nExtra redactions:")
            for pid, placeholder, value in extras:
                print(f"  {pid:18} {placeholder:22} {value!r}")


if __name__ == "__main__":
    main()
