"""Write the Process Monitor filter used for the network check.

    python packaging/windows/make_procmon_filter.py   # needs: pip install procmon-parser

Writes two filters into packaging/windows/:

- replace_o_matic_network.pmc: Process Name is Replace-o-matic.exe, and
  Operation begins with TCP or UDP (Process Monitor ORs rules on the same column
  and ANDs different columns). For looking by hand: the list must stay empty.
- replace_o_matic_process.pmc: Process Name is Replace-o-matic.exe only. Used by
  procmon_check.ps1, so the capture also proves Process Monitor saw the app
  (thousands of file and registry events) while the network count stays zero.

Both drop filtered-out events, so a capture holds nothing from other programs.
"""

import os

from procmon_parser import Column, Rule, RuleAction, RuleRelation, dump_configuration

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = [
    Rule(Column.PROCESS_NAME, RuleRelation.IS, "Replace-o-matic.exe", RuleAction.INCLUDE),
    Rule(Column.OPERATION, RuleRelation.BEGINS_WITH, "TCP", RuleAction.INCLUDE),
    Rule(Column.OPERATION, RuleRelation.BEGINS_WITH, "UDP", RuleAction.INCLUDE),
]


def main() -> None:
    for name, rules in (("replace_o_matic_network.pmc", RULES), ("replace_o_matic_process.pmc", RULES[:1])):
        path = os.path.join(HERE, name)
        with open(path, "wb") as f:
            dump_configuration({"FilterRules": rules, "DestructiveFilter": 1}, f)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
