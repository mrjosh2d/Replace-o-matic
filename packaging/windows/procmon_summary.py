"""Summarise a Process Monitor capture of Replace-o-matic.exe without keeping it.

    python packaging/windows/procmon_summary.py capture.pml   # needs: pip install procmon-parser

Prints event counts by class and every network (TCP/UDP) operation. Prints no
paths, so the summary is safe to commit; the .pml itself is not (it lists the
names of the files the app opened). Exit code 1 if there was any network event
or no event from the app at all.
"""

import collections
import sys

from procmon_parser import ProcmonLogsReader
from procmon_parser.consts import EventClass

APP = "replace-o-matic.exe"


def main() -> int:
    by_class = collections.Counter()
    network = []
    with open(sys.argv[1], "rb") as f:
        for event in ProcmonLogsReader(f):
            if event.process.process_name.lower() != APP:
                continue
            # Class 6 (named IPC by procmon-parser) is local pipe reads and writes.
            event_class = EventClass(int(event.event_class)).name
            by_class[event_class] += 1
            operation = event.operation if isinstance(event.operation, str) else event.operation.name
            if event_class.upper() == "NETWORK" or operation.upper().startswith(("TCP", "UDP")):
                network.append(f"{operation} {event.path}")
    total = sum(by_class.values())
    print(f"events from {APP}: {total}")
    for name, count in by_class.most_common():
        print(f"  {name}: {count}")
    print(f"network (TCP/UDP) events: {len(network)}")
    for line in network[:50]:
        print("  " + line)
    if total == 0:
        print("FAILED: no events from the app; the capture did not see it")
        return 1
    return 1 if network else 0


if __name__ == "__main__":
    sys.exit(main())
