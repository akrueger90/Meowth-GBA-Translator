import threading
from types import SimpleNamespace

from meowth.core import TranslationConfig
from meowth.gui import app as app_module


class FakeEngine:
    def __init__(self, config, callbacks):
        self.config = config
        self.callbacks = callbacks
        self._stop_event = threading.Event()


def test_review_engine_is_reused_until_configuration_changes(monkeypatch, tmp_path):
    created = []

    def create_engine(config, callbacks):
        engine = FakeEngine(config, callbacks)
        created.append(engine)
        return engine

    config = TranslationConfig(work_dir=tmp_path)
    form = SimpleNamespace(get_config=lambda: config)
    gui = SimpleNamespace(
        config_form=form,
        log_view=object(),
        engine=None,
        _review_engine=None,
    )
    monkeypatch.setattr(app_module, "GUICallbacks", lambda gui, log_view: object())
    monkeypatch.setattr(app_module, "TranslationEngine", create_engine)

    app_module.MeowthGUI._ensure_engine_for_review(gui)
    first_engine = gui.engine
    app_module.MeowthGUI._ensure_engine_for_review(gui)

    assert gui.engine is first_engine
    assert len(created) == 1

    form.get_config = lambda: TranslationConfig(
        work_dir=tmp_path,
        target_lang="de",
    )
    app_module.MeowthGUI._ensure_engine_for_review(gui)

    assert gui.engine is not first_engine
    assert len(created) == 2


def test_stopped_review_engine_is_recreated(monkeypatch, tmp_path):
    created = []

    def create_engine(config, callbacks):
        engine = FakeEngine(config, callbacks)
        created.append(engine)
        return engine

    config = TranslationConfig(work_dir=tmp_path)
    gui = SimpleNamespace(
        config_form=SimpleNamespace(get_config=lambda: config),
        log_view=object(),
        engine=None,
        _review_engine=None,
    )
    monkeypatch.setattr(app_module, "GUICallbacks", lambda gui, log_view: object())
    monkeypatch.setattr(app_module, "TranslationEngine", create_engine)

    app_module.MeowthGUI._ensure_engine_for_review(gui)
    gui.engine._stop_event.set()
    app_module.MeowthGUI._ensure_engine_for_review(gui)

    assert len(created) == 2
