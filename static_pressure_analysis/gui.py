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
CONNECTOR_COLOR = "#555555"
CONNECTOR_ARROW_COLOR = "#333333"
CANVAS_BG = "#F5F5F0"


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

        # Drag state
        self._drag_data = {"node_id": None, "offset_x": 0, "offset_y": 0}
        # Connector drawing state
        self._conn_state = {"active": False, "source_id": None, "line_id": None}
        # Toolbox drag-and-drop state
        self._toolbox_drag = {"active": False, "node_type": None, "ghost_id": None}

        self._last_results: list[AnalysisResult] = []

        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()

    # ----- Menu bar -------------------------------------------------------- #
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

    # ----- Main layout ----------------------------------------------------- #
    def _build_layout(self):
        # Top-level paned window: left (toolbox) | center (canvas) | right (props)
        self.main_pw = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_pw.pack(fill=tk.BOTH, expand=True)

        # Left panel: Equipment Toolbox
        left_frame = ttk.Frame(self.main_pw, width=180)
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

    # ----- Toolbox --------------------------------------------------------- #
    def _build_toolbox(self, parent):
        ttk.Label(parent, text="Equipment Toolbox", font=("Helvetica", 11, "bold")).pack(
            pady=(10, 5), padx=10, anchor="w"
        )
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5)

        desc = ttk.Label(parent, text="Drag items onto the canvas", foreground="gray")
        desc.pack(pady=(2, 8), padx=10, anchor="w")

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
            btn.bind("<ButtonPress-1>", lambda e, t=nt: self._toolbox_start_drag(e, t))
            btn.bind("<B1-Motion>", self._toolbox_drag_motion)
            btn.bind("<ButtonRelease-1>", self._toolbox_drop)

    # ----- Center panel (canvas + scenarios) ------------------------------- #
    def _build_center(self, parent):
        vpw = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        vpw.pack(fill=tk.BOTH, expand=True)

        # Canvas
        canvas_frame = ttk.Frame(vpw)
        vpw.add(canvas_frame, weight=3)

        self.canvas = tk.Canvas(canvas_frame, bg=CANVAS_BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self._canvas_click)
        self.canvas.bind("<Button-3>", self._canvas_right_click)

        # Scenario / results area
        bottom_frame = ttk.Frame(vpw)
        vpw.add(bottom_frame, weight=1)
        self._build_scenario_panel(bottom_frame)

    # ----- Scenario panel -------------------------------------------------- #
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
        ttk.Button(toolbar, text="Edit Overrides", command=self._edit_scenario_overrides).pack(side=tk.LEFT, padx=2)

        cols = ("name",)
        self.scenario_tree = ttk.Treeview(scen_frame, columns=cols, show="headings", height=4)
        self.scenario_tree.heading("name", text="Scenario Name")
        self.scenario_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        # Tab 2: Results
        result_frame = ttk.Frame(nb)
        nb.add(result_frame, text="Results")

        self.result_text = tk.Text(result_frame, height=8, state=tk.DISABLED, font=("Courier", 10))
        self.result_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    # ----- Properties panel ------------------------------------------------ #
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
                  text=f"From: {src.name if src else '?'}\nTo: {tgt.name if tgt else '?'}").pack(anchor="w", pady=(0, 8))

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

    # ----- Keyboard shortcuts ---------------------------------------------- #
    def _bind_shortcuts(self):
        self.root.bind("<Control-n>", lambda e: self._new_project())
        self.root.bind("<Control-o>", lambda e: self._open_project())
        self.root.bind("<Control-s>", lambda e: self._save_project())
        self.root.bind("<F5>", lambda e: self._run_analysis())
        self.root.bind("<Delete>", lambda e: self._delete_selected())
        self.root.bind("<Escape>", lambda e: self._cancel_actions())

    # ----- File operations ------------------------------------------------- #
    def _new_project(self):
        self.project = Project()
        self.selected_node_id = None
        self.selected_connector_id = None
        self._last_results = []
        self._redraw()
        self._refresh_scenario_tree()
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
        self._redraw()
        self._refresh_scenario_tree()
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

    # ----- Toolbox drag and drop ------------------------------------------ #
    def _toolbox_start_drag(self, event, node_type: NodeType):
        self._toolbox_drag["active"] = True
        self._toolbox_drag["node_type"] = node_type

    def _toolbox_drag_motion(self, event):
        if not self._toolbox_drag["active"]:
            return
        # Update cursor to indicate drag
        self.canvas.config(cursor="crosshair")

    def _toolbox_drop(self, event):
        if not self._toolbox_drag["active"]:
            return
        self._toolbox_drag["active"] = False
        self.canvas.config(cursor="")

        # Convert screen coordinates to canvas coordinates
        try:
            cx = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
            cy = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
        except Exception:
            return

        # Check if drop is on the canvas
        if cx < 0 or cy < 0 or cx > self.canvas.winfo_width() or cy > self.canvas.winfo_height():
            return

        node_type = self._toolbox_drag["node_type"]
        node = Node(node_type=node_type, x=cx, y=cy)
        self.project.add_node(node)
        self._redraw()
        self._select_node(node.id)

    # ----- Canvas drawing -------------------------------------------------- #
    def _redraw(self):
        self.canvas.delete("all")
        # Draw connectors first (behind nodes)
        for conn in self.project.connectors.values():
            self._draw_connector(conn)
        # Draw nodes
        for node in self.project.nodes.values():
            self._draw_node(node)
        # Draw in-progress connector line
        if self._conn_state["active"] and self._conn_state["line_id"]:
            pass  # already drawn dynamically

    def _draw_node(self, node: Node):
        x, y = node.x, node.y
        hw, hh = NODE_WIDTH / 2, NODE_HEIGHT / 2
        color = NODE_COLORS.get(node.node_type, "#888888")
        is_selected = node.id == self.selected_node_id

        outline_color = "#FFD700" if is_selected else "#333333"
        outline_width = 3 if is_selected else 1

        tag = f"node_{node.id}"

        # Shape varies by type
        if node.node_type == NodeType.FAN:
            # Draw a rounded rectangle approximation
            self._draw_rounded_rect(x - hw, y - hh, x + hw, y + hh, 12,
                                     fill=color, outline=outline_color, width=outline_width, tags=tag)
        elif node.node_type == NodeType.DUCT_SPLIT:
            # Diamond shape
            pts = [x, y - hh, x + hw, y, x, y + hh, x - hw, y]
            self.canvas.create_polygon(pts, fill=color, outline=outline_color, width=outline_width, tags=tag)
        elif node.node_type == NodeType.PRESSURE_OUTPUT:
            # Circle
            r = min(hw, hh)
            self.canvas.create_oval(x - r, y - r, x + r, y + r,
                                     fill=color, outline=outline_color, width=outline_width, tags=tag)
        else:
            # Rectangle for damper and mixing plenum
            self.canvas.create_rectangle(x - hw, y - hh, x + hw, y + hh,
                                          fill=color, outline=outline_color, width=outline_width, tags=tag)

        # Label
        display_name = node.name
        if len(display_name) > 16:
            display_name = display_name[:14] + ".."
        self.canvas.create_text(x, y - 6, text=display_name, fill="white",
                                 font=("Helvetica", 9, "bold"), tags=tag)

        # Subtitle with key info
        subtitle = self._node_subtitle(node)
        if subtitle:
            self.canvas.create_text(x, y + 10, text=subtitle, fill="#FFFFFFCC",
                                     font=("Helvetica", 8), tags=tag)

        # Show pressure result if available
        if self._last_results:
            result = self._last_results[0]  # show first scenario on canvas
            sp = result.pressures.get(node.id)
            if sp is not None and node.node_type == NodeType.PRESSURE_OUTPUT:
                self.canvas.create_text(x, y + hh + 14, text=f"{sp:+.3f} in.wg",
                                         fill="#CC0000", font=("Helvetica", 9, "bold"), tags=tag)

        # Bind events
        self.canvas.tag_bind(tag, "<ButtonPress-1>", lambda e, nid=node.id: self._node_press(e, nid))
        self.canvas.tag_bind(tag, "<B1-Motion>", self._node_drag)
        self.canvas.tag_bind(tag, "<ButtonRelease-1>", self._node_release)
        self.canvas.tag_bind(tag, "<Button-3>", lambda e, nid=node.id: self._node_right_click(e, nid))

    def _draw_rounded_rect(self, x1, y1, x2, y2, r, **kwargs):
        tags = kwargs.pop("tags", "")
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        self.canvas.create_polygon(points, smooth=True, tags=tags, **kwargs)

    def _node_subtitle(self, node: Node) -> str:
        p = node.parameters
        if isinstance(p, FanParameters):
            return f"{p.airflow:.0f} CFM | {p.static_pressure:.2f} in.wg"
        if isinstance(p, DamperParameters):
            return f"ΔP {p.pressure_drop:.2f} in.wg"
        if isinstance(p, MixingPlenumParameters):
            return f"ΔP {p.pressure_drop:.2f} in.wg"
        if isinstance(p, DuctSplitParameters):
            return f"ΔP {p.pressure_drop:.2f} in.wg"
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

        # Draw line with arrow
        self.canvas.create_line(
            src.x, src.y, tgt.x, tgt.y,
            fill=color, width=width, arrow=tk.LAST, arrowshape=(12, 14, 5),
            tags=tag,
        )

        # Label at midpoint
        mx = (src.x + tgt.x) / 2
        my = (src.y + tgt.y) / 2
        label = conn.label or f"{conn.length:.0f}ft"
        if conn.length > 0:
            self.canvas.create_text(mx, my - 10, text=label, fill="#333",
                                     font=("Helvetica", 8), tags=tag)
            dp = conn.pressure_drop
            self.canvas.create_text(mx, my + 4, text=f"ΔP {dp:.3f} in.wg",
                                     fill="#666", font=("Helvetica", 7), tags=tag)

        self.canvas.tag_bind(tag, "<Button-1>", lambda e, cid=conn.id: self._select_connector(cid))

    # ----- Node interactions ----------------------------------------------- #
    def _node_press(self, event, node_id: str):
        if self._conn_state["active"]:
            # Complete the connector
            self._finish_connector(node_id)
            return

        self._select_node(node_id)
        node = self.project.nodes.get(node_id)
        if node:
            self._drag_data["node_id"] = node_id
            self._drag_data["offset_x"] = node.x - self.canvas.canvasx(event.x)
            self._drag_data["offset_y"] = node.y - self.canvas.canvasy(event.y)

    def _node_drag(self, event):
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
        menu.add_command(label="Connect from here...", command=lambda: self._start_connector(node_id))
        menu.add_command(label="Delete", command=lambda: self._delete_node(node_id))
        menu.tk_popup(event.x_root, event.y_root)

    def _select_node(self, node_id: str):
        self.selected_node_id = node_id
        self.selected_connector_id = None
        node = self.project.nodes.get(node_id)
        if node:
            self._show_node_props(node)
        self._redraw()

    def _select_connector(self, conn_id: str):
        self.selected_connector_id = conn_id
        self.selected_node_id = None
        conn = self.project.connectors.get(conn_id)
        if conn:
            self._show_connector_props(conn)
        self._redraw()

    # ----- Connector drawing ----------------------------------------------- #
    def _start_connector(self, source_id: str):
        self._conn_state["active"] = True
        self._conn_state["source_id"] = source_id
        self.canvas.config(cursor="crosshair")
        self.canvas.bind("<Motion>", self._connector_motion)

    def _connector_motion(self, event):
        if not self._conn_state["active"]:
            return
        src = self.project.nodes.get(self._conn_state["source_id"])
        if not src:
            return
        # Remove old temp line
        if self._conn_state["line_id"]:
            self.canvas.delete(self._conn_state["line_id"])
        lid = self.canvas.create_line(
            src.x, src.y,
            self.canvas.canvasx(event.x), self.canvas.canvasy(event.y),
            fill="#999", dash=(4, 4), width=2, arrow=tk.LAST,
        )
        self._conn_state["line_id"] = lid

    def _finish_connector(self, target_id: str):
        source_id = self._conn_state["source_id"]
        if source_id and target_id and source_id != target_id:
            conn = Connector(source_id=source_id, target_id=target_id)
            self.project.add_connector(conn)
        self._cancel_connector()
        self._redraw()

    def _cancel_connector(self):
        if self._conn_state["line_id"]:
            self.canvas.delete(self._conn_state["line_id"])
        self._conn_state["active"] = False
        self._conn_state["source_id"] = None
        self._conn_state["line_id"] = None
        self.canvas.config(cursor="")
        self.canvas.unbind("<Motion>")

    def _cancel_actions(self):
        self._cancel_connector()
        self.selected_node_id = None
        self.selected_connector_id = None
        self._show_no_selection()
        self._redraw()

    # ----- Canvas click ---------------------------------------------------- #
    def _canvas_click(self, event):
        if self._conn_state["active"]:
            # Clicked on empty canvas - cancel connector
            self._cancel_connector()
            return
        # Deselect
        self.selected_node_id = None
        self.selected_connector_id = None
        self._show_no_selection()
        self._redraw()

    def _canvas_right_click(self, event):
        if self._conn_state["active"]:
            self._cancel_connector()

    # ----- Delete ---------------------------------------------------------- #
    def _delete_selected(self):
        if self.selected_node_id:
            self._delete_node(self.selected_node_id)
        elif self.selected_connector_id:
            self.project.remove_connector(self.selected_connector_id)
            self.selected_connector_id = None
            self._show_no_selection()
            self._redraw()

    def _delete_node(self, node_id: str):
        self.project.remove_node(node_id)
        if self.selected_node_id == node_id:
            self.selected_node_id = None
            self._show_no_selection()
        self._redraw()

    # ----- Scenarios ------------------------------------------------------- #
    def _refresh_scenario_tree(self):
        self.scenario_tree.delete(*self.scenario_tree.get_children())
        for i, s in enumerate(self.project.scenarios):
            self.scenario_tree.insert("", "end", iid=str(i), values=(s.name,))

    def _add_scenario(self):
        name = f"Scenario {len(self.project.scenarios) + 1}"
        self.project.scenarios.append(Scenario(name=name))
        self._refresh_scenario_tree()

    def _remove_scenario(self):
        sel = self.scenario_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.project.scenarios):
            self.project.scenarios.pop(idx)
        self._refresh_scenario_tree()

    def _edit_scenario_overrides(self):
        sel = self.scenario_tree.selection()
        if not sel:
            messagebox.showinfo("Info", "Select a scenario first.")
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.project.scenarios):
            return
        scenario = self.project.scenarios[idx]
        ScenarioEditorDialog(self.root, self.project, scenario, self._refresh_scenario_tree)

    # ----- Analysis -------------------------------------------------------- #
    def _run_analysis(self):
        if not self.project.scenarios:
            result = run_analysis(self.project)
            self._last_results = [result]
        else:
            sel = self.scenario_tree.selection()
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

            self.result_text.insert(tk.END, f"  {'Node':<25} {'Type':<18} {'SP (in.wg)':>12} {'Airflow (CFM)':>14}\n")
            self.result_text.insert(tk.END, f"  {'-'*25} {'-'*18} {'-'*12} {'-'*14}\n")

            for nid, sp in res.pressures.items():
                node = self.project.nodes.get(nid)
                if not node:
                    continue
                af = res.airflows.get(nid, 0)
                self.result_text.insert(
                    tk.END,
                    f"  {node.name:<25} {node.node_type.value:<18} {sp:>+12.3f} {af:>14.0f}\n",
                )

            self.result_text.insert(tk.END, "\n")

        self.result_text.config(state=tk.DISABLED)

    def _clear_results(self):
        self.result_text.config(state=tk.NORMAL)
        self.result_text.delete("1.0", tk.END)
        self.result_text.config(state=tk.DISABLED)


