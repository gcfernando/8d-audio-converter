"""Explicit CI diagnostics for the real GUI entry point, including frozen builds.

Inactive unless AUDIO8D_GUI_SMOKE_REPORT is set by the packaging test harness.
No system input, security settings or real user profile is used by the harness.
"""

import json
import os
import tkinter as tk
from pathlib import Path

import customtkinter as ctk


class GuiProbe:
    """Observe startup and inject the reproducible constructor-close race."""

    def __init__(self, app, report: Path, case: str) -> None:
        from .gui_app import CustomizeDialog, StyleChooser

        self.app, self.report, self.case = app, report, case
        self.ready = False
        self.injected = False
        self.errors: list[str] = []
        self.closed_callbacks: list[str] = []
        self.original_reporter = app.report_callback_exception
        self.original_color = ctk.CTkToplevel._windows_set_titlebar_color
        target = StyleChooser if case == "close-style" else CustomizeDialog

        def reporter(exc, value, tb):
            if app._closed() and isinstance(value, tk.TclError):
                self.closed_callbacks.append(str(value))
            else:
                self.errors.append(f"{exc.__name__}: {value}")
            try:
                self.original_reporter(exc, value, tb)
            except Exception as error:
                self.errors.append(f"error reporter failed: {error}")

        def title_color(window, *args, **kwargs):
            if case != "warm" and isinstance(window, target) and not self.injected:
                self.injected = True
                # The real CustomTkinter update processes close while its
                # constructor is between creating the Toplevel and binding it.
                app.after_idle(app.close)
            return self.original_color(window, *args, **kwargs)

        app.report_callback_exception = reporter
        if case != "warm":
            ctk.CTkToplevel._windows_set_titlebar_color = title_color
        app.after(100, self.check)
        app.after(45000, self.timeout)

    def check(self) -> None:
        if self.app._closed():
            return
        if (
            self.case == "warm"
            and self.app.chooser is not None
            and self.app.customize is not None
        ):
            self.ready = bool(
                self.app.chooser.winfo_exists() and self.app.customize.winfo_exists()
            )
            self.app.close()
            return
        self.app.after(100, self.check)

    def timeout(self) -> None:
        self.errors.append("GUI warm-up or constructor-close injection timed out")
        self.app.close()

    def finish(self) -> int:
        ctk.CTkToplevel._windows_set_titlebar_color = self.original_color
        expected = self.ready if self.case == "warm" else self.injected
        success = expected and self.app._closed() and not self.errors
        data = {
            "case": self.case,
            "success": success,
            "warm_dialogs_ready": self.ready,
            "close_injected": self.injected,
            "errors": self.errors,
            "shutdown_callbacks": self.closed_callbacks,
        }
        self.report.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return 0 if success else 1


def install(app) -> GuiProbe | None:
    """Enable diagnostics only for an explicit new report in an isolated home."""
    requested = os.environ.get("AUDIO8D_GUI_SMOKE_REPORT")
    if not requested:
        return None
    report = Path(requested).resolve()
    home = os.environ.get("AUDIO8D_HOME")
    if not home or report.parent != Path(home).resolve() or report.exists():
        raise ValueError("GUI smoke reports require a new file inside AUDIO8D_HOME")
    case = os.environ.get("AUDIO8D_GUI_SMOKE_CASE", "warm")
    if case not in {"warm", "close-style", "close-customize"}:
        raise ValueError("Unknown GUI smoke case")
    report.parent.mkdir(parents=True, exist_ok=True)
    return GuiProbe(app, report, case)
