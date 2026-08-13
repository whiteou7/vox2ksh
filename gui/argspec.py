"""Introspects apply_chart.build_arg_parser() into control specs for the
Advanced panel, instead of hand-duplicating the option list - see
apply_chart.py's build_arg_parser() docstring for why it's a separate
function. Anything added to that parser shows up here automatically; nothing
needs editing on the GUI side when apply_chart.py grows a new flag.

Excluded: everything the GUI already computes per song/chart itself
(the positional chart folder, -d/--difficulty, -a/--audio, -o/--output,
--dry, --se-bank-dir) - matching the task's own "per-chart args such as -d
or -o can be omitted" instruction, extended to the other per-chart/per-batch
paths this project's apply_chart.py grew for the GUI's benefit.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: F401,E402  (adds scripts/audio to sys.path)
import apply_chart  # noqa: E402

PER_CHART_DESTS = {"folder", "difficulty", "audio", "output", "dry", "se_bank_dir", "help"}


class OptionSpec:
    """One CLI option, ready for a widget to bind to.

    kind: "bool" (store_true, default False), "choice" (argparse `choices`),
    "float" / "int" (numeric Entry), or "str" (anything else).
    """

    def __init__(self, action):
        self.dest = action.dest
        self.flag = max(action.option_strings, key=len)   # prefer --long-form
        self.default = action.default
        # argparse defers %(default)s-style substitution to display time
        # (HelpFormatter._expand_help), which we're bypassing by reading
        # action.help directly - so do the same substitution here, the same
        # way, or "(default %(default)g)" and the "50%%"-style escaped
        # literal percents in apply_chart.py's help text show up unexpanded.
        raw = (action.help or "").strip()
        try:
            self.help = raw % vars(action)
        except (KeyError, ValueError, TypeError):
            self.help = raw
        self.choices = list(action.choices) if action.choices else None
        if action.const is True and action.default is False:
            self.kind = "bool"
        elif self.choices:
            self.kind = "choice"
        elif action.type is float:
            self.kind = "float"
        elif action.type is int:
            self.kind = "int"
        else:
            self.kind = "str"

    def __repr__(self):
        return "OptionSpec(%s, %s, default=%r)" % (self.flag, self.kind, self.default)


def advanced_options():
    """-> list[OptionSpec], in the order apply_chart.py declares them."""
    ap = apply_chart.build_arg_parser()
    out = []
    for action in ap._actions:
        if action.dest in PER_CHART_DESTS:
            continue
        out.append(OptionSpec(action))
    return out


def build_cli_args(values):
    """{dest: current_value} + the option specs -> ["--flag", "val", ...],
    only for values that differ from the script's own default (so an
    untouched Advanced panel produces exactly the same command line as
    leaving it closed, and the debug console shows only what was actually
    customised).
    """
    specs = {s.dest: s for s in advanced_options()}
    args = []
    for dest, value in values.items():
        spec = specs.get(dest)
        if spec is None or value == spec.default:
            continue
        if spec.kind == "bool":
            if value:
                args.append(spec.flag)
            continue
        args += [spec.flag, str(value)]
    return args
