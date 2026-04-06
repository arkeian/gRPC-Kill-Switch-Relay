import json
import os
import threading
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static, DataTable, Input, Button, Label, Switch
class AddFlagModal(ModalScreen[dict | None]):

    CSS = """
    AddFlagModal {
        align: center middle;
    }

    #add-dialog {
        width: 60;
        max-width: 95%;
        min-width: 40;
        height: auto;
        max-height: 80%;
        border: solid $panel;
        background: $surface;
        padding: 1 2;
    }

    #add-dialog Label {
        margin-top: 1;
    }

    #add-dialog Input {
        margin-bottom: 0;
    }

    #add-buttons {
        margin-top: 1;
        align: center middle;
    }

    #add-buttons Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="add-dialog"):
            yield Label("[b]Add New Flag[/]")
            yield Label("Name:")
            yield Input(placeholder="e.g. my-new-flag", id="flag-name")
            yield Label("Description:")
            yield Input(placeholder="Short description", id="flag-desc")
            yield Label("Enabled:")
            with Horizontal():
                yield Switch(value=False, id="flag-enabled")
            with Horizontal(id="add-buttons"):
                yield Button("Create", variant="primary", id="btn-create")
                yield Button("Cancel", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn-create":
            name = self.query_one("#flag-name", Input).value.strip()
            desc = self.query_one("#flag-desc", Input).value.strip()
            enabled = self.query_one("#flag-enabled", Switch).value
            if name:
                self.dismiss({"name": name, "description": desc, "enabled": enabled})
            else:
                self.notify("Flag name is required.", severity="error")
        else:
            self.dismiss(None)


class FlagInfoModal(ModalScreen):

    CSS = """
    FlagInfoModal {
        align: center middle;
    }

    #info-dialog {
        width: 60;
        height: 14;
        border: solid $panel;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, flag_data):
        super().__init__()
        self._flag = flag_data

    def compose(self) -> ComposeResult:
        f = self._flag
        status = "[green]ENABLED[/]" if f['enabled'] else "[red]DISABLED[/]"
        with Vertical(id="info-dialog"):
            yield Label(f"[b]Flag: {f['name']}[/]")
            yield Static(f"Status: {status}")
            yield Static(f"Description: {f.get('description', '')}")
            yield Static(f"Protected: {'Yes' if f.get('protected') else 'No'}")
            with Horizontal():
                yield Button("Close", id="btn-close")

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss()


