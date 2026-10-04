from specforge_desktop.collector import SpecsCollector


def test_collect_core_fields():
    snap = SpecsCollector().collect()
    assert snap.system["hostname"]
    assert snap.cpu["logical_cores"] >= 1
    assert snap.memory["total_bytes"] > 0
    assert isinstance(snap.gpu, list)
    assert isinstance(snap.power, list)
    assert "toolkit_detected" in snap.cuda
