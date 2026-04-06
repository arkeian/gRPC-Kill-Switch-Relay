import threading

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Static, Input, Button, Select, Label
from generated import killswitch_pb2


class PolicyTestingTab(Container):

    CSS = """
    PolicyTestingTab {
        height: 1fr;
        layout: vertical;
        padding: 1 2;
    }

    #policy-header {
        height: 3;
    }

    #policy-form {
        height: auto;
        max-height: 20;
        padding: 1;
        border: round $primary;
    }

    #policy-form Label {
        margin-top: 1;
    }

    #policy-form Input {
        margin-bottom: 0;
    }

    #policy-result {
        margin-top: 1;
        padding: 1;
        height: auto;
        min-height: 5;
        border: round $secondary;
    }

    #validate-btn {
        margin-top: 1;
    }

    #proposed-state {
        width: 30;
    }
    """

    def __init__(self, client):
        super().__init__()
        self._client = client
        self._flags_cache = []

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]Policy Testing[/]  |  Dry-run policy validation without modifying flags",
            id="policy-header",
        )
        with Vertical(id="policy-form"):
            yield Label("Flag Name:")
            yield Select([], id="flag-select", prompt="Select a flag...")
            yield Label("Proposed State:")
            yield Select(
                [("Enable (True)", "true"), ("Disable (False)", "false")],
                id="proposed-state",
                prompt="Select proposed state...",
            )
            yield Label("Changed By:")
            yield Input(value="grus-policy-test", id="changed-by")
            yield Button("Validate", variant="primary", id="validate-btn")
        yield Static("[dim]Select a flag and proposed state, then press Validate.[/]", id="policy-result")

    def on_mount(self):
        self._refresh_flag_list()

    def _refresh_flag_list(self):
        def _fetch():
            try:
                resp = self._client.list_flags()
                self._flags_cache = list(resp.flags)
                options = [(f.name, f.name) for f in resp.flags]
                self.app.call_from_thread(self._update_select, options)
            except Exception as e:
                self.app.call_from_thread(
                    self.notify, f"Failed to load flags: {e}", severity="error"
                )

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_select(self, options):
        select = self.query_one("#flag-select", Select)
        select.set_options(options)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "validate-btn":
            self._run_validation()

    def _run_validation(self):
        select = self.query_one("#flag-select", Select)
        proposed_select = self.query_one("#proposed-state", Select)
        changed_by_input = self.query_one("#changed-by", Input)

        if select.value is Select.BLANK:
            self.notify("Please select a flag.", severity="warning")
            return

        if proposed_select.value is Select.BLANK:
            self.notify("Please select a proposed state.", severity="warning")
            return

        flag_name = select.value
        proposed_enabled = proposed_select.value == "true"
        changed_by = changed_by_input.value.strip() or "grus-policy-test"

        current_flag = None
        for f in self._flags_cache:
            if f.name == flag_name:
                current_flag = f
                break

        if current_flag is None:
            current_flag = killswitch_pb2.Flag(name=flag_name, enabled=False)

        proposed_flag = killswitch_pb2.Flag(
            name=flag_name,
            enabled=proposed_enabled,
            description=current_flag.description,
        )

        result_widget = self.query_one("#policy-result", Static)
        result_widget.update("[dim]Validating...[/]")

        def _validate():
            try:
                resp = self._client.validate_change(
                    current_flag=current_flag,
                    proposed_flag=proposed_flag,
                    changed_by=changed_by,
                )

                current_state = "[green]ON[/]" if current_flag.enabled else "[red]OFF[/]"
                proposed_state = "[green]ON[/]" if proposed_enabled else "[red]OFF[/]"

                lines = [
                    f"[b]Flag:[/] {flag_name}",
                    f"[b]Current:[/] {current_state}  ->  [b]Proposed:[/] {proposed_state}",
                    f"[b]Changed By:[/] {changed_by}",
                    "",
                ]

                if resp.approved:
                    lines.append("[green bold]RESULT: APPROVED[/]")
                else:
                    lines.append("[red bold]RESULT: DENIED[/]")
                    lines.append(f"[red]Reason: {resp.denial_reason}[/]")

                self.app.call_from_thread(result_widget.update, "\n".join(lines))
            except Exception as e:
                self.app.call_from_thread(
                    result_widget.update, f"[red]Validation failed: {e}[/]"
                )

        threading.Thread(target=_validate, daemon=True).start()
