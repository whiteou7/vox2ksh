"""Builds the Advanced panel from render_chart.build_arg_parser(), skipping options the worker sets per chart (-d, -a, -o, --se-bank-dir, --dry).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: F401,E402  (adds scripts/audio to sys.path)
import render_chart  # noqa: E402

PER_CHART_DESTS = {"folder", "difficulty", "audio", "output", "dry", "se_bank_dir", "help"}


class OptionSpec:
    def __init__(self, action):
        self.dest = action.dest
        self.flag = max(action.option_strings, key=len)
        self.default = action.default
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
    ap = render_chart.build_arg_parser()
    out = []
    for action in ap._actions:
        if action.dest in PER_CHART_DESTS:
            continue
        out.append(OptionSpec(action))
    return out


def build_cli_args(values):
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
