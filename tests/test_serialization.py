"""Tests for project serialization (save/load)."""

import json
import tempfile
import unittest
from pathlib import Path

from static_pressure_analysis.models import (
    Connector,
    DamperParameters,
    FanParameters,
    Node,
    NodeType,
    Project,
    Scenario,
)
from static_pressure_analysis.serialization import (
    dict_to_project,
    load_project,
    project_to_dict,
    save_project,
)


class TestSerialization(unittest.TestCase):
    def _make_project(self) -> Project:
        p = Project(name="Test")
        fan = Node(node_type=NodeType.FAN,
                   parameters=FanParameters(bhp=5, static_pressure=2.5, airflow=5000),
                   x=100, y=200)
        damper = Node(node_type=NodeType.DAMPER,
                      parameters=DamperParameters(pressure_drop=0.3),
                      x=300, y=200)
        p.add_node(fan)
        p.add_node(damper)
        p.add_connector(Connector(source_id=fan.id, target_id=damper.id, length=50))
        p.scenarios.append(Scenario(name="Low", fan_overrides={fan.id: {"airflow": 3000}}))
        return p

    def test_roundtrip_dict(self):
        p = self._make_project()
        d = project_to_dict(p)
        p2 = dict_to_project(d)
        self.assertEqual(p2.name, "Test")
        self.assertEqual(len(p2.nodes), 2)
        self.assertEqual(len(p2.connectors), 1)
        self.assertEqual(len(p2.scenarios), 1)

    def test_roundtrip_file(self):
        p = self._make_project()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        save_project(p, path)
        p2 = load_project(path)
        self.assertEqual(p2.name, "Test")
        self.assertEqual(len(p2.nodes), 2)
        # Verify fan parameters preserved
        fans = [n for n in p2.nodes.values() if n.node_type == NodeType.FAN]
        self.assertEqual(len(fans), 1)
        self.assertIsInstance(fans[0].parameters, FanParameters)
        self.assertEqual(fans[0].parameters.airflow, 5000)
        Path(path).unlink()

    def test_serialized_json_is_valid(self):
        p = self._make_project()
        d = project_to_dict(p)
        s = json.dumps(d)
        d2 = json.loads(s)
        self.assertEqual(d, d2)


if __name__ == "__main__":
    unittest.main()
