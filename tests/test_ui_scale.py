"""Size of the interface (Einstellungen → Darstellung): 100-200 %, effective after a restart."""
import os
import pytest
from src.utils import ui_scale


@pytest.fixture
def scale_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_scale.paths, "DATA_DIR", str(tmp_path))
    # Registered with monkeypatch, so the factor set by apply_before_start() is removed after the test
    monkeypatch.setenv("QT_SCALE_FACTOR", "1")
    monkeypatch.delenv("QT_SCALE_FACTOR")
    return tmp_path / "darstellung.json"


def test_scale_is_saved_and_applied_before_start(scale_file, monkeypatch):
    assert ui_scale.load() == 100 # nothing chosen yet
    ui_scale.apply_before_start()
    assert "QT_SCALE_FACTOR" not in os.environ
    ui_scale.save(175)
    assert ui_scale.load() == 175
    ui_scale.apply_before_start()
    assert os.environ["QT_SCALE_FACTOR"] == "1.75"
    with pytest.raises(ValueError):
        ui_scale.save(130)


def test_damaged_or_unknown_values_fall_back_to_100(scale_file):
    for content in ("kein json", '{"scale": 300}', '["x"]'):
        scale_file.write_text(content, encoding="utf-8")
        assert ui_scale.load() == 100


def test_settings_tab_saves_the_choice(controller, seller, scale_file, qapp, monkeypatch):
    import src.views.settings_interface as module
    asked = []
    monkeypatch.setattr(module, "confirm", lambda *a: asked.append(a) or False) # no restart now
    settings = module.SettingsInterface(controller)
    combo = settings.scaleCombo
    assert [combo.itemText(i) for i in range(combo.count())] == ["100 %", "125 %", "150 %", "175 %", "200 %"]
    settings.load_settings()
    combo.setCurrentIndex(3)
    assert ui_scale.load() == 175 and asked and "Neustart" in asked[0][2]
    # The size is saved on its own: it is no unsaved change of the other settings
    assert not settings.has_unsaved_changes()
