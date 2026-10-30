"""Recursive-descent parser for MiniC with syntax error detection and recovery.

Grammar (EBNF)
--------------
program      -> { function | statement } EOF
function     -> type ID '(' [ params ] ')' block
params       -> 'void' | type ID { ',' type ID }
statement    -> declaration ';' | assignment ';' | call ';'
              | if_stmt | while_stmt | for_stmt | block
              | 'print' '(' [ args ] ')' ';' | 'return' [ expr ] ';'
              | 'break' ';' | 'continue' ';' | ';'
declaration  -> type ID [ '[' NUM ']' ] [ '=' expr ] { ',' ID [ '=' expr ] }
assignment   -> ID [ '[' expr ']' ] ( '=' | '+=' | '-=' ) expr | ID ( '++' | '--' )
if_stmt      -> 'if' '(' expr ')' statement [ 'else' statement ]
while_stmt   -> 'while' '(' expr ')' statement
for_stmt     -> 'for' '(' [ declaration | assignment ] ';' [ expr ] ';' [ assignment ] ')' statement
block        -> '{' { statement } '}'
expr         -> or ;  or -> and { '||' and } ;  and -> eq { '&&' eq }
eq           -> rel { ('=='|'!=') rel } ;  rel -> add { ('<'|'>'|'<='|'>=') add }
add          -> mul { ('+'|'-') mul } ;  mul -> unary { ('*'|'/'|'%') unary }
unary        -> ('!'|'-') unary | primary
primary      -> NUM | FLOAT | STRING | CHAR | 'true' | 'false'
              | ID [ '(' [ args ] ')' | '[' expr ']' ] | '(' expr ')'

Recovery strategies
-------------------
1. Phrase-level recovery (local correction inside `expect`):
     substitution  - wrong token that is a common confusion (',' for ';')
     deletion      - one extraneous token before the expected one
     insertion     - a missing ';' ')' ']' '(' or '}' when context allows it
2. Error productions - the grammar is augmented with rules for common
   mistakes (missing parentheses around a condition, '=' in a condition,
   misspelled keywords, 'else' without 'if', consecutive operators, ...)
3. Panic mode - if no local repair applies, the statement is abandoned and
   tokens are skipped until a synchronizing token (';', '}', '{' or a
   statement keyword) is found.
"""

from .tokens import (Token, ID, NUM, FLOAT, STRING, CHAR, EOF, TYPE_KEYWORDS,
                     STMT_KEYWORDS, BINARY_OPS, ASSIGN_OPS, EXPR_START, SYNC_TOKENS)
from .diagnostics import (Diagnostic, make_repair, PANIC, PHRASE, ERROR_PRODUCTION, NONE)

MODES = {
    "full": "Full recovery (phrase level + error productions + panic mode)",
    "panic": "Panic mode only",
    "none": "No recovery (stop at first error)",
}

PRECEDENCE = [("||",), ("&&",), ("==", "!="), ("<", ">", "<=", ">="), ("+", "-"), ("*", "/", "%")]

# Expected token -> found token pairs that are typical typos (phrase-level substitution)
SUBSTITUTIONS = {(";", ","), (")", "]"), ("]", ")"), ("(", "["), ("[", "(")}

NO_DELETE = {"{", "}", EOF} | TYPE_KEYWORDS | STMT_KEYWORDS
OPERAND_END = {ID, NUM, FLOAT, STRING, CHAR, "true", "false", ")", "]"}


def kind_name(kind):
    return {ID: "an identifier", NUM: "a number"}.get(kind, f"'{kind}'")


class ParseError(Exception):
    def __init__(self, diag):
        super().__init__(diag.message if diag else "suppressed")
        self.diag = diag


class Halt(Exception):
    """Raised in 'none' mode: a traditional parser that stops at the first error."""


class Node:
    def __init__(self, label, children=None, error=False):
        self.label = label
        self.children = [c for c in (children or []) if c is not None]
        self.error = error

    def add(self, *kids):
        self.children.extend(k for k in kids if k is not None)
        return self

    def to_text(self, indent=""):
        mark = "!! " if self.error else ""
        lines = [f"{indent}{mark}{self.label}"]
        for c in self.children:
            lines.append(c.to_text(indent + "  "))
        return "\n".join(lines)


