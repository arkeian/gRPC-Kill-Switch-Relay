import threading
import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Header, Footer, TabbedContent, TabPane, Static
from textual.timer import Timer

from tui.tabs.flag_management import FlagManagementTab
from tui.tabs.live_stream import LiveStreamTab
from tui.tabs.audit_history import AuditHistoryTab
from tui.tabs.policy_testing import PolicyTestingTab
from tui.tabs.system_logs import SystemLogsTab


class ServiceStatus(Static):

    def __init__(self, process_manager, grpc_client, **kwargs):
        super().__init__(**kwargs)
        self._pm = process_manager
        self._client = grpc_client
        self._services = ['flag_store', 'policy_evaluator', 'broadcaster', 'audit_logger']
        self._labels = {
            'flag_store': 'FS',
            'policy_evaluator': 'PE',
            'broadcaster': 'BC',
            'audit_logger': 'AL',
        }

    def on_mount(self):
        self.set_interval(3.0, self._refresh_status)
        self._refresh_status()

    def _refresh_status(self):
        parts = []
        for svc in self._services:
            up = self._pm.check_service(svc)
            dot = "[green]\u25cf[/]" if up else "[red]\u25cb[/]"
            parts.append(f"{dot} {self._labels[svc]}")
        self.update(" | ".join(parts))


class GrusApp(App):

    CSS = """
    Screen {
        layout: vertical;
    }

    #title-bar {
        dock: top;
        height: 1;
        background: $primary-background;
        color: $text;
        text-align: center;
        text-style: bold;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $panel;
        padding: 0 1;
    }

    TabbedContent {
        height: 1fr;
    }
    """

    TITLE = "GRUS"
    SUB_TITLE = "Kill Switch Relay Control Center"

    BINDINGS = [
        Binding("q", "quit_app", "Quit", show=True),
        Binding("question_mark", "help_overlay", "Help", show=True),
        Binding("1", "tab_1", "Flags", show=True),
        Binding("2", "tab_2", "Stream", show=True),
        Binding("3", "tab_3", "Audit", show=True),
        Binding("4", "tab_4", "Policy", show=True),
        Binding("5", "tab_5", "Logs", show=True),
    ]

    def __init__(self, cfg, grpc_client, process_manager):
        super().__init__()
        self._cfg = cfg
        self._client = grpc_client
        self._pm = process_manager

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="tabs"):
            with TabPane("Flags", id="tab-flags"):
                yield FlagManagementTab(self._client, self._cfg)
            with TabPane("Stream", id="tab-stream"):
                yield LiveStreamTab(self._client)
            with TabPane("Audit", id="tab-audit"):
                yield AuditHistoryTab(self._client)
            with TabPane("Policy", id="tab-policy"):
                yield PolicyTestingTab(self._client)
            with TabPane("Logs", id="tab-logs"):
                yield SystemLogsTab(self._cfg)
        yield ServiceStatus(self._pm, self._client, id="status-bar")
        yield Footer()

    def action_quit_app(self):
        self.exit()

    def action_help_overlay(self):
        tab = self.query_one(TabbedContent)
        active = tab.active
        help_texts = {
            "tab-flags": (
                "[b]Flag Management[/]\n\n"
                "  [b]T[/] Toggle flag   [b]A[/] Add flag\n"
                "  [b]D[/] Delete flag   [b]I[/] Flag info\n"
                "  [b]R[/] Refresh       [b]X[/] Export JSON\n"
            ),
            "tab-stream": (
                "[b]Live Stream Monitor[/]\n\n"
                "  [b]P[/] Pause/Resume   [b]C[/] Clear\n"
                "  [b]F[/] Filter          [b]S[/] Search\n"
            ),
            "tab-audit": (
                "[b]Audit History[/]\n\n"
                "  [b]R[/] Refresh   [b]F[/] Filter by flag\n"
                "  [b]N[/] Next page [b]P[/] Prev page\n"
                "  [b]X[/] Export CSV\n"
            ),
            "tab-policy": (
                "[b]Policy Testing[/]\n\n"
                "  Fill in the form and press [b]Enter[/] to validate.\n"
                "  This is a dry-run — no flags are modified.\n"
            ),
            "tab-logs": (
                "[b]System Logs[/]\n\n"
                "  [b]P[/] Pause/Resume   [b]C[/] Clear\n"
                "  [b]S[/] Search\n"
            ),
        }
        text = help_texts.get(active, "No help available for this tab.")
        self.notify(text, title="Keyboard Shortcuts", timeout=8)

    def _switch_tab(self, tab_id):
        tabs = self.query_one(TabbedContent)
        tabs.active = tab_id
        self._focus_active_tab(tab_id)

    def _focus_active_tab(self, tab_id):
        focus_map = {
            "tab-flags": "#flag-table",
            "tab-stream": "#stream-log",
            "tab-audit": "#audit-table",
            "tab-policy": "#flag-select",
            "tab-logs": "#logs-log",
        }
        selector = focus_map.get(tab_id)
        if selector:
            try:
                self.query_one(selector).focus()
            except Exception:
                pass

    def action_tab_1(self):
        self._switch_tab("tab-flags")

    def action_tab_2(self):
        self._switch_tab("tab-stream")

    def action_tab_3(self):
        self._switch_tab("tab-audit")

    def action_tab_4(self):
        self._switch_tab("tab-policy")

    def action_tab_5(self):
        self._switch_tab("tab-logs")
