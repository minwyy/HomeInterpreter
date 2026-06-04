from app import config


def test_memory_defaults_present():
    assert config.MEMORY_ENABLED is True
    assert config.MEMORY_WINDOW_HOURS == 24
    assert config.MEMORY_MAX_MESSAGES == 50
    assert config.MEMORY_MAX_CHARS == 1000
