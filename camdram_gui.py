"""
Searchable GUI for Camdram people ranked by total roles.
Uses cached data - click 'Fetch Data' to populate (takes ~10 min).
"""

import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from camdram_data import load_rankings, load_role_rankings


class CamdramGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Camdram – People by Roles")
        self.root.geometry("900x500")
        self.root.minsize(400, 300)

        self.rankings: list[tuple] = []
        self.filtered: list[tuple] = []
        self.sort_column = "count"  # column id for sorting
        self.sort_desc = True  # descending by default
        self.roles_list: list[tuple[str, int]] = []
        self.role_rankings: dict[str, list[tuple[int, str, str, int]]] = {}

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Tab 1: By person ---
        tab1 = ttk.Frame(notebook, padding="5")
        notebook.add(tab1, text="By person")

        # Header
        header = ttk.Frame(tab1, padding="10 5")
        header.pack(fill=tk.X)
        ttk.Label(header, text="People ranked by total roles (Camdram)", font=("", 14, "bold")).pack(anchor=tk.W)
        ttk.Label(header, text="Search by name:").pack(anchor=tk.W, pady=(5, 0))

        # Search
        search_frame = ttk.Frame(header)
        search_frame.pack(fill=tk.X, pady=2)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search)
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=40)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(search_frame, text="Clear", command=self._clear_search).pack(side=tk.LEFT)

        # Fetch button
        ttk.Button(header, text="Fetch Data (refresh cache)", command=self._fetch_data).pack(anchor=tk.W, pady=5)

        # Status
        self.status_var = tk.StringVar()
        ttk.Label(header, textvariable=self.status_var).pack(anchor=tk.W, pady=2)

        # Table
        table_frame = ttk.Frame(tab1, padding="10")
        table_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("count", "shows", "titles", "top_pct", "name", "top_role")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=20,
        )
        self.tree.heading("count", text="Roles", command=lambda: self._sort_by("count"))
        self.tree.heading("shows", text="Shows", command=lambda: self._sort_by("shows"))
        self.tree.heading("titles", text="Role types", command=lambda: self._sort_by("titles"))
        self.tree.heading("top_pct", text="Top %", command=lambda: self._sort_by("top_pct"))
        self.tree.heading("name", text="Name", command=lambda: self._sort_by("name"))
        self.tree.heading("top_role", text="Top role", command=lambda: self._sort_by("top_role"))
        self.tree.column("count", width=50, minwidth=45)
        self.tree.column("shows", width=50, minwidth=45)
        self.tree.column("titles", width=55, minwidth=50)
        self.tree.column("top_pct", width=48, minwidth=42)
        self.tree.column("name", width=180, minwidth=80)
        self.tree.column("top_role", width=200, minwidth=100)
        scrollbar_y = ttk.Scrollbar(table_frame)
        scrollbar_x = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL)
        self.tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        scrollbar_y.config(command=self.tree.yview)
        scrollbar_x.config(command=self.tree.xview)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)

        # --- Tab 2: By role ---
        tab2 = ttk.Frame(notebook, padding="5")
        notebook.add(tab2, text="By role")
        ttk.Label(tab2, text="Select a role to see who has done it most often:", font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 5))
        paned = ttk.PanedWindow(tab2, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        # Left: list of roles
        role_list_frame = ttk.Frame(paned)
        paned.add(role_list_frame, weight=0)
        ttk.Label(role_list_frame, text="Role").pack(anchor=tk.W)
        role_list_scroll = ttk.Scrollbar(role_list_frame)
        self.role_listbox = tk.Listbox(
            role_list_frame,
            height=25,
            font=("", 10),
            yscrollcommand=role_list_scroll.set,
            selectmode=tk.SINGLE,
        )
        role_list_scroll.config(command=self.role_listbox.yview)
        self.role_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        role_list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.role_listbox.bind("<<ListboxSelect>>", self._on_role_select)
        # Right: ranking for selected role
        rank_frame = ttk.Frame(paned)
        paned.add(rank_frame, weight=1)
        ttk.Label(rank_frame, text="Ranking (double-click name to open profile)").pack(anchor=tk.W)
        self.role_rank_cols = ("rank", "name", "count")
        self.role_tree = ttk.Treeview(
            rank_frame,
            columns=self.role_rank_cols,
            show="headings",
            selectmode="browse",
            height=25,
        )
        self.role_tree.heading("rank", text="Rank")
        self.role_tree.heading("name", text="Name")
        self.role_tree.heading("count", text="Count")
        self.role_tree.column("rank", width=60)
        self.role_tree.column("name", width=280)
        self.role_tree.column("count", width=70)
        role_tree_scroll = ttk.Scrollbar(rank_frame)
        self.role_tree.configure(yscrollcommand=role_tree_scroll.set)
        self.role_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        role_tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        role_tree_scroll.config(command=self.role_tree.yview)
        self.role_tree.bind("<Double-1>", self._on_role_rank_double_click)
        self.role_status_var = tk.StringVar()
        ttk.Label(rank_frame, textvariable=self.role_status_var).pack(anchor=tk.W, pady=2)

        self.search_entry.focus_set()

    def _sort_by(self, column: str) -> None:
        """Set sort column (and toggle asc/desc if same column), then refresh."""
        if column == self.sort_column:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_column = column
            # Default desc for numeric columns, asc for name/top_role
            self.sort_desc = column in ("count", "shows", "titles", "top_pct")
        self._refresh_list()

    def _on_search(self, *args):
        q = self.search_var.get().strip().lower()
        if not q:
            self.filtered = self.rankings[:]
        else:
            self.filtered = [r for r in self.rankings if q in r[1].lower()]
        self._refresh_list()

    def _clear_search(self):
        self.search_var.set("")
        self.search_entry.focus_set()

    def _fetch_data(self):
        if not messagebox.askyesno(
            "Fetch Data",
            "This will fetch all shows and roles from the API (~10 min). Continue?",
        ):
            return

        def do_fetch():
            try:
                subprocess.run(
                    [sys.executable, str(Path(__file__).parent / "rank_all_people.py"), "--refresh"],
                    cwd=str(Path(__file__).parent),
                    check=True,
                )
                self.root.after(0, self._on_fetch_done)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))

        self.status_var.set("Fetching data... (this may take ~10 minutes)")
        threading.Thread(target=do_fetch, daemon=True).start()

    def _on_fetch_done(self):
        self.status_var.set("Loading...")
        self.rankings = load_rankings()
        self.filtered = self.rankings[:]
        self._refresh_list()
        self.roles_list, self.role_rankings = load_role_rankings()
        self._refresh_role_listbox()
        messagebox.showinfo("Done", "Data fetched successfully.")

    def _refresh_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        # Sort by the selected column only.
        # Tuple starts with: (pid, name, slug, count, top_role, top_role_count, num_shows, num_titles, top_pct, ...)
        col_to_idx = {"count": 3, "shows": 6, "titles": 7, "top_pct": 8, "name": 1, "top_role": 4}
        idx = col_to_idx.get(self.sort_column, 3)
        reverse = self.sort_desc
        if self.sort_column in ("count", "shows", "titles", "top_pct"):
            sorted_rows = sorted(
                self.filtered,
                key=lambda r: (r[idx] if r[idx] is not None else 0),
                reverse=reverse,
            )
        elif self.sort_column == "name":
            sorted_rows = sorted(
                self.filtered,
                key=lambda r: (r[1] or "").lower(),
                reverse=reverse,
            )
        else:
            # top_role: alphabetically by role name (asc/desc), then by frequency (count desc)
            def top_role_key(r):
                name_part = (r[4] or "").lower()
                # Inverted char codes so reverse=True gives A-Z, reverse=False gives Z-A; -r[5] keeps freq desc
                name_key = tuple(255 - ord(c) for c in name_part)
                return (name_key, -r[5])
            sorted_rows = sorted(self.filtered, key=top_role_key, reverse=not reverse)
        for r in sorted_rows:
            pid, name, slug, count, top_role, top_role_count, num_shows, num_titles, top_pct, *_ = r
            top_str = f"{top_role} ({top_role_count})" if top_role_count else "—"
            self.tree.insert(
                "",
                tk.END,
                values=(count, num_shows, num_titles, f"{top_pct}%", name, top_str),
                iid=str(pid),
            )
        self.status_var.set(f"Showing {len(self.filtered)} of {len(self.rankings)} people (sorted by {self.sort_column})")

    def _on_select(self, event):
        pass

    def _on_role_select(self, event) -> None:
        sel = self.role_listbox.curselection()
        if not sel or not self.role_rankings:
            return
        idx = sel[0]
        if idx >= len(self.roles_list):
            return
        role_name, _ = self.roles_list[idx]
        ranked = self.role_rankings.get(role_name, [])
        for item in self.role_tree.get_children():
            self.role_tree.delete(item)
        rank = 0
        prev_count = None
        for pid, name, slug, count in ranked:
            if prev_count is None or count != prev_count:
                rank += 1
            prev_count = count
            self.role_tree.insert("", tk.END, values=(rank, name, count), iid=str(pid))

        self.role_status_var.set(f"{role_name}: {len(ranked)} people")

    def _on_role_rank_double_click(self, event) -> None:
        sel = self.role_tree.selection()
        if not sel:
            return
        try:
            pid = int(self.role_tree.item(sel[0], "iid"))
        except (ValueError, TypeError):
            return
        sel_role = self.role_listbox.curselection()
        if not sel_role or sel_role[0] >= len(self.roles_list):
            return
        role_name = self.roles_list[sel_role[0]][0]
        for row in self.role_rankings.get(role_name, []):
            if row[0] == pid and row[2]:
                import webbrowser
                webbrowser.open(f"https://www.camdram.net/people/{row[2]}")
                break

    def _on_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        item = sel[0]
        try:
            pid = int(item)
        except ValueError:
            return
        for r in self.filtered:
            if r[0] == pid and r[2]:
                import webbrowser
                webbrowser.open(f"https://www.camdram.net/people/{r[2]}")
                break

    def _refresh_role_listbox(self) -> None:
        self.role_listbox.delete(0, tk.END)
        for role_name, num_people in self.roles_list:
            self.role_listbox.insert(tk.END, f"  {role_name}  ({num_people})")
        if self.roles_list:
            self.role_listbox.selection_set(0)
            self._on_role_select(None)

    def run(self):
        self.rankings = load_rankings()
        if not self.rankings:
            messagebox.showerror(
                "No Data",
                "No cache found. Run rank_all_people.py first to fetch and cache the data.",
            )
            return
        self.filtered = self.rankings[:]
        self._refresh_list()
        self.roles_list, self.role_rankings = load_role_rankings()
        self._refresh_role_listbox()
        self.root.mainloop()


def main():
    app = CamdramGUI()
    app.run()


if __name__ == "__main__":
    main()
