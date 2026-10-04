from specforge_desktop.gui import format_core_lines


def test_format_core_lines_shows_all_typical_cores():
    # Old fixed-height panel clipped after ~Core 05; dashboard lists every core.
    lines = format_core_lines([float(i) for i in range(16)], expected=16)
    assert len(lines) == 16
    assert "Core 00" in lines[0]
    assert "Core 05" in lines[5]
    assert "Core 15" in lines[15]


def test_format_core_lines_compacts_very_wide_cpus():
    cores = [float(i % 40) for i in range(64)]
    lines = format_core_lines(cores, expected=64, dense_after=16)
    joined = "\n".join(lines)
    assert "64 logical" in joined
    assert "omitted while monitoring" in joined
    assert "Core 00" in joined
    assert "Core 63" in joined
    assert joined.count("Core ") < 64


def test_format_core_lines_reports_affinity_gap():
    lines = format_core_lines([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], expected=16)
    assert any("only 6 of 16" in line for line in lines)
