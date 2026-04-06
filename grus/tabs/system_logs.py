import os
import threading
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Static, RichLog, Input, Select
from textual.containers import Container, Horizontal


SERVICE_COLORS = {
    'flag_store': 'blue',
    'policy_evaluator': 'green',
    'broadcaster': 'yellow',
    'audit_logger': 'magenta',
    'grus': 'cyan',
}

LOG_FILES = ['flag_store.log', 'policy_evaluator.log', 'broadcaster.log', 'audit_logger.log', 'grus.log']


class SystemLogsTab(Container):

    BINDINGS = [
        Binding("p", "toggle_pause", "Pause", show=True),
        Binding("c", "clear_log", "Clear", show=True),
        Binding("s", "search_log", "Search", show=True),
    ]

    CSS = """
    SystemLogsTab {
        height: 1fr;
        layout: vertical;
    }

    #logs-header {
        height: 3;
        padding: 0 1;
    }

    #logs-log {
        height: 1fr;
    }

    #logs-search {
        height: 3;
        display: none;
    }
    """

    def __init__(self, cfg):
        super().__init__()
        self._cfg = cfg
        self._paused = False
        self._search_text = ""
        self._running = False
        self._tail_thread = None
        self._log_dir = os.path.join(
            cfg.get('_project_root', '.'),
            cfg.get('logging', {}).get('directory', 'logs'),
        )

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]System Logs[/]  |  "
            "[dim]P[/]:Pause  [dim]C[/]:Clear  [dim]S[/]:Search  "
            "[green]\u25cf TAILING[/]",
            id="logs-header",
        )
        yield Input(placeholder="Search text (press Enter)...", id="logs-search")
        yield RichLog(highlight=True, markup=True, wrap=True, id="logs-log")

    def on_mount(self):
        self._running = True
        self._tail_thread = threading.Thread(target=self._tail_loop, daemon=True)
        self._tail_thread.start()
        self.query_one("#logs-log", RichLog).focus()

    def _tail_loop(self):
        positions = {}
        for fname in LOG_FILES:
            fpath = os.path.join(self._log_dir, fname)
            if os.path.isfile(fpath):
                positions[fname] = os.path.getsize(fpath)
            else:
                positions[fname] = 0

        while self._running:
            for fname in LOG_FILES:
                if self._paused:
                    break

                fpath = os.path.join(self._log_dir, fname)
                if not os.path.isfile(fpath):
                    continue

                current_size = os.path.getsize(fpath)
                if current_size <= positions.get(fname, 0):
                    if current_size < positions.get(fname, 0):
                        positions[fname] = 0
                    continue

                try:
                    with open(fpath, 'r') as f:
                        f.seek(positions.get(fname, 0))
                        new_lines = f.read()
                        positions[fname] = f.tell()

                    svc_name = fname.replace('.log', '')
                    color = SERVICE_COLORS.get(svc_name, 'white')

                    for line in new_lines.splitlines():
                        if not line.strip():
                            continue
                        if self._search_text and self._search_text.lower() not in line.lower():
                            continue
                        tag = svc_name.upper().replace('_', ' ')
                        formatted = f"[{color}][{tag}][/] {line}"
                        self.app.call_from_thread(self._append_line, formatted)
                except Exception:
                    pass

            time.sleep(0.5)

    def _append_line(self, line):
        try:
            log_widget = self.query_one("#logs-log", RichLog)
            log_widget.write(line)
        except Exception:
            pass

    def action_toggle_pause(self):
        self._paused = not self._paused
        header = self.query_one("#logs-header", Static)
        if self._paused:
            header.update(
                "[b]System Logs[/]  |  "
                "[dim]P[/]:Resume  [dim]C[/]:Clear  [dim]S[/]:Search  "
                "[yellow]\u25a0 PAUSED[/]"
            )
        else:
            header.update(
                "[b]System Logs[/]  |  "
                "[dim]P[/]:Pause  [dim]C[/]:Clear  [dim]S[/]:Search  "
                "[green]\u25cf TAILING[/]"
            )

    def action_clear_log(self):
        log_widget = self.query_one("#logs-log", RichLog)
        log_widget.clear()
        self.notify("Logs cleared.")

    def action_search_log(self):
        search_input = self.query_one("#logs-search", Input)
        if search_input.styles.display == "none":
            search_input.styles.display = "block"
            search_input.focus()
        else:
            search_input.styles.display = "none"
            self._search_text = ""

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "logs-search":
            self._search_text = event.value.strip()
            event.input.styles.display = "none"
            if self._search_text:
                self.notify(f"Searching: '{self._search_text}'")
            else:
                self.notify("Search cleared.")

    def on_unmount(self):
        self._running = False
