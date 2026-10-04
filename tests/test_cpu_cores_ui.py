from specforge_desktop.gui import cpu_section_height


def test_cpu_section_height_fits_typical_core_counts():
    # Old fixed height (170) only showed ~6 cores after the header block.
    assert cpu_section_height(6) > 170
    # Typical desktops (8–16 logical cores) stay within the scrollable max.
    assert 200 <= cpu_section_height(8) <= 380
    assert 200 <= cpu_section_height(16) <= 380
    # Very wide machines cap height and rely on the section scrollbar.
    assert cpu_section_height(64) == 380
    assert cpu_section_height(0) == 200


def test_cpu_section_height_grows_with_core_count():
    assert cpu_section_height(12) > cpu_section_height(8)