class FlagManagementTab(Container):

    BINDINGS = [
        Binding("t", "toggle_flag", "Toggle", show=True),
        Binding("a", "add_flag", "Add", show=True),
        Binding("d", "delete_flag", "Delete", show=True),
        Binding("i", "flag_info", "Info", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("x", "export_json", "Export", show=True),
    ]

    CSS = """
    FlagManagementTab {
        height: 1fr;
        layout: vertical;
    }

    #flag-header {
        height: 3;
        padding: 0 1;
    }

    #flag-table {
        height: 1fr;
    }
    """

    def __init__(self, client, cfg):
        super().__init__()
        self._client = client
        self._cfg = cfg
        self._flags = []

        try:
            import tomli
        except ModuleNotFoundError:
            import tomllib as tomli

        rules_path = cfg.get('_policy_config_file', '')
        self._protected = set()
        self._mutex_pairs = []
        if rules_path and os.path.isfile(rules_path):
            with open(rules_path, 'rb') as f:
                rules = tomli.load(f)
            self._protected = set(rules.get('protected_flags', []))
            self._mutex_pairs = [tuple(g['flags']) for g in rules.get('mutual_exclusion', [])]

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]Flag Management[/]  |  "
            "[dim]T[/]:Toggle  [dim]A[/]:Add  [dim]D[/]:Delete  "
            "[dim]I[/]:Info  [dim]R[/]:Refresh  [dim]X[/]:Export",
            id="flag-header",
        )
        table = DataTable(id="flag-table")
        table.cursor_type = "row"
        table.add_columns("Status", "Name", "Description", "Badges")
        yield table

    def on_mount(self):
        self._load_flags()
        self.query_one("#flag-table", DataTable).focus()

    def _load_flags(self):
        table = self.query_one("#flag-table", DataTable)
        table.clear()
        self._flags = []

        try:
            resp = self._client.list_flags()
            for f in resp.flags:
                flag_dict = {
                    'name': f.name,
                    'enabled': f.enabled,
                    'description': f.description,
                    'protected': f.name in self._protected,
                }
                self._flags.append(flag_dict)

                status = "[green]\u25cf ON [/]" if f.enabled else "[red]\u25cb OFF[/]"
                badges = []
                if f.name in self._protected:
                    badges.append("[yellow]protected[/]")
                for a, b in self._mutex_pairs:
                    if f.name in (a, b):
                        partner = b if f.name == a else a
                        badges.append(f"[cyan]\u21c4 mutex:{partner}[/]")
                badge_str = " ".join(badges) if badges else ""

                table.add_row(status, f.name, f.description, badge_str)
        except Exception as e:
            self.notify(f"Failed to load flags: {e}", severity="error")

    def _get_selected_flag(self):
        table = self.query_one("#flag-table", DataTable)
        if table.cursor_row is not None and table.cursor_row < len(self._flags):
            return self._flags[table.cursor_row]
        return None

    def action_toggle_flag(self):
        flag = self._get_selected_flag()
        if flag is None:
            self.notify("No flag selected.", severity="warning")
            return

        new_enabled = not flag['enabled']

        def _do_toggle():
            try:
                resp = self._client.set_flag(
                    name=flag['name'],
                    enabled=new_enabled,
                    description=flag['description'],
                    changed_by='grus-operator',
                    reason=f"Toggled via Grus TUI",
                )
                if resp.success:
                    self.app.call_from_thread(self._load_flags)
                    action = "enabled" if new_enabled else "disabled"
                    self.app.call_from_thread(
                        self.notify, f"Flag '{flag['name']}' {action}."
                    )
                else:
                    self.app.call_from_thread(
                        self.notify, f"Denied: {resp.message}", severity="error"
                    )
            except Exception as e:
                self.app.call_from_thread(
                    self.notify, f"Toggle failed: {e}", severity="error"
                )

        threading.Thread(target=_do_toggle, daemon=True).start()

    def action_add_flag(self):
        def _on_result(result):
            if result is None:
                return

            def _do_add():
                try:
                    resp = self._client.set_flag(
                        name=result['name'],
                        enabled=result['enabled'],
                        description=result['description'],
                        changed_by='grus-operator',
                        reason='Created via Grus TUI',
                    )
                    if resp.success:
                        self.app.call_from_thread(self._load_flags)
                        self.app.call_from_thread(
                            self.notify, f"Flag '{result['name']}' created."
                        )
                    else:
                        self.app.call_from_thread(
                            self.notify, f"Denied: {resp.message}", severity="error"
                        )
                except Exception as e:
                    self.app.call_from_thread(
                        self.notify, f"Create failed: {e}", severity="error"
                    )

            threading.Thread(target=_do_add, daemon=True).start()

        self.app.push_screen(AddFlagModal(), callback=_on_result)

    def action_delete_flag(self):
        flag = self._get_selected_flag()
        if flag is None:
            self.notify("No flag selected.", severity="warning")
            return

        def _do_disable():
            try:
                resp = self._client.set_flag(
                    name=flag['name'],
                    enabled=False,
                    description=flag['description'],
                    changed_by='grus-operator',
                    reason='Disabled via Grus TUI (delete)',
                )
                if resp.success:
                    self.app.call_from_thread(self._load_flags)
                    self.app.call_from_thread(
                        self.notify, f"Flag '{flag['name']}' disabled."
                    )
                else:
                    self.app.call_from_thread(
                        self.notify, f"Denied: {resp.message}", severity="error"
                    )
            except Exception as e:
                self.app.call_from_thread(
                    self.notify, f"Delete failed: {e}", severity="error"
                )

        threading.Thread(target=_do_disable, daemon=True).start()

    def action_flag_info(self):
        flag = self._get_selected_flag()
        if flag is None:
            self.notify("No flag selected.", severity="warning")
            return
        self.app.push_screen(FlagInfoModal(flag))

    def action_refresh(self):
        self._load_flags()
        self.notify("Flags refreshed.")

    def action_export_json(self):
        if not self._flags:
            self.notify("No flags to export.", severity="warning")
            return

        export_path = os.path.join(self._cfg.get('_project_root', '.'), 'flags_export.json')
        export_data = []
        for f in self._flags:
            export_data.append({
                'name': f['name'],
                'enabled': f['enabled'],
                'description': f['description'],
            })

        with open(export_path, 'w') as fh:
            json.dump(export_data, fh, indent=2)

        self.notify(f"Exported {len(export_data)} flags to {export_path}")
