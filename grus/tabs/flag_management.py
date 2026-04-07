import json
import os
import tempfile
import threading
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static, DataTable, Input, Button, Label, Switch, Select


class AddFlagModal(ModalScreen[dict | None]):

    BINDINGS = [
        Binding("escape", "cancel", show=False),
    ]

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

    def __init__(self, existing_flags: list[dict] | None = None):
        super().__init__()
        existing_flags = existing_flags or []
        self._flag_enabled_by_name: dict[str, bool] = {
            f.get("name", ""): bool(f.get("enabled", False))
            for f in existing_flags
            if f.get("name")
        }
        self._mutex_options = [("None", "")]
        self._mutex_options.extend(
            (name, name) for name in sorted(self._flag_enabled_by_name.keys())
        )

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
            yield Label("Protected:")
            with Horizontal():
                yield Switch(value=False, id="flag-protected")
            yield Label("Mutex With:")
            yield Select(
                self._mutex_options,
                id="flag-mutex",
                prompt="Select a flag...",
            )
            with Horizontal(id="add-buttons"):
                yield Button("Create", variant="primary", id="btn-create")
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#flag-name", Input).focus()
        self._update_create_enabled()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _apply_enabled_lock(self) -> None:
        enabled_switch = self.query_one("#flag-enabled", Switch)
        mutex_select = self.query_one("#flag-mutex", Select)

        mutex_with = mutex_select.value
        if mutex_with is Select.BLANK or mutex_with is Select.NULL:
            mutex_with = ""
        if mutex_with and mutex_with in self._flag_enabled_by_name:
            partner_enabled = self._flag_enabled_by_name[mutex_with]
            enabled_switch.value = not partner_enabled
            enabled_switch.disabled = True
        else:
            enabled_switch.disabled = False

        self._update_create_enabled()

    def _update_create_enabled(self) -> None:
        name = self.query_one("#flag-name", Input).value.strip()
        mutex_with = self.query_one("#flag-mutex", Select).value
        mutex_selected = mutex_with is not Select.BLANK and mutex_with is not Select.NULL

        create_btn = self.query_one("#btn-create", Button)
        create_btn.disabled = not (bool(name) and mutex_selected)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "flag-mutex":
            self._apply_enabled_lock()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "flag-name":
            self._update_create_enabled()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn-create":
            name = self.query_one("#flag-name", Input).value.strip()
            desc = self.query_one("#flag-desc", Input).value.strip()
            enabled = self.query_one("#flag-enabled", Switch).value
            protected = self.query_one("#flag-protected", Switch).value
            mutex_with = self.query_one("#flag-mutex", Select).value
            if mutex_with is Select.BLANK or mutex_with is Select.NULL:
                self.notify("Please select a Mutex option (None or a flag).", severity="warning")
                return
            if name:
                self.dismiss(
                    {
                        "name": name,
                        "description": desc,
                        "enabled": enabled,
                        "protected": protected,
                        "mutex_with": mutex_with or "",
                    }
                )
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


