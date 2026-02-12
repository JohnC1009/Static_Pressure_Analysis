"""Save and load project files as JSON."""

import json
from pathlib import Path

from .models import (
    Connector,
    DamperParameters,
    DuctSplitParameters,
    FanParameters,
    MixingPlenumParameters,
    Node,
    NodeParameters,
    NodeType,
    PressureOutputParameters,
    Project,
    Scenario,
)

_PARAM_TYPE_MAP = {
    "FanParameters": FanParameters,
    "DamperParameters": DamperParameters,
    "MixingPlenumParameters": MixingPlenumParameters,
    "DuctSplitParameters": DuctSplitParameters,
    "PressureOutputParameters": PressureOutputParameters,
}


def _serialize_params(params: NodeParameters) -> dict:
    d = {"_type": type(params).__name__}
    d.update(vars(params))
    return d


def _deserialize_params(d: dict) -> NodeParameters:
    ptype = d.pop("_type", "NodeParameters")
    cls = _PARAM_TYPE_MAP.get(ptype, NodeParameters)
    return cls(**d)


def project_to_dict(project: Project) -> dict:
    nodes = {}
    for nid, node in project.nodes.items():
        nodes[nid] = {
            "node_type": node.node_type.value,
            "name": node.name,
            "id": node.id,
            "x": node.x,
            "y": node.y,
            "parameters": _serialize_params(node.parameters),
        }

    connectors = {}
    for cid, conn in project.connectors.items():
        connectors[cid] = {
            "id": conn.id,
            "source_id": conn.source_id,
            "target_id": conn.target_id,
            "length": conn.length,
            "diameter": conn.diameter,
            "friction_rate": conn.friction_rate,
            "label": conn.label,
        }

    scenarios = []
    for s in project.scenarios:
        scenarios.append({
            "name": s.name,
            "fan_overrides": s.fan_overrides,
        })

    return {
        "name": project.name,
        "nodes": nodes,
        "connectors": connectors,
        "scenarios": scenarios,
    }


def dict_to_project(d: dict) -> Project:
    project = Project(name=d.get("name", "Untitled"))

    for nid, ndata in d.get("nodes", {}).items():
        node_type = NodeType(ndata["node_type"])
        params = _deserialize_params(ndata.get("parameters", {}))
        node = Node(
            node_type=node_type,
            name=ndata.get("name", ""),
            id=ndata.get("id", nid),
            x=ndata.get("x", 0),
            y=ndata.get("y", 0),
            parameters=params,
        )
        project.nodes[node.id] = node

    for cid, cdata in d.get("connectors", {}).items():
        conn = Connector(
            id=cdata.get("id", cid),
            source_id=cdata.get("source_id", ""),
            target_id=cdata.get("target_id", ""),
            length=cdata.get("length", 0),
            diameter=cdata.get("diameter", 12),
            friction_rate=cdata.get("friction_rate", 0.08),
            label=cdata.get("label", ""),
        )
        project.connectors[conn.id] = conn

    for sdata in d.get("scenarios", []):
        project.scenarios.append(Scenario(
            name=sdata.get("name", ""),
            fan_overrides=sdata.get("fan_overrides", {}),
        ))

    return project


def save_project(project: Project, filepath: str | Path):
    filepath = Path(filepath)
    with open(filepath, "w") as f:
        json.dump(project_to_dict(project), f, indent=2)


def load_project(filepath: str | Path) -> Project:
    filepath = Path(filepath)
    with open(filepath, "r") as f:
        data = json.load(f)
    return dict_to_project(data)
