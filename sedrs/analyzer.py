"""Facade that runs every phase and collects the results."""

import time
from collections import Counter
from dataclasses import dataclass, field

from .lexer import Lexer
from .delimiters import check_delimiters
from .parser import Parser, Node
from .repair import apply_repairs


@dataclass
class AnalysisResult:
    source: str
    mode: str
    tokens: list
    diagnostics: list
    tree: Node
    log: list
    corrected: str
    corrected_marks: list
    repairs: list
    halted: bool
    suppressed: int
    elapsed_ms: float
    stats: dict = field(default_factory=dict)

    @property
    def errors(self):
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self):
        return [d for d in self.diagnostics if d.severity == "warning"]

    @property
    def notes(self):
        return [d for d in self.diagnostics if d.severity == "note"]


def analyze(source: str, mode: str = "full") -> AnalysisResult:
    t0 = time.perf_counter()

    lexer = Lexer(source)
    tokens, lex_diags, lex_repairs = lexer.tokenize()
    if mode == "none" and lex_diags:
        # a non-recovering compiler stops at the first lexical error
        lex_diags = lex_diags[:1]
        lex_diags[0].strategy = "No Recovery"
        lex_diags[0].action = "compilation halted at first lexical error"
        tree = Node("PARSING HALTED (lexical error)", error=True)
        parser_diags, parser_repairs, log, halted, suppressed = [], [], [], True, 0
        delim = []
    else:
        delim = check_delimiters(tokens) if mode != "none" else []
        parser = Parser(tokens, source, mode)
        tree = parser.parse()
        parser_diags, parser_repairs = parser.diagnostics, parser.repairs
        log, halted, suppressed = parser.log, parser.halted, parser.suppressed

    diags = sorted(lex_diags + parser_diags + delim, key=lambda d: (d.pos, d.phase != "Lexical"))
    repairs = (lex_repairs if mode == "full" else []) + (parser_repairs if mode != "none" else [])
    corrected, marks = apply_repairs(source, repairs)

    elapsed = (time.perf_counter() - t0) * 1000
    by_strategy = Counter(d.strategy for d in diags if d.severity != "note")
    stats = {
        "lines": source.count("\n") + 1,
        "tokens": len(tokens) - 1,
        "errors": sum(d.severity == "error" for d in diags),
        "warnings": sum(d.severity == "warning" for d in diags),
        "notes": sum(d.severity == "note" for d in diags),
        "repairs": len(repairs),
        "by_strategy": dict(by_strategy),
    }
    return AnalysisResult(source, mode, tokens, diags, tree, log, corrected, marks,
                          repairs, halted, suppressed, elapsed, stats)
