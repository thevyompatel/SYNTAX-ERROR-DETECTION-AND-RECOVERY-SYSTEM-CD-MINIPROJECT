"""Lexical analyser for MiniC with lexical error detection and recovery.

Lexical errors handled
----------------------
* illegal character (e.g. '@', '#', '$')       -> character deleted
* single '&' or '|'                            -> replaced with '&&' / '||'
* unterminated string literal                  -> closing quote inserted
* unterminated block comment                   -> '*/' inserted at EOF
* malformed number (e.g. 12.5.3)               -> extra part deleted
* identifier starting with a digit (e.g. 9abc) -> treated as identifier '_9abc'
* malformed character literal                  -> treated as char literal
"""

from .tokens import Token, KEYWORDS, OPERATORS, ID, NUM, FLOAT, STRING, CHAR, EOF
from .diagnostics import Diagnostic, make_repair, LEXICAL


class Lexer:
    def __init__(self, source: str):
        self.src = source
        self.i = 0
        self.line = 1
        self.col = 1
        self.tokens = []
        self.diagnostics = []
        self.repairs = []

    # ------------------------------------------------------------------ helpers
    def _peek(self, k=0):
        j = self.i + k
        return self.src[j] if j < len(self.src) else ""

    def _advance(self, n=1):
        for _ in range(n):
            if self.i >= len(self.src):
                return
            if self.src[self.i] == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            self.i += 1

    def _error(self, line, col, pos, length, msg, action, suggestion=""):
        self.diagnostics.append(Diagnostic(
            "Lexical", "error", line, col, msg, LEXICAL, action, suggestion, pos, max(1, length)))

    def _add(self, kind, lexeme, line, col, pos):
        self.tokens.append(Token(kind, lexeme, line, col, pos))

    # --------------------------------------------------------------------- main
    def tokenize(self):
        src = self.src
        while self.i < len(src):
            c = src[self.i]
            line, col, pos = self.line, self.col, self.i

            if c in " \t\r\n":
                self._advance()
                continue

            # comments
            if c == "/" and self._peek(1) == "/":
                while self.i < len(src) and src[self.i] != "\n":
                    self._advance()
                continue
            if c == "/" and self._peek(1) == "*":
                end = src.find("*/", self.i + 2)
                if end == -1:
                    self._error(line, col, pos, 2, "unterminated block comment",
                                "inserted '*/' at end of file",
                                "close the comment with */")
                    self.repairs.append(make_repair(len(src), 0, " */", "close comment"))
                    self._advance(len(src) - self.i)
                else:
                    self._advance(end + 2 - self.i)
                continue

            if c.isdigit() or (c == "." and self._peek(1).isdigit()):
                self._number(line, col, pos)
                continue

            if c.isalpha() or c == "_":
                j = self.i
                while j < len(src) and (src[j].isalnum() or src[j] == "_"):
                    j += 1
                word = src[self.i:j]
                self._add(word if word in KEYWORDS else ID, word, line, col, pos)
                self._advance(j - self.i)
                continue

            if c == '"':
                self._string(line, col, pos)
                continue

            if c == "'":
                self._char(line, col, pos)
                continue

            op = next((o for o in OPERATORS if src.startswith(o, self.i)), None)
            if op:
                self._add(op, op, line, col, pos)
                self._advance(len(op))
                continue

            if c in "&|":
                fixed = c * 2
                self._error(line, col, pos, 1, f"invalid operator '{c}'",
                            f"replaced with logical operator '{fixed}'",
                            f"did you mean '{fixed}'? (bitwise operators are not supported)")
                self.repairs.append(make_repair(pos, 1, fixed, "fix operator"))
                # kind is the corrected operator, lexeme keeps the source width
                self._add(fixed, c, line, col, pos)
                self._advance()
                continue

            # anything else is an illegal character: report and delete it
            self._error(line, col, pos, 1, f"illegal character '{c}'",
                        f"deleted '{c}' and continued scanning")
            self.repairs.append(make_repair(pos, 1, "", "delete illegal char"))
            self._advance()

        self.tokens.append(Token(EOF, "", self.line, self.col, len(src)))
        return self.tokens, self.diagnostics, self.repairs

    # ---------------------------------------------------------------- literals
    def _number(self, line, col, pos):
        src = self.src
        j = self.i
        while j < len(src) and (src[j].isdigit() or src[j] == "."):
            j += 1
        text = src[self.i:j]

        # identifier that starts with a digit, e.g. 9abc
        if j < len(src) and (src[j].isalpha() or src[j] == "_"):
            while j < len(src) and (src[j].isalnum() or src[j] == "_"):
                j += 1
            bad = src[self.i:j]
            self._error(line, col, pos, len(bad),
                        f"invalid identifier '{bad}' (identifiers cannot start with a digit)",
                        f"treated as identifier '_{bad}'",
                        f"rename it, e.g. '_{bad}'")
            self.repairs.append(make_repair(pos, 0, "_", "fix identifier"))
            self._add(ID, bad, line, col, pos)
            self._advance(j - self.i)
            return

        if text.count(".") > 1:
            first = text.index(".")
            second = text.index(".", first + 1)
            good = text[:second]
            self._error(line, col, pos, len(text), f"malformed number '{text}'",
                        f"truncated to '{good}'", "a number may contain only one decimal point")
            self.repairs.append(make_repair(pos + second, len(text) - second, "", "fix number"))
            self._add(FLOAT, text, line, col, pos)
        elif "." in text:
            self._add(FLOAT, text, line, col, pos)
        else:
            self._add(NUM, text, line, col, pos)
        self._advance(j - self.i)

    def _string(self, line, col, pos):
        src = self.src
        j = self.i + 1
        while j < len(src) and src[j] not in '"\n':
            j += 2 if src[j] == "\\" else 1
        if j < len(src) and src[j] == '"':
            self._add(STRING, src[self.i:j + 1], line, col, pos)
            self._advance(j + 1 - self.i)
            return
        j = min(j, len(src))
        text = src[self.i:j].rstrip("\r")
        self._error(line, col, pos, len(text), "unterminated string literal",
                    "inserted closing '\"' at end of line",
                    "strings must be closed on the same line")
        self.repairs.append(make_repair(pos + len(text), 0, '"', "close string"))
        self._add(STRING, text, line, col, pos)
        self._advance(len(text))

    def _char(self, line, col, pos):
        src = self.src
        if self._peek(1) == "\\" and self._peek(3) == "'":
            n = 4
        elif self._peek(1) not in ("'", "\n", "") and self._peek(2) == "'":
            n = 3
        else:
            # malformed: consume up to the next quote on this line (or 1 char)
            j = self.i + 1
            while j < len(src) and src[j] not in "'\n;":
                j += 1
            n = (j - self.i + 1) if j < len(src) and src[j] == "'" else (j - self.i)
            text = src[self.i:self.i + n]
            fixed = "'" + (text.strip("'")[:1] or " ") + "'"
            self._error(line, col, pos, n, f"malformed character literal {text}",
                        f"truncated to {fixed}",
                        "a char literal holds exactly one character, e.g. 'a'")
            self.repairs.append(make_repair(pos, n, fixed, "fix char literal"))
            self._add(CHAR, text, line, col, pos)
            self._advance(n)
            return
        self._add(CHAR, src[self.i:self.i + n], line, col, pos)
        self._advance(n)


def tokenize(source: str):
    return Lexer(source).tokenize()
