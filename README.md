# SEDRS: Syntax Error Detection and Recovery System

Compiler Design Mini Project

| Name | Enrollment No. |
|---|---|
| Vyom Patel | 202307020084 |
| Priti Sisodiya | 20230702088 |
| Krushil Rafaliya | 202307020090 |

SEDRS is a front end for **MiniC**, a small C-like language. It finds lexical and syntax errors and recovers from them so it can keep checking the rest of the program. For each error it reports:

- the line and column
- a clear message and a suggested fix
- the recovery strategy it used and what that strategy did

Finally, it writes out a **corrected program**, which re-parses with 0 errors.

## Requirements
Python 3.8 or newer. The project uses no third-party libraries, and Tkinter ships with Python on Windows.

## How to run
```
run.bat                                          (or double-click it) launches the GUI
python main.py                                   launches the GUI
python main.py samples\08_mixed_errors.mc        prints a colour report to the console
python main.py FILE --mode panic|none|full       runs in a different recovery mode
python main.py FILE --tokens --tree --log        adds the token table, parse tree and recovery log
python main.py FILE --compare --fix fixed.mc     compares the modes and writes the corrected program
python main.py --ll1 "a + * b ) * 3"             prints the LL(1) panic-mode trace
python -m unittest discover -s tests -v          runs the 40 unit tests
```

## Recovery strategies implemented
| Strategy | Examples handled |
|---|---|
| Lexical recovery | `@` `$` deleted, `&` changed to `&&`, unterminated string or comment closed, `3.14.15` truncated, `2ndValue` renamed, `'ab'` truncated |
| Phrase level (insert / delete / substitute) | missing `;` `)` `]` `}` `(`, extra `)`, `,` used for `;` in a for-header |
| Error productions | misspelled keywords (`whlie`, `pritn`, `itn`, `retrun`, `fi`), `if x > 3 {`, `if (x = 5)`, `x == 10;`, stray `else`, `a + * b`, missing `,` between arguments, empty `if (c);` body |
| Panic mode | skips to a synchronizing token `; } {` or a keyword, comments out the discarded statement, suppresses cascading errors |
| Global delimiter analysis | reports where an unmatched `( [ {` was **opened** (the root cause) |
| LL(1) synch sets | table-driven predictive parser built from FIRST/FOLLOW, using the textbook panic-mode algorithm |

## Project layout
```
main.py            CLI entry point (launches the GUI when given no arguments)
gui.py             Tkinter GUI
sedrs/             core package: tokens, lexer, delimiters, parser, repair, ll1, analyzer
samples/           8 demo programs (01 is valid; 02-08 each exercise a different error class)
tests/             unit tests
docs/              project report (DOCX and PDF) and screenshots
```

## Demo script (about 5 minutes)
1. Open `01_valid_program`. It reports 0 errors. Show the **Tokens** and **Parse Tree** tabs.
2. Open `02_missing_semicolons`. Each missing `;` is reported at the end of the right line (phrase level).
3. Open `04_misspelled_keywords` (error productions), then `07_lexical_errors` (lexical recovery).
4. Open `08_mixed_errors`. Click a diagnostic to jump to its source line, and hover over the red code.
5. Switch between **Full**, **Panic only** and **None**, then open the **Statistics** tab to compare the three modes.
6. Open **Corrected Code**, click **Apply Fixes** and re-analyze. The program now has 0 errors.
7. Open the **LL(1) Parser** tab and show FIRST/FOLLOW, the table with `synch` entries, and the trace for `a + * b ) * 3`.
8. Type a new error live in the editor. **Live** mode re-analyzes the program as you type.
