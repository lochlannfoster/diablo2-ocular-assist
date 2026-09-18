import gems


def test_seven_gems_five_grades():
    assert len(gems.GEMS) == 7 and len(gems.GRADES) == 5
    assert gems.name("Ruby") == "Perfect Ruby"
    assert gems.name("Ruby", "Normal") == "Ruby"
    assert gems.name("Ruby", "Chipped") == "Chipped Ruby"


def test_values_third_per_grade_below_perfect():
    assert gems.value("Amethyst") == 0.0027
    assert gems.value("Amethyst", "Flawless") == 0.0027 / 3
    assert gems.value("Amethyst", "Chipped") == 0.0027 / 81
    assert gems.value("Skull") == 0.0008
    assert set(gems.PERFECT_VALUES) == set(gems.GEMS)


def test_format_value_two_significant_figures_no_exponent():
    assert [gems.format_value(v) for v in (0.0027, 0.0009, 0.0008 / 81, 1.0)] == \
        [".0027", ".0009", ".0000099", "1"]


def test_table_and_sort():
    lines = gems.table(2, values=True)
    assert lines[0].split() == ["Amethyst", ".0027", "Sapphire", ".0008"]
    assert len(lines) == 4
    assert gems.ordered("value")[0] == "Amethyst"
    assert gems.ordered("value")[1:] == list(gems.GEMS[1:])
    assert gems.table(1, sort="value")[0].strip() == "Amethyst"
    assert len(gems.table(7)) == 1 and len(gems.table(99)) == 1


def test_grade_table_header_and_rows():
    lines = gems.grade_table()
    assert lines[0].split() == ["Chip", "Flwd", "Norm", "Flwls", "Perf"]
    assert lines[1].split() == ["Amethyst", ".000033", ".0001", ".0003", ".0009", ".0027"]
    assert len(lines) == 8
    # Grade columns line up: the last value ends at the same offset on every row.
    assert len({len(line) for line in lines}) == 1
    assert gems.grade_table(values=False)[1].strip() == "Amethyst"
