"""Table-driven LL(1) predictive parser with panic-mode error recovery.

This module implements the textbook algorithm (Aho, Lam, Sethi, Ullman -
"Compilers: Principles, Techniques and Tools", sec. 4.4.5):

  1. compute FIRST and FOLLOW sets of an arbitrary grammar
  2. build the predictive parsing table M[A, a]
  3. mark empty entries M[A, b] with "synch" for every b in FOLLOW(A)
  4. parse with an explicit stack; on error:
       - top is a terminal that does not match   -> pop it  ("insert" it)
       - M[A, a] is empty                         -> skip input symbol a
       - M[A, a] is synch                         -> pop non-terminal A
"""

from .lexer import Lexer
from .tokens import ID, NUM, FLOAT, EOF

EPS = "ε"
END = "$"

DEFAULT_GRAMMAR = """\
E  -> T E'
E' -> + T E' | - T E' | ε
T  -> F T'
T' -> * F T' | / F T' | ε
F  -> ( E ) | id | num"""


class GrammarError(Exception):
    pass


class Grammar:
    def __init__(self, text: str):
        self.productions = {}          # A -> list of RHS (list of symbols)
        self.order = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            sep = "->" if "->" in line else ("→" if "→" in line else None)
            if not sep:
                raise GrammarError(f"missing '->' in: {line}")
            lhs, rhs = (s.strip() for s in line.split(sep, 1))
            if not lhs or " " in lhs:
                raise GrammarError(f"invalid left-hand side: '{lhs}'")
            if lhs not in self.productions:
                self.productions[lhs] = []
                self.order.append(lhs)
            for alt in rhs.split("|"):
                syms = [s for s in alt.split() if s not in ("ε", "eps", "epsilon", "#")]
                self.productions[lhs].append(syms)
        if not self.order:
            raise GrammarError("grammar is empty")
        self.start = self.order[0]
        self.nonterminals = list(self.order)
        self.terminals = sorted({s for alts in self.productions.values() for a in alts
                                 for s in a if s not in self.productions})
        self._first()
        self._follow()
        self._table()

    # ------------------------------------------------------------ FIRST
    def first_of(self, symbols):
        out = set()
        for s in symbols:
            f = self.first[s] if s in self.productions else {s}
            out |= f - {EPS}
            if EPS not in f:
                return out
        out.add(EPS)
        return out

    def _first(self):
        self.first = {a: set() for a in self.nonterminals}
        changed = True
        while changed:
            changed = False
            for a, alts in self.productions.items():
                for rhs in alts:
                    f = self.first_of(rhs)
                    if not f <= self.first[a]:
                        self.first[a] |= f
                        changed = True

    # ------------------------------------------------------------ FOLLOW
    def _follow(self):
        self.follow = {a: set() for a in self.nonterminals}
        self.follow[self.start].add(END)
        changed = True
        while changed:
            changed = False
            for a, alts in self.productions.items():
                for rhs in alts:
                    for i, b in enumerate(rhs):
                        if b not in self.productions:
                            continue
                        f = self.first_of(rhs[i + 1:])
                        add = (f - {EPS}) | (self.follow[a] if EPS in f else set())
                        if not add <= self.follow[b]:
                            self.follow[b] |= add
                            changed = True

    # ------------------------------------------------------------ TABLE
    def _table(self):
        self.table = {a: {} for a in self.nonterminals}
        self.conflicts = []
        for a, alts in self.productions.items():
            for rhs in alts:
                f = self.first_of(rhs)
                targets = (f - {EPS}) | (self.follow[a] if EPS in f else set())
                for t in targets:
                    if t in self.table[a] and self.table[a][t] != rhs:
                        self.conflicts.append(
                            f"M[{a}, {t}]: {fmt(a, self.table[a][t])}  vs  {fmt(a, rhs)}")
                    else:
                        self.table[a][t] = rhs
        # synch entries for panic-mode recovery
        for a in self.nonterminals:
            for t in self.follow[a]:
                self.table[a].setdefault(t, "synch")

    @property
    def is_ll1(self):
        return not self.conflicts

    @property
    def columns(self):
        return self.terminals + [END]


def fmt(lhs, rhs):
    return f"{lhs} → {' '.join(rhs) if rhs else EPS}"


def tokens_for(grammar, text):
    """Map source text to grammar terminals (identifiers -> id, numbers -> num)."""
    toks, _, _ = Lexer(text).tokenize()
    out = []
    for t in toks:
        if t.kind == EOF:
            break
        if t.kind == ID and t.lexeme not in grammar.terminals:
            out.append(("id", t.lexeme))
        elif t.kind in (NUM, FLOAT):
            out.append(("num", t.lexeme))
        else:
            out.append((t.lexeme, t.lexeme))
    return out


def parse_ll1(grammar, tokens, max_steps=500):
    """Return (trace_rows, errors). Each row: stack, input, action, error flag."""
    inp = list(tokens) + [(END, END)]
    stack = [END, grammar.start]
    ip = 0
    rows, errors = [], []

    def row(action, err=False):
        rows.append({
            "stack": " ".join(stack),
            "input": " ".join(lx for _, lx in inp[ip:]),
            "action": action,
            "error": err,
        })

    for _ in range(max_steps):
        top = stack[-1]
        a, lexeme = inp[ip]
        if top == END and a == END:
            row("ACCEPT" if not errors else f"ACCEPT (after recovering from {len(errors)} error(s))")
            return rows, errors
        if top not in grammar.productions:                     # terminal or $
            if top == a:
                row(f"match '{lexeme}'")
                stack.pop()
                ip += 1
            elif top == END:                                    # extra input after a complete parse
                msg = f"extra input '{lexeme}' after a complete expression"
                errors.append(msg)
                row(f"ERROR: {msg} -> skip '{lexeme}'", True)
                ip += 1
            else:
                msg = f"missing '{top}' before '{lexeme}'"
                errors.append(msg)
                row(f"ERROR: {msg} -> pop '{top}' (pretend it was inserted)", True)
                stack.pop()
            continue
        entry = grammar.table[top].get(a)
        if isinstance(entry, list):
            row(f"output {fmt(top, entry)}")
            stack.pop()
            stack.extend(reversed(entry))
        elif entry == "synch":
            msg = f"unexpected '{lexeme}' while expanding {top}"
            errors.append(msg)
            row(f"ERROR: {msg}; M[{top}, {a}] = synch -> pop {top}", True)
            stack.pop()
        else:
            msg = f"unexpected '{lexeme}' while expanding {top}"
            errors.append(msg)
            if a == END:
                row(f"ERROR: {msg}; at end of input -> pop {top}", True)
                stack.pop()
            else:
                row(f"ERROR: {msg}; M[{top}, {a}] empty -> skip '{lexeme}'", True)
                ip += 1
    row("ABORT: step limit reached", True)
    return rows, errors
