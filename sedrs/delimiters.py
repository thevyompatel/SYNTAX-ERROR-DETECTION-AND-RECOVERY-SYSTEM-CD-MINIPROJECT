"""Global delimiter-balance analysis.

A single stack-based pass over the token stream that matches ( ) [ ] { }.
Because it sees the whole program at once it can say *where* an unmatched
bracket was opened - information a left-to-right parser has already lost by
the time it notices the problem. Results are reported as notes that explain
the root cause of the parser's syntax errors.
"""

from .diagnostics import Diagnostic, GLOBAL
from .tokens import EOF

PAIRS = {")": "(", "]": "[", "}": "{"}
OPEN = {"(": ")", "[": "]", "{": "}"}
NAMES = {"(": "parenthesis", "[": "bracket", "{": "brace",
         ")": "parenthesis", "]": "bracket", "}": "brace"}


def check_delimiters(tokens):
    diags = []
    stack = []
    for t in tokens:
        if t.kind == EOF:
            break
        if t.kind in ("{", "}"):
            # '(' and '[' never span a block boundary: report them here, where
            # the mistake is, instead of at some far-away closing brace
            while stack and stack[-1].kind in ("(", "["):
                o = stack.pop()
                diags.append(_note(o, f"'{o.kind}' opened at line {o.line} is not closed "
                                      f"before '{t.kind}' at line {t.line}",
                                   f"insert '{OPEN[o.kind]}' before '{t.kind}'"))
        if t.kind in OPEN:
            stack.append(t)
        elif t.kind in PAIRS:
            want = PAIRS[t.kind]
            if stack and stack[-1].kind == want:
                stack.pop()
            elif any(s.kind == want for s in stack):
                # mismatch: everything opened after the matching opener is unclosed
                while stack and stack[-1].kind != want:
                    o = stack.pop()
                    diags.append(_note(o, f"'{o.kind}' opened at line {o.line} is not closed "
                                          f"before '{t.kind}' at line {t.line}",
                                       f"insert '{OPEN[o.kind]}' before line {t.line}"))
                stack.pop()
            else:
                diags.append(_note(t, f"unmatched closing {NAMES[t.kind]} '{t.kind}'",
                                   f"remove it or add a matching '{want}'"))
    for o in stack:
        diags.append(_note(o, f"'{o.kind}' opened at line {o.line} is never closed",
                           f"add a matching '{OPEN[o.kind]}'"))
    diags.sort(key=lambda d: d.pos)
    return diags


def _note(tok, msg, suggestion):
    return Diagnostic("Delimiter", "note", tok.line, tok.col, msg, GLOBAL,
                      "reported root cause (balance analysis over whole file)",
                      suggestion, tok.pos, 1)
