"""Diagnostics (error / warning records) and source repairs."""

import itertools
from dataclasses import dataclass, field

# Recovery strategy names (used in reports, GUI and statistics)
PANIC = "Panic Mode"
PHRASE = "Phrase Level"
ERROR_PRODUCTION = "Error Production"
GLOBAL = "Global (Delimiter)"
LEXICAL = "Lexical Recovery"
NONE = "No Recovery"

STRATEGIES = [PANIC, PHRASE, ERROR_PRODUCTION, GLOBAL, LEXICAL]


@dataclass
class Diagnostic:
    phase: str          # Lexical | Syntax | Delimiter
    severity: str       # error | warning | note
    line: int
    col: int
    message: str
    strategy: str       # one of the strategy names above
    action: str = ""    # what the recovery routine actually did
    suggestion: str = ""
    pos: int = 0        # source offset (for editor highlighting)
    length: int = 1

    def format(self) -> str:
        s = f"{self.line}:{self.col}: {self.severity}: {self.message}"
        if self.suggestion:
            s += f"  (hint: {self.suggestion})"
        return s


@dataclass(order=True)
class Repair:
    """A textual edit: replace source[pos:pos+length] with text."""
    pos: int
    seq: int
    length: int = field(compare=False)
    text: str = field(compare=False)
    reason: str = field(compare=False, default="")


_seq = itertools.count()


def make_repair(pos: int, length: int, text: str, reason: str = "") -> Repair:
    """Create a repair; the sequence number keeps same-position edits ordered."""
    return Repair(pos, next(_seq), length, text, reason)
