from specforge_desktop.collector import SpecsCollector


def test_collect_core_fields():
    snap = SpecsCollector().collect()
    assert snap.system["hostname"]
    assert snap.cpu["logical_cores"] >= 1
    assert snap.memory["total_bytes"] > 0
    assert isinstance(snap.gpu, list)
    assert isinstance(snap.power, list)
    assert "toolkit_detected" in snap.cuda


def test_per_core_percent_covers_all_logical_cores():
    snap = SpecsCollector().collect()
    logical = snap.cpu["logical_cores"]
    per_core = snap.cpu["per_core_percent"]
    assert isinstance(per_core, list)
    assert len(per_core) == logical
    assert snap.cpu["process_bitness"] in (32, 64)
