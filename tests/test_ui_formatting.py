"""Output formatting schema (no Qt)."""

from __future__ import annotations

from assistant.ui.formatting import MAX_TABLE_ROWS, TableOutput, TextOutput, parse_output

POWERSHELL = """\
Name UsedGB FreeGB
---- ------ ------
C     224.4    6.4
D     192.2   52.3
E         0      0
"""


def test_powershell_format_table_becomes_a_table():
    table = parse_output(POWERSHELL)
    assert isinstance(table, TableOutput)
    assert table.headers == ["Name", "UsedGB", "FreeGB"]
    assert table.rows == [["C", "224.4", "6.4"], ["D", "192.2", "52.3"], ["E", "0", "0"]]
    assert table.numeric == [False, True, True]


def test_wide_values_under_short_dashes_keep_their_column():
    text = "Name      Length\n----      ------\nDocuments      5\nx            120\n"
    table = parse_output(text)
    assert isinstance(table, TableOutput)
    assert table.rows == [["Documents", "5"], ["x", "120"]]


def test_empty_cells_are_kept_in_place():
    text = "Name  Status  Owner\n----  ------  -----\na     ok\nb             sam\n"
    table = parse_output(text)
    assert isinstance(table, TableOutput)
    assert table.rows == [["a", "ok", ""], ["b", "", "sam"]]


def test_json_is_pretty_printed():
    out = parse_output('{"a":1,"b":[1,2]}')
    assert isinstance(out, TextOutput) and out.kind == "json"
    assert out.text.startswith('{\n  "a": 1')


def test_tab_separated_text_is_a_table():
    table = parse_output("pid\tname\n12\tcode\n7\tssh\n")
    assert isinstance(table, TableOutput) and table.rows == [["12", "code"], ["7", "ssh"]]


def test_whitespace_aligned_numeric_output_is_a_table():
    table = parse_output("Drive Used Free\nC 224 6\nD 192 52\n")
    assert isinstance(table, TableOutput) and table.headers == ["Drive", "Used", "Free"]


def test_prose_and_word_lists_stay_plain_text():
    for text in (
        "The disk is almost full.\nTry cleaning up.",
        "alpha beta\ngamma delta\nepsilon zeta\n",  # same width but no numbers
        "Error: file not found",
        "",
    ):
        assert isinstance(parse_output(text), TextOutput)


def test_huge_tables_are_capped_and_report_the_rest():
    rows = "\n".join(f"n{i} {i}" for i in range(MAX_TABLE_ROWS + 25))
    table = parse_output("Name Value\n---- -----\n" + rows)
    assert isinstance(table, TableOutput)
    assert len(table.rows) == MAX_TABLE_ROWS and table.hidden_rows == 25


def test_header_only_underline_is_not_a_table():
    assert isinstance(parse_output("Name Value\n---- -----\n"), TextOutput)


def test_misaligned_underlined_text_falls_back_to_word_columns():
    sample = "Name UsedGB FreeGB\n---- ------ ------\nC 224.4 6.4\nD 192.2 52.3\n"
    table = parse_output(sample)
    assert isinstance(table, TableOutput)
    assert table.rows == [
        ["C", "224.4", "6.4"],
        ["D", "192.2", "52.3"],
    ]  # no dash row, no cut words
