"""Shutdown races must not create dialogs in a destroyed Tcl application."""

import logging
import time
import tkinter as tk
from types import SimpleNamespace

import pytest

pytest.importorskip("customtkinter")
from src import gui_app  # noqa: E402


def _window():
    app = SimpleNamespace(
        _closing=False,
        _handling_error=False,
        _warming_dialogs=False,
        _last_input=time.perf_counter() - 100,
        busy=False,
        chooser=None,
        customize=None,
        scheduled=[],
    )
    app._closed = lambda: app._closing
    app._reading_count = lambda: 0
    app._warm_dialogs = lambda: gui_app.Audio8DApp._warm_dialogs(app)
    app._when_alive = lambda *args: app.scheduled.append(args)
    return app


@pytest.mark.parametrize("dialog", ["chooser", "customize"])
def test_close_during_dialog_constructor_is_a_normal_shutdown(monkeypatch, dialog):
    app = _window()
    if dialog == "customize":
        app.chooser = object()

    def interrupted(_parent):
        app._closing = True
        raise tk.TclError(
            'can\'t invoke "bind" command: application has been destroyed'
        )

    monkeypatch.setattr(gui_app, "StyleChooser", interrupted)
    monkeypatch.setattr(gui_app, "CustomizeDialog", interrupted)
    gui_app.Audio8DApp._warm_dialogs(app)
    assert not app._warming_dialogs
    assert app.scheduled == []
    assert getattr(app, dialog) is None


def test_a_live_dialog_failure_is_not_hidden(monkeypatch):
    app = _window()

    def broken(_parent):
        raise tk.TclError("real live-window error")

    monkeypatch.setattr(gui_app, "StyleChooser", broken)
    with pytest.raises(tk.TclError, match="real live-window error"):
        gui_app.Audio8DApp._warm_dialogs(app)
    assert not app._warming_dialogs


def test_constructor_event_pumping_cannot_reenter_warmup(monkeypatch):
    app = _window()
    made = []

    def chooser(parent):
        made.append(parent)
        gui_app.Audio8DApp._warm_dialogs(parent)
        return SimpleNamespace(build_cards=lambda: None)

    monkeypatch.setattr(gui_app, "StyleChooser", chooser)
    gui_app.Audio8DApp._warm_dialogs(app)
    assert made == [app]
    assert app.chooser is not None
    assert len(app.scheduled) == 1


def test_closed_window_never_builds_or_reports_another_dialog(monkeypatch):
    app = _window()
    app._closing = True
    app._show_error = lambda _error: pytest.fail("closed callback tried to show error")
    monkeypatch.setattr(
        gui_app, "ErrorDialog", lambda *_args: pytest.fail("new dialog")
    )
    gui_app.Audio8DApp._warm_dialogs(app)
    gui_app.Audio8DApp._show_error(app, tk.TclError("application has been destroyed"))
    gui_app.Audio8DApp.report_callback_exception(
        app, tk.TclError, tk.TclError("closed"), None
    )
    assert app.scheduled == []


def test_live_callback_error_is_reported():
    app = _window()
    shown = []
    app._show_error = shown.append
    error = RuntimeError("keep this diagnostic")
    gui_app.Audio8DApp.report_callback_exception(app, type(error), error, None)
    assert shown == [error]


def test_error_dialog_failure_cannot_escape_or_recurse(monkeypatch, caplog):
    app = _window()
    calls = []

    def broken(*_args):
        calls.append("first")
        gui_app.Audio8DApp._show_error(app, RuntimeError("nested callback"))
        raise tk.TclError("dialog constructor failed")

    monkeypatch.setattr(gui_app, "ErrorDialog", broken)
    gui_app.Audio8DApp._show_error(app, RuntimeError("original error"))
    assert calls == ["first"]
    assert not app._handling_error
    assert "original error" in caplog.text
    assert "Could not display the error dialog" in caplog.text
    monkeypatch.setattr(
        gui_app, "ErrorDialog", lambda *_args: calls.append("recovered")
    )
    gui_app.Audio8DApp._show_error(app, RuntimeError("next error"))
    assert calls == ["first", "recovered"]


@pytest.mark.parametrize("closes_during_callback", [False, True])
def test_deferred_tcl_failure_is_ignored_only_after_shutdown(closes_during_callback):
    app = _window()
    callbacks = []
    app.after = lambda _delay, callback: callbacks.append(callback) or "timer-id"

    def work():
        app._closing = closes_during_callback
        raise tk.TclError("constructor interrupted")

    assert gui_app.Audio8DApp._when_alive(app, 1, work) == "timer-id"
    if closes_during_callback:
        callbacks[0]()
    else:
        with pytest.raises(tk.TclError, match="constructor interrupted"):
            callbacks[0]()


def test_pending_callback_does_not_run_after_close():
    app = _window()
    callbacks, ran = [], []
    app.after = lambda _delay, callback: callbacks.append(callback) or "timer-id"
    gui_app.Audio8DApp._when_alive(app, 1, lambda: ran.append(True))
    app._closing = True
    callbacks[0]()
    assert ran == []
    assert gui_app.Audio8DApp._when_alive(app, 1, lambda: None) is None


def test_close_still_destroys_the_window_if_cleanup_fails():
    app = _window()
    app.pages = {}
    app.log_handler = logging.NullHandler()
    destroyed = []
    app.destroy = lambda: destroyed.append(True)

    def failed_cleanup():
        raise RuntimeError("cleanup failed")

    app.addon_cancel = SimpleNamespace(set=failed_cleanup)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        gui_app.Audio8DApp.close(app)
    assert app._closing
    assert destroyed == [True]
