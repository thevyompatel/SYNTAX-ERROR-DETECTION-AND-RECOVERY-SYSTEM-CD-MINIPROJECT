"""Token definitions for the MiniC language."""

from dataclasses import dataclass

TYPE_KEYWORDS = {"int", "float", "char", "bool", "void"}
STMT_KEYWORDS = {"if", "else", "while", "for", "return", "print", "break", "continue"}
LITERAL_KEYWORDS = {"true", "false"}
KEYWORDS = TYPE_KEYWORDS | STMT_KEYWORDS | LITERAL_KEYWORDS

# Longest operators first so the scanner uses maximal munch.
OPERATORS = [
    "==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=",
    "+", "-", "*", "/", "%", "=", "<", ">", "!",
    ";", ",", "(", ")", "{", "}", "[", "]",
]

# Token kinds that are not keywords / operators.
ID, NUM, FLOAT, STRING, CHAR, EOF = "ID", "NUM", "FLOAT", "STRING", "CHAR", "EOF"

BINARY_OPS = {"||", "&&", "==", "!=", "<", ">", "<=", ">=", "+", "-", "*", "/", "%"}
ASSIGN_OPS = {"=", "+=", "-="}
EXPR_START = {ID, NUM, FLOAT, STRING, CHAR, "true", "false", "(", "-", "!"}

# Tokens at which panic mode may resume parsing (synchronizing set).
SYNC_TOKENS = {";", "}", "{", EOF} | TYPE_KEYWORDS | (STMT_KEYWORDS - {"else"})


@dataclass
class Token:
    kind: str          # ID, NUM, keyword text, operator text, EOF ...
    lexeme: str        # exact text from the source
    line: int          # 1-based
    col: int           # 1-based
    pos: int           # 0-based offset into the source
    virtual: bool = False   # True if inserted by phrase-level recovery

    @property
    def end(self) -> int:
        return self.pos + (0 if self.virtual else len(self.lexeme))

    def describe(self) -> str:
        if self.kind == EOF:
            return "end of file"
        if self.kind in (ID, NUM, FLOAT, STRING, CHAR):
            return f"{self.kind.lower()} '{self.lexeme}'"
        return f"'{self.lexeme}'"

    def __str__(self) -> str:
        return f"<{self.kind}, '{self.lexeme}', {self.line}:{self.col}>"


def category(tok: Token) -> str:
    """Human-readable token class used by the token table."""
    if tok.kind in TYPE_KEYWORDS or tok.kind in STMT_KEYWORDS or tok.kind in LITERAL_KEYWORDS:
        return "Keyword"
    if tok.kind == ID:
        return "Identifier"
    if tok.kind in (NUM, FLOAT):
        return "Number"
    if tok.kind == STRING:
        return "String literal"
    if tok.kind == CHAR:
        return "Char literal"
    if tok.kind == EOF:
        return "End of input"
    if tok.kind in "(){}[];,":
        return "Delimiter"
    return "Operator"
