"""Unit tests for SEDRS.  Run with:  python -m unittest discover -s tests -v"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sedrs import analyze                                      # noqa: E402
from sedrs.diagnostics import PANIC, PHRASE, ERROR_PRODUCTION, LEXICAL, GLOBAL  # noqa: E402
from sedrs.ll1 import Grammar, DEFAULT_GRAMMAR, parse_ll1, tokens_for  # noqa: E402


def wrap(body):
    return "int main() {\n" + body + "\n    return 0;\n}\n"


class Base(unittest.TestCase):
    def check(self, src, strategy, fragment, mode="full"):
        res = analyze(src, mode)
        hits = [d for d in res.diagnostics if d.strategy == strategy and fragment in d.message]
        self.assertTrue(hits, f"no '{fragment}' via {strategy}; got:\n" +
                        "\n".join(f"  {d.strategy}: {d.message}" for d in res.diagnostics))
        return res

    def assert_fixed_clean(self, src):
        fixed = analyze(src).corrected
        again = analyze(fixed)
        self.assertEqual(again.stats["errors"], 0,
                         f"corrected code still has errors:\n{fixed}\n" +
                         "\n".join(d.message for d in again.errors))


class TestValid(Base):
    def test_valid_programs_have_no_errors(self):
        for name in ("01_valid_program.mc",):
            with open(os.path.join(ROOT, "samples", name), encoding="utf-8") as f:
                res = analyze(f.read())
            self.assertEqual(res.diagnostics, [])

    def test_constructs(self):
        src = wrap("int a[3]; a[0] = 1; float f = .5; char c = 'x'; bool b = !true || false;\n"
                   "for (a[1] = 0; a[1] < 3; a[1]++) { if (a[1] % 2 == 0) continue; else break; }\n"
                   "while (f <= 2.0) f += 0.5; print(\"ok\", -f);")
        self.assertEqual(analyze(src).diagnostics, [])


class TestLexical(Base):
    def test_illegal_character(self):
        self.check(wrap("int a = 5 @ 2;"), LEXICAL, "illegal character '@'")

    def test_single_ampersand(self):
        self.check(wrap("if (1 & 2) { }"), LEXICAL, "invalid operator '&'")

    def test_unterminated_string(self):
        self.check(wrap('print("hello);'), LEXICAL, "unterminated string")

    def test_identifier_starting_with_digit(self):
        self.check(wrap("int 9lives = 1;"), LEXICAL, "invalid identifier '9lives'")

    def test_malformed_number(self):
        self.check(wrap("float x = 1.2.3;"), LEXICAL, "malformed number")

    def test_unterminated_comment(self):
        self.check("int x; /* never closed", LEXICAL, "unterminated block comment")


class TestPhraseLevel(Base):
    def test_missing_semicolon_inserted(self):
        res = self.check(wrap("int a = 1\n    int b = 2;"), PHRASE, "missing ';'")
        self.assertIn("int a = 1;", res.corrected)

    def test_comma_replaced_by_semicolon(self):
        self.check(wrap("int i; for (i = 0, i < 3, i++) { }"), PHRASE, "but found ','")

    def test_missing_close_paren(self):
        self.check(wrap("int x = (1 + 2;"), PHRASE, "missing ')'")

    def test_extra_close_paren_deleted(self):
        self.check(wrap("print(1));"), PHRASE, "unexpected ')'")

    def test_missing_close_brace_at_eof(self):
        self.check("int main() {\n int x = 1;\n", PHRASE, "missing '}'")

    def test_stray_close_brace(self):
        self.check("int x;\n}\n", PHRASE, "unmatched '}'")


class TestErrorProductions(Base):
    def test_misspelled_keywords(self):
        for typo, kw in (("whlie (1) { }", "while"), ("pritn(1);", "print"),
                         ("itn y = 2;", "int"), ("retrun 1;", "return"), ("fi (1) { }", "if")):
            with self.subTest(typo=typo):
                self.check(wrap(typo), ERROR_PRODUCTION, f"did you mean keyword '{kw}'")

    def test_user_function_not_flagged_as_typo(self):
        src = "int prin(int a) { return a; }\n" + wrap("prin(2);")
        self.assertEqual(analyze(src).diagnostics, [])

    def test_missing_parentheses_in_condition(self):
        self.check(wrap("int x; if x > 1 { }"), ERROR_PRODUCTION, "must be enclosed in parentheses")

    def test_assignment_in_condition(self):
        self.check(wrap("int x; if (x = 1) { }"), ERROR_PRODUCTION, "assignment '=' used inside")

    def test_comparison_as_statement(self):
        self.check(wrap("int x; x == 1;"), ERROR_PRODUCTION, "'==' used as a statement")

    def test_else_without_if(self):
        self.check(wrap("int x; else { x = 1; }"), ERROR_PRODUCTION, "'else' without")

    def test_consecutive_operators(self):
        self.check(wrap("int x = 1 + * 2;"), ERROR_PRODUCTION, "unexpected operator '*'")

    def test_missing_comma_in_arguments(self):
        self.check(wrap('print("a" 1);'), ERROR_PRODUCTION, "missing ','")

    def test_empty_if_body_warning(self):
        res = analyze(wrap("int x; if (x > 1); x = 2;"))
        self.assertEqual(len(res.warnings), 1)


class TestPanicMode(Base):
    def test_missing_operand_discards_statement(self):
        res = self.check(wrap("int a = (1 + ) * 2;\n    int b = 3;"), PANIC, "expected an expression")
        self.assertIn("/*", res.corrected)

    def test_parsing_continues_after_panic(self):
        res = analyze(wrap("int = 5;\n    int b = 1 +;\n    x == ;"))
        self.assertGreaterEqual(res.stats["errors"], 3)

    def test_panic_only_mode_uses_no_phrase_level(self):
        res = analyze(wrap("int a = 1\n    int b = 2;"), "panic")
        self.assertTrue(res.errors)
        self.assertTrue(all(d.strategy in (PANIC, LEXICAL) for d in res.errors))


class TestModesAndGlobal(Base):
    def test_no_recovery_stops_at_first_error(self):
        res = analyze(wrap("int a = 1\n    int b = 2\n    int c = 3"), "none")
        self.assertTrue(res.halted)
        self.assertEqual(res.stats["errors"], 1)

    def test_full_mode_finds_all(self):
        res = analyze(wrap("int a = 1\n    int b = 2\n    int c = 3"), "full")
        self.assertEqual(res.stats["errors"], 3)

    def test_delimiter_root_cause(self):
        self.check(wrap("if (1 > 0 { }"), GLOBAL, "'(' opened at line 2")


class TestCorrectedCode(Base):
    def test_all_samples_fix_to_clean_programs(self):
        folder = os.path.join(ROOT, "samples")
        for name in sorted(os.listdir(folder)):
            with self.subTest(sample=name), open(os.path.join(folder, name), encoding="utf-8") as f:
                self.assert_fixed_clean(f.read())


class TestBugFixes(Base):
    def test_unknown_call_is_not_misread_as_for(self):
        res = analyze("int main() { foo(); return 0; }")
        self.assertFalse(any("did you mean" in d.message for d in res.diagnostics),
                         [d.message for d in res.diagnostics])

    def test_misspelled_print_call_still_detected(self):
        self.check("int main() { pritn(1); }", "Error Production", "did you mean keyword 'print'")

    def test_misspelled_for_still_detected(self):
        self.check("int main() { int i; fro (i = 0; i < 3; i++) { } }",
                   "Error Production", "did you mean keyword 'for'")

    def test_missing_body_at_end_of_file(self):
        res = self.check("int x = 1;\nwhile (x)", "Phrase Level", "missing body after 'while'")
        self.assert_fixed_clean(res.source)

    def test_missing_body_before_closing_brace(self):
        res = self.check("int main() { if (1) }", "Phrase Level", "missing body after 'if'")
        self.assert_fixed_clean(res.source)


class TestLL1(unittest.TestCase):
    def setUp(self):
        self.g = Grammar(DEFAULT_GRAMMAR)

    def test_first_follow(self):
        self.assertEqual(self.g.first["E"], {"(", "id", "num"})
        self.assertEqual(self.g.first["E'"], {"+", "-", "ε"})
        self.assertEqual(self.g.follow["E"], {")", "$"})
        self.assertEqual(self.g.follow["F"], {"+", "-", "*", "/", ")", "$"})

    def test_is_ll1_and_has_synch(self):
        self.assertTrue(self.g.is_ll1)
        self.assertEqual(self.g.table["F"][")"], "synch")

    def test_accepts_valid_input(self):
        rows, errors = parse_ll1(self.g, tokens_for(self.g, "a * (b + 3)"))
        self.assertEqual(errors, [])
        self.assertTrue(rows[-1]["action"].startswith("ACCEPT"))

    def test_recovers_from_errors(self):
        rows, errors = parse_ll1(self.g, tokens_for(self.g, "a + * b )"))
        self.assertEqual(len(errors), 2)
        self.assertTrue(rows[-1]["action"].startswith("ACCEPT"))

    def test_detects_conflict(self):
        g = Grammar("S -> a A | a B\nA -> b\nB -> c")
        self.assertFalse(g.is_ll1)


if __name__ == "__main__":
    unittest.main()
