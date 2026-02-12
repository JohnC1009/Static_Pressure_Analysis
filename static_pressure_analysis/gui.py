"""GUI for the Static Pressure Analysis tool using tkinter.

Architecture modelled after HVAC-Flow-Analysis:
  - Toolbox panel (left):  click-to-select, click-canvas-to-place
  - Canvas (centre):       nodes with visible inlet/outlet ports,
                           bezier-style connectors, drag-to-move
  - Property panel (right): dynamic form for selected node / connector
  - Scenario table (bottom): inline-editable overrides per fan
"""

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
# Accent / header colour per type
NODE_ACCENT = {
    NodeType.FAN:              "#3B7DD8",
    NodeType.DAMPER:           "#D4802A",
    NodeType.MIXING_PLENUM:    "#4AA84A",
    NodeType.DUCT_SPLIT:       "#9B5FB5",
    NodeType.PRESSURE_OUTPUT:  "#C94444",
}
# Light body fill per type
NODE_BODY = {
    NodeType.FAN:              "#EAF1FB",
    NodeType.DAMPER:           "#FDF0E0",
    NodeType.MIXING_PLENUM:    "#E4F6E4",
    NodeType.DUCT_SPLIT:       "#F2EAF7",
    NodeType.PRESSURE_OUTPUT:  "#FBEAEA",
}
# Icon letter shown in the header circle
NODE_ICON = {
    NodeType.FAN:              "F",
    NodeType.DAMPER:           "D",
    NodeType.MIXING_PLENUM:    "M",
    NodeType.DUCT_SPLIT:       "Y",
    NodeType.PRESSURE_OUTPUT:  "P",
}

NODE_W   = 180
NODE_H   = 68
HDR_H    = 26
PORT_R   = 8
SHADOW   = 3          # drop-shadow offset
CORNER   = 10         # rounded-corner radius
GRID_SZ  = 40         # background grid spacing
CANVAS_BG     = "#F0F0EC"
GRID_COLOR    = "#E2E2DE"
CONNECTOR_CLR = "#5A8CBF"
SELECT_CLR    = "#FF9800"

# Interaction modes
_SELECT      = "select"
_PLACE       = "place"
_CONNECT_SRC = "connect_src"
_CONNECT_TGT = "connect_tgt"

