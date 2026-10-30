"""SEDRS - Syntax Error Detection and Recovery System (entry point).

Usage
  python main.py                         launch the GUI
  python main.py FILE [options]          analyse a MiniC file on the console

Options
  --mode full|panic|none   recovery mode (default: full)
  --tokens                 print the token table
  --tree                   print the parse tree
  --log                    print the parser's recovery log
  --fix OUTFILE            write the automatically corrected program
  --compare                run all three modes and compare the results
  --ll1 "EXPR"             run the table-driven LL(1) parser on an expression
"""

import argparse
import os
import sys

from sedrs import analyze
from sedrs.parser import MODES
from sedrs.tokens import category

if os.name == "nt":
    os.system("")                       # enable ANSI colours on Windows terminals
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

C = {"error": "\033[91m", "warning": "\033[93m", "note": "\033[96m",
     "b": "\033[1m", "dim": "\033[2m", "g": "\033[92m", "x": "\033[0m"}


def print_report(res, path, show_tokens=False, show_tree=False, show_log=False):
    lines = res.source.splitlines()
    print(f"{C['b']}SEDRS analysis of {path}{C['x']}  [{MODES[res.mode]}]")
    print("=" * 78)
    if show_tokens:
        print(f"{C['b']}TOKENS{C['x']}")
        for t in res.tokens:
            print(f"  {t.line:>3}:{t.col:<3} {category(t):<15} {t.kind:<8} {t.lexeme}")
        print()

    for d in res.diagnostics:
        col = C[d.severity]
        print(f"{col}{C['b']}{d.severity.upper()}{C['x']} [{d.phase}] line {d.line}, col {d.col}: {d.message}")
        if 0 < d.line <= len(lines):
            src = lines[d.line - 1].replace("\t", " ")
            print(f"   {C['dim']}{d.line:>4} |{C['x']} {src}")
            print(f"        | {' ' * (d.col - 1)}{col}^{C['x']}")
        print(f"        {C['g']}recovery:{C['x']} {d.strategy} - {d.action}")
        if d.suggestion:
            print(f"        {C['g']}hint:{C['x']} {d.suggestion}")
        print()

    s = res.stats
    print("-" * 78)
    status = "HALTED at first error" if res.halted else "completed"
    print(f"Parsing {status}: {s['errors']} error(s), {s['warnings']} warning(s), "
          f"{s['notes']} note(s), {s['repairs']} repair(s), "
          f"{res.suppressed} cascading error(s) suppressed, {res.elapsed_ms:.2f} ms")
    if s["by_strategy"]:
        print("By recovery strategy: " + ", ".join(f"{k}: {v}" for k, v in s["by_strategy"].items()))
    if show_log:
        print(f"\n{C['b']}RECOVERY LOG{C['x']}")
        print("\n".join(res.log) or "  (no events)")
    if show_tree:
        print(f"\n{C['b']}PARSE TREE{C['x']}")
        print(res.tree.to_text("  "))


def compare(source, path):
    print(f"{C['b']}Comparison of recovery modes for {path}{C['x']}\n")
    print(f"{'Mode':<62}{'Errors':>7}{'Warn':>6}{'Lines analysed':>16}")
    total = source.count("\n") + 1
    for mode, label in MODES.items():
        r = analyze(source, mode)
        last = r.diagnostics[-1].line if r.halted and r.diagnostics else total
        print(f"{label:<62}{r.stats['errors']:>7}{r.stats['warnings']:>6}{f'{last}/{total}':>16}")
    print()


def run_ll1(expr):
    from sedrs.ll1 import Grammar, DEFAULT_GRAMMAR, parse_ll1, tokens_for
    g = Grammar(DEFAULT_GRAMMAR)
    print(f"{C['b']}Grammar{C['x']}\n{DEFAULT_GRAMMAR}\n")
    print(f"{C['b']}FIRST / FOLLOW{C['x']}")
    for nt in g.nonterminals:
        print(f"  {nt:<4} FIRST = {{ {', '.join(sorted(g.first[nt]))} }}   "
              f"FOLLOW = {{ {', '.join(sorted(g.follow[nt]))} }}")
    rows, errors = parse_ll1(g, tokens_for(g, expr))
    print(f"\n{C['b']}Trace for: {expr}{C['x']}")
    print(f"  {'Stack':<28}{'Input':<28}Action")
    for r in rows:
        mark = C["error"] if r["error"] else ""
        print(f"  {mark}{r['stack']:<28}{r['input']:<28}{r['action']}{C['x']}")
    print(f"\n{len(errors)} error(s) recovered." if errors else "\nAccepted with no errors.")


def main():
    ap = argparse.ArgumentParser(description="Syntax Error Detection and Recovery System")
    ap.add_argument("file", nargs="?")
    ap.add_argument("--mode", choices=list(MODES), default="full")
    ap.add_argument("--tokens", action="store_true")
    ap.add_argument("--tree", action="store_true")
    ap.add_argument("--log", action="store_true")
    ap.add_argument("--fix", metavar="OUTFILE")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--ll1", metavar="EXPR")
    args = ap.parse_args()

    if args.ll1:
        run_ll1(args.ll1)
        return
    if not args.file:
        from gui import run_gui
        run_gui()
        return

    with open(args.file, encoding="utf-8") as f:
        source = f.read()
    if args.compare:
        compare(source, args.file)
    res = analyze(source, args.mode)
    print_report(res, args.file, args.tokens, args.tree, args.log)
    if args.fix:
        with open(args.fix, "w", encoding="utf-8") as f:
            f.write(res.corrected)
        print(f"\nCorrected program written to {args.fix}")
    sys.exit(1 if res.stats["errors"] else 0)


if __name__ == "__main__":
    main()