class DeleteConfirmModal(ModalScreen[bool]):

    CSS = """
    DeleteConfirmModal {
        align: center middle;
    }

    #delete-dialog {
        width: 60;
        max-width: 95%;
        min-width: 40;
        height: auto;
        max-height: 80%;
        border: solid $panel;
        background: $surface;
        padding: 1 2;
    }

    #delete-dialog Label,
    #delete-dialog Static {
        margin-bottom: 1;
    }

    #delete-buttons {
        margin-top: 1;
        align: center middle;
    }

    #delete-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, flag_name: str):
        super().__init__()
        self._flag_name = flag_name

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="delete-dialog"):
            yield Label(f"[b]Delete flag '{self._flag_name}'?[/]")
            yield Static("This action will permanently remove the flag.\nAre you sure you want to continue?")
            with Horizontal(id="delete-buttons"):
                yield Button("Delete", variant="error", id="btn-delete")
                yield Button("Cancel", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn-delete":
            self.dismiss(True)
        else:
            self.dismiss(False)


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

        self._policy_rules_path = cfg.get('_policy_config_file', '')

        try:
            import tomli
        except ModuleNotFoundError:
            import tomllib as tomli

        self._protected = set()
        self._mutex_pairs = []
        self._reload_policy_rules(tomli)

    def _reload_policy_rules(self, tomli_module=None) -> None:
        try:
            if tomli_module is None:
                try:
                    import tomli as tomli_module
                except ModuleNotFoundError:
                    import tomllib as tomli_module

            rules_path = self._policy_rules_path
            if rules_path and os.path.isfile(rules_path):
                with open(rules_path, 'rb') as f:
                    rules = tomli_module.load(f)
                self._protected = set(rules.get('protected_flags', []))
                self._mutex_pairs = [tuple(g['flags']) for g in rules.get('mutual_exclusion', [])]
            else:
                self._protected = set()
                self._mutex_pairs = []
        except Exception:
            self._protected = set()
            self._mutex_pairs = []

    def _read_policy_rules(self) -> dict:
        rules_path = self._policy_rules_path
        if not rules_path or not os.path.isfile(rules_path):
            return {}
        try:
            try:
                import tomli
            except ModuleNotFoundError:
                import tomllib as tomli
            with open(rules_path, 'rb') as f:
                return tomli.load(f)
        except Exception:
            return {}

    def _write_policy_rules(self, rules: dict) -> None:
        rules_path = self._policy_rules_path
        if not rules_path:
            raise RuntimeError("Policy rules file not configured")

        protected_flags = sorted(set(rules.get('protected_flags', [])))
        mutex_groups = rules.get('mutual_exclusion', [])
        mutex_pairs: list[tuple[str, str]] = []
        for g in mutex_groups:
            flags = g.get('flags', []) if isinstance(g, dict) else []
            if isinstance(flags, list) and len(flags) == 2:
                a, b = str(flags[0]), str(flags[1])
                if a and b and a != b:
                    mutex_pairs.append((a, b))

        mw = rules.get('maintenance_window', {}) if isinstance(rules.get('maintenance_window', {}), dict) else {}
        start_hour = int(mw.get('start_hour', 2))
        end_hour = int(mw.get('end_hour', 4))
        timezone_offset = int(mw.get('timezone_offset', 7))

        lines: list[str] = []
        lines.append(f"protected_flags = {json.dumps(protected_flags)}")
        lines.append("")
        for a, b in mutex_pairs:
            lines.append("[[mutual_exclusion]]")
            lines.append(f"flags = {json.dumps([a, b])}")
            lines.append("")
        lines.append("[maintenance_window]")
        lines.append(f"start_hour = {start_hour}")
        lines.append(f"end_hour = {end_hour}")
        lines.append(f"timezone_offset = {timezone_offset}")
        lines.append("")

        os.makedirs(os.path.dirname(rules_path) or '.', exist_ok=True)
        with tempfile.NamedTemporaryFile('w', delete=False, dir=os.path.dirname(rules_path) or '.', encoding='utf-8') as tmp:
            tmp.write("\n".join(lines))
            tmp_path = tmp.name
        os.replace(tmp_path, rules_path)

    def _apply_policy_updates(self, new_flag_name: str, protected: bool, mutex_with: str) -> None:
        if not self._policy_rules_path:
            return

        rules = self._read_policy_rules()
        if not rules:
            rules = {
                'protected_flags': [],
                'mutual_exclusion': [],
                'maintenance_window': {'start_hour': 2, 'end_hour': 4, 'timezone_offset': 7},
            }

        if protected:
            pf = list(rules.get('protected_flags', []))
            if new_flag_name not in pf:
                pf.append(new_flag_name)
            rules['protected_flags'] = pf

        if mutex_with and mutex_with != new_flag_name:
            existing = set()
            for g in rules.get('mutual_exclusion', []) or []:
                flags = g.get('flags', []) if isinstance(g, dict) else []
                if isinstance(flags, list) and len(flags) == 2:
                    existing.add(tuple(sorted((str(flags[0]), str(flags[1])))))

            key = tuple(sorted((new_flag_name, mutex_with)))
            if key not in existing:
                groups = list(rules.get('mutual_exclusion', []))
                groups.append({'flags': [new_flag_name, mutex_with]})
                rules['mutual_exclusion'] = groups

        self._write_policy_rules(rules)
        self._reload_policy_rules()

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
        self.set_interval(30.0, self._periodic_prune_policy_rules)

    def _periodic_prune_policy_rules(self) -> None:
        if not self._policy_rules_path:
            return

        def _do_prune():
            try:
                resp = self._client.list_flags()
                existing_names = {f.name for f in resp.flags}
                changed = self._prune_policy_rules(existing_names)
                if changed:
                    self.app.call_from_thread(self._load_flags)
            except Exception:
                return

        threading.Thread(target=_do_prune, daemon=True).start()

    def _prune_policy_rules(self, existing_names: set[str]) -> bool:
        """Remove stale/invalid entries from policy_rules.toml.

        - Drops any mutex group containing Select.NULL
        - De-dupes mutex pairs (unordered)
        """

        if not self._policy_rules_path:
            return False

        rules = self._read_policy_rules()
        if not rules:
            return False

        original = json.dumps(rules, sort_keys=True, default=str)

        pf = rules.get('protected_flags', [])
        if not isinstance(pf, list):
            pf = []
        pf_clean = [str(x) for x in pf if str(x) and str(x) != 'Select.NULL']
        rules['protected_flags'] = sorted(set(pf_clean))

        mutex_groups = rules.get('mutual_exclusion', [])
        if not isinstance(mutex_groups, list):
            mutex_groups = []

        seen_pairs: set[tuple[str, str]] = set()
        cleaned_groups: list[dict] = []
        for g in mutex_groups:
            if not isinstance(g, dict):
                continue
            flags = g.get('flags', [])
            if not isinstance(flags, list) or len(flags) != 2:
                continue
            a, b = str(flags[0]), str(flags[1])
            if not a or not b or a == b:
                continue
            if a == 'Select.NULL' or b == 'Select.NULL':
                continue

            key = tuple(sorted((a, b)))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            cleaned_groups.append({'flags': [a, b]})

        rules['mutual_exclusion'] = cleaned_groups

        updated = json.dumps(rules, sort_keys=True, default=str)
        if updated == original:
            return False

        self._write_policy_rules(rules)
        self._reload_policy_rules()
        return True

    def _load_flags(self):
        self._reload_policy_rules()
        table = self.query_one("#flag-table", DataTable)
        table.clear()
        self._flags = []

        try:
            resp = self._client.list_flags()
            existing_names = {f.name for f in resp.flags}
            try:
                self._prune_policy_rules(existing_names)
            except Exception:
                pass
            display_mutex_pairs = [
                (a, b)
                for (a, b) in self._mutex_pairs
                if a in existing_names and b in existing_names
            ]
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
                for a, b in display_mutex_pairs:
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
                        try:
                            self._apply_policy_updates(
                                new_flag_name=result['name'],
                                protected=bool(result.get('protected', False)),
                                mutex_with=str(result.get('mutex_with', '') or ''),
                            )
                        except Exception as e:
                            self.app.call_from_thread(
                                self.notify,
                                f"Policy rules update failed: {e}",
                                severity="error",
                            )
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

        self.app.push_screen(AddFlagModal(existing_flags=self._flags), callback=_on_result)

    def action_delete_flag(self):
        flag = self._get_selected_flag()
        if flag is None:
            self.notify("No flag selected.", severity="warning")
            return

        def _on_confirm(result):
            if not result:
                return

            def _do_delete():
                try:
                    resp = self._client.set_flag(
                        name=flag['name'],
                        enabled=False,
                        description=flag['description'],
                        changed_by='grus-operator',
                        reason='Deleted via Grus TUI',
                    )
                    if resp.success:
                        self.app.call_from_thread(self._load_flags)
                        self.app.call_from_thread(
                            self.notify, f"Flag '{flag['name']}' deleted."
                        )
                    else:
                        self.app.call_from_thread(
                            self.notify, f"Denied: {resp.message}", severity="error"
                        )
                except Exception as e:
                    self.app.call_from_thread(
                        self.notify, f"Delete failed: {e}", severity="error"
                    )

            threading.Thread(target=_do_delete, daemon=True).start()

        self.app.push_screen(DeleteConfirmModal(flag['name']), callback=_on_confirm)

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