# Font tuples (family, size, weight)
_FNT_HDR  = ("Segoe UI", 11, "bold")
_FNT_NODE = ("Segoe UI",  9, "bold")
_FNT_SUB  = ("Segoe UI",  8)
_FNT_PORT = ("Segoe UI",  7, "bold")
_FNT_ICON = ("Segoe UI",  9, "bold")
_FNT_CONN = ("Segoe UI",  8)
_FNT_RES  = ("Segoe UI",  9, "bold")
_FNT_PROP = ("Segoe UI", 10, "bold")


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #
def _rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Draw a rounded rectangle on *canvas* and return its item id."""
    pts = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1, x2, y1 + r,
        x2, y2 - r,
        x2, y2, x2 - r, y2,
        x1 + r, y2,
        x1, y2, x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ------------------------------------------------------------------ #
#  Main application                                                    #
# ------------------------------------------------------------------ #
class StaticPressureApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Static Pressure Analysis")
        self.root.geometry("1400x850")
        self.root.minsize(1000, 600)

        # --- ttk theme ---------------------------------------------------
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Toolbox.TLabel", font=_FNT_HDR, padding=(10, 6))
        style.configure("Hint.TLabel",    foreground="#888", wraplength=170,
                         font=("Segoe UI", 9))
        style.configure("StatusBar.TLabel", relief="sunken", anchor="w",
                         padding=(8, 3), font=("Segoe UI", 9))
        style.configure("PropHeader.TLabel", font=_FNT_PROP)

        self.project = Project()
        self.selected_node_id: str | None = None
        self.selected_conn_id: str | None = None

        self._mode = _SELECT
        self._place_type: NodeType | None = None
        self._conn_src_id: str | None = None
        self._conn_line: int | None = None

        self._drag = {"id": None, "ox": 0, "oy": 0}
        self._results: list[AnalysisResult] = []
        self._tb_btns: dict[NodeType, tk.Canvas] = {}

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
        fm.add_command(label="Open…",        command=self._open_project, accelerator="Ctrl+O")
        fm.add_command(label="Save…",        command=self._save_project, accelerator="Ctrl+S")
        fm.add_separator()
        fm.add_command(label="Exit", command=self.root.quit)
        mb.add_cascade(label="File", menu=fm)

        am = tk.Menu(mb, tearoff=0)
        am.add_command(label="Run Analysis",      command=self._run_analysis,  accelerator="F5")
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

        left = ttk.Frame(pw, width=210)
        pw.add(left, weight=0)
        self._build_toolbox(left)

        centre = ttk.Frame(pw)
        pw.add(centre, weight=1)
        self._build_centre(centre)

        right = ttk.Frame(pw, width=280)
        pw.add(right, weight=0)
        self._build_props(right)

    # ============================================================== #
    #  TOOLBOX                                                         #
    # ============================================================== #
    def _build_toolbox(self, parent):
        ttk.Label(parent, text="Equipment Toolbox",
                  style="Toolbox.TLabel").pack(pady=(8, 2), padx=10, anchor="w")
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8)

        self._tb_hint = ttk.Label(parent, style="Hint.TLabel",
            text="Click an item, then click\nthe canvas to place it.")
        self._tb_hint.pack(pady=(4, 8), padx=12, anchor="w")

        for nt in NodeType:
            btn = self._make_tool_btn(parent, nt)
            btn.pack(pady=3, padx=12, fill=tk.X)
            self._tb_btns[nt] = btn

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8, pady=(14, 6))

        self._conn_btn = self._make_action_btn(parent, "Connect Nodes",
                                                "#5A6E80", self._tool_connect)
        self._conn_btn.pack(pady=3, padx=12, fill=tk.X)

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8, pady=(14, 6))

        self._sel_btn = self._make_action_btn(parent, "Select / Move",
                                               "#3B6FA0", self._reset_mode)
        self._sel_btn.pack(pady=3, padx=12, fill=tk.X)

    def _make_tool_btn(self, parent, nt: NodeType) -> tk.Canvas:
        """Create a mini-canvas button with an icon circle + label."""
        accent = NODE_ACCENT[nt]
        icon   = NODE_ICON[nt]
        h = 34
        c = tk.Canvas(parent, height=h, bg="#FAFAFA", highlightthickness=0,
                      cursor="hand2")
        # icon circle
        r = 12
        cx, cy = 20, h // 2
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=accent,
                       outline="", tags=("bg",))
        c.create_text(cx, cy, text=icon, fill="white", font=_FNT_ICON,
                       tags=("bg",))
        # label
        c.create_text(42, cy, text=nt.value, anchor="w", fill="#333",
                       font=("Segoe UI", 10), tags=("bg",))
        # border
        c.create_rectangle(0, 0, 999, h - 1, outline="#D0D0D0", width=1,
                            tags=("border",))
        c.bind("<Button-1>", lambda e, t=nt: self._tool_select(t))
        c.bind("<Enter>", lambda e, cv=c: cv.config(bg="#E8F0FE"))
        c.bind("<Leave>", lambda e, cv=c: cv.config(bg="#FAFAFA"))
        return c

    def _make_action_btn(self, parent, text, color, cmd) -> tk.Canvas:
        h = 32
        c = tk.Canvas(parent, height=h, bg=color, highlightthickness=0,
                      cursor="hand2")
        c.create_text(c.winfo_reqwidth() // 2 or 90, h // 2,
                       text=text, fill="white", font=("Segoe UI", 10, "bold"),
                       tags=("lbl",))
        c.create_rectangle(0, 0, 999, h - 1, outline=color, width=1,
                            tags=("border",))
        c.bind("<Button-1>", lambda e: cmd())
        return c

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
        self._tb_hint.config(text="Click a source node,\nthen click a target node\nto create a connector.\nPress Esc to cancel.")
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
        for nt, c in self._tb_btns.items():
            if self._mode == _PLACE and self._place_type == nt:
                c.config(bg="#D0E4F7")
                c.itemconfig("border", outline=NODE_ACCENT[nt], width=2)
            else:
                c.config(bg="#FAFAFA")
                c.itemconfig("border", outline="#D0D0D0", width=1)

        if self._mode in (_CONNECT_SRC, _CONNECT_TGT):
            self._conn_btn.itemconfig("border", outline="#FFB74D", width=2)
        else:
            self._conn_btn.itemconfig("border",
                outline=self._conn_btn.cget("bg"), width=1)

        if self._mode == _SELECT:
            self._sel_btn.itemconfig("border", outline="#FFB74D", width=2)
        else:
            self._sel_btn.itemconfig("border",
                outline=self._sel_btn.cget("bg"), width=1)

    # ============================================================== #
    #  CENTRE PANEL                                                    #
    # ============================================================== #
    def _build_centre(self, parent):
        vpw = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        vpw.pack(fill=tk.BOTH, expand=True)

        cf = ttk.Frame(vpw)
        vpw.add(cf, weight=3)

        self._status_var = tk.StringVar(value="Mode: Select / Move")
        ttk.Label(cf, textvariable=self._status_var,
                  style="StatusBar.TLabel").pack(fill=tk.X)

        self.canvas = tk.Canvas(cf, bg=CANVAS_BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>",  self._canvas_click)
        self.canvas.bind("<Button-3>",  self._canvas_rclick)
        self.canvas.bind("<Motion>",    self._canvas_motion)
        self.canvas.bind("<Configure>", lambda e: self._redraw())

        bf = ttk.Frame(vpw)
        vpw.add(bf, weight=1)
        self._build_scenario_panel(bf)

    def _update_status(self):
        if self._mode == _PLACE and self._place_type:
            self._status_var.set(
                f"Place {self._place_type.value}  \u2014  Click canvas to place, Esc to cancel")
        elif self._mode == _CONNECT_SRC:
            self._status_var.set(
                "Connect  \u2014  Click a source node  (Esc to cancel)")
        elif self._mode == _CONNECT_TGT:
            src = self.project.nodes.get(self._conn_src_id)
            name = src.name if src else "?"
            self._status_var.set(
                f"Connect  \u2014  Source: {name}  \u2014  Click a target node  (Esc to cancel)")
        else:
            self._status_var.set("Select / Move")

    # ============================================================== #
    #  SCENARIO PANEL                                                  #
    # ============================================================== #
    def _build_scenario_panel(self, parent):
        nb = ttk.Notebook(parent)
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        sf = ttk.Frame(nb)
        nb.add(sf, text="  Scenarios  ")

        tb = ttk.Frame(sf)
        tb.pack(fill=tk.X, padx=6, pady=(6, 4))
        ttk.Button(tb, text="+ Add Scenario",
                   command=self._add_scenario).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tb, text="- Remove Selected",
                   command=self._remove_scenario).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(tb, text="Double-click Override cells to edit",
                  foreground="#888", font=("Segoe UI", 9)).pack(side=tk.LEFT)

        self._scen_frame = ttk.Frame(sf)
        self._scen_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.scen_tree: ttk.Treeview | None = None
        self._scen_cols: list[str] = []
        self._rebuild_scen_tree()

        rf = ttk.Frame(nb)
        nb.add(rf, text="  Results  ")
        self.result_text = tk.Text(rf, height=8, state=tk.DISABLED,
                                    font=("Consolas", 10), bg="#FAFAFA",
                                    relief="flat", padx=8, pady=6)
        self.result_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def _fan_nodes(self) -> list[Node]:
        return [n for n in self.project.nodes.values()
                if n.node_type == NodeType.FAN]

    def _rebuild_scen_tree(self):
        for w in self._scen_frame.winfo_children():
            w.destroy()

        fans = self._fan_nodes()
        cols = ["scenario_name"]
        heads = {"scenario_name": "Scenario"}
        widths = {"scenario_name": 130}

        for fan in fans:
            short = fan.name[:12]
            for sfx, hdr, w in [
                ("_bcfm", f"{short} Base CFM",     90),
                ("_ocfm", f"{short} Ovr CFM",     100),
                ("_bsp",  f"{short} Base SP",       80),
                ("_osp",  f"{short} Ovr SP",       100),
            ]:
                cid = f"f{fan.id}{sfx}"
                cols.append(cid)
                heads[cid] = hdr
                widths[cid] = w

        tree = ttk.Treeview(self._scen_frame, columns=cols, show="headings",
                            height=5)
        for c in cols:
            tree.heading(c, text=heads.get(c, c))
            tree.column(c, width=widths.get(c, 80), minwidth=60)

        vsb = ttk.Scrollbar(self._scen_frame, orient=tk.VERTICAL,
                             command=tree.yview)
        hsb = ttk.Scrollbar(self._scen_frame, orient=tk.HORIZONTAL,
                             command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self._scen_frame.rowconfigure(0, weight=1)
        self._scen_frame.columnconfigure(0, weight=1)

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
        self.project.scenarios.append(
            Scenario(name=f"Scenario {len(self.project.scenarios) + 1}"))
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
        ttk.Label(parent, text="Properties",
                  style="Toolbox.TLabel").pack(pady=(8, 2), padx=10, anchor="w")
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8)

        # Scrollable container
        sf = ttk.Frame(parent)
        sf.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(sf, highlightthickness=0)
        vsb = ttk.Scrollbar(sf, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._props = ttk.Frame(canvas)
        self._props_win = canvas.create_window((0, 0), window=self._props,
                                                anchor="nw")

        def _on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(self._props_win, width=canvas.winfo_width())
        self._props.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>",
                     lambda e: canvas.itemconfig(self._props_win,
                                                  width=e.width))

        self._pvars: dict[str, tk.StringVar] = {}
        self._show_no_sel()

    def _clear_props(self):
        for w in self._props.winfo_children():
            w.destroy()
        self._pvars.clear()

    def _show_no_sel(self):
        self._clear_props()
        ttk.Label(self._props,
                  text="Select a node or connector\nto view its properties.",
                  foreground="#999", font=("Segoe UI", 10),
                  justify="center").pack(pady=30, padx=10)

    def _show_node_props(self, node: Node):
        self._clear_props()
        accent = NODE_ACCENT.get(node.node_type, "#666")

        # Header
        hf = ttk.Frame(self._props)
        hf.pack(fill=tk.X, pady=(10, 6), padx=10)
        icon_c = tk.Canvas(hf, width=28, height=28, highlightthickness=0)
        icon_c.pack(side=tk.LEFT, padx=(0, 8))
        icon_c.create_oval(2, 2, 26, 26, fill=accent, outline="")
        icon_c.create_text(14, 14, text=NODE_ICON.get(node.node_type, "?"),
                            fill="white", font=_FNT_ICON)
        ttk.Label(hf, text=node.node_type.value,
                  style="PropHeader.TLabel").pack(side=tk.LEFT)

        ttk.Separator(self._props, orient=tk.HORIZONTAL).pack(
            fill=tk.X, padx=10, pady=(0, 6))

        self._add_field("Name", "name", node.name)

        # Parameter fields
        ttk.Label(self._props, text="Parameters",
                  font=("Segoe UI", 9, "bold"), foreground="#555").pack(
            anchor="w", padx=12, pady=(8, 2))
        params = node.parameters
        for f in dataclass_fields(type(params)):
            v = getattr(params, f.name)
            label = f.name.replace("_", " ").title()
            self._add_field(label, f"p_{f.name}", str(v))

        ttk.Button(self._props, text="Apply",
                   command=lambda: self._apply_node(node)).pack(
            pady=(12, 8), padx=12, anchor="e")

    def _show_conn_props(self, conn: Connector):
        self._clear_props()

        ttk.Label(self._props, text="Duct Connector",
                  style="PropHeader.TLabel").pack(
            anchor="w", padx=12, pady=(10, 4))
        ttk.Separator(self._props, orient=tk.HORIZONTAL).pack(
            fill=tk.X, padx=10, pady=(0, 6))

        src = self.project.nodes.get(conn.source_id)
        tgt = self.project.nodes.get(conn.target_id)
        info = ttk.Frame(self._props)
        info.pack(fill=tk.X, padx=12, pady=(0, 6))
        ttk.Label(info, text="From:", foreground="#888",
                  font=("Segoe UI", 9)).pack(anchor="w")
        ttk.Label(info, text=f"  {src.name if src else '?'}",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Label(info, text="To:", foreground="#888",
                  font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))
        ttk.Label(info, text=f"  {tgt.name if tgt else '?'}",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")

        ttk.Label(self._props, text="Duct Properties",
                  font=("Segoe UI", 9, "bold"), foreground="#555").pack(
            anchor="w", padx=12, pady=(8, 2))

        self._add_field("Label", "label", conn.label)
        self._add_field("Length (ft)", "length", str(conn.length))
        self._add_field("Diameter (in)", "diameter", str(conn.diameter))
        self._add_field("Friction (in/100ft)", "friction_rate",
                        str(conn.friction_rate))

        ttk.Separator(self._props, orient=tk.HORIZONTAL).pack(
            fill=tk.X, padx=10, pady=(8, 4))
        ttk.Label(self._props,
                  text=f"Pressure Drop: {conn.pressure_drop:.4f} in.wg",
                  font=("Consolas", 9), foreground="#C94444").pack(
            anchor="w", padx=12, pady=(2, 4))

        ttk.Button(self._props, text="Apply",
                   command=lambda: self._apply_conn(conn)).pack(
            pady=(12, 8), padx=12, anchor="e")

    def _add_field(self, label, key, value):
        f = ttk.Frame(self._props)
        f.pack(fill=tk.X, padx=12, pady=2)
        ttk.Label(f, text=label, width=20, anchor="w",
                  font=("Segoe UI", 9)).pack(side=tk.LEFT)
        var = tk.StringVar(value=value)
        self._pvars[key] = var
        ttk.Entry(f, textvariable=var, width=14).pack(
            side=tk.LEFT, fill=tk.X, expand=True)

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
        self._draw_grid()
        for conn in self.project.connectors.values():
            self._draw_connector(conn)
        for node in self.project.nodes.values():
            self._draw_node(node)

    def _draw_grid(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        for x in range(0, max(w, 2000), GRID_SZ):
            self.canvas.create_line(x, 0, x, max(h, 2000),
                                     fill=GRID_COLOR, width=1)
        for y in range(0, max(h, 2000), GRID_SZ):
            self.canvas.create_line(0, y, max(w, 2000), y,
                                     fill=GRID_COLOR, width=1)

    # -- Nodes -------------------------------------------------------------

    def _draw_node(self, node: Node):
        x, y = node.x, node.y
        hw, hh = NODE_W / 2, NODE_H / 2
        accent = NODE_ACCENT.get(node.node_type, "#888")
        body   = NODE_BODY.get(node.node_type, "#f5f5f5")
        icon   = NODE_ICON.get(node.node_type, "?")
        sel    = node.id == self.selected_node_id
        tag    = f"n_{node.id}"

        # Drop shadow
        _rounded_rect(self.canvas,
                       x - hw + SHADOW, y - hh + SHADOW,
                       x + hw + SHADOW, y + hh + SHADOW,
                       CORNER, fill="#C8C8C0", outline="", tags=(tag,))

        # Body
        oc = SELECT_CLR if sel else accent
        ow = 2.5 if sel else 1.5
        _rounded_rect(self.canvas, x - hw, y - hh, x + hw, y + hh,
                       CORNER, fill=body, outline=oc, width=ow, tags=(tag,))

        # Header bar (clipped to top of body)
        self.canvas.create_rectangle(x - hw + 1, y - hh + 1,
                                      x + hw - 1, y - hh + HDR_H,
                                      fill=accent, outline="", tags=(tag,))

        # Icon circle in header
        ir = 9
        ix = x - hw + 18
        iy = y - hh + HDR_H // 2
        self.canvas.create_oval(ix - ir, iy - ir, ix + ir, iy + ir,
                                 fill="white", outline="", tags=(tag,))
        self.canvas.create_text(ix, iy, text=icon, fill=accent,
                                 font=_FNT_ICON, tags=(tag,))

        # Name
        dname = node.name if len(node.name) <= 18 else node.name[:16] + ".."
        self.canvas.create_text(ix + ir + 6, iy, text=dname, anchor="w",
                                 fill="white", font=_FNT_NODE, tags=(tag,))

        # Subtitle
        sub = self._subtitle(node)
        if sub:
            self.canvas.create_text(x, y + 6, text=sub, fill="#666",
                                     font=_FNT_SUB, tags=(tag,))

        # Analysis result annotation
        if self._results:
            sp = self._results[0].pressures.get(node.id)
            if sp is not None and node.node_type == NodeType.PRESSURE_OUTPUT:
                self.canvas.create_text(x, y + hh + 14,
                    text=f"{sp:+.3f} in.wg", fill="#C94444",
                    font=_FNT_RES, tags=(tag,))

        # --- Ports ---
        if node.node_type != NodeType.FAN:
            self._draw_port(x - hw, y, node.id, "inlet", tag)
        if node.node_type != NodeType.PRESSURE_OUTPUT:
            self._draw_port(x + hw, y, node.id, "outlet", tag)

        # Bind
        self.canvas.tag_bind(tag, "<ButtonPress-1>",
            lambda e, nid=node.id: self._node_press(e, nid))
        self.canvas.tag_bind(tag, "<B1-Motion>", self._node_drag)
        self.canvas.tag_bind(tag, "<ButtonRelease-1>", self._node_release)
        self.canvas.tag_bind(tag, "<Button-3>",
            lambda e, nid=node.id: self._node_rclick(e, nid))

    def _draw_port(self, px, py, nid, direction, parent_tag):
        """Draw a port circle at (px, py)."""
        if direction == "inlet":
            fill, outline, label = "#50C878", "#2E8B57", "IN"
            ptag = f"inp_{nid}"
        else:
            fill, outline, label = "#5A8CBF", "#3A6C9F", "OUT"
            ptag = f"outp_{nid}"

        # Outer ring for visibility
        self.canvas.create_oval(px - PORT_R - 2, py - PORT_R - 2,
                                 px + PORT_R + 2, py + PORT_R + 2,
                                 fill="white", outline="", tags=(parent_tag,))
        self.canvas.create_oval(px - PORT_R, py - PORT_R,
                                 px + PORT_R, py + PORT_R,
                                 fill=fill, outline=outline, width=1.5,
                                 tags=(parent_tag, ptag, "port"))
        self.canvas.create_text(px, py, text=label, fill="white",
                                 font=("Segoe UI", 6, "bold"),
                                 tags=(parent_tag,))

    def _subtitle(self, node: Node) -> str:
        p = node.parameters
        if isinstance(p, FanParameters):
            return f"{p.airflow:.0f} CFM  |  {p.static_pressure:.2f} in.wg"
        if isinstance(p, DamperParameters):
            return f"\u0394P {p.pressure_drop:.2f} in.wg"
        if isinstance(p, MixingPlenumParameters):
            return f"\u0394P {p.pressure_drop:.2f} in.wg"
        if isinstance(p, DuctSplitParameters):
            return f"\u0394P {p.pressure_drop:.2f} in.wg"
        if isinstance(p, PressureOutputParameters):
            return p.label
        return ""

    # -- Connectors --------------------------------------------------------

    def _draw_connector(self, conn: Connector):
        src = self.project.nodes.get(conn.source_id)
        tgt = self.project.nodes.get(conn.target_id)
        if not src or not tgt:
            return
        sel   = conn.id == self.selected_conn_id
        color = SELECT_CLR if sel else CONNECTOR_CLR
        w     = 3 if sel else 2
        tag   = f"c_{conn.id}"

        hw = NODE_W / 2
        x1, y1 = src.x + hw, src.y
        x2, y2 = tgt.x - hw, tgt.y

        # Bezier control points
        dx = max(abs(x2 - x1) * 0.45, 50)
        pts = [x1, y1, x1 + dx, y1, x2 - dx, y2, x2, y2]

        # Shadow
        shadow_pts = [p + 2 for p in pts]
        self.canvas.create_line(*shadow_pts, fill="#C8C8C0", width=w + 2,
                                 smooth=True, tags=(tag,))
        # Main line
        self.canvas.create_line(*pts, fill=color, width=w, smooth=True,
                                 arrow=tk.LAST, arrowshape=(10, 13, 5),
                                 tags=(tag,))

        # Label
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        lbl = conn.label or (f"{conn.length:.0f} ft" if conn.length > 0
                              else "")
        if lbl:
            # Background pill
            self.canvas.create_oval(mx - 30, my - 10, mx + 30, my + 10,
                                     fill="white", outline="#DDD", width=1,
                                     tags=(tag,))
            self.canvas.create_text(mx, my, text=lbl, fill="#555",
                                     font=_FNT_CONN, tags=(tag,))

        self.canvas.tag_bind(tag, "<Button-1>",
            lambda e, cid=conn.id: self._conn_click(cid))

    # ============================================================== #
    #  CANVAS INTERACTIONS                                             #
    # ============================================================== #
    def _canvas_click(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        if self._mode == _PLACE and self._place_type:
            node = Node(node_type=self._place_type, x=cx, y=cy)
            self.project.add_node(node)
            self._redraw()
            self._select_node(node.id)
            if node.node_type == NodeType.FAN:
                self._rebuild_scen_tree()
            return

        if self._mode == _CONNECT_SRC:
            return
        if self._mode == _CONNECT_TGT:
            self._cancel_connect()
            self._mode = _CONNECT_SRC
            self._update_status()
            self._redraw()
            return

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
                fill="#999", dash=(6, 4), width=2, arrow=tk.LAST)

    # -- Node interactions -------------------------------------------------

    def _node_press(self, event, nid):
        if self._mode == _PLACE:
            return

        if self._mode == _CONNECT_SRC:
            node = self.project.nodes.get(nid)
            if not node:
                return
            if node.node_type == NodeType.PRESSURE_OUTPUT:
                return
            self._conn_src_id = nid
            self._mode = _CONNECT_TGT
            self._update_status()
            self._highlight_tools()
            return

        if self._mode == _CONNECT_TGT:
            node = self.project.nodes.get(nid)
            if not node:
                return
            if node.node_type == NodeType.FAN or nid == self._conn_src_id:
                return
            conn = Connector(source_id=self._conn_src_id, target_id=nid)
            self.project.add_connector(conn)
            self._cancel_connect()
            self._mode = _CONNECT_SRC
            self._update_status()
            self._redraw()
            return

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
        menu.add_command(label="Connect from here\u2026",
            command=lambda: self._start_connect_from(nid))
        menu.add_separator()
        menu.add_command(label="Delete",
            command=lambda: self._delete_node(nid))
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
        self._rebuild_scen_tree()
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
        self._rebuild_scen_tree()
        self._results = run_all_scenarios(self.project)
        self._show_results(self._results)
        self._redraw()

    def _show_results(self, results):
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete("1.0", tk.END)
        for res in results:
            self.result_text.insert(tk.END, f"{'='*60}\n")
            self.result_text.insert(tk.END,
                f" Scenario: {res.scenario_name or 'Baseline'}\n")
            self.result_text.insert(tk.END, f"{'='*60}\n")
            if res.warnings:
                for w in res.warnings:
                    self.result_text.insert(tk.END, f"  WARNING: {w}\n")
            self.result_text.insert(tk.END,
                f"  {'Node':<25} {'Type':<18} "
                f"{'SP (in.wg)':>12} {'Airflow (CFM)':>14}\n")
            self.result_text.insert(tk.END,
                f"  {'-'*25} {'-'*18} {'-'*12} {'-'*14}\n")
            for nid, sp in res.pressures.items():
                node = self.project.nodes.get(nid)
                if not node:
                    continue
                af = res.airflows.get(nid, 0)
                self.result_text.insert(tk.END,
                    f"  {node.name:<25} {node.node_type.value:<18} "
                    f"{sp:>+12.3f} {af:>14.0f}\n")
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
