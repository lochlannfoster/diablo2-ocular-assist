import pytest

import runes


def test_thirty_three_runes_in_order():
    assert len(runes.RUNES) == 33
    assert runes.RUNES[0] == "El" and runes.RUNES[-1] == "Zod"
    assert len(set(runes.RUNES)) == 33
    assert runes.number("el") == 1
    assert runes.number("Zod") == 33
    assert runes.number("Ist") == 24


def test_table_numbers_down_columns():
    lines = runes.table(3)
    assert len(lines) == 11
    assert lines[0].split() == ["1", "El", "12", "Sol", "23", "Mal"]
    assert lines[-1].split() == ["11", "Amn", "22", "Um", "33", "Zod"]
    # Monospace alignment: the second column starts at the same offset on every line.
    offsets = {line.index(str(n + 12).rjust(2)) for n, line in enumerate(lines)}
    assert len(offsets) == 1


def test_table_columns_clamped_and_complete():
    for columns in (0, 1, 2, 4, 5, 6, 99):
        cells = " ".join(runes.table(columns)).split()
        pairs = sorted(zip(map(int, cells[0::2]), cells[1::2]))
        assert pairs == list(enumerate(runes.RUNES, start=1))
    assert len(runes.table(1)) == 33
    assert len(runes.table(6)) == 6


def test_every_rune_has_a_value_and_higher_runes_cost_more():
    assert set(runes.VALUES) == set(runes.RUNES)
    assert runes.value("ber") == 3.5 and runes.value("El") == 0.0008
    # Ist upward each cost at least as much as the one before, except Cham
    # and Zod, which trade below their number.
    prices = [runes.VALUES[r] for r in runes.RUNES[:runes.number("Ber")]]
    assert prices == sorted(prices)
    assert runes.VALUES["Cham"] < runes.VALUES["Jah"] > runes.VALUES["Zod"]


def test_format_value_shorthand():
    assert [runes.format_value(v) for v in (3.5, 3, 0.9, 0.16, 0.0008)] == \
        ["3.5", "3", ".9", ".16", ".0008"]


def test_table_with_values_aligns_on_the_decimal_point():
    lines = runes.table(3, values=True)
    assert lines[0].split() == ["1", "El", ".0008", "12", "Sol", ".0008", "23", "Mal", ".1"]
    assert lines[7].split()[-3:] == ["30", "Ber", "3.5"]
    # Same column offset for the "12 Sol" cell on every line -> value widths are fixed.
    offsets = {line.index(str(n + 12).rjust(2)) for n, line in enumerate(lines)}
    assert len(offsets) == 1
    # Decimal points of the third column line up.
    dots = {line.rindex(".") for line in lines if "." in line.split("   ")[-1]}
    assert len(dots) == 1
    # Values off is the old table exactly.
    assert all(" ." not in line for line in runes.table(3))


def test_sorted_by_value_keeps_numbers_and_ties_in_number_order():
    lines = runes.table(1, values=True, sort="value")
    names = [line.split()[1] for line in lines]
    assert names[:4] == ["Ber", "Jah", "Sur", "Lo"]
    assert names[-14:] == list(runes.RUNES[:14])          # all .0008, number order
    assert lines[0].split()[0] == "30"                    # the number travels with the rune
    assert sorted(names, key=runes.number) == list(runes.RUNES)


def test_drop_tiers():
    assert runes.tier("El") == runes.tier("Dol") == "normal"
    assert runes.tier("Hel") == runes.tier("Ist") == "nightmare"
    assert runes.tier("Gul") == runes.tier("Zod") == "hell"


def test_table_style_wraps_padded_fields():
    calls = []

    def style(name, field, text):
        calls.append((name, field, text))
        return f"<{text}>"

    line = runes.table(1, values=True, style=style)[0]
    assert line == " 1 <El   > < .0008>"
    assert calls[:2] == [("El", "name", "El   "), ("El", "value", " .0008")]
