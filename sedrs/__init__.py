"""SEDRS - Syntax Error Detection and Recovery System.

Compiler Design Mini Project
Team: Vyom Patel (202307020084), Priti Sisodiya (20230702088),
      Krushil Rafaliya (202307020090)

Package layout
--------------
tokens.py      Token definitions, keyword / operator tables
diagnostics.py Diagnostic + Repair records shared by every phase
lexer.py       Scanner with lexical error recovery
delimiters.py  Global delimiter-balance analysis (stack based)
parser.py      Recursive-descent parser with panic-mode, phrase-level
               and error-production recovery
repair.py      Applies recorded repairs to produce corrected source
ll1.py         Table-driven LL(1) parser: FIRST/FOLLOW, parse table with
               synch entries, panic-mode trace (textbook algorithm)
analyzer.py    One-call facade used by the GUI, CLI and tests
"""

from .analyzer import analyze, AnalysisResult  # noqa: F401

__version__ = "1.0.0"
