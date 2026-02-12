"""Tests for core data models."""

import unittest

from static_pressure_analysis.models import (
    Connector,
    DamperParameters,
    FanParameters,
    MixingPlenumParameters,
    Node,
    NodeType,
    Project,
)


class TestNode(unittest.TestCase):
    def test_fan_default_params(self):
        node = Node(node_type=NodeType.FAN)
        self.assertIsInstance(node.parameters, FanParameters)
        self.assertEqual(node.parameters.bhp, 0.0)

    def test_damper_default_params(self):
        node = Node(node_type=NodeType.DAMPER)
        self.assertIsInstance(node.parameters, DamperParameters)

    def test_auto_name(self):
        node = Node(node_type=NodeType.FAN)
        self.assertTrue(node.name.startswith("Fan_"))


class TestConnector(unittest.TestCase):
    def test_pressure_drop_zero_length(self):
        c = Connector(length=0, friction_rate=0.08)
        self.assertEqual(c.pressure_drop, 0.0)

    def test_pressure_drop(self):
        c = Connector(length=100, friction_rate=0.08)
        self.assertAlmostEqual(c.pressure_drop, 0.08)

    def test_pressure_drop_200ft(self):
        c = Connector(length=200, friction_rate=0.1)
        self.assertAlmostEqual(c.pressure_drop, 0.2)


class TestProject(unittest.TestCase):
    def test_add_remove_node(self):
        p = Project()
        n = Node(node_type=NodeType.FAN)
        p.add_node(n)
        self.assertIn(n.id, p.nodes)
        p.remove_node(n.id)
        self.assertNotIn(n.id, p.nodes)

    def test_remove_node_removes_connectors(self):
        p = Project()
        n1 = Node(node_type=NodeType.FAN)
        n2 = Node(node_type=NodeType.DAMPER)
        p.add_node(n1)
        p.add_node(n2)
        c = Connector(source_id=n1.id, target_id=n2.id)
        p.add_connector(c)
        self.assertIn(c.id, p.connectors)
        p.remove_node(n1.id)
        self.assertNotIn(c.id, p.connectors)

    def test_get_downstream_nodes(self):
        p = Project()
        n1 = Node(node_type=NodeType.FAN)
        n2 = Node(node_type=NodeType.DAMPER)
        p.add_node(n1)
        p.add_node(n2)
        p.add_connector(Connector(source_id=n1.id, target_id=n2.id))
        downstream = p.get_downstream_nodes(n1.id)
        self.assertEqual(len(downstream), 1)
        self.assertEqual(downstream[0].id, n2.id)


if __name__ == "__main__":
    unittest.main()
