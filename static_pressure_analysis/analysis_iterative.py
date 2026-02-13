"""Hardy-Cross iterative network solver for static pressure analysis.

Solves for balanced airflow distribution and pressures across the entire
duct network, including networks with multiple fans and shared paths
(e.g. a toilet exhaust fan feeding into a GX fan that also pulls from
a riser).

Algorithm overview:
1. Build an internal directed graph of *elements* (connectors and
   resistance-bearing nodes) with pressure-flow relationships.
2. Assign an initial flow guess satisfying mass conservation at every
   junction.
3. Identify independent loops (using a spanning-tree approach).
4. Iteratively apply the Hardy-Cross correction:
       delta_Q = - sum(h_i) / sum(dh_i/dQ)
   where h_i is the signed head loss in element *i* around the loop.
5. Repeat until the maximum correction is below the convergence
   tolerance.
6. Compute pressures via a single BFS pass from each fan using the
   converged flows.

Pressure-flow model for ducts
------------------------------
  DP = R * |Q|^n  (signed in the direction of Q)

where the resistance coefficient R = friction_rate * length / 100
at the *rated* conditions, and n = 1.9 (typical for turbulent duct
flow per ASHRAE).  For small flows we use a linearised region to
avoid numerical issues near Q = 0.

Nodes with a fixed ``pressure_drop`` (dampers, plenums, splits, …)
are treated as constant-loss elements (n = 0 for the purpose of
Hardy-Cross — loss is independent of flow).

Fans are treated as fixed-pressure-rise elements whose airflow is
*determined by the solver*, not prescribed.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from .models import (
    Connector,
    DamperParameters,
    DuctSinkSourceParameters,
    DuctSplitParameters,
    FanParameters,
    MixingPlenumParameters,
    Node,
    NodeType,
    PressureOutputParameters,
    Project,
    RigidDuctParameters,
    Scenario,
)

# ── Constants ─────────────────────────────────────────────────────────

FLOW_EXPONENT = 1.9        # Turbulent duct flow exponent
CONVERGENCE_TOL = 0.1      # CFM — stop when max |delta_Q| < this
MAX_ITERATIONS = 500
MIN_FLOW_LINEAR = 1.0      # CFM — below this, linearise the h(Q) curve


# ── Internal graph representation ─────────────────────────────────────

@dataclass
class _Element:
    """A single resistance element in the network graph.

    Each element connects two *junctions* (node IDs) and has a
    pressure-flow relationship.
    """
    id: str
    from_junc: str
    to_junc: str
    # Resistance parameters
    resistance: float = 0.0   # R in DP = R * |Q|^n
    fixed_loss: float = 0.0   # Constant pressure drop (in. w.g.)
    fan_rise: float = 0.0     # Pressure rise if this element is a fan
    flow: float = 0.0         # Current flow (CFM), positive = from -> to

    def head_loss(self) -> float:
        """Signed pressure drop across this element at current flow.

        Positive means pressure *decreases* in the from->to direction.
        Fan elements contribute a negative head loss (pressure rise).
        """
        hl = self.fixed_loss
        Q = self.flow
        if self.resistance > 0.0:
            if abs(Q) < MIN_FLOW_LINEAR:
                # Linearise around MIN_FLOW_LINEAR to keep derivative nonzero
                R_lin = self.resistance * abs(MIN_FLOW_LINEAR) ** (FLOW_EXPONENT - 1)
                hl += R_lin * Q
            else:
                hl += self.resistance * abs(Q) ** FLOW_EXPONENT * (1 if Q >= 0 else -1)
        hl -= self.fan_rise
        return hl

    def dhead_dflow(self) -> float:
        """Derivative d(head_loss)/d(Q) at current flow."""
        dh = 0.0
        Q = self.flow
        if self.resistance > 0.0:
            if abs(Q) < MIN_FLOW_LINEAR:
                dh += self.resistance * abs(MIN_FLOW_LINEAR) ** (FLOW_EXPONENT - 1)
            else:
                dh += self.resistance * FLOW_EXPONENT * abs(Q) ** (FLOW_EXPONENT - 1)
        # fixed_loss and fan_rise are constant w.r.t. Q
        return max(dh, 1e-12)  # guard against zero


# ── Result class (shared with BFS engine) ─────────────────────────────

@dataclass
class IterativeAnalysisResult:
    """Results from the iterative solver."""
    scenario_name: str = ""
    pressures: dict = field(default_factory=dict)   # node_id -> in.w.g.
    airflows: dict = field(default_factory=dict)     # node_id -> CFM
    element_flows: dict = field(default_factory=dict)  # element_id -> CFM
    iterations: int = 0
    converged: bool = False
    warnings: list = field(default_factory=list)


# ── Helper: build graph ───────────────────────────────────────────────

def _duct_resistance(length: float, diameter: float,
                     friction_rate: float) -> float:
    """Compute the resistance coefficient R such that DP = R * |Q|^n.

    The friction_rate is given at a *reference* flow.  We convert it to
    an absolute resistance by assuming the reference is for
    Q_ref = V_ref * A where V_ref produces the stated friction rate.

    For simplicity (matching the existing model), we treat
    friction_rate * length / 100 as the loss at Q = Q_ref and solve:
        R = (friction_rate * length / 100) / Q_ref^n

    We estimate Q_ref from the duct diameter using typical velocity of
    ~1000 fpm:
        A = pi * (D/24)^2   [ft^2, D in inches]
        Q_ref = 1000 * A    [CFM]

    This gives physically reasonable resistance that scales with flow.
    """
    if length <= 0 or friction_rate <= 0 or diameter <= 0:
        return 0.0
    area_ft2 = math.pi * (diameter / 24.0) ** 2
    q_ref = 1000.0 * area_ft2  # CFM at ~1000 fpm
    if q_ref < 1.0:
        q_ref = 1.0
    dp_ref = friction_rate * length / 100.0
    return dp_ref / (q_ref ** FLOW_EXPONENT)


def _get_node_fixed_loss(node: Node) -> float:
    """Return the fixed pressure loss for a node (0 if none)."""
    params = node.parameters
    if isinstance(params, (DamperParameters, MixingPlenumParameters,
                           DuctSplitParameters, DuctSinkSourceParameters)):
        return params.pressure_drop
    return 0.0


def _apply_scenario(project: Project, scenario: Scenario) -> dict:
    """Return fan_id -> effective FanParameters with scenario overrides."""
    effective = {}
    for nid, node in project.nodes.items():
        if node.node_type == NodeType.FAN:
            params = node.parameters
            if isinstance(params, FanParameters):
                airflow = params.airflow
                sp = params.static_pressure
                bhp = params.bhp
                if nid in scenario.fan_overrides:
                    ov = scenario.fan_overrides[nid]
                    airflow = ov.get("airflow", airflow)
                    sp = ov.get("static_pressure", sp)
                    bhp = ov.get("bhp", bhp)
                effective[nid] = FanParameters(bhp=bhp, static_pressure=sp,
                                               airflow=airflow)
    return effective


def _build_elements(project: Project,
                    effective_fans: dict) -> tuple[list[_Element], set[str]]:
    """Convert the project into a flat list of _Element objects.

    Returns (elements, junction_ids).

    Mapping strategy:
    - Each Connector becomes one element (duct friction resistance).
    - Each node that has a fixed pressure_drop (damper, plenum, etc.)
      or is a fan is turned into an element connecting a virtual
      "pre-node" junction to the real node junction.
    - Rigid Duct nodes become elements with duct resistance.
    - Pressure Output nodes are pass-through (zero loss).
    """
    elements: list[_Element] = []
    junctions: set[str] = set()

    # 1. Connector elements  (source_id -> target_id)
    for conn in project.connectors.values():
        R = _duct_resistance(conn.length, conn.diameter, conn.friction_rate)
        elements.append(_Element(
            id=f"conn_{conn.id}",
            from_junc=conn.source_id,
            to_junc=conn.target_id,
            resistance=R,
        ))
        junctions.add(conn.source_id)
        junctions.add(conn.target_id)

    # 2. Node-internal elements
    for nid, node in project.nodes.items():
        junctions.add(nid)

        if node.node_type == NodeType.FAN:
            fan_p = effective_fans.get(nid)
            if fan_p:
                # Fan element: virtual junction "fan_pre_<id>" -> nid
                pre = f"fan_pre_{nid}"
                junctions.add(pre)
                elements.append(_Element(
                    id=f"fan_{nid}",
                    from_junc=pre,
                    to_junc=nid,
                    fan_rise=fan_p.static_pressure,
                ))
                # Rewire all connectors that target this fan to point
                # at the virtual pre-junction instead
                for el in elements:
                    if el.to_junc == nid and el.id != f"fan_{nid}":
                        el.to_junc = pre

        elif node.node_type == NodeType.RIGID_DUCT:
            params = node.parameters
            if isinstance(params, RigidDuctParameters):
                # Rigid duct node acts as inline resistance
                pre = f"duct_pre_{nid}"
                junctions.add(pre)
                R = _duct_resistance(params.length, params.diameter,
                                     params.friction_rate)
                elements.append(_Element(
                    id=f"duct_{nid}",
                    from_junc=pre,
                    to_junc=nid,
                    resistance=R,
                ))
                # Rewire incoming connectors to the pre-junction
                for el in elements:
                    if el.to_junc == nid and el.id != f"duct_{nid}":
                        el.to_junc = pre

        else:
            fixed = _get_node_fixed_loss(node)
            if fixed > 0.0:
                pre = f"node_pre_{nid}"
                junctions.add(pre)
                elements.append(_Element(
                    id=f"node_{nid}",
                    from_junc=pre,
                    to_junc=nid,
                    fixed_loss=fixed,
                ))
                # Rewire incoming connectors to the pre-junction
                for el in elements:
                    if el.to_junc == nid and el.id != f"node_{nid}":
                        el.to_junc = pre

    return elements, junctions


# ── Loop detection via spanning tree ──────────────────────────────────

def _find_loops(elements: list[_Element],
                junctions: set[str]) -> list[list[tuple[_Element, int]]]:
    """Find independent loops using a spanning-tree approach.

    Returns a list of loops.  Each loop is a list of (element, direction)
    tuples where direction is +1 (element traversed from_junc->to_junc)
    or -1 (reversed).
    """
    if not elements or not junctions:
        return []

    # Build adjacency (undirected)
    adj: dict[str, list[tuple[str, _Element]]] = {j: [] for j in junctions}
    for el in elements:
        if el.from_junc in adj and el.to_junc in adj:
            adj[el.from_junc].append((el.to_junc, el))
            adj[el.to_junc].append((el.from_junc, el))

    # BFS spanning tree
    tree_edges: set[str] = set()
    parent: dict[str, str | None] = {}
    parent_element: dict[str, _Element | None] = {}
    visited: set[str] = set()
    non_tree: list[_Element] = []

    start = next(iter(junctions))
    queue = deque([start])
    visited.add(start)
    parent[start] = None
    parent_element[start] = None

    while queue:
        u = queue.popleft()
        for v, el in adj[u]:
            if v not in visited:
                visited.add(v)
                parent[v] = u
                parent_element[v] = el
                tree_edges.add(el.id)
                queue.append(v)

    # Non-tree (chord) edges define independent loops
    for el in elements:
        if el.id not in tree_edges:
            non_tree.append(el)

    loops = []
    for chord in non_tree:
        # Find path from chord.from_junc to chord.to_junc in the tree
        path_a = _path_to_root(chord.from_junc, parent)
        path_b = _path_to_root(chord.to_junc, parent)
        if path_a is None or path_b is None:
            continue

        # Find the common ancestor
        set_a = set(path_a)
        lca = None
        for node in path_b:
            if node in set_a:
                lca = node
                break
        if lca is None:
            continue

        # Build loop: from_junc -> lca <- to_junc + chord
        loop_elements: list[tuple[_Element, int]] = []

        # Forward path: from_junc up to lca
        cur = chord.from_junc
        while cur != lca:
            p = parent[cur]
            el = parent_element[cur]
            if el is not None:
                direction = +1 if el.to_junc == cur else -1
                loop_elements.append((el, direction))
            cur = p

        # Reverse path: to_junc up to lca (add in reverse)
        reverse_part: list[tuple[_Element, int]] = []
        cur = chord.to_junc
        while cur != lca:
            p = parent[cur]
            el = parent_element[cur]
            if el is not None:
                direction = -1 if el.to_junc == cur else +1
                reverse_part.append((el, direction))
            cur = p
        loop_elements.extend(reversed(reverse_part))

        # Add the chord itself (traversed from from_junc to to_junc = +1)
        loop_elements.append((chord, +1))

        if loop_elements:
            loops.append(loop_elements)

    return loops


def _path_to_root(node: str, parent: dict) -> list[str] | None:
    """Walk from *node* to the spanning-tree root, return the path."""
    path = []
    cur = node
    seen = set()
    while cur is not None:
        if cur in seen:
            return None  # cycle guard
        seen.add(cur)
        path.append(cur)
        cur = parent.get(cur)
    return path


# ── Initial flow assignment ───────────────────────────────────────────

def _assign_initial_flows(elements: list[_Element],
                          junctions: set[str],
                          effective_fans: dict) -> None:
    """Assign an initial flow guess that satisfies continuity.

    Strategy: BFS from each fan, pushing the fan's rated airflow
    downstream and splitting evenly at branches.
    """
    # Build adjacency from elements (directed)
    out_adj: dict[str, list[_Element]] = {j: [] for j in junctions}
    for el in elements:
        if el.from_junc in out_adj:
            out_adj[el.from_junc].append(el)

    # Reset all flows
    for el in elements:
        el.flow = 0.0

    # Identify fan elements and seed flow
    fan_elements = [el for el in elements if el.fan_rise > 0]

    for fan_el in fan_elements:
        fan_id = fan_el.to_junc
        fan_p = effective_fans.get(fan_id)
        seed_flow = fan_p.airflow if fan_p else 1000.0

        visited: set[str] = set()
        queue = deque([(fan_el.from_junc, seed_flow)])
        fan_el.flow = seed_flow
        visited.add(fan_el.from_junc)

        while queue:
            junc, q = queue.popleft()
            downstream = [e for e in out_adj.get(junc, [])
                          if e.to_junc not in visited or e.to_junc == junc]
            # Filter to only unvisited targets (or the fan element itself)
            downstream = [e for e in out_adj.get(junc, [])
                          if e.to_junc not in visited]
            if not downstream:
                continue
            branch_q = q / len(downstream)
            for e in downstream:
                e.flow += branch_q
                visited.add(e.to_junc)
                queue.append((e.to_junc, branch_q))

    # Ensure every element has at least a small flow to avoid zero-division
    for el in elements:
        if el.flow == 0.0 and el.resistance > 0.0:
            el.flow = MIN_FLOW_LINEAR


# ── Branch balancing (for tree topologies) ────────────────────────────

def _downstream_resistance(el: _Element,
                           from_adj: dict[str, list[_Element]],
                           visited: set[str]) -> float:
    """Recursively sum resistance along a path from an element to leaf nodes.

    Returns the total effective resistance along the path.  At branches,
    parallel resistances are combined: 1/R_total = sum(1/R_i).
    """
    R = el.resistance
    if el.fixed_loss > 0:
        # Treat fixed loss as resistance at a nominal 1000 CFM
        R += el.fixed_loss / (1000.0 ** FLOW_EXPONENT)

    target = el.to_junc
    if target in visited:
        return R
    visited.add(target)

    children = [e for e in from_adj.get(target, []) if e.to_junc not in visited]
    if not children:
        return R

    if len(children) == 1:
        return R + _downstream_resistance(children[0], from_adj, visited.copy())

    # Parallel branches: 1/R_eff = sum(1/R_i)
    inv_sum = 0.0
    for child in children:
        r_child = _downstream_resistance(child, from_adj, visited.copy())
        if r_child > 0:
            inv_sum += 1.0 / r_child
        else:
            inv_sum += 1e12  # Near-zero resistance = huge conductance
    r_parallel = 1.0 / inv_sum if inv_sum > 0 else 0.0
    return R + r_parallel


def _balance_branches(elements: list[_Element],
                      junctions: set[str]) -> None:
    """Redistribute flows at branch junctions based on downstream resistance.

    For tree topologies (no loops), Hardy-Cross has no corrections to make.
    This function splits flow inversely proportional to downstream resistance
    at every branching junction, which gives a physically reasonable result.
    """
    from_adj: dict[str, list[_Element]] = {j: [] for j in junctions}
    to_adj: dict[str, list[_Element]] = {j: [] for j in junctions}
    for el in elements:
        if el.from_junc in from_adj:
            from_adj[el.from_junc].append(el)
        if el.to_junc in to_adj:
            to_adj[el.to_junc].append(el)

    # Find junctions with multiple outgoing elements (branches)
    for junc in junctions:
        outgoing = from_adj.get(junc, [])
        if len(outgoing) <= 1:
            continue

        # Total inflow to this junction
        incoming = to_adj.get(junc, [])
        total_inflow = sum(el.flow for el in incoming)
        if total_inflow <= 0:
            continue

        # Compute downstream resistance for each branch
        branch_R: list[float] = []
        for el in outgoing:
            r = _downstream_resistance(el, from_adj, {junc})
            branch_R.append(max(r, 1e-20))

        # Split flow inversely proportional to resistance
        # Q_i proportional to 1/R_i^(1/n) where n = FLOW_EXPONENT
        conductances = [1.0 / (r ** (1.0 / FLOW_EXPONENT)) for r in branch_R]
        total_cond = sum(conductances)
        if total_cond <= 0:
            continue

        for el, cond in zip(outgoing, conductances):
            branch_flow = total_inflow * (cond / total_cond)
            _set_downstream_flow(el, branch_flow, from_adj, set())


def _set_downstream_flow(el: _Element, flow: float,
                         from_adj: dict[str, list[_Element]],
                         visited: set[str]) -> None:
    """Set flow on an element and propagate downstream."""
    el.flow = flow
    target = el.to_junc
    if target in visited:
        return
    visited.add(target)

    children = from_adj.get(target, [])
    if len(children) == 1:
        _set_downstream_flow(children[0], flow, from_adj, visited)
    elif len(children) > 1:
        # Compute downstream resistance for sub-branches
        branch_R = []
        for child in children:
            r = _downstream_resistance(child, from_adj, {target})
            branch_R.append(max(r, 1e-20))
        conductances = [1.0 / (r ** (1.0 / FLOW_EXPONENT)) for r in branch_R]
        total_cond = sum(conductances)
        if total_cond > 0:
            for child, cond in zip(children, conductances):
                child_flow = flow * (cond / total_cond)
                _set_downstream_flow(child, child_flow, from_adj, visited.copy())


# ── Hardy-Cross iteration ─────────────────────────────────────────────

def _iterate(elements: list[_Element],
             loops: list[list[tuple[_Element, int]]]) -> tuple[int, bool]:
    """Run the Hardy-Cross iteration loop.

    Returns (iterations_used, converged).
    """
    if not loops:
        return 0, True  # No loops means branch-balancing already handled it

    for iteration in range(1, MAX_ITERATIONS + 1):
        max_correction = 0.0

        for loop in loops:
            sum_h = 0.0
            sum_dh = 0.0
            for el, direction in loop:
                h = el.head_loss() * direction
                dh = el.dhead_dflow()
                sum_h += h
                sum_dh += dh

            if sum_dh < 1e-15:
                continue

            delta_q = -sum_h / sum_dh

            # Apply relaxation for stability
            if abs(delta_q) > 5000:
                delta_q = 5000 * (1 if delta_q > 0 else -1)

            for el, direction in loop:
                el.flow += delta_q * direction

            max_correction = max(max_correction, abs(delta_q))

        if max_correction < CONVERGENCE_TOL:
            return iteration, True

    return MAX_ITERATIONS, False


# ── Pressure assignment (post-convergence) ────────────────────────────

def _compute_pressures(elements: list[_Element],
                       junctions: set[str],
                       effective_fans: dict,
                       project: Project) -> dict[str, float]:
    """BFS from fans to compute absolute pressures using converged flows.

    The fan's discharge junction gets pressure = fan SP rise above
    whatever arrives at the inlet.  We set the "atmosphere" reference
    at fan inlets to 0 so that the fan discharge starts at +SP.
    """
    pressures: dict[str, float] = {}

    # Build adjacency
    from_adj: dict[str, list[_Element]] = {j: [] for j in junctions}
    to_adj: dict[str, list[_Element]] = {j: [] for j in junctions}
    for el in elements:
        if el.from_junc in from_adj:
            from_adj[el.from_junc].append(el)
        if el.to_junc in to_adj:
            to_adj[el.to_junc].append(el)

    # Identify fan discharge junctions and seed pressures
    fan_elements = {el.to_junc: el for el in elements if el.fan_rise > 0}

    # Seed fan pre-junctions at 0.0 (atmospheric reference)
    for el in elements:
        if el.fan_rise > 0:
            pressures[el.from_junc] = 0.0

    # BFS outward from seeded junctions
    visited: set[str] = set()
    queue: deque[str] = deque()

    for junc in list(pressures.keys()):
        visited.add(junc)
        queue.append(junc)

    while queue:
        junc = queue.popleft()
        p_here = pressures[junc]

        # Follow elements leaving this junction
        for el in from_adj.get(junc, []):
            target = el.to_junc
            p_target = p_here - el.head_loss()
            if target not in pressures:
                pressures[target] = p_target
            else:
                # Take the value from the path that arrived first
                # (or average for more accuracy)
                pass
            if target not in visited:
                visited.add(target)
                queue.append(target)

        # Also follow elements arriving at this junction (reverse)
        for el in to_adj.get(junc, []):
            source = el.from_junc
            # p_source = p_here + head_loss (since going backwards)
            p_source = p_here + el.head_loss()
            if source not in pressures:
                pressures[source] = p_source
            if source not in visited:
                visited.add(source)
                queue.append(source)

    return pressures


# ── Public API ────────────────────────────────────────────────────────

def run_iterative_analysis(project: Project,
                           scenario: Scenario | None = None) -> IterativeAnalysisResult:
    """Run a Hardy-Cross iterative analysis on the duct network.

    This solver automatically balances airflow across all paths based on
    their resistance, then computes pressures at every node.
    """
    if scenario is None:
        scenario = Scenario(name="Baseline")

    result = IterativeAnalysisResult(scenario_name=scenario.name)
    effective_fans = _apply_scenario(project, scenario)

    fan_nodes = [n for n in project.nodes.values()
                 if n.node_type == NodeType.FAN]
    if not fan_nodes:
        result.warnings.append("No fan nodes found in the network.")
        return result

    # Build internal graph
    elements, junctions = _build_elements(project, effective_fans)

    if not elements:
        result.warnings.append("No elements in the network.")
        return result

    # Initial flow guess
    _assign_initial_flows(elements, junctions, effective_fans)

    # Balance branches based on downstream resistance (important for trees)
    _balance_branches(elements, junctions)

    # Detect loops
    loops = _find_loops(elements, junctions)

    # Iterate (corrects flows in looped networks)
    iters, converged = _iterate(elements, loops)
    result.iterations = iters
    result.converged = converged
    if not converged:
        result.warnings.append(
            f"Solver did not converge after {MAX_ITERATIONS} iterations "
            f"(tolerance={CONVERGENCE_TOL} CFM)."
        )

    # Compute pressures from converged flows
    pressures = _compute_pressures(elements, junctions, effective_fans,
                                   project)

    # Map back to project node IDs
    for nid in project.nodes:
        if nid in pressures:
            result.pressures[nid] = round(pressures[nid], 4)

    # Map airflows: for each real node, the flow is the sum of incoming
    # element flows (or outgoing, by conservation they should be equal)
    for nid in project.nodes:
        inflow = 0.0
        for el in elements:
            if el.to_junc == nid:
                inflow += el.flow
        if inflow != 0.0:
            result.airflows[nid] = round(abs(inflow), 1)
        else:
            # Try outflow
            outflow = 0.0
            for el in elements:
                if el.from_junc == nid:
                    outflow += el.flow
            if outflow != 0.0:
                result.airflows[nid] = round(abs(outflow), 1)

    # Element flows for detailed reporting
    for el in elements:
        result.element_flows[el.id] = round(el.flow, 1)

    return result


def run_all_iterative(project: Project) -> list[IterativeAnalysisResult]:
    """Run the iterative analysis for every scenario."""
    if not project.scenarios:
        return [run_iterative_analysis(project)]
    return [run_iterative_analysis(project, s) for s in project.scenarios]