def edit_distance(a: str, b: str) -> int:
    """Optimal string alignment distance (Levenshtein + adjacent transposition)."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def closest_keyword(word, candidates):
    best, best_d = None, 99
    for kw in sorted(candidates):
        d = edit_distance(word, kw)
        limit = 1 if len(kw) <= 4 else 2
        if d <= limit and d < best_d and len(word) >= 2:
            best, best_d = kw, d
    return best


class Parser:
    def __init__(self, tokens, source="", mode="full"):
        self.toks = list(tokens)
        self.src = source
        self.i = 0
        self.mode = mode
        self.full = mode == "full"
        self.diagnostics = []
        self.repairs = []
        self.log = []
        self.suppressed = 0
        self.halted = False
        self._last_panic_i = -1
        # names of user functions (so a call like 'pritn(...)' is only flagged
        # as a misspelled keyword when no such function is declared)
        self.functions = {self.toks[k + 1].lexeme for k in range(len(self.toks) - 2)
                          if self.toks[k].kind in TYPE_KEYWORDS and self.toks[k + 1].kind == ID
                          and self.toks[k + 2].kind == "("}

    # ------------------------------------------------------------ token access
    @property
    def cur(self) -> Token:
        return self.toks[self.i]

    @property
    def prev(self) -> Token:
        return self.toks[self.i - 1] if self.i > 0 else self.toks[0]

    def peek(self, k=1) -> Token:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def at(self, *kinds) -> bool:
        return self.cur.kind in kinds

    def advance(self) -> Token:
        t = self.cur
        if t.kind != EOF:
            self.i += 1
        return t

    # ------------------------------------------------------------- reporting
    def report(self, message, strategy, action="", tok=None, severity="error",
               suggestion="", after=None):
        """Record a diagnostic. `after` places it just after that token."""
        if after is not None:
            line, col, pos = after.line, after.col + len(after.lexeme), after.end
        else:
            tok = tok or self.cur
            line, col, pos = tok.line, tok.col, tok.pos
        length = 1 if after is not None else max(1, len((tok or self.cur).lexeme))

        if severity == "error":
            if self.mode == "none":
                d = Diagnostic("Syntax", "error", line, col, message, NONE,
                               "parsing halted - remaining input not analysed", suggestion, pos, length)
                self.diagnostics.append(d)
                self.log.append(f"L{line}:{col}  DETECT  {message}")
                self.log.append("          HALT    no recovery mode - parser stops here")
                self.halted = True
                raise Halt()
            if strategy == PANIC:
                if self.i == self._last_panic_i:      # cascading error: no progress since last
                    self.suppressed += 1
                    self.log.append(f"L{line}:{col}  SUPPRESS cascading error: {message}")
                    return None
                self._last_panic_i = self.i

        d = Diagnostic("Syntax", severity, line, col, message, strategy, action, suggestion, pos, length)
        self.diagnostics.append(d)
        self.log.append(f"L{line}:{col}  DETECT  {severity}: {message}")
        if action:
            self.log.append(f"          {strategy.upper():<16} {action}")
        return d

    def error(self, message, suggestion=""):
        """Unrecoverable locally -> raise to the statement level (panic mode)."""
        raise ParseError(self.report(message, PANIC, tok=self.cur, suggestion=suggestion))

    def repair(self, pos, length, text, reason):
        self.repairs.append(make_repair(pos, length, text, reason))

    # --------------------------------------------------- phrase-level `expect`
    def can_insert(self, kind) -> bool:
        c, p = self.cur, self.prev
        new_line = c.line > p.line
        if kind == ";":
            return c.kind in ("}", EOF) or new_line or c.kind in TYPE_KEYWORDS or c.kind in STMT_KEYWORDS
        if kind == ")":
            return (c.kind in (";", "{", "}", EOF) or new_line
                    or c.kind in TYPE_KEYWORDS or c.kind in STMT_KEYWORDS)
        if kind == "]":
            return c.kind not in EXPR_START
        if kind == "(":
            return c.kind in EXPR_START
        if kind == "}":
            return c.kind == EOF
        return False

    def expect(self, kind, context, insert_ok=None) -> Token:
        t = self.cur
        if t.kind == kind:
            return self.advance()

        if self.full:
            # (a) substitution of a commonly confused token
            if (kind, t.kind) in SUBSTITUTIONS:
                self.report(f"expected {kind_name(kind)} {context} but found '{t.lexeme}'", PHRASE,
                            f"replaced '{t.lexeme}' with '{kind}'", tok=t)
                self.repair(t.pos, len(t.lexeme), kind, "substitute")
                self.advance()
                return Token(kind, kind, t.line, t.col, t.pos, virtual=True)

            # (b) deletion of one extraneous token
            if self.peek().kind == kind and t.kind not in NO_DELETE:
                self.report(f"unexpected {t.describe()} {context}", PHRASE,
                            f"deleted extraneous '{t.lexeme}'", tok=t)
                self.repair(t.pos, len(t.lexeme), "", "delete")
                self.advance()
                return self.advance()

            # (c) insertion of a missing token
            if insert_ok if insert_ok is not None else self.can_insert(kind):
                p = self.prev
                self.report(f"missing '{kind}' {context}", PHRASE, f"inserted '{kind}'", after=p,
                            suggestion=f"add '{kind}' after '{p.lexeme}'")
                self.repair(p.end, 0, kind, "insert")
                return Token(kind, kind, p.line, p.col + len(p.lexeme), p.end, virtual=True)

        self.error(f"expected {kind_name(kind)} {context} but found {t.describe()}")

    def end_statement(self, context):
        if self.at(";"):
            self.advance()
            return
        c, p = self.cur, self.prev
        if self.full and c.line == p.line and c.kind in EXPR_START - {"-", "!"} and p.kind in OPERAND_END:
            self.error(f"missing operator between '{p.lexeme}' and '{c.lexeme}'",
                       "insert an operator (e.g. '+') or end the statement with ';'")
        self.expect(";", context)

    # ----------------------------------------------------------- panic mode
    def recover(self, diag, start):
        """Skip to a synchronizing token and discard the broken statement."""
        if self.i == start and self.cur.kind != EOF:
            self.advance()                       # guarantee progress
        while self.cur.kind != EOF:
            k = self.cur.kind
            if k == ";":
                self.advance()
                break
            if k in SYNC_TOKENS:
                break
            self.advance()

        dropped = self.toks[start:self.i]
        sync = self.cur.describe()
        if dropped:
            p0, p1 = dropped[0].pos, dropped[-1].end
            text = " ".join(t.lexeme for t in dropped)
            preview = text if len(text) <= 45 else text[:42] + "..."
            action = f"discarded `{preview}` ({len(dropped)} tokens); resumed at {sync}"
            # earlier local repairs inside the discarded text are now meaningless
            self.repairs = [r for r in self.repairs if not (p0 <= r.pos <= p1)]
            body = self.src[p0:p1].replace("*/", "* /")
            self.repair(p0, p1 - p0, f"/* {body} */", "discard")
        else:
            action = f"no tokens skipped; resumed at {sync}"
        if diag is not None:
            diag.action = action
        self.log.append(f"          {PANIC.upper():<16} {action}")
        return Node(f"ERROR -> {action}", error=True)

    # -------------------------------------------------------------- program
    def parse(self) -> Node:
        root = Node("Program")
        try:
            while not self.at(EOF):
                before = self.i
                if self.at("}"):
                    t = self.cur
                    if self.full:
                        self.report("unmatched '}' at top level", PHRASE, "deleted stray '}'", tok=t)
                        self.repair(t.pos, 1, "", "delete")
                    else:
                        self.report("unexpected '}' at top level", PANIC, "skipped '}'", tok=t)
                    self.advance()
                    continue
                root.add(self.top_level())
                if self.i == before:
                    self.advance()
        except Halt:
            root.add(Node("PARSING HALTED (no recovery)", error=True))
        return root

    def top_level(self):
        if self.full and self.at(ID) and self.peek().kind == ID:
            self.misspelled_keyword()                   # e.g. 'itn main()'
        if (self.cur.kind in TYPE_KEYWORDS and self.peek().kind == ID
                and self.peek(2).kind == "("):
            start = self.i
            try:
                return self.function()
            except ParseError as e:
                return self.recover(e.diag, start)
        return self.statement()

    def function(self):
        rtype = self.advance()
        name = self.advance()
        self.advance()                                       # '('
        node = Node(f"Function: {rtype.lexeme} {name.lexeme}()")
        params = Node("Parameters")
        if self.at("void") and self.peek().kind == ")":
            self.advance()
        elif not self.at(")"):
            while True:
                if self.cur.kind in TYPE_KEYWORDS:
                    ptype = self.advance()
                else:
                    self.error(f"expected parameter type but found {self.cur.describe()}",
                               "parameters are declared as: type name")
                pname = self.expect(ID, "as parameter name")
                params.add(Node(f"Param: {ptype.lexeme} {pname.lexeme}"))
                if not self.at(","):
                    break
                self.advance()
        self.expect(")", "to close parameter list")
        node.add(params)
        if self.full and self.at(";"):
            self.advance()
            node.label = node.label.replace("Function", "Prototype")
            return node
        if not self.at("{"):
            self.error(f"expected '{{' to begin body of function '{name.lexeme}' "
                       f"but found {self.cur.describe()}")
        return node.add(self.block())

    # ----------------------------------------------------------- statements
    def statement(self):
        start = self.i
        try:
            return self._statement()
        except ParseError as e:
            return self.recover(e.diag, start)

    def _statement(self):
        k = self.cur.kind
        if k in TYPE_KEYWORDS:
            node = self.declaration()
            self.end_statement("after declaration")
            return node
        if k == "if":
            return self.if_statement()
        if k == "while":
            return self.while_statement()
        if k == "for":
            return self.for_statement()
        if k == "{":
            return self.block()
        if k == "print":
            return self.print_statement()
        if k == "return":
            self.advance()
            expr = None if self.at(";") or self.cur.kind not in EXPR_START else self.expression()
            self.end_statement("after return statement")
            return Node("Return", [expr])
        if k in ("break", "continue"):
            self.advance()
            self.end_statement(f"after '{k}'")
            return Node(k.capitalize())
        if k == ";":
            self.advance()
            return Node("Empty statement")
        if k == "else":
            return self.dangling_else()
        if k == ID:
            return self.id_statement()
        self.error(f"unexpected {self.cur.describe()} at start of statement",
                   "a statement must begin with a type, a keyword or an identifier")

    def declaration(self, allow_list=True):
        t = self.advance()
        node = Node("Declaration", [Node(f"Type: {t.lexeme}")])
        while True:
            name = self.expect(ID, f"after type '{t.lexeme}'")
            var = Node(f"Var: {name.lexeme}")
            if self.at("["):
                self.advance()
                size = self.expect(NUM, "as array size")
                self.expect("]", "after array size")
                var.label += f"[{size.lexeme}]"
            if self.at("="):
                self.advance()
                var.add(Node("Init", [self.expression()]))
            node.add(var)
            if not (allow_list and self.at(",")):
                return node
            self.advance()

    def id_statement(self):
        if self.full:
            kw = self.misspelled_keyword()
            if kw:
                return self._statement()
        if self.peek().kind == "(":
            name = self.advance()
            node = self.call(name)
            self.end_statement("after function call")
            return node
        node = self.assignment()
        self.end_statement("after assignment")
        return node

    def assignment(self):
        name = self.expect(ID, "at start of assignment")
        target = Node(f"Id: {name.lexeme}")
        if self.at("["):
            self.advance()
            target = Node(f"Index: {name.lexeme}", [self.expression()])
            self.expect("]", "to close array index")
        if self.at("++", "--"):
            op = self.advance()
            return Node(f"Update '{op.kind}'", [target])
        if self.at(*ASSIGN_OPS):
            op = self.advance().kind
        elif self.full and self.at("=="):
            t = self.cur
            self.report("comparison '==' used as a statement", ERROR_PRODUCTION,
                        "interpreted as assignment '='", tok=t, suggestion="use '=' to assign a value")
            self.repair(t.pos, 2, "=", "substitute")
            self.advance()
            op = "="
        elif (self.full and self.cur.line == name.line
              and self.cur.kind in (NUM, FLOAT, STRING, CHAR, "true", "false")):
            self.report(f"missing '=' after '{name.lexeme}'", PHRASE, "inserted '='", after=name)
            self.repair(name.end, 0, " =", "insert")
            op = "="
        elif self.cur.kind == ID and self.cur.line == name.line:
            self.error(f"unknown type name '{name.lexeme}'",
                       "valid types are int, float, char, bool and void")
        else:
            self.error(f"expected '=', '(', '[' or '++' after identifier '{name.lexeme}' "
                       f"but found {self.cur.describe()}")
        return Node(f"Assignment '{op}'", [target, self.expression()])

    def misspelled_keyword(self):
        """Error production: identifier that is a typo of a keyword."""
        t, nxt = self.cur, self.peek()
        if nxt.kind == ID:
            cands = TYPE_KEYWORDS | {"return"}
        elif nxt.kind == "(" and t.lexeme not in self.functions:
            # 'name(...);' is shaped like a function call, so it can only be a
            # misspelled 'print' - never 'if'/'while'/'for' (e.g. 'foo();' is
            # NOT 'for').  Those need a body after ')', not a ';'.
            after = self.after_matching_paren(self.i + 1)
            if after is not None and after.kind == ";":
                cands = {"print"}
            else:
                cands = {"if", "while", "for", "print"}
        elif nxt.kind == ";":
            cands = {"return", "break", "continue"}
        elif nxt.kind in EXPR_START - {"(", "-"} and nxt.line == t.line:
            cands = {"return"}
        else:
            return None
        kw = closest_keyword(t.lexeme, cands)
        if not kw:
            return None
        self.report(f"unknown identifier '{t.lexeme}' - did you mean keyword '{kw}'?",
                    ERROR_PRODUCTION, f"treated '{t.lexeme}' as keyword '{kw}'", tok=t,
                    suggestion=f"replace '{t.lexeme}' with '{kw}'")
        self.repair(t.pos, len(t.lexeme), kw, "keyword")
        self.toks[self.i] = Token(kw, t.lexeme, t.line, t.col, t.pos)
        return kw

    def after_matching_paren(self, k):
        """Return the token after the ')' that matches the '(' at index k,
        or None if the parentheses are not closed before a '{', '}' or EOF.
        (A ';' inside is allowed - a for-header contains two of them.)"""
        depth = 0
        while k < len(self.toks) and self.toks[k].kind != EOF:
            kind = self.toks[k].kind
            if kind == "(":
                depth += 1
            elif kind == ")":
                depth -= 1
                if depth == 0:
                    return self.toks[min(k + 1, len(self.toks) - 1)]
            elif kind in ("{", "}"):
                return None
            k += 1
        return None

    def dangling_else(self):
        t = self.cur
        if not self.full:
            self.error("'else' without a matching 'if'")
        self.report("'else' without a matching 'if'", ERROR_PRODUCTION,
                    "ignored 'else' and parsed the following statement", tok=t,
                    suggestion="check for a ';' or '}' that ends the 'if' too early")
        self.repair(t.pos, 4, "", "delete")
        self.advance()
        return Node("Stray else (ignored)", [self.statement()], error=True)

    def body(self, kw):
        if self.full and self.at("}", EOF):
            # phrase level: the statement ends before its body, e.g. 'while (x)'
            # at the end of the file or just before a '}'
            p = self.prev
            self.report(f"missing body after '{kw}'", PHRASE, "inserted an empty block '{ }'",
                        after=p, suggestion=f"add a statement or a block {{ ... }} after the '{kw}'")
            self.repair(p.end, 0, " { }", "insert")
            return Node("Block (empty, inserted)", error=True)
        if self.at(";") and self.full:
            self.report(f"empty body after '{kw}' (stray ';')", ERROR_PRODUCTION,
                        "accepted ';' as an empty statement", severity="warning",
                        suggestion="remove the ';' if the next statement is meant to be the body")
        return self.statement()

    def condition(self, kw):
        if self.at("("):
            self.advance()
            e = self.assign_in_condition(self.expression())
            self.expect(")", f"to close '{kw}' condition")
            return e
        if self.full and self.cur.kind in EXPR_START:
            first = self.cur
            e = self.assign_in_condition(self.expression())
            if self.at(")"):
                self.report(f"missing '(' before '{kw}' condition", ERROR_PRODUCTION,
                            "inserted '('", tok=first)
                self.repair(first.pos, 0, "(", "insert")
                self.advance()
            else:
                self.report(f"'{kw}' condition must be enclosed in parentheses", ERROR_PRODUCTION,
                            "inserted '(' and ')' around the condition", tok=first,
                            suggestion=f"write {kw} (condition)")
                self.repair(first.pos, 0, "(", "insert")
                self.repair(self.prev.end, 0, ")", "insert")
            return e
        self.expect("(", f"after '{kw}'")

    def assign_in_condition(self, left):
        if self.at("=") and self.full:
            t = self.cur
            self.report("assignment '=' used inside a condition", ERROR_PRODUCTION,
                        "interpreted as comparison '=='", tok=t,
                        suggestion="use '==' to compare values")
            self.repair(t.pos, 1, "==", "substitute")
            self.advance()
            return Node("BinOp: ==", [left, self.expression()])
        return left

    def if_statement(self):
        self.advance()
        cond = self.condition("if")
        node = Node("If", [Node("Condition", [cond]), Node("Then", [self.body("if")])])
        if self.at("else"):
            self.advance()
            node.add(Node("Else", [self.body("else")]))
        return node

    def while_statement(self):
        self.advance()
        cond = self.condition("while")
        return Node("While", [Node("Condition", [cond]), Node("Body", [self.body("while")])])

    def for_statement(self):
        self.advance()
        self.expect("(", "after 'for'")
        init = cond = update = None
        if not self.at(";"):
            if self.cur.kind in TYPE_KEYWORDS:
                init = self.declaration(allow_list=False)
            else:
                init = self.assignment()
        self.expect(";", "after for-loop initialisation", insert_ok=self.full)
        if not self.at(";"):
            cond = self.expression()
        self.expect(";", "after for-loop condition", insert_ok=self.full)
        if not self.at(")"):
            update = self.assignment()
        self.expect(")", "to close for-loop header")
        return Node("For", [Node("Init", [init]), Node("Condition", [cond]),
                            Node("Update", [update]), Node("Body", [self.body("for")])])

    def print_statement(self):
        self.advance()
        self.expect("(", "after 'print'")
        args = self.arguments()
        self.expect(")", "to close print arguments")
        self.end_statement("after print statement")
        return Node("Print", args)

    def block(self):
        lb = self.advance()
        node = Node("Block")
        while not self.at("}", EOF):
            before = self.i
            node.add(self.statement())
            if self.i == before:
                self.advance()
        if self.at("}"):
            self.advance()
        elif self.full:
            self.expect("}", f"to close block opened at line {lb.line}")
        else:
            self.report(f"end of file reached inside block opened at line {lb.line}", PANIC,
                        "no synchronizing token left - parsing ends", tok=self.cur)
        return node

    # ---------------------------------------------------------- expressions
    def expression(self):
        return self.binary(0)

    def binary(self, level):
        if level == len(PRECEDENCE):
            return self.unary()
        left = self.binary(level + 1)
        while self.cur.kind in PRECEDENCE[level]:
            op = self.advance()
            # error production: two binary operators in a row, e.g. a + * b
            if self.full and self.cur.kind in BINARY_OPS and self.cur.kind != "-":
                extra = self.cur
                self.report(f"unexpected operator '{extra.lexeme}' after '{op.lexeme}'",
                            ERROR_PRODUCTION, f"deleted extra operator '{extra.lexeme}'", tok=extra)
                self.repair(extra.pos, len(extra.lexeme), "", "delete")
                self.advance()
            right = self.binary(level + 1)
            left = Node(f"BinOp: {op.kind}", [left, right])
        return left

    def unary(self):
        if self.at("!", "-"):
            op = self.advance()
            return Node(f"Unary: {op.kind}", [self.unary()])
        return self.primary()

    def primary(self):
        t = self.cur
        if t.kind in (NUM, FLOAT):
            self.advance()
            return Node(f"Number: {t.lexeme}")
        if t.kind in (STRING, CHAR):
            self.advance()
            return Node(f"{t.kind.capitalize()}: {t.lexeme}")
        if t.kind in ("true", "false"):
            self.advance()
            return Node(f"Bool: {t.lexeme}")
        if t.kind == ID:
            self.advance()
            if self.at("("):
                return self.call(t)
            if self.at("["):
                self.advance()
                idx = self.expression()
                self.expect("]", "to close array index")
                return Node(f"Index: {t.lexeme}", [idx])
            return Node(f"Id: {t.lexeme}")
        if t.kind == "(":
            self.advance()
            e = self.expression()
            self.expect(")", "to close parenthesised expression")
            return e
        self.error(f"expected an expression but found {t.describe()}",
                   "an operand (identifier, number or '(') is missing")

    def call(self, name):
        self.advance()                                       # '('
        args = self.arguments()
        self.expect(")", f"to close call to '{name.lexeme}'")
        return Node(f"Call: {name.lexeme}()", args)

    def arguments(self):
        if self.at(")"):
            return []
        args = [self.expression()]
        while True:
            if self.at(","):
                self.advance()
            elif (self.full and self.cur.kind in EXPR_START - {"-", "!", "("}
                  and self.prev.kind in OPERAND_END):
                # error production: missing ',' between arguments, e.g. print("x" y)
                p = self.prev
                self.report(f"missing ',' between arguments '{p.lexeme}' and '{self.cur.lexeme}'",
                            ERROR_PRODUCTION, "inserted ','", after=p)
                self.repair(p.end, 0, ",", "insert")
            else:
                return args
            args.append(self.expression())


def parse(tokens, source="", mode="full"):
    p = Parser(tokens, source, mode)
    tree = p.parse()
    return tree, p
