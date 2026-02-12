"""GUI for the Static Pressure Analysis tool using tkinter.

Architecture modelled after HVAC-Flow-Analysis:
  - Toolbox panel (left):  click-to-select, click-canvas-to-place
  - Canvas (centre):       nodes with visible inlet/outlet ports,
                           bezier-style connectors, drag-to-move
  - Property panel (right): dynamic form for selected node / connector
  - Scenario table (bottom): inline-editable overrides per fan
"""

import math
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

# ------------------------------------------------------------------ #
#  Visual constants                                                    #
# ------------------------------------------------------------------ #
NODE_COLORS = {
    NodeType.FAN:              "#4A90D9",
    NodeType.DAMPER:           "#E8943A",
    NodeType.MIXING_PLENUM:    "#6BBF6B",
    NodeType.DUCT_SPLIT:       "#C47DD8",
    NodeType.PRESSURE_OUTPUT:  "#E05555",
}
NODE_BG = {
    NodeType.FAN:              "#dce9f7",
    NodeType.DAMPER:           "#fdebd0",
    NodeType.MIXING_PLENUM:    "#d5f5d5",
    NodeType.DUCT_SPLIT:       "#eeddf5",
    NodeType.PRESSURE_OUTPUT:  "#fbd5d5",
}

NODE_W = 160
NODE_H = 54
PORT_R = 6
CANVAS_BG = "#F5F5F0"

# Interaction modes
_SELECT = "select"
_PLACE  = "place"
_CONNECT_SRC = "connect_src"   # waiting for source click
_CONNECT_TGT = "connect_tgt"   # waiting for target click


