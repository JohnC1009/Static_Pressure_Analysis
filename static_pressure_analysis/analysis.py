"""Static pressure analysis engine.

Traverses the duct network from each fan downstream, accumulating
pressure losses through connectors and nodes, and records the
resulting static pressure at every Pressure Output node.
"""

from dataclasses import dataclass, field

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


@dataclass
class AnalysisResult:
    """Results for a single scenario."""
    scenario_name: str = ""
    # node_id -> computed static pressure (in. w.g.)
    pressures: dict = field(default_factory=dict)
    # node_id -> airflow at that point (CFM)
    airflows: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def _get_node_pressure_drop(node: Node) -> float:
    """Return the pressure loss across a node."""
    params = node.parameters
    if isinstance(params, DamperParameters):
        return params.pressure_drop
    if isinstance(params, MixingPlenumParameters):
        return params.pressure_drop
    if isinstance(params, DuctSplitParameters):
        return params.pressure_drop
    return 0.0


def _apply_scenario(project: Project, scenario: Scenario) -> dict:
    """Return a dict of fan_id -> effective FanParameters with overrides applied."""
    effective = {}
    for nid, node in project.nodes.items():
        if node.node_type == NodeType.FAN:
            params = node.parameters
            if isinstance(params, FanParameters):
                airflow = params.airflow
                sp = params.static_pressure
                bhp = params.bhp
                if nid in scenario.fan_overrides:
                    overrides = scenario.fan_overrides[nid]
                    airflow = overrides.get("airflow", airflow)
                    sp = overrides.get("static_pressure", sp)
                    bhp = overrides.get("bhp", bhp)
                effective[nid] = FanParameters(bhp=bhp, static_pressure=sp, airflow=airflow)
    return effective


def run_analysis(project: Project, scenario: Scenario | None = None) -> AnalysisResult:
    """Run a static pressure analysis on the network for a given scenario.

    Algorithm:
    1. Identify all fan nodes as starting points.
    2. For each fan, set the initial static pressure to the fan's rated SP.
    3. Traverse downstream through connectors and nodes, subtracting
       pressure losses at each step.
    4. Record pressures at Pressure Output nodes.
    """
    if scenario is None:
        scenario = Scenario(name="Baseline")

    result = AnalysisResult(scenario_name=scenario.name)
    effective_fans = _apply_scenario(project, scenario)

    # Find all fan nodes
    fan_nodes = [
        n for n in project.nodes.values()
        if n.node_type == NodeType.FAN
    ]

    if not fan_nodes:
        result.warnings.append("No fan nodes found in the network.")
        return result

    # BFS from each fan
    for fan in fan_nodes:
        fan_params = effective_fans.get(fan.id)
        if fan_params is None:
            continue

        initial_sp = fan_params.static_pressure
        initial_airflow = fan_params.airflow

        # visited tracks node_id -> (static_pressure, airflow)
        visited = {}
        # queue: (node_id, current_sp, current_airflow)
        queue = [(fan.id, initial_sp, initial_airflow)]
        visited[fan.id] = (initial_sp, initial_airflow)
        result.pressures[fan.id] = initial_sp
        result.airflows[fan.id] = initial_airflow

        while queue:
            current_id, current_sp, current_airflow = queue.pop(0)
            downstream_conns = project.get_connections_from(current_id)

            # For duct splits, divide airflow among branches proportionally
            current_node = project.nodes.get(current_id)
            num_branches = len(downstream_conns)

            for conn in downstream_conns:
                # Pressure loss through the duct connector
                duct_loss = conn.pressure_drop

                target_id = conn.target_id
                target_node = project.nodes.get(target_id)
                if target_node is None:
                    continue

                # Pressure loss through the target node
                node_loss = _get_node_pressure_drop(target_node)

                sp_at_target = current_sp - duct_loss - node_loss

                # Airflow: if current node is a duct split, divide evenly
                # (users can adjust via scenario or connector properties)
                branch_airflow = current_airflow
                if current_node and current_node.node_type == NodeType.DUCT_SPLIT and num_branches > 1:
                    branch_airflow = current_airflow / num_branches

                # If target is a mixing plenum, airflow accumulates
                if target_node.node_type == NodeType.MIXING_PLENUM:
                    prev_af = result.airflows.get(target_id, 0.0)
                    branch_airflow = prev_af + branch_airflow
                    # Use the lowest incoming SP (conservative)
                    prev_sp = result.pressures.get(target_id)
                    if prev_sp is not None:
                        sp_at_target = min(sp_at_target, prev_sp)

                # If this is a fan node downstream (e.g., return fan feeding supply fan),
                # the fan adds pressure
                if target_node.node_type == NodeType.FAN:
                    fan_p = effective_fans.get(target_id)
                    if fan_p:
                        sp_at_target = sp_at_target + fan_p.static_pressure
                        branch_airflow = fan_p.airflow

                result.pressures[target_id] = sp_at_target
                result.airflows[target_id] = branch_airflow

                if target_id not in visited:
                    visited[target_id] = (sp_at_target, branch_airflow)
                    queue.append((target_id, sp_at_target, branch_airflow))

    return result


def run_all_scenarios(project: Project) -> list[AnalysisResult]:
    """Run analysis for every scenario in the project."""
    if not project.scenarios:
        return [run_analysis(project)]
    return [run_analysis(project, s) for s in project.scenarios]
