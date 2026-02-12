"""GUI for the Static Pressure Analysis tool using tkinter."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dataclasses import fields as dataclass_fields

from .models import (
    Connector,
    DamperParameters,
    DuctSplitParameters,
    FanParameters,
    MixingPlenumParameters,
    Node,
    NodeType,
    PressureOutputParameters,
    Project,
    Scenario,
)
from .analysis import run_analysis, run_all_scenarios, AnalysisResult
from .serialization import save_project, load_project


# --------------------------------------------------------------------------- #
#  Visual constants
# --------------------------------------------------------------------------- #
NODE_COLORS = {
    NodeType.FAN: "#4A90D9",
    NodeType.DAMPER: "#E8943A",
    NodeType.MIXING_PLENUM: "#6BBF6B",
    NodeType.DUCT_SPLIT: "#C47DD8",
    NodeType.PRESSURE_OUTPUT: "#E05555",
}

NODE_WIDTH = 120
NODE_HEIGHT = 50
PORT_RADIUS = 6
CONNECTOR_COLOR = "#555555"
CANVAS_BG = "#F5F5F0"

# Interaction modes
MODE_SELECT = "select"
MODE_PLACE = "place"
MODE_CONNECT = "connect"


# --------------------------------------------------------------------------- #
#  Main application
# --------------------------------------------------------------------------- #
class StaticPressureApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Static Pressure Analysis")
        self.root.geometry("1400x800")
        self.root.minsize(1000, 600)

        self.project = Project()
        self.selected_node_id: str | None = None
        self.selected_connector_id: str | None = None

        # Interaction mode
        self._mode = MODE_SELECT
        self._place_node_type: NodeType | None = None  # which type to place
        self._connect_source_id: str | None = None       # source during connect
        self._connect_temp_line: int | None = None        # canvas id of temp line

        # Drag state for moving existing nodes
        self._drag_data = {"node_id": None, "offset_x": 0, "offset_y": 0}

        self._last_results: list[AnalysisResult] = []

        # Toolbox button references (for highlighting active tool)
        self._toolbox_buttons: dict[NodeType, tk.Label] = {}

        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()

    # ------------------------------------------------------------------ #
    #  Menu bar                                                           #
    # ------------------------------------------------------------------ #
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Project", command=self._new_project, accelerator="Ctrl+N")
        file_menu.add_command(label="Open...", command=self._open_project, accelerator="Ctrl+O")
        file_menu.add_command(label="Save...", command=self._save_project, accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        analysis_menu = tk.Menu(menubar, tearoff=0)
        analysis_menu.add_command(label="Run Analysis", command=self._run_analysis, accelerator="F5")
        analysis_menu.add_command(label="Run All Scenarios", command=self._run_all_scenarios)
        menubar.add_cascade(label="Analysis", menu=analysis_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Delete Selected", command=self._delete_selected, accelerator="Delete")
        menubar.add_cascade(label="Edit", menu=edit_menu)

        self.root.config(menu=menubar)

    # ------------------------------------------------------------------ #
    #  Main layout                                                        #
    # ------------------------------------------------------------------ #
    def _build_layout(self):
        self.main_pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_pw.pack(fill=tk.BOTH, expand=True)

        # Left panel: Equipment Toolbox
        left_frame = ttk.Frame(self.main_pw, width=190)
        self.main_pw.add(left_frame, weight=0)
        self._build_toolbox(left_frame)

        # Center: Canvas + scenario area (vertical split)
        center_frame = ttk.Frame(self.main_pw)
        self.main_pw.add(center_frame, weight=1)
        self._build_center(center_frame)

        # Right panel: Properties
        right_frame = ttk.Frame(self.main_pw, width=280)
        self.main_pw.add(right_frame, weight=0)
        self._build_properties_panel(right_frame)

    # ------------------------------------------------------------------ #
    #  Toolbox                                                            #
    # ------------------------------------------------------------------ #
    def _build_toolbox(self, parent):
        ttk.Label(parent, text="Equipment Toolbox", font=("Helvetica", 11, "bold")).pack(
            pady=(10, 5), padx=10, anchor="w"
        )
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5)

        self._toolbox_hint = ttk.Label(parent, text="Click an item, then\nclick the canvas to place it.",
                                        foreground="gray", wraplength=160)
        self._toolbox_hint.pack(pady=(4, 8), padx=10, anchor="w")

        for nt in NodeType:
            btn = tk.Label(
                parent,
                text=f"  {nt.value}  ",
                bg=NODE_COLORS[nt],
                fg="white",
                font=("Helvetica", 10, "bold"),
                relief="raised",
                padx=8,
                pady=6,
                cursor="hand2",
            )
            btn.pack(pady=4, padx=15, fill=tk.X)
            btn.bind("<Button-1>", lambda e, t=nt: self._toolbox_select(t))
            self._toolbox_buttons[nt] = btn

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=(12, 4))

        # Connect mode button
        self._connect_btn = tk.Button(
            parent, text="Connect Nodes", bg="#555555", fg="white",
            font=("Helvetica", 10, "bold"), relief="raised", padx=8, pady=6,
            cursor="hand2", command=self._enter_connect_mode,
        )
        self._connect_btn.pack(pady=4, padx=15, fill=tk.X)

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=(12, 4))

        # Select mode (pointer) button
        self._select_btn = tk.Button(
            parent, text="Select / Move", bg="#336699", fg="white",
            font=("Helvetica", 10, "bold"), relief="sunken", padx=8, pady=6,
            cursor="hand2", command=self._enter_select_mode,
        )
        self._select_btn.pack(pady=4, padx=15, fill=tk.X)

    def _toolbox_select(self, node_type: NodeType):
        """Select a node type to place on the canvas."""
        self._cancel_connect()
        self._mode = MODE_PLACE
        self._place_node_type = node_type
        self.canvas.config(cursor="crosshair")
        self._update_toolbox_highlights()
        self._toolbox_hint.config(text=f"Click on the canvas to\nplace a {node_type.value}.\nPress Esc to cancel.")

    def _enter_connect_mode(self):
        """Switch to connect mode: click source node, then target node."""
        self._mode = MODE_CONNECT
        self._connect_source_id = None
        self._place_node_type = None
        self.canvas.config(cursor="crosshair")
        self._update_toolbox_highlights()
        self._toolbox_hint.config(text="Click a source node,\nthen click a target node\nto draw a connector.\nPress Esc to cancel.")

    def _enter_select_mode(self):
        """Return to normal select/move mode."""
        self._cancel_connect()
        self._mode = MODE_SELECT
        self._place_node_type = None
        self.canvas.config(cursor="")
        self._update_toolbox_highlights()
        self._toolbox_hint.config(text="Click an item, then\nclick the canvas to place it.")

    def _update_toolbox_highlights(self):
        """Update button relief to show which tool is active."""
        for nt, btn in self._toolbox_buttons.items():
            if self._mode == MODE_PLACE and self._place_node_type == nt:
                btn.config(relief="sunken", bd=3)
            else:
                btn.config(relief="raised", bd=2)

        if self._mode == MODE_CONNECT:
            self._connect_btn.config(relief="sunken")
        else:
            self._connect_btn.config(relief="raised")

        if self._mode == MODE_SELECT:
            self._select_btn.config(relief="sunken")
        else:
            self._select_btn.config(relief="raised")

    # ------------------------------------------------------------------ #
    #  Center panel (canvas + scenarios)                                  #
    # ------------------------------------------------------------------ #
    def _build_center(self, parent):
        vpw = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        vpw.pack(fill=tk.BOTH, expand=True)

        canvas_frame = ttk.Frame(vpw)
        vpw.add(canvas_frame, weight=3)

        # Status bar above canvas
        self._status_var = tk.StringVar(value="Mode: Select / Move")
        status_bar = ttk.Label(canvas_frame, textvariable=self._status_var, relief="sunken",
                               anchor="w", padding=(6, 2))
        status_bar.pack(fill=tk.X, side=tk.TOP)

        self.canvas = tk.Canvas(canvas_frame, bg=CANVAS_BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<Button-1>", self._canvas_click)
        self.canvas.bind("<Button-3>", self._canvas_right_click)
        self.canvas.bind("<Motion>", self._canvas_motion)

        # Scenario / results area
        bottom_frame = ttk.Frame(vpw)
        vpw.add(bottom_frame, weight=1)
        self._build_scenario_panel(bottom_frame)

    # ------------------------------------------------------------------ #
    #  Scenario panel                                                     #
    # ------------------------------------------------------------------ #
    def _build_scenario_panel(self, parent):
        nb = ttk.Notebook(parent)
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Tab 1: Scenarios
        scen_frame = ttk.Frame(nb)
        nb.add(scen_frame, text="Scenarios")

        toolbar = ttk.Frame(scen_frame)
        toolbar.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(toolbar, text="Add Scenario", command=self._add_scenario).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Remove Selected", command=self._remove_scenario).pack(side=tk.LEFT, padx=2)
        ttk.Label(toolbar, text="  (Double-click Override CFM / Override SP cells to edit)",
                  foreground="gray").pack(side=tk.LEFT, padx=8)

        # Columns: scenario name, then for each fan: base CFM, override CFM, base SP, override SP
        # We'll rebuild columns dynamically when fans change.
        self._scen_tree_frame = ttk.Frame(scen_frame)
        self._scen_tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        self.scenario_tree: ttk.Treeview | None = None
        self._build_scenario_tree()

        # Tab 2: Results
        result_frame = ttk.Frame(nb)
        nb.add(result_frame, text="Results")

        self.result_text = tk.Text(result_frame, height=8, state=tk.DISABLED, font=("Courier", 10))
        self.result_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def _get_fan_nodes(self) -> list[Node]:
        return [n for n in self.project.nodes.values() if n.node_type == NodeType.FAN]

    def _build_scenario_tree(self):
        """(Re)build the scenario treeview with current fan nodes as columns."""
        for w in self._scen_tree_frame.winfo_children():
            w.destroy()

        fans = self._get_fan_nodes()

        # Build column ids: scenario_name, then per fan: fan_<id>_base_cfm, fan_<id>_ov_cfm, etc.
        col_ids = ["scenario_name"]
        col_headings = {"scenario_name": "Scenario"}
        col_widths = {"scenario_name": 120}

        for fan in fans:
            p = fan.parameters
            base_cfm = p.airflow if isinstance(p, FanParameters) else 0
            base_sp = p.static_pressure if isinstance(p, FanParameters) else 0

            c_bcfm = f"f_{fan.id}_bcfm"
            c_ocfm = f"f_{fan.id}_ocfm"
            c_bsp = f"f_{fan.id}_bsp"
            c_osp = f"f_{fan.id}_osp"

            col_ids.extend([c_bcfm, c_ocfm, c_bsp, c_osp])
            short = fan.name[:12]
            col_headings[c_bcfm] = f"{short}\nBase CFM"
            col_headings[c_ocfm] = f"{short}\nOverride CFM"
            col_headings[c_bsp] = f"{short}\nBase SP"
            col_headings[c_osp] = f"{short}\nOverride SP"
            col_widths[c_bcfm] = 90
            col_widths[c_ocfm] = 100
            col_widths[c_bsp] = 80
            col_widths[c_osp] = 100

        if not col_ids:
            col_ids = ["scenario_name"]

        tree = ttk.Treeview(self._scen_tree_frame, columns=col_ids, show="headings",
                            height=5)
        for cid in col_ids:
            tree.heading(cid, text=col_headings.get(cid, cid))
            tree.column(cid, width=col_widths.get(cid, 80), minwidth=60)

        # Scrollbar
        hsb = ttk.Scrollbar(self._scen_tree_frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(xscrollcommand=hsb.set)
        tree.pack(fill=tk.BOTH, expand=True)
        hsb.pack(fill=tk.X)

        tree.bind("<Double-1>", self._scenario_double_click)
        self.scenario_tree = tree
        self._scen_col_ids = col_ids
        self._refresh_scenario_rows()

    def _refresh_scenario_rows(self):
        """Populate scenario tree rows from project data."""
        if self.scenario_tree is None:
            return
        self.scenario_tree.delete(*self.scenario_tree.get_children())
        fans = self._get_fan_nodes()

        for i, scen in enumerate(self.project.scenarios):
            vals = [scen.name]
            for fan in fans:
                p = fan.parameters
                base_cfm = p.airflow if isinstance(p, FanParameters) else 0
                base_sp = p.static_pressure if isinstance(p, FanParameters) else 0
                ov = scen.fan_overrides.get(fan.id, {})
                ov_cfm = ov.get("airflow", "")
                ov_sp = ov.get("static_pressure", "")
                vals.extend([
                    f"{base_cfm:.0f}",
                    str(ov_cfm) if ov_cfm != "" else "",
                    f"{base_sp:.2f}",
                    str(ov_sp) if ov_sp != "" else "",
                ])
            self.scenario_tree.insert("", "end", iid=str(i), values=vals)

    def _scenario_double_click(self, event):
        """Handle double-click to inline-edit scenario cells."""
        if self.scenario_tree is None:
            return
        tree = self.scenario_tree
        region = tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = tree.identify_column(event.x)
        row = tree.identify_row(event.y)
        if not row:
            return

        col_idx = int(col.replace("#", "")) - 1  # 0-based index into _scen_col_ids
        if col_idx < 0 or col_idx >= len(self._scen_col_ids):
            return
        col_id = self._scen_col_ids[col_idx]

        # Allow editing: scenario name, or override columns (those containing '_ocfm' or '_osp')
        editable = (col_id == "scenario_name" or "_ocfm" in col_id or "_osp" in col_id)
        if not editable:
            return

        bbox = tree.bbox(row, col)
        if not bbox:
            return

        current_val = tree.set(row, col_id)
        entry = ttk.Entry(tree, width=10)
        entry.insert(0, current_val)
        entry.select_range(0, tk.END)
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        entry.focus_set()

        def _commit(e=None):
            new_val = entry.get()
            tree.set(row, col_id, new_val)
            entry.destroy()
            # Persist back to the scenario model
            self._persist_scenario_row(int(row))

        entry.bind("<Return>", _commit)
        entry.bind("<FocusOut>", _commit)
        entry.bind("<Escape>", lambda e: entry.destroy())

    def _persist_scenario_row(self, row_idx: int):
        """Write the tree row values back into the Scenario object."""
        if row_idx < 0 or row_idx >= len(self.project.scenarios):
            return
        scen = self.project.scenarios[row_idx]
        tree = self.scenario_tree
        row_id = str(row_idx)

        # Scenario name
        scen.name = tree.set(row_id, "scenario_name")

        fans = self._get_fan_nodes()
        scen.fan_overrides = {}
        for fan in fans:
            ov_cfm_col = f"f_{fan.id}_ocfm"
            ov_sp_col = f"f_{fan.id}_osp"
            ov_cfm_str = tree.set(row_id, ov_cfm_col).strip()
            ov_sp_str = tree.set(row_id, ov_sp_col).strip()
            overrides = {}
            if ov_cfm_str:
                try:
                    overrides["airflow"] = float(ov_cfm_str)
                except ValueError:
                    pass
            if ov_sp_str:
                try:
                    overrides["static_pressure"] = float(ov_sp_str)
                except ValueError:
                    pass
            if overrides:
                scen.fan_overrides[fan.id] = overrides

    # ------------------------------------------------------------------ #
    #  Properties panel                                                   #
    # ------------------------------------------------------------------ #
    def _build_properties_panel(self, parent):
        ttk.Label(parent, text="Properties", font=("Helvetica", 11, "bold")).pack(
            pady=(10, 5), padx=10, anchor="w"
        )
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5)

        self.props_container = ttk.Frame(parent)
        self.props_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self._props_vars: dict[str, tk.StringVar] = {}
        self._show_no_selection()

    def _clear_props(self):
        for w in self.props_container.winfo_children():
            w.destroy()
        self._props_vars.clear()

    def _show_no_selection(self):
        self._clear_props()
        ttk.Label(self.props_container, text="Select a node or connector\nto view properties.",
                  foreground="gray").pack(pady=20)

    def _show_node_props(self, node: Node):
        self._clear_props()
        ttk.Label(self.props_container, text=f"Type: {node.node_type.value}",
                  font=("Helvetica", 10, "bold")).pack(anchor="w", pady=(0, 8))

        # Name
        self._add_prop_field("Name", "name", node.name)

        # Type-specific parameters
        params = node.parameters
        for f in dataclass_fields(type(params)):
            val = getattr(params, f.name)
            label = f.name.replace("_", " ").title()
            self._add_prop_field(label, f"param_{f.name}", str(val))

        ttk.Button(self.props_container, text="Apply", command=lambda: self._apply_node_props(node)).pack(
            pady=10, anchor="e"
        )

    def _show_connector_props(self, conn: Connector):
        self._clear_props()
        ttk.Label(self.props_container, text="Duct Connector",
                  font=("Helvetica", 10, "bold")).pack(anchor="w", pady=(0, 8))

        src = self.project.nodes.get(conn.source_id)
        tgt = self.project.nodes.get(conn.target_id)
        ttk.Label(self.props_container,
                  text=f"From: {src.name if src else '?'}\nTo: {tgt.name if tgt else '?'}").pack(
            anchor="w", pady=(0, 8))

        self._add_prop_field("Label", "label", conn.label)
        self._add_prop_field("Length (ft)", "length", str(conn.length))
        self._add_prop_field("Diameter (in)", "diameter", str(conn.diameter))
        self._add_prop_field("Friction Rate (in/100ft)", "friction_rate", str(conn.friction_rate))

        ttk.Button(self.props_container, text="Apply", command=lambda: self._apply_connector_props(conn)).pack(
            pady=10, anchor="e"
        )

    def _add_prop_field(self, label: str, key: str, value: str):
        frame = ttk.Frame(self.props_container)
        frame.pack(fill=tk.X, pady=2)
        ttk.Label(frame, text=label, width=20, anchor="w").pack(side=tk.LEFT)
        var = tk.StringVar(value=value)
        self._props_vars[key] = var
        entry = ttk.Entry(frame, textvariable=var, width=15)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _apply_node_props(self, node: Node):
        name_var = self._props_vars.get("name")
        if name_var:
            node.name = name_var.get()

        params = node.parameters
        for f in dataclass_fields(type(params)):
            var = self._props_vars.get(f"param_{f.name}")
            if var is None:
                continue
            try:
                if f.type == "float" or f.type is float:
                    setattr(params, f.name, float(var.get()))
                else:
                    setattr(params, f.name, var.get())
            except ValueError:
                pass

        self._redraw()
        # Rebuild scenario table if a fan's base values changed
        if node.node_type == NodeType.FAN:
            self._build_scenario_tree()

    def _apply_connector_props(self, conn: Connector):
        for attr in ("label", "length", "diameter", "friction_rate"):
            var = self._props_vars.get(attr)
            if var is None:
                continue
            try:
                if attr == "label":
                    setattr(conn, attr, var.get())
                else:
                    setattr(conn, attr, float(var.get()))
            except ValueError:
                pass
        self._redraw()

    # ------------------------------------------------------------------ #
    #  Keyboard shortcuts                                                 #
    # ------------------------------------------------------------------ #
    def _bind_shortcuts(self):
        self.root.bind("<Control-n>", lambda e: self._new_project())
        self.root.bind("<Control-o>", lambda e: self._open_project())
        self.root.bind("<Control-s>", lambda e: self._save_project())
        self.root.bind("<F5>", lambda e: self._run_analysis())
        self.root.bind("<Delete>", lambda e: self._delete_selected())
        self.root.bind("<Escape>", lambda e: self._cancel_all())

    # ------------------------------------------------------------------ #
    #  File operations                                                    #
    # ------------------------------------------------------------------ #
    def _new_project(self):
        self.project = Project()
        self.selected_node_id = None
        self.selected_connector_id = None
        self._last_results = []
        self._enter_select_mode()
        self._redraw()
        self._build_scenario_tree()
        self._show_no_selection()
        self._clear_results()

    def _open_project(self):
        path = filedialog.askopenfilename(
            title="Open Project",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.project = load_project(path)
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to load project:\n{exc}")
            return
        self.selected_node_id = None
        self.selected_connector_id = None
        self._enter_select_mode()
        self._redraw()
        self._build_scenario_tree()
        self._show_no_selection()

    def _save_project(self):
        path = filedialog.asksaveasfilename(
            title="Save Project",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            save_project(self.project, path)
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to save project:\n{exc}")

    # ------------------------------------------------------------------ #
    #  Canvas drawing                                                     #
    # ------------------------------------------------------------------ #
    def _redraw(self):
        self.canvas.delete("all")
        # Connectors first (behind nodes)
        for conn in self.project.connectors.values():
            self._draw_connector(conn)
        # Nodes
        for node in self.project.nodes.values():
            self._draw_node(node)
        # Status bar text
        self._update_status()

    def _update_status(self):
        if self._mode == MODE_PLACE and self._place_node_type:
            self._status_var.set(f"Mode: Place {self._place_node_type.value}  --  Click canvas to place, Esc to cancel")
        elif self._mode == MODE_CONNECT:
            if self._connect_source_id:
                src = self.project.nodes.get(self._connect_source_id)
                name = src.name if src else "?"
                self._status_var.set(f"Mode: Connect  --  Source: {name}  --  Click a target node (Esc to cancel)")
            else:
                self._status_var.set("Mode: Connect  --  Click a source node (Esc to cancel)")
        else:
            self._status_var.set("Mode: Select / Move")

    def _draw_node(self, node: Node):
        x, y = node.x, node.y
        hw, hh = NODE_WIDTH / 2, NODE_HEIGHT / 2
        color = NODE_COLORS.get(node.node_type, "#888888")
        is_selected = node.id == self.selected_node_id

        outline_color = "#FFD700" if is_selected else "#333333"
        outline_width = 3 if is_selected else 1

        tag = f"node_{node.id}"
        body_tag = f"body_{node.id}"

        # Shape varies by type
        if node.node_type == NodeType.FAN:
            self._draw_rounded_rect(x - hw, y - hh, x + hw, y + hh, 12,
                                     fill=color, outline=outline_color, width=outline_width,
                                     tags=(tag, body_tag))
        elif node.node_type == NodeType.DUCT_SPLIT:
            pts = [x, y - hh, x + hw, y, x, y + hh, x - hw, y]
            self.canvas.create_polygon(pts, fill=color, outline=outline_color,
                                        width=outline_width, tags=(tag, body_tag))
        elif node.node_type == NodeType.PRESSURE_OUTPUT:
            r = min(hw, hh)
            self.canvas.create_oval(x - r, y - r, x + r, y + r,
                                     fill=color, outline=outline_color, width=outline_width,
                                     tags=(tag, body_tag))
        else:
            self.canvas.create_rectangle(x - hw, y - hh, x + hw, y + hh,
                                          fill=color, outline=outline_color, width=outline_width,
                                          tags=(tag, body_tag))

        # Label
        display_name = node.name
        if len(display_name) > 16:
            display_name = display_name[:14] + ".."
        self.canvas.create_text(x, y - 6, text=display_name, fill="white",
                                 font=("Helvetica", 9, "bold"), tags=(tag,))

        subtitle = self._node_subtitle(node)
        if subtitle:
            self.canvas.create_text(x, y + 10, text=subtitle, fill="#FFFFFFCC",
                                     font=("Helvetica", 8), tags=(tag,))

        # Pressure result annotation
        if self._last_results:
            result = self._last_results[0]
            sp = result.pressures.get(node.id)
            if sp is not None and node.node_type == NodeType.PRESSURE_OUTPUT:
                self.canvas.create_text(x, y + hh + 14, text=f"{sp:+.3f} in.wg",
                                         fill="#CC0000", font=("Helvetica", 9, "bold"), tags=(tag,))

        # --- Connection ports --- #
        # Input port (left side) - except fans which are sources
        if node.node_type != NodeType.FAN:
            in_tag = f"inport_{node.id}"
            px, py = x - hw - PORT_RADIUS, y
            self.canvas.create_oval(px - PORT_RADIUS, py - PORT_RADIUS,
                                     px + PORT_RADIUS, py + PORT_RADIUS,
                                     fill="#44AA44", outline="#228822", width=1,
                                     tags=(tag, in_tag))
            self.canvas.create_text(px, py, text="IN", fill="white",
                                     font=("Helvetica", 5), tags=(tag, in_tag))

        # Output port (right side) - except pressure output which is a sink
        if node.node_type != NodeType.PRESSURE_OUTPUT:
            out_tag = f"outport_{node.id}"
            px, py = x + hw + PORT_RADIUS, y
            self.canvas.create_oval(px - PORT_RADIUS, py - PORT_RADIUS,
                                     px + PORT_RADIUS, py + PORT_RADIUS,
                                     fill="#DD6644", outline="#AA4422", width=1,
                                     tags=(tag, out_tag))
            self.canvas.create_text(px, py, text="OUT", fill="white",
                                     font=("Helvetica", 5), tags=(tag, out_tag))

        # Bind events on the whole node group
        self.canvas.tag_bind(tag, "<ButtonPress-1>", lambda e, nid=node.id: self._node_press(e, nid))
        self.canvas.tag_bind(tag, "<B1-Motion>", self._node_drag)
        self.canvas.tag_bind(tag, "<ButtonRelease-1>", self._node_release)
        self.canvas.tag_bind(tag, "<Button-3>", lambda e, nid=node.id: self._node_right_click(e, nid))

    def _draw_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        tags = kwargs.pop("tags", "")
        points = [
            x1 + r, y1, x2 - r, y1,
            x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r,
            x1, y1 + r, x1, y1,
        ]
        self.canvas.create_polygon(points, smooth=True, tags=tags, **kwargs)

    def _node_subtitle(self, node: Node) -> str:
        p = node.parameters
        if isinstance(p, FanParameters):
            return f"{p.airflow:.0f} CFM | {p.static_pressure:.2f} in.wg"
        if isinstance(p, DamperParameters):
            return f"dP {p.pressure_drop:.2f} in.wg"
        if isinstance(p, MixingPlenumParameters):
            return f"dP {p.pressure_drop:.2f} in.wg"
        if isinstance(p, DuctSplitParameters):
            return f"dP {p.pressure_drop:.2f} in.wg"
        if isinstance(p, PressureOutputParameters):
            return p.label
        return ""

    def _draw_connector(self, conn: Connector):
        src = self.project.nodes.get(conn.source_id)
        tgt = self.project.nodes.get(conn.target_id)
        if not src or not tgt:
            return

        is_selected = conn.id == self.selected_connector_id
        color = "#FFD700" if is_selected else CONNECTOR_COLOR
        width = 3 if is_selected else 2

        tag = f"conn_{conn.id}"

        # Line from source output port to target input port
        hw = NODE_WIDTH / 2
        sx = src.x + hw + PORT_RADIUS
        sy = src.y
        tx = tgt.x - hw - PORT_RADIUS
        ty = tgt.y

        self.canvas.create_line(
            sx, sy, tx, ty,
            fill=color, width=width, arrow=tk.LAST, arrowshape=(12, 14, 5),
            tags=(tag,),
        )

        mx = (sx + tx) / 2
        my = (sy + ty) / 2
        label = conn.label or f"{conn.length:.0f}ft"
        if conn.length > 0:
            self.canvas.create_text(mx, my - 10, text=label, fill="#333",
                                     font=("Helvetica", 8), tags=(tag,))
            dp = conn.pressure_drop
            self.canvas.create_text(mx, my + 4, text=f"dP {dp:.3f} in.wg",
                                     fill="#666", font=("Helvetica", 7), tags=(tag,))

        self.canvas.tag_bind(tag, "<Button-1>", lambda e, cid=conn.id: self._connector_click(e, cid))

    # ------------------------------------------------------------------ #
    #  Canvas interactions                                                #
    # ------------------------------------------------------------------ #
    def _canvas_click(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        if self._mode == MODE_PLACE and self._place_node_type:
            # Place a new node at the click location
            node = Node(node_type=self._place_node_type, x=cx, y=cy)
            self.project.add_node(node)
            self._redraw()
            self._select_node(node.id)
            # Rebuild scenario tree if a fan was placed
            if node.node_type == NodeType.FAN:
                self._build_scenario_tree()
            return

        if self._mode == MODE_CONNECT:
            # Clicking empty canvas during connect mode: cancel if source selected
            if self._connect_source_id:
                self._cancel_connect()
                self._mode = MODE_CONNECT  # stay in connect mode
                self._update_status()
                self._redraw()
            return

        # Select mode: clicked empty canvas -> deselect
        self.selected_node_id = None
        self.selected_connector_id = None
        self._show_no_selection()
        self._redraw()

    def _canvas_right_click(self, event):
        if self._mode != MODE_SELECT:
            self._cancel_all()
            self._enter_select_mode()

    def _canvas_motion(self, event):
        """Draw a rubber-band line when connecting."""
        if self._mode == MODE_CONNECT and self._connect_source_id:
            src = self.project.nodes.get(self._connect_source_id)
            if not src:
                return
            if self._connect_temp_line:
                self.canvas.delete(self._connect_temp_line)
            hw = NODE_WIDTH / 2
            sx = src.x + hw + PORT_RADIUS
            sy = src.y
            self._connect_temp_line = self.canvas.create_line(
                sx, sy,
                self.canvas.canvasx(event.x), self.canvas.canvasy(event.y),
                fill="#999", dash=(4, 4), width=2, arrow=tk.LAST,
            )

    # ------------------------------------------------------------------ #
    #  Node interactions                                                  #
    # ------------------------------------------------------------------ #
    def _node_press(self, event, node_id: str):
        if self._mode == MODE_CONNECT:
            self._handle_connect_click(node_id)
            return

        if self._mode == MODE_PLACE:
            # Ignore node clicks while in place mode (canvas_click handles placement)
            return

        # Select mode: select and prepare for drag
        self._select_node(node_id)
        node = self.project.nodes.get(node_id)
        if node:
            self._drag_data["node_id"] = node_id
            self._drag_data["offset_x"] = node.x - self.canvas.canvasx(event.x)
            self._drag_data["offset_y"] = node.y - self.canvas.canvasy(event.y)

    def _node_drag(self, event):
        if self._mode != MODE_SELECT:
            return
        nid = self._drag_data["node_id"]
        if not nid:
            return
        node = self.project.nodes.get(nid)
        if not node:
            return
        node.x = self.canvas.canvasx(event.x) + self._drag_data["offset_x"]
        node.y = self.canvas.canvasy(event.y) + self._drag_data["offset_y"]
        self._redraw()

    def _node_release(self, event):
        self._drag_data["node_id"] = None

    def _node_right_click(self, event, node_id: str):
        menu = tk.Menu(self.canvas, tearoff=0)
        menu.add_command(label="Connect from here...",
                         command=lambda: self._start_connect_from(node_id))
        menu.add_separator()
        menu.add_command(label="Delete", command=lambda: self._delete_node(node_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _select_node(self, node_id: str):
        self.selected_node_id = node_id
        self.selected_connector_id = None
        node = self.project.nodes.get(node_id)
        if node:
            self._show_node_props(node)
        self._redraw()

    def _connector_click(self, event, conn_id: str):
        if self._mode != MODE_SELECT:
            return
        self.selected_connector_id = conn_id
        self.selected_node_id = None
        conn = self.project.connectors.get(conn_id)
        if conn:
            self._show_connector_props(conn)
        self._redraw()

    # ------------------------------------------------------------------ #
    #  Connect mode logic                                                 #
    # ------------------------------------------------------------------ #
    def _handle_connect_click(self, node_id: str):
        """Handle clicking a node while in connect mode."""
        if self._connect_source_id is None:
            # First click: select source
            self._connect_source_id = node_id
            self._update_status()
            self._redraw()
        else:
            # Second click: create connection
            if node_id != self._connect_source_id:
                conn = Connector(source_id=self._connect_source_id, target_id=node_id)
                self.project.add_connector(conn)
            self._cancel_connect()
            self._mode = MODE_CONNECT  # stay in connect mode for chaining
            self._update_status()
            self._redraw()

    def _start_connect_from(self, node_id: str):
        """Enter connect mode with a specific source (from right-click menu)."""
        self._mode = MODE_CONNECT
        self._connect_source_id = node_id
        self._place_node_type = None
        self.canvas.config(cursor="crosshair")
        self._update_toolbox_highlights()
        self._update_status()
        self._redraw()

    def _cancel_connect(self):
        """Clear connect state but don't change mode."""
        self._connect_source_id = None
        if self._connect_temp_line:
            self.canvas.delete(self._connect_temp_line)
            self._connect_temp_line = None

    def _cancel_all(self):
        """Cancel any in-progress action and return to select mode."""
        self._cancel_connect()
        self._enter_select_mode()
        self._redraw()

    # ------------------------------------------------------------------ #
    #  Delete                                                             #
    # ------------------------------------------------------------------ #
    def _delete_selected(self):
        if self.selected_node_id:
            self._delete_node(self.selected_node_id)
        elif self.selected_connector_id:
            self.project.remove_connector(self.selected_connector_id)
            self.selected_connector_id = None
            self._show_no_selection()
            self._redraw()

    def _delete_node(self, node_id: str):
        was_fan = False
        node = self.project.nodes.get(node_id)
        if node and node.node_type == NodeType.FAN:
            was_fan = True
        self.project.remove_node(node_id)
        if self.selected_node_id == node_id:
            self.selected_node_id = None
            self._show_no_selection()
        self._redraw()
        if was_fan:
            self._build_scenario_tree()

    # ------------------------------------------------------------------ #
    #  Scenarios                                                          #
    # ------------------------------------------------------------------ #
    def _add_scenario(self):
        name = f"Scenario {len(self.project.scenarios) + 1}"
        self.project.scenarios.append(Scenario(name=name))
        self._refresh_scenario_rows()

    def _remove_scenario(self):
        if self.scenario_tree is None:
            return
        sel = self.scenario_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.project.scenarios):
            self.project.scenarios.pop(idx)
        self._refresh_scenario_rows()

    # ------------------------------------------------------------------ #
    #  Analysis                                                           #
    # ------------------------------------------------------------------ #
    def _run_analysis(self):
        if not self.project.scenarios:
            result = run_analysis(self.project)
            self._last_results = [result]
        else:
            sel = self.scenario_tree.selection() if self.scenario_tree else ()
            if sel:
                idx = int(sel[0])
                scenario = self.project.scenarios[idx]
                result = run_analysis(self.project, scenario)
                self._last_results = [result]
            else:
                result = run_analysis(self.project)
                self._last_results = [result]
        self._show_results(self._last_results)
        self._redraw()

    def _run_all_scenarios(self):
        self._last_results = run_all_scenarios(self.project)
        self._show_results(self._last_results)
        self._redraw()

    def _show_results(self, results: list[AnalysisResult]):
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete("1.0", tk.END)

        for res in results:
            self.result_text.insert(tk.END, f"{'='*60}\n")
            self.result_text.insert(tk.END, f" Scenario: {res.scenario_name or 'Baseline'}\n")
            self.result_text.insert(tk.END, f"{'='*60}\n")

            if res.warnings:
                for w in res.warnings:
                    self.result_text.insert(tk.END, f"  WARNING: {w}\n")

            self.result_text.insert(tk.END,
                f"  {'Node':<25} {'Type':<18} {'SP (in.wg)':>12} {'Airflow (CFM)':>14}\n")
            self.result_text.insert(tk.END,
                f"  {'-'*25} {'-'*18} {'-'*12} {'-'*14}\n")

            for nid, sp in res.pressures.items():
                node = self.project.nodes.get(nid)
                if not node:
                    continue
                af = res.airflows.get(nid, 0)
                self.result_text.insert(tk.END,
                    f"  {node.name:<25} {node.node_type.value:<18} {sp:>+12.3f} {af:>14.0f}\n")

            self.result_text.insert(tk.END, "\n")

        self.result_text.config(state=tk.DISABLED)

    def _clear_results(self):
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete("1.0", tk.END)
        self.result_text.config(state=tk.DISABLED)


# --------------------------------------------------------------------------- #
#  Entry point helper                                                         #
# --------------------------------------------------------------------------- #
def run_app():
    root = tk.Tk()
    StaticPressureApp(root)
    root.mainloop()