# ------------------------------------------------------------------ #
#  Main application                                                    #
# ------------------------------------------------------------------ #
class StaticPressureApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Static Pressure Analysis")
        self.root.geometry("1400x850")
        self.root.minsize(1000, 600)

        self.project = Project()
        self.selected_node_id: str | None = None
        self.selected_conn_id: str | None = None

        # Mode state
        self._mode = _SELECT
        self._place_type: NodeType | None = None
        self._conn_src_id: str | None = None
        self._conn_line: int | None = None   # canvas id of rubber-band line

        # Node drag state
        self._drag = {"id": None, "ox": 0, "oy": 0}

        self._results: list[AnalysisResult] = []

        # Toolbox button widgets (for highlight toggling)
        self._tb_btns: dict[NodeType, tk.Label] = {}

        self._build_menu()
        self._build_layout()
        self._bind_keys()

    # ============================================================== #
    #  MENU                                                            #
    # ============================================================== #
    def _build_menu(self):
        mb = tk.Menu(self.root)
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="New Project",  command=self._new_project,  accelerator="Ctrl+N")
        fm.add_command(label="Open...",      command=self._open_project, accelerator="Ctrl+O")
        fm.add_command(label="Save...",      command=self._save_project, accelerator="Ctrl+S")
        fm.add_separator()
        fm.add_command(label="Exit", command=self.root.quit)
        mb.add_cascade(label="File", menu=fm)

        am = tk.Menu(mb, tearoff=0)
        am.add_command(label="Run Analysis",       command=self._run_analysis, accelerator="F5")
        am.add_command(label="Run All Scenarios",  command=self._run_all)
        mb.add_cascade(label="Analysis", menu=am)

        em = tk.Menu(mb, tearoff=0)
        em.add_command(label="Delete Selected", command=self._delete_selected, accelerator="Delete")
        mb.add_cascade(label="Edit", menu=em)

        self.root.config(menu=mb)

    def _bind_keys(self):
        self.root.bind("<Control-n>", lambda e: self._new_project())
        self.root.bind("<Control-o>", lambda e: self._open_project())
        self.root.bind("<Control-s>", lambda e: self._save_project())
        self.root.bind("<F5>",        lambda e: self._run_analysis())
        self.root.bind("<Delete>",    lambda e: self._delete_selected())
        self.root.bind("<Escape>",    lambda e: self._reset_mode())

    # ============================================================== #
    #  LAYOUT                                                          #
    # ============================================================== #
    def _build_layout(self):
        pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        # Left: toolbox
        left = ttk.Frame(pw, width=200)
        pw.add(left, weight=0)
        self._build_toolbox(left)

        # Centre: canvas + scenario
        centre = ttk.Frame(pw)
        pw.add(centre, weight=1)
        self._build_centre(centre)

        # Right: properties
        right = ttk.Frame(pw, width=280)
        pw.add(right, weight=0)
        self._build_props(right)

    # ============================================================== #
    #  TOOLBOX                                                         #
    # ============================================================== #
    def _build_toolbox(self, parent):
        ttk.Label(parent, text="Equipment Toolbox",
                  font=("Segoe UI", 11, "bold")).pack(pady=(10, 5), padx=10, anchor="w")
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5)

        self._tb_hint = ttk.Label(parent,
            text="Click an item, then click\nthe canvas to place it.",
            foreground="gray", wraplength=170)
        self._tb_hint.pack(pady=(4, 8), padx=10, anchor="w")

        for nt in NodeType:
            btn = tk.Label(parent, text=f"  {nt.value}  ",
                           bg=NODE_COLORS[nt], fg="white",
                           font=("Segoe UI", 10, "bold"),
                           relief="raised", padx=8, pady=6, cursor="hand2")
            btn.pack(pady=4, padx=15, fill=tk.X)
            btn.bind("<Button-1>", lambda e, t=nt: self._tool_select(t))
            self._tb_btns[nt] = btn

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=(12, 4))

        # Connect button
        self._conn_btn = tk.Button(parent, text="Connect Nodes",
            bg="#555555", fg="white", font=("Segoe UI", 10, "bold"),
            relief="raised", padx=8, pady=6, cursor="hand2",
            command=self._tool_connect)
        self._conn_btn.pack(pady=4, padx=15, fill=tk.X)

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5, pady=(12, 4))

        self._sel_btn = tk.Button(parent, text="Select / Move",
            bg="#336699", fg="white", font=("Segoe UI", 10, "bold"),
            relief="sunken", padx=8, pady=6, cursor="hand2",
            command=self._reset_mode)
        self._sel_btn.pack(pady=4, padx=15, fill=tk.X)

    # -- Toolbox actions ---------------------------------------------------

    def _tool_select(self, nt: NodeType):
        self._cancel_connect()
        self._mode = _PLACE
        self._place_type = nt
        self.canvas.config(cursor="crosshair")
        self._highlight_tools()
        self._tb_hint.config(text=f"Click on the canvas to\nplace a {nt.value}.\nPress Esc to cancel.")
        self._update_status()

    def _tool_connect(self):
        self._cancel_connect()
        self._mode = _CONNECT_SRC
        self._place_type = None
        self.canvas.config(cursor="crosshair")
        self._highlight_tools()
        self._tb_hint.config(text="Click a source node's\nOUT port, then click\na target node's IN port.\nPress Esc to cancel.")
        self._update_status()

    def _reset_mode(self):
        self._cancel_connect()
        self._mode = _SELECT
        self._place_type = None
        self.canvas.config(cursor="")
        self._highlight_tools()
        self._tb_hint.config(text="Click an item, then click\nthe canvas to place it.")
        self._update_status()
        self._redraw()

    def _highlight_tools(self):
        for nt, btn in self._tb_btns.items():
            if self._mode == _PLACE and self._place_type == nt:
                btn.config(relief="sunken", bd=3)
            else:
                btn.config(relief="raised", bd=2)
        self._conn_btn.config(relief="sunken" if self._mode in (_CONNECT_SRC, _CONNECT_TGT) else "raised")
        self._sel_btn.config(relief="sunken" if self._mode == _SELECT else "raised")

    # ============================================================== #
    #  CENTRE PANEL (canvas + scenarios)                               #
    # ============================================================== #
    def _build_centre(self, parent):
        vpw = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        vpw.pack(fill=tk.BOTH, expand=True)

        # Canvas frame
        cf = ttk.Frame(vpw)
        vpw.add(cf, weight=3)

        self._status_var = tk.StringVar(value="Mode: Select / Move")
        ttk.Label(cf, textvariable=self._status_var, relief="sunken",
                  anchor="w", padding=(6, 2)).pack(fill=tk.X)

        self.canvas = tk.Canvas(cf, bg=CANVAS_BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>",  self._canvas_click)
        self.canvas.bind("<Button-3>",  self._canvas_rclick)
        self.canvas.bind("<Motion>",    self._canvas_motion)

        # Bottom: scenarios / results
        bf = ttk.Frame(vpw)
        vpw.add(bf, weight=1)
        self._build_scenario_panel(bf)

    def _update_status(self):
        if self._mode == _PLACE and self._place_type:
            self._status_var.set(f"Mode: Place {self._place_type.value}  —  Click canvas to place, Esc to cancel")
        elif self._mode == _CONNECT_SRC:
            self._status_var.set("Mode: Connect  —  Click a source node's OUT port  (Esc to cancel)")
        elif self._mode == _CONNECT_TGT:
            src = self.project.nodes.get(self._conn_src_id)
            name = src.name if src else "?"
            self._status_var.set(f"Mode: Connect  —  Source: {name}  —  Click a target node's IN port  (Esc to cancel)")
        else:
            self._status_var.set("Mode: Select / Move")

    # ============================================================== #
    #  SCENARIO PANEL                                                  #
    # ============================================================== #
    def _build_scenario_panel(self, parent):
        nb = ttk.Notebook(parent)
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Tab 1: Scenarios
        sf = ttk.Frame(nb); nb.add(sf, text="Scenarios")
        tb = ttk.Frame(sf); tb.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(tb, text="Add Scenario",   command=self._add_scenario).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="Remove Selected", command=self._remove_scenario).pack(side=tk.LEFT, padx=2)
        ttk.Label(tb, text="  Double-click Override CFM / Override SP cells to edit",
                  foreground="gray").pack(side=tk.LEFT, padx=8)
        self._scen_frame = ttk.Frame(sf)
        self._scen_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        self.scen_tree: ttk.Treeview | None = None
        self._scen_cols: list[str] = []
        self._rebuild_scen_tree()

        # Tab 2: Results
        rf = ttk.Frame(nb); nb.add(rf, text="Results")
        self.result_text = tk.Text(rf, height=8, state=tk.DISABLED, font=("Courier", 10))
        self.result_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def _fan_nodes(self) -> list[Node]:
        return [n for n in self.project.nodes.values() if n.node_type == NodeType.FAN]

    def _rebuild_scen_tree(self):
        for w in self._scen_frame.winfo_children():
            w.destroy()

        fans = self._fan_nodes()
        cols = ["scenario_name"]
        heads = {"scenario_name": "Scenario"}
        widths = {"scenario_name": 120}

        for fan in fans:
            p = fan.parameters
            short = fan.name[:12]
            for suffix, hdr, w in [
                ("_bcfm", f"{short} Base CFM",     90),
                ("_ocfm", f"{short} Override CFM", 100),
                ("_bsp",  f"{short} Base SP",       80),
                ("_osp",  f"{short} Override SP",  100),
            ]:
                cid = f"f{fan.id}{suffix}"
                cols.append(cid)
                heads[cid] = hdr
                widths[cid] = w

        tree = ttk.Treeview(self._scen_frame, columns=cols, show="headings", height=5)
        for c in cols:
            tree.heading(c, text=heads.get(c, c))
            tree.column(c, width=widths.get(c, 80), minwidth=60)

        hsb = ttk.Scrollbar(self._scen_frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(xscrollcommand=hsb.set)
        tree.pack(fill=tk.BOTH, expand=True)
        hsb.pack(fill=tk.X)
        tree.bind("<Double-1>", self._scen_dblclick)

        self.scen_tree = tree
        self._scen_cols = cols
        self._refresh_scen_rows()

    def _refresh_scen_rows(self):
        if not self.scen_tree:
            return
        self.scen_tree.delete(*self.scen_tree.get_children())
        fans = self._fan_nodes()
        for i, scen in enumerate(self.project.scenarios):
            vals = [scen.name]
            for fan in fans:
                p = fan.parameters
                bcfm = p.airflow if isinstance(p, FanParameters) else 0
                bsp  = p.static_pressure if isinstance(p, FanParameters) else 0
                ov = scen.fan_overrides.get(fan.id, {})
                vals += [f"{bcfm:.0f}",
                         str(ov.get("airflow", "")),
                         f"{bsp:.2f}",
                         str(ov.get("static_pressure", ""))]
            self.scen_tree.insert("", "end", iid=str(i), values=vals)

    def _scen_dblclick(self, event):
        tree = self.scen_tree
        if not tree:
            return
        if tree.identify("region", event.x, event.y) != "cell":
            return
        col = tree.identify_column(event.x)
        row = tree.identify_row(event.y)
        if not row:
            return
        ci = int(col.replace("#", "")) - 1
        if ci < 0 or ci >= len(self._scen_cols):
            return
        cid = self._scen_cols[ci]
        # Editable: scenario name, override columns (_ocfm, _osp)
        if cid != "scenario_name" and "_ocfm" not in cid and "_osp" not in cid:
            return
        bbox = tree.bbox(row, col)
        if not bbox:
            return
        cur = tree.set(row, cid)
        entry = ttk.Entry(tree, width=10)
        entry.insert(0, cur)
        entry.select_range(0, tk.END)
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        entry.focus_set()
        def commit(e=None):
            tree.set(row, cid, entry.get())
            entry.destroy()
            self._persist_scen_row(int(row))
        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", lambda e: entry.destroy())

    def _persist_scen_row(self, idx):
        if idx < 0 or idx >= len(self.project.scenarios):
            return
        scen = self.project.scenarios[idx]
        scen.name = self.scen_tree.set(str(idx), "scenario_name")
        fans = self._fan_nodes()
        scen.fan_overrides = {}
        for fan in fans:
            ov_cfm = self.scen_tree.set(str(idx), f"f{fan.id}_ocfm").strip()
            ov_sp  = self.scen_tree.set(str(idx), f"f{fan.id}_osp").strip()
            ov = {}
            if ov_cfm:
                try: ov["airflow"] = float(ov_cfm)
                except ValueError: pass
            if ov_sp:
                try: ov["static_pressure"] = float(ov_sp)
                except ValueError: pass
            if ov:
                scen.fan_overrides[fan.id] = ov

    def _add_scenario(self):
        self.project.scenarios.append(Scenario(name=f"Scenario {len(self.project.scenarios)+1}"))
        self._refresh_scen_rows()

    def _remove_scenario(self):
        if not self.scen_tree:
            return
        sel = self.scen_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.project.scenarios):
            self.project.scenarios.pop(idx)
        self._refresh_scen_rows()

    # ============================================================== #
    #  PROPERTIES PANEL                                                #
    # ============================================================== #
    def _build_props(self, parent):
        ttk.Label(parent, text="Properties", font=("Segoe UI", 11, "bold")).pack(
            pady=(10, 5), padx=10, anchor="w")
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5)
        self._props = ttk.Frame(parent)
        self._props.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self._pvars: dict[str, tk.StringVar] = {}
        self._show_no_sel()

    def _clear_props(self):
        for w in self._props.winfo_children():
            w.destroy()
        self._pvars.clear()

    def _show_no_sel(self):
        self._clear_props()
        ttk.Label(self._props, text="Select a node or connector\nto view properties.",
                  foreground="gray").pack(pady=20)

    def _show_node_props(self, node: Node):
        self._clear_props()
        ttk.Label(self._props, text=f"Type: {node.node_type.value}",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 8))
        self._add_field("Name", "name", node.name)
        params = node.parameters
        for f in dataclass_fields(type(params)):
            v = getattr(params, f.name)
            self._add_field(f.name.replace("_", " ").title(), f"p_{f.name}", str(v))
        ttk.Button(self._props, text="Apply",
                   command=lambda: self._apply_node(node)).pack(pady=10, anchor="e")

    def _show_conn_props(self, conn: Connector):
        self._clear_props()
        ttk.Label(self._props, text="Duct Connector",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 8))
        src = self.project.nodes.get(conn.source_id)
        tgt = self.project.nodes.get(conn.target_id)
        ttk.Label(self._props,
            text=f"From: {src.name if src else '?'}\nTo: {tgt.name if tgt else '?'}").pack(
            anchor="w", pady=(0, 8))
        self._add_field("Label", "label", conn.label)
        self._add_field("Length (ft)", "length", str(conn.length))
        self._add_field("Diameter (in)", "diameter", str(conn.diameter))
        self._add_field("Friction Rate (in/100ft)", "friction_rate", str(conn.friction_rate))
        ttk.Label(self._props,
            text=f"Computed dP: {conn.pressure_drop:.4f} in.wg",
            font=("Consolas", 9)).pack(anchor="w", pady=(8, 0))
        ttk.Button(self._props, text="Apply",
                   command=lambda: self._apply_conn(conn)).pack(pady=10, anchor="e")

    def _add_field(self, label, key, value):
        f = ttk.Frame(self._props); f.pack(fill=tk.X, pady=2)
        ttk.Label(f, text=label, width=22, anchor="w").pack(side=tk.LEFT)
        var = tk.StringVar(value=value)
        self._pvars[key] = var
        ttk.Entry(f, textvariable=var, width=15).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _apply_node(self, node: Node):
        v = self._pvars.get("name")
        if v:
            node.name = v.get()
        params = node.parameters
        for f in dataclass_fields(type(params)):
            v = self._pvars.get(f"p_{f.name}")
            if v is None:
                continue
            try:
                if f.type == "float" or f.type is float:
                    setattr(params, f.name, float(v.get()))
                else:
                    setattr(params, f.name, v.get())
            except ValueError:
                pass
        self._redraw()
        if node.node_type == NodeType.FAN:
            self._rebuild_scen_tree()

    def _apply_conn(self, conn: Connector):
        for attr in ("label", "length", "diameter", "friction_rate"):
            v = self._pvars.get(attr)
            if v is None:
                continue
            try:
                if attr == "label":
                    setattr(conn, attr, v.get())
                else:
                    setattr(conn, attr, float(v.get()))
            except ValueError:
                pass
        self._redraw()
        # refresh the computed dP display
        self._show_conn_props(conn)

    # ============================================================== #
    #  FILE OPS                                                        #
    # ============================================================== #
    def _new_project(self):
        self.project = Project()
        self.selected_node_id = self.selected_conn_id = None
        self._results = []
        self._reset_mode()
        self._redraw()
        self._rebuild_scen_tree()
        self._show_no_sel()
        self._clear_results()

    def _open_project(self):
        path = filedialog.askopenfilename(title="Open Project",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.project = load_project(path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load project:\n{e}")
            return
        self.selected_node_id = self.selected_conn_id = None
        self._reset_mode()
        self._redraw()
        self._rebuild_scen_tree()
        self._show_no_sel()

    def _save_project(self):
        path = filedialog.asksaveasfilename(title="Save Project",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            save_project(self.project, path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save project:\n{e}")

    # ============================================================== #
    #  CANVAS DRAWING                                                  #
    # ============================================================== #
    def _redraw(self):
        self.canvas.delete("all")
        for conn in self.project.connectors.values():
            self._draw_connector(conn)
        for node in self.project.nodes.values():
            self._draw_node(node)

    # -- Nodes -------------------------------------------------------------

    def _draw_node(self, node: Node):
        x, y = node.x, node.y
        hw, hh = NODE_W / 2, NODE_H / 2
        accent = NODE_COLORS.get(node.node_type, "#888")
        bg = NODE_BG.get(node.node_type, "#f5f5f5")
        sel = node.id == self.selected_node_id
        tag = f"n_{node.id}"

        # Body
        oc = "#ff9800" if sel else accent
        ow = 3 if sel else 1.5
        self.canvas.create_rectangle(x - hw, y - hh, x + hw, y + hh,
            fill=bg, outline=oc, width=ow, tags=(tag, "node_body"))

        # Header bar
        hdr_h = 22
        self.canvas.create_rectangle(x - hw, y - hh, x + hw, y - hh + hdr_h,
            fill=accent, outline=accent, tags=(tag,))

        # Name text
        dname = node.name if len(node.name) <= 20 else node.name[:18] + ".."
        self.canvas.create_text(x, y - hh + hdr_h / 2, text=dname,
            fill="white", font=("Segoe UI", 9, "bold"), tags=(tag,))

        # Status text
        sub = self._subtitle(node)
        if sub:
            self.canvas.create_text(x, y + 4, text=sub,
                fill="#555", font=("Consolas", 7), tags=(tag,))

        # Analysis result
        if self._results:
            sp = self._results[0].pressures.get(node.id)
            if sp is not None and node.node_type == NodeType.PRESSURE_OUTPUT:
                self.canvas.create_text(x, y + hh + 12, text=f"{sp:+.3f} in.wg",
                    fill="#CC0000", font=("Segoe UI", 9, "bold"), tags=(tag,))

        # -- Ports --
        # Inlet (left) — all except Fan
        if node.node_type != NodeType.FAN:
            pid = f"inp_{node.id}"
            px, py = x - hw, y
            self.canvas.create_oval(px - PORT_R, py - PORT_R,
                px + PORT_R, py + PORT_R,
                fill="#50c878", outline="#228822", width=1.5,
                tags=(tag, pid, "port", "inlet_port"))
            self.canvas.create_text(px + PORT_R + 6, py, text="IN",
                fill="#228822", font=("Segoe UI", 6), anchor="w", tags=(tag,))

        # Outlet (right) — all except Pressure Output
        if node.node_type != NodeType.PRESSURE_OUTPUT:
            pod = f"outp_{node.id}"
            px, py = x + hw, y
            self.canvas.create_oval(px - PORT_R, py - PORT_R,
                px + PORT_R, py + PORT_R,
                fill="#4a90d9", outline="#2a60a9", width=1.5,
                tags=(tag, pod, "port", "outlet_port"))
            self.canvas.create_text(px - PORT_R - 6, py, text="OUT",
                fill="#2a60a9", font=("Segoe UI", 6), anchor="e", tags=(tag,))

        # Bind whole node group
        self.canvas.tag_bind(tag, "<ButtonPress-1>",   lambda e, nid=node.id: self._node_press(e, nid))
        self.canvas.tag_bind(tag, "<B1-Motion>",       self._node_drag)
        self.canvas.tag_bind(tag, "<ButtonRelease-1>", self._node_release)
        self.canvas.tag_bind(tag, "<Button-3>",        lambda e, nid=node.id: self._node_rclick(e, nid))

    def _subtitle(self, node: Node) -> str:
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

    # -- Connectors --------------------------------------------------------

    def _draw_connector(self, conn: Connector):
        src = self.project.nodes.get(conn.source_id)
        tgt = self.project.nodes.get(conn.target_id)
        if not src or not tgt:
            return
        sel = conn.id == self.selected_conn_id
        color = "#ff9800" if sel else "#4a90d9"
        w = 3 if sel else 2
        tag = f"c_{conn.id}"

        hw = NODE_W / 2
        x1, y1 = src.x + hw, src.y          # outlet port
        x2, y2 = tgt.x - hw, tgt.y          # inlet port

        # Smooth bezier-ish curve using canvas line with smooth=True
        dx = max(abs(x2 - x1) * 0.4, 40)
        pts = [x1, y1,
               x1 + dx, y1,
               x2 - dx, y2,
               x2, y2]
        self.canvas.create_line(*pts, fill=color, width=w,
            smooth=True, arrow=tk.LAST, arrowshape=(12, 14, 5), tags=(tag,))

        # Label at midpoint
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        lbl = conn.label or f"{conn.length:.0f}ft"
        if conn.length > 0:
            self.canvas.create_text(mx, my - 10, text=lbl,
                fill="#333", font=("Segoe UI", 8), tags=(tag,))
            self.canvas.create_text(mx, my + 4,
                text=f"dP {conn.pressure_drop:.3f} in.wg",
                fill="#666", font=("Segoe UI", 7), tags=(tag,))

        self.canvas.tag_bind(tag, "<Button-1>",
            lambda e, cid=conn.id: self._conn_click(cid))

    # ============================================================== #
    #  CANVAS INTERACTIONS                                             #
    # ============================================================== #

    def _canvas_click(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        # --- Place mode ---
        if self._mode == _PLACE and self._place_type:
            node = Node(node_type=self._place_type, x=cx, y=cy)
            self.project.add_node(node)
            self._redraw()
            self._select_node(node.id)
            if node.node_type == NodeType.FAN:
                self._rebuild_scen_tree()
            return

        # --- Connect: clicked empty canvas (not on a node) ---
        if self._mode == _CONNECT_SRC:
            # Clicked empty area, nothing to do — stay in connect mode
            return
        if self._mode == _CONNECT_TGT:
            # Clicked empty area — cancel source selection, stay in connect mode
            self._cancel_connect()
            self._mode = _CONNECT_SRC
            self._update_status()
            self._redraw()
            return

        # --- Select mode: clicked empty canvas → deselect ---
        self.selected_node_id = self.selected_conn_id = None
        self._show_no_sel()
        self._redraw()

    def _canvas_rclick(self, event):
        if self._mode != _SELECT:
            self._reset_mode()

    def _canvas_motion(self, event):
        if self._mode == _CONNECT_TGT and self._conn_src_id:
            src = self.project.nodes.get(self._conn_src_id)
            if not src:
                return
            if self._conn_line:
                self.canvas.delete(self._conn_line)
            hw = NODE_W / 2
            sx, sy = src.x + hw, src.y
            ex = self.canvas.canvasx(event.x)
            ey = self.canvas.canvasy(event.y)
            self._conn_line = self.canvas.create_line(
                sx, sy, ex, ey,
                fill="#999", dash=(4, 4), width=2, arrow=tk.LAST)

    def _nid_from_tags(self, tags) -> str | None:
        """Extract node id from canvas item tags like 'outp_abc1' or 'inp_abc1'."""
        for t in tags:
            if t.startswith("outp_") or t.startswith("inp_"):
                return t.split("_", 1)[1]
            if t.startswith("n_"):
                return t[2:]
        return None

    # -- Node interactions -------------------------------------------------

    def _node_press(self, event, nid):
        if self._mode == _PLACE:
            return

        # --- Connect: select source node ---
        if self._mode == _CONNECT_SRC:
            node = self.project.nodes.get(nid)
            if not node:
                return
            # Source must have an outlet (not a Pressure Output)
            if node.node_type == NodeType.PRESSURE_OUTPUT:
                return
            self._conn_src_id = nid
            self._mode = _CONNECT_TGT
            self._update_status()
            self._highlight_tools()
            return

        # --- Connect: select target node → create connector ---
        if self._mode == _CONNECT_TGT:
            node = self.project.nodes.get(nid)
            if not node:
                return
            # Target must have an inlet (not a Fan) and not be the source
            if node.node_type == NodeType.FAN or nid == self._conn_src_id:
                return
            conn = Connector(source_id=self._conn_src_id, target_id=nid)
            self.project.add_connector(conn)
            self._cancel_connect()
            self._mode = _CONNECT_SRC  # stay in connect mode for chaining
            self._update_status()
            self._redraw()
            return

        # --- Select mode: select node and prepare drag ---
        self._select_node(nid)
        node = self.project.nodes.get(nid)
        if node:
            self._drag["id"] = nid
            self._drag["ox"] = node.x - self.canvas.canvasx(event.x)
            self._drag["oy"] = node.y - self.canvas.canvasy(event.y)

    def _node_drag(self, event):
        if self._mode != _SELECT:
            return
        nid = self._drag["id"]
        if not nid:
            return
        node = self.project.nodes.get(nid)
        if not node:
            return
        node.x = self.canvas.canvasx(event.x) + self._drag["ox"]
        node.y = self.canvas.canvasy(event.y) + self._drag["oy"]
        self._redraw()

    def _node_release(self, event):
        self._drag["id"] = None

    def _node_rclick(self, event, nid):
        menu = tk.Menu(self.canvas, tearoff=0)
        menu.add_command(label="Connect from here…",
            command=lambda: self._start_connect_from(nid))
        menu.add_separator()
        menu.add_command(label="Delete", command=lambda: self._delete_node(nid))
        menu.tk_popup(event.x_root, event.y_root)

    def _select_node(self, nid):
        self.selected_node_id = nid
        self.selected_conn_id = None
        node = self.project.nodes.get(nid)
        if node:
            self._show_node_props(node)
        self._redraw()

    def _conn_click(self, cid):
        if self._mode != _SELECT:
            return
        self.selected_conn_id = cid
        self.selected_node_id = None
        conn = self.project.connectors.get(cid)
        if conn:
            self._show_conn_props(conn)
        self._redraw()

    # -- Connect helpers ---------------------------------------------------

    def _start_connect_from(self, nid):
        self._mode = _CONNECT_TGT
        self._conn_src_id = nid
        self._place_type = None
        self.canvas.config(cursor="crosshair")
        self._highlight_tools()
        self._update_status()

    def _cancel_connect(self):
        self._conn_src_id = None
        if self._conn_line:
            self.canvas.delete(self._conn_line)
            self._conn_line = None

    # ============================================================== #
    #  DELETE                                                          #
    # ============================================================== #
    def _delete_selected(self):
        if self.selected_node_id:
            self._delete_node(self.selected_node_id)
        elif self.selected_conn_id:
            self.project.remove_connector(self.selected_conn_id)
            self.selected_conn_id = None
            self._show_no_sel()
            self._redraw()

    def _delete_node(self, nid):
        was_fan = False
        node = self.project.nodes.get(nid)
        if node and node.node_type == NodeType.FAN:
            was_fan = True
        self.project.remove_node(nid)
        if self.selected_node_id == nid:
            self.selected_node_id = None
            self._show_no_sel()
        self._redraw()
        if was_fan:
            self._rebuild_scen_tree()

    # ============================================================== #
    #  ANALYSIS                                                        #
    # ============================================================== #
    def _run_analysis(self):
        sel = self.scen_tree.selection() if self.scen_tree else ()
        if sel:
            idx = int(sel[0])
            result = run_analysis(self.project, self.project.scenarios[idx])
        else:
            result = run_analysis(self.project)
        self._results = [result]
        self._show_results(self._results)
        self._redraw()

    def _run_all(self):
        self._results = run_all_scenarios(self.project)
        self._show_results(self._results)
        self._redraw()

    def _show_results(self, results):
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


# ------------------------------------------------------------------ #
#  Entry point                                                         #
# ------------------------------------------------------------------ #
def run_app():
    root = tk.Tk()
    StaticPressureApp(root)
    root.mainloop()
