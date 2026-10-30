"""Apply recorded repairs to the source to produce a corrected program."""


def apply_repairs(source, repairs):
    """Return (corrected_text, highlight_ranges).

    highlight_ranges are (start, end) offsets in the corrected text that were
    produced by a repair, so the GUI can highlight them.
    """
    # Longer edits first at the same position so a discarded-statement comment
    # wins over smaller edits that fall inside it.
    ordered = sorted(repairs, key=lambda r: (r.pos, -r.length, r.seq))
    out, marks = [], []
    last, last_reason, size = 0, "", 0
    for r in ordered:
        if r.pos < last or (r.pos == last and last_reason == "discard" and r.length == 0):
            continue                                   # overlaps an applied edit
        chunk = source[last:r.pos]
        out.append(chunk)
        size += len(chunk)
        if r.text:
            marks.append((size, size + len(r.text)))
        elif r.length:
            marks.append((size, size))                 # deletion point
        out.append(r.text)
        size += len(r.text)
        last = r.pos + r.length
        last_reason = r.reason
    out.append(source[last:])
    return "".join(out), marks