# --------------------------------------------------------------------------- #
#  Scenario Editor Dialog
# --------------------------------------------------------------------------- #
class ScenarioEditorDialog:
    """Modal dialog to edit fan overrides for a scenario."""

    def __init__(self, parent, project: Project, scenario: Scenario, on_close=None):
        self.project = project
        self.scenario = scenario
        self.on_close = on_close

        self.win = tk.Toplevel(parent)
        self.win.title(f"Edit Scenario: {scenario.name}")
        self.win.geometry("650x400")
        self.win.transient(parent)
        self.win.grab_set()

        # Scenario name
        name_frame = ttk.Frame(self.win)
        name_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(name_frame, text="Scenario Name:").pack(side=tk.LEFT)
        self.name_var = tk.StringVar(value=scenario.name)
        ttk.Entry(name_frame, textvariable=self.name_var, width=30).pack(side=tk.LEFT, padx=5)

        # Fan overrides table
        ttk.Label(self.win, text="Fan Airflow Overrides:", font=("Helvetica", 10, "bold")).pack(
            anchor="w", padx=10, pady=(10, 2))

        cols = ("fan_name", "base_airflow", "override_airflow", "base_sp", "override_sp")
        self.tree = ttk.Treeview(self.win, columns=cols, show="headings", height=8)
        self.tree.heading("fan_name", text="Fan")
        self.tree.heading("base_airflow", text="Base CFM")
        self.tree.heading("override_airflow", text="Override CFM")
        self.tree.heading("base_sp", text="Base SP")
        self.tree.heading("override_sp", text="Override SP")
        self.tree.column("fan_name", width=120)
        self.tree.column("base_airflow", width=100)
        self.tree.column("override_airflow", width=120)
        self.tree.column("base_sp", width=100)
        self.tree.column("override_sp", width=120)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self._fan_ids = []
        self._populate()

        self.tree.bind("<Double-1>", self._on_double_click)

        btn_frame = ttk.Frame(self.win)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.win.destroy).pack(side=tk.RIGHT, padx=5)

    def _populate(self):
        from .models import FanParameters as FP
        for nid, node in self.project.nodes.items():
            if node.node_type != NodeType.FAN:
                continue
            params = node.parameters
            if not isinstance(params, FP):
                continue
            overrides = self.scenario.fan_overrides.get(nid, {})
            ov_af = overrides.get("airflow", "")
            ov_sp = overrides.get("static_pressure", "")
            self.tree.insert("", "end", iid=nid, values=(
                node.name,
                f"{params.airflow:.0f}",
                str(ov_af) if ov_af != "" else "",
                f"{params.static_pressure:.2f}",
                str(ov_sp) if ov_sp != "" else "",
            ))
            self._fan_ids.append(nid)

    def _on_double_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row:
            return

        # Only allow editing override columns (#3 and #5)
        col_idx = int(col.replace("#", ""))
        if col_idx not in (3, 5):
            return

        # Get cell bbox
        bbox = self.tree.bbox(row, col)
        if not bbox:
            return

        current_val = self.tree.set(row, col)
        entry = ttk.Entry(self.tree, width=10)
        entry.insert(0, current_val)
        entry.select_range(0, tk.END)
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        entry.focus_set()

        def _commit(e=None):
            self.tree.set(row, col, entry.get())
            entry.destroy()

        entry.bind("<Return>", _commit)
        entry.bind("<FocusOut>", _commit)

    def _save(self):
        self.scenario.name = self.name_var.get()
        self.scenario.fan_overrides = {}

        for nid in self._fan_ids:
            ov_af = self.tree.set(nid, "#3").strip()
            ov_sp = self.tree.set(nid, "#5").strip()
            overrides = {}
            if ov_af:
                try:
                    overrides["airflow"] = float(ov_af)
                except ValueError:
                    pass
            if ov_sp:
                try:
                    overrides["static_pressure"] = float(ov_sp)
                except ValueError:
                    pass
            if overrides:
                self.scenario.fan_overrides[nid] = overrides

        if self.on_close:
            self.on_close()
        self.win.destroy()


# --------------------------------------------------------------------------- #
#  Entry point helper
# --------------------------------------------------------------------------- #
def run_app():
    root = tk.Tk()
    StaticPressureApp(root)
    root.mainloop()
