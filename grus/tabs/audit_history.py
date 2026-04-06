import csv
import os
import threading
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Static, DataTable, Input
from textual.containers import Container


class AuditHistoryTab(Container):

    BINDINGS = [
        Binding("r", "refresh", "Refresh", show=True),
        Binding("f", "filter_flag", "Filter", show=True),
        Binding("n", "next_page", "Next", show=True),
        Binding("p", "prev_page", "Prev", show=True),
        Binding("x", "export_csv", "Export", show=True),
    ]

    CSS = """
    AuditHistoryTab {
        height: 1fr;
        layout: vertical;
    }

    #audit-header {
        height: 3;
        padding: 0 1;
    }

    #audit-table {
        height: 1fr;
    }

    #audit-filter {
        height: 3;
        display: none;
    }

    #audit-status {
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    """

    PAGE_SIZE = 20

    def __init__(self, client):
        super().__init__()
        self._client = client
        self._records = []
        self._page = 0
        self._filter_name = ""

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]Audit History[/]  |  "
            "[dim]R[/]:Refresh  [dim]F[/]:Filter  "
            "[dim]N[/]:Next  [dim]P[/]:Prev  [dim]X[/]:Export",
            id="audit-header",
        )
        yield Input(
            placeholder="Filter by flag name (press Enter)...",
            id="audit-filter",
        )
        table = DataTable(id="audit-table")
        table.cursor_type = "row"
        table.add_columns("Timestamp", "Flag", "Old", "New", "Changed By", "Policy", "Reason")
        yield table
        yield Static("Page 1", id="audit-status")

    def on_mount(self):
        self._load_records()
        self.query_one("#audit-table", DataTable).focus()

    def _load_records(self):
        def _fetch():
            try:
                resp = self._client.get_history(
                    flag_name=self._filter_name,
                    limit=0,
                )
                self._records = []
                for r in resp.records:
                    self._records.append({
                        'timestamp': r.changed_at,
                        'flag_name': r.flag_name,
                        'old_value': r.old_value,
                        'new_value': r.new_value,
                        'changed_by': r.changed_by,
                        'policy_result': r.policy_result,
                        'reason': r.reason,
                    })
                self.app.call_from_thread(self._render_page)
            except Exception as e:
                self.app.call_from_thread(
                    self.notify, f"Failed to load audit history: {e}", severity="error"
                )

        threading.Thread(target=_fetch, daemon=True).start()

    def _render_page(self):
        table = self.query_one("#audit-table", DataTable)
        table.clear()

        start = self._page * self.PAGE_SIZE
        end = start + self.PAGE_SIZE
        page_records = self._records[start:end]

        for r in page_records:
            ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['timestamp']))
            old_val = "[green]ON[/]" if r['old_value'] else "[red]OFF[/]"
            new_val = "[green]ON[/]" if r['new_value'] else "[red]OFF[/]"
            policy = "[green]approved[/]" if r['policy_result'] == 'approved' else f"[red]{r['policy_result']}[/]"
            table.add_row(ts, r['flag_name'], old_val, new_val, r['changed_by'], policy, r['reason'])

        total_pages = max(1, (len(self._records) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        status = self.query_one("#audit-status", Static)
        filter_text = f" | Filter: '{self._filter_name}'" if self._filter_name else ""
        status.update(f"Page {self._page + 1}/{total_pages} | {len(self._records)} records{filter_text}")

    def action_refresh(self):
        self._page = 0
        self._load_records()
        self.notify("Audit history refreshed.")

    def action_filter_flag(self):
        filter_input = self.query_one("#audit-filter", Input)
        if filter_input.styles.display == "none":
            filter_input.styles.display = "block"
            filter_input.focus()
        else:
            filter_input.styles.display = "none"

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "audit-filter":
            self._filter_name = event.value.strip()
            self._page = 0
            event.input.styles.display = "none"
            self._load_records()
            if self._filter_name:
                self.notify(f"Filtering by: '{self._filter_name}'")
            else:
                self.notify("Filter cleared.")

    def action_next_page(self):
        total_pages = max(1, (len(self._records) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        if self._page < total_pages - 1:
            self._page += 1
            self._render_page()

    def action_prev_page(self):
        if self._page > 0:
            self._page -= 1
            self._render_page()

    def action_export_csv(self):
        if not self._records:
            self.notify("No records to export.", severity="warning")
            return

        export_path = os.path.join('.', 'audit_export.csv')
        with open(export_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Timestamp', 'Flag', 'Old Value', 'New Value', 'Changed By', 'Policy Result', 'Reason'])
            for r in self._records:
                ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['timestamp']))
                writer.writerow([
                    ts, r['flag_name'], r['old_value'], r['new_value'],
                    r['changed_by'], r['policy_result'], r['reason'],
                ])

        self.notify(f"Exported {len(self._records)} records to {export_path}")
