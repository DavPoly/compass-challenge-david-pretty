from archive.viewer.quote_locate_utils import Word, locate_quote


def _words(lines: list[str]) -> list[Word]:
    words: list[Word] = []
    for line_number, line in enumerate(lines):
        top = 10.0 + 20.0 * line_number
        for column, text in enumerate(line.split()):
            x0 = 10.0 + 50.0 * column
            words.append(Word(text, x0, top, x0 + 40.0, top + 10.0))
    return words


def test_single_line_quote_gives_one_box() -> None:
    match = locate_quote(_words(["Total due 500 EUR"]), "due 500", None)
    assert match is not None
    assert len(match.boxes) == 1
    assert (match.boxes[0].x0, match.boxes[0].x1) == (60.0, 150.0)
    assert match.value_boxes == []


def test_multi_line_quote_gives_one_box_per_line() -> None:
    words = _words(["The invoice is", "due on Monday"])
    match = locate_quote(words, "invoice is due on", None)
    assert match is not None
    assert [box.top for box in match.boxes] == [10.0, 30.0]


def test_ellipsis_pieces_are_located_in_order() -> None:
    words = _words(["alpha beta gamma delta epsilon zeta eta theta"])
    for marker in ("...", "[…]", "…", "[...]"):
        quote = f"alpha beta gamma {marker} zeta eta theta"
        assert locate_quote(words, quote, None) is not None, marker


def test_ellipsis_pieces_out_of_order_do_not_match() -> None:
    words = _words(["alpha beta gamma delta epsilon zeta eta theta"])
    quote = "zeta eta theta ... alpha beta gamma"
    assert locate_quote(words, quote, None) is None


def test_pdf_glued_words_match_spaced_quote() -> None:
    glued = [Word("PavageBrightwater", 0, 0, 90, 10)]
    assert locate_quote(glued, "Pavage Brightwater", None) is not None


def test_spaced_pdf_words_match_glued_quote() -> None:
    words = _words(["Pavage Brightwater inc"])
    match = locate_quote(words, "PavageBrightwater", None)
    assert match is not None
    assert len(match.boxes) == 1


def test_accent_case_and_apostrophe_differences_match() -> None:
    words = _words(["L’équipe d’Éric est prête"])
    assert locate_quote(words, "l'equipe d'eric EST", None) is not None


def test_value_inside_quote_is_boxed() -> None:
    words = _words(["Total due 500 EUR by friday"])
    match = locate_quote(words, "Total due 500 EUR", "500")
    assert match is not None
    assert len(match.value_boxes) == 1
    assert match.value_boxes[0].x0 == 110.0


def test_value_prefers_occurrence_inside_quote() -> None:
    words = _words(["500 apples", "Total due 500 EUR"])
    match = locate_quote(words, "Total due 500 EUR", "500")
    assert match is not None
    assert match.value_boxes[0].top == 30.0


def test_value_not_found_gives_empty_value_boxes() -> None:
    match = locate_quote(_words(["Total due 500"]), "Total due", "999")
    assert match is not None
    assert match.value_boxes == []


def test_missing_quote_returns_none() -> None:
    assert locate_quote(_words(["Total due 500"]), "unrelated", None) is None


def test_empty_quote_and_empty_page_return_none() -> None:
    assert locate_quote(_words(["Total due"]), "", None) is None
    assert locate_quote(_words(["Total due"]), "   ", None) is None
    assert locate_quote([], "Total due", None) is None
