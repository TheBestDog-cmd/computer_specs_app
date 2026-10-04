from specforge_desktop import collector


def test_rejects_useless_processor_strings():
    assert collector._looks_like_cpu_brand("x86_64") is False
    assert collector._looks_like_cpu_brand("Intel64 Family 6 Model 158 Stepping 10, Genuine") is False
    assert collector._looks_like_cpu_brand("AMD64 Family 25 Model 33 Stepping 0") is False


def test_accepts_real_cpu_brand():
    assert collector._looks_like_cpu_brand("Intel(R) Core(TM) i7-10700K CPU @ 3.80GHz") is True
    assert collector._looks_like_cpu_brand("AMD Ryzen 7 5800X 8-Core Processor") is True


def test_cpu_model_returns_string():
    model = collector._cpu_model()
    assert isinstance(model, str)
    assert model
    assert collector._looks_like_cpu_brand(model) or model == "Unknown CPU"
