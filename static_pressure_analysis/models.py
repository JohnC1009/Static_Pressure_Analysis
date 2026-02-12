"""Core data models for the static pressure analysis network."""

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class NodeType(Enum):
    FAN = "Fan"
    DAMPER = "Damper"
    MIXING_PLENUM = "Mixing Plenum"
    DUCT_SPLIT = "Duct Split"
    PRESSURE_OUTPUT = "Pressure Output"


@dataclass
class NodeParameters:
    """Base parameters shared by all nodes."""
    pass


@dataclass
class FanParameters(NodeParameters):
    bhp: float = 0.0            # Brake horsepower
    static_pressure: float = 0.0  # Inches of water gauge (in. w.g.)
    airflow: float = 0.0         # CFM


@dataclass
class DamperParameters(NodeParameters):
    pressure_drop: float = 0.0   # Inches of water gauge (in. w.g.)


@dataclass
class MixingPlenumParameters(NodeParameters):
    pressure_drop: float = 0.0   # in. w.g. loss through the plenum


@dataclass
class DuctSplitParameters(NodeParameters):
    """A duct split divides airflow among downstream branches.

    Split ratios are determined by the downstream connections and
    their associated airflow fractions.
    """
    pressure_drop: float = 0.0   # Fitting loss in. w.g.


@dataclass
class PressureOutputParameters(NodeParameters):
    """A measurement node that displays calculated static pressure."""
    label: str = "SP"


@dataclass
class Node:
    node_type: NodeType
    name: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    x: float = 0.0
    y: float = 0.0
    parameters: NodeParameters = field(default_factory=NodeParameters)

    def __post_init__(self):
        if not self.name:
            self.name = f"{self.node_type.value}_{self.id[:4]}"
        if isinstance(self.parameters, NodeParameters) and type(self.parameters) is NodeParameters:
            self.parameters = self._default_params()

    def _default_params(self) -> NodeParameters:
        defaults = {
            NodeType.FAN: FanParameters,
            NodeType.DAMPER: DamperParameters,
            NodeType.MIXING_PLENUM: MixingPlenumParameters,
            NodeType.DUCT_SPLIT: DuctSplitParameters,
            NodeType.PRESSURE_OUTPUT: PressureOutputParameters,
        }
        return defaults.get(self.node_type, NodeParameters)()


@dataclass
class Connector:
    """A duct connector between two nodes.

    Airflow travels from source_id to target_id.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    source_id: str = ""
    target_id: str = ""
    length: float = 0.0         # Feet
    diameter: float = 12.0      # Inches (equivalent round diameter)
    friction_rate: float = 0.08  # in. w.g. per 100 ft
    label: str = ""

    @property
    def pressure_drop(self) -> float:
        """Calculate duct friction loss: friction_rate * length / 100."""
        return self.friction_rate * self.length / 100.0


@dataclass
class Scenario:
    """An operating scenario with per-fan airflow overrides."""
    name: str = "Baseline"
    fan_overrides: dict = field(default_factory=dict)
    # fan_overrides maps fan node_id -> {"airflow": cfm, "static_pressure": sp}


@dataclass
class Project:
    """Top-level container for the entire network model."""
    name: str = "Untitled Project"
    nodes: dict = field(default_factory=dict)      # id -> Node
    connectors: dict = field(default_factory=dict)  # id -> Connector
    scenarios: list = field(default_factory=list)    # list of Scenario

    def add_node(self, node: Node) -> Node:
        self.nodes[node.id] = node
        return node

    def remove_node(self, node_id: str):
        self.nodes.pop(node_id, None)
        # Remove any connectors attached to this node
        to_remove = [
            cid for cid, c in self.connectors.items()
            if c.source_id == node_id or c.target_id == node_id
        ]
        for cid in to_remove:
            self.connectors.pop(cid, None)

    def add_connector(self, connector: Connector) -> Connector:
        self.connectors[connector.id] = connector
        return connector

    def remove_connector(self, connector_id: str):
        self.connectors.pop(connector_id, None)

    def get_connections_from(self, node_id: str) -> list:
        return [c for c in self.connectors.values() if c.source_id == node_id]

    def get_connections_to(self, node_id: str) -> list:
        return [c for c in self.connectors.values() if c.target_id == node_id]

    def get_upstream_nodes(self, node_id: str) -> list:
        """Return nodes that connect into the given node."""
        conns = self.get_connections_to(node_id)
        return [self.nodes[c.source_id] for c in conns if c.source_id in self.nodes]

    def get_downstream_nodes(self, node_id: str) -> list:
        """Return nodes that the given node connects to."""
        conns = self.get_connections_from(node_id)
        return [self.nodes[c.target_id] for c in conns if c.target_id in self.nodes]
