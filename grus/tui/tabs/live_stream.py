import threading
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Static, RichLog, Input
from textual.containers import Container


class LiveStreamTab(Container):

    BINDINGS = [
        Binding("p", "toggle_pause", "Pause", show=True),
        Binding("c", "clear_log", "Clear", show=True),
        Binding("f", "filter_stream", "Filter", show=True),
        Binding("s", "search_stream", "Search", show=True),
    ]

    CSS = """
    LiveStreamTab {
        height: 1fr;
        layout: vertical;
    }

    #stream-header {
        height: 3;
        padding: 0 1;
    }

    #stream-log {
        height: 1fr;
    }

    #stream-filter {
        height: 3;
        display: none;
    }
    """

    def __init__(self, client):
        super().__init__()
        self._client = client
        self._paused = False
        self._filter_text = ""
        self._stream_thread = None
        self._running = False

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]Live Stream Monitor[/]  |  "
            "[dim]P[/]:Pause  [dim]C[/]:Clear  [dim]F[/]:Filter  [dim]S[/]:Search  "
            "[green]\u25cf LIVE[/]",
            id="stream-header",
        )
        yield Input(placeholder="Filter by flag name (press Enter to apply, Escape to cancel)...", id="stream-filter")
        yield RichLog(highlight=True, markup=True, wrap=True, id="stream-log")

    def on_mount(self):
        self._running = True
        self._stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._stream_thread.start()
        self.query_one("#stream-log", RichLog).focus()

    def _stream_loop(self):
        while self._running:
            try:
                stream = self._client.subscribe_flags()
                for update in stream:
                    if not self._running:
                        break
                    if self._paused:
                        continue

                    name = update.flag.name
                    if self._filter_text and self._filter_text.lower() not in name.lower():
                        continue

                    ts = time.strftime('%H:%M:%S', time.localtime(update.timestamp))
                    change = update.change_type
                    by = update.changed_by

                    if change == 'ENABLED':
                        line = f"[green][{ts}] {name}: ENABLED by {by}[/]"
                    elif change == 'UPDATED':
                        line = f"[blue][{ts}] {name}: UPDATED by {by}[/]"
                    elif change == 'DELETED':
                        line = f"[red][{ts}] {name}: DELETED by {by}[/]"
                    else:
                        line = f"[red][{ts}] {name}: DISABLED by {by}[/]"

                    self.app.call_from_thread(self._append_line, line)
            except Exception:
                if not self._running:
                    break
                time.sleep(2)

    def _append_line(self, line):
        try:
            log_widget = self.query_one("#stream-log", RichLog)
            log_widget.write(line)
        except Exception:
            pass

    def action_toggle_pause(self):
        self._paused = not self._paused
        header = self.query_one("#stream-header", Static)
        if self._paused:
            header.update(
                "[b]Live Stream Monitor[/]  |  "
                "[dim]P[/]:Resume  [dim]C[/]:Clear  [dim]F[/]:Filter  [dim]S[/]:Search  "
                "[yellow]\u25a0 PAUSED[/]"
            )
        else:
            header.update(
                "[b]Live Stream Monitor[/]  |  "
                "[dim]P[/]:Pause  [dim]C[/]:Clear  [dim]F[/]:Filter  [dim]S[/]:Search  "
                "[green]\u25cf LIVE[/]"
            )

    def action_clear_log(self):
        log_widget = self.query_one("#stream-log", RichLog)
        log_widget.clear()
        self.notify("Stream log cleared.")

    def action_filter_stream(self):
        filter_input = self.query_one("#stream-filter", Input)
        if filter_input.styles.display == "none":
            filter_input.styles.display = "block"
            filter_input.focus()
        else:
            filter_input.styles.display = "none"
            self._filter_text = ""

    def action_search_stream(self):
        self.action_filter_stream()

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "stream-filter":
            self._filter_text = event.value.strip()
            event.input.styles.display = "none"
            if self._filter_text:
                self.notify(f"Filtering: '{self._filter_text}'")
            else:
                self.notify("Filter cleared.")

    def on_unmount(self):
        self._running = False
