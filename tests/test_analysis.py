"""Tests for the static pressure analysis engine."""

import unittest

from static_pressure_analysis.models import (
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
from static_pressure_analysis.analysis import run_analysis, run_all_scenarios


class TestSimpleNetwork(unittest.TestCase):
    """Fan -> Duct -> Damper -> Duct -> Pressure Output"""

    def setUp(self):
        self.project = Project()
        self.fan = Node(
            node_type=NodeType.FAN,
            parameters=FanParameters(bhp=5.0, static_pressure=2.5, airflow=5000),
        )
        self.damper = Node(
            node_type=NodeType.DAMPER,
            parameters=DamperParameters(pressure_drop=0.3),
        )
        self.sp_out = Node(
            node_type=NodeType.PRESSURE_OUTPUT,
            parameters=PressureOutputParameters(label="SP-1"),
        )
        self.project.add_node(self.fan)
        self.project.add_node(self.damper)
        self.project.add_node(self.sp_out)

        # Fan -> Damper: 50ft duct at 0.08/100ft
        self.duct1 = Connector(source_id=self.fan.id, target_id=self.damper.id,
                               length=50, friction_rate=0.08)
        # Damper -> SP output: 100ft duct
        self.duct2 = Connector(source_id=self.damper.id, target_id=self.sp_out.id,
                               length=100, friction_rate=0.08)
        self.project.add_connector(self.duct1)
        self.project.add_connector(self.duct2)

    def test_baseline_pressure(self):
        result = run_analysis(self.project)
        # Fan: 2.5 in.wg
        self.assertAlmostEqual(result.pressures[self.fan.id], 2.5)

        # After duct1 (50ft * 0.08/100 = 0.04) and damper (0.3):
        # 2.5 - 0.04 - 0.3 = 2.16
        self.assertAlmostEqual(result.pressures[self.damper.id], 2.16)

        # After duct2 (100ft * 0.08/100 = 0.08) and SP output (0 loss):
        # 2.16 - 0.08 - 0 = 2.08
        self.assertAlmostEqual(result.pressures[self.sp_out.id], 2.08)

    def test_airflow_propagation(self):
        result = run_analysis(self.project)
        self.assertEqual(result.airflows[self.fan.id], 5000)
        self.assertEqual(result.airflows[self.damper.id], 5000)
        self.assertEqual(result.airflows[self.sp_out.id], 5000)

    def test_scenario_override(self):
        scenario = Scenario(
            name="Low Flow",
            fan_overrides={self.fan.id: {"airflow": 3000, "static_pressure": 1.5}},
        )
        result = run_analysis(self.project, scenario)
        self.assertAlmostEqual(result.pressures[self.fan.id], 1.5)
        self.assertEqual(result.airflows[self.fan.id], 3000)


class TestDuctSplit(unittest.TestCase):
    """Fan -> Duct Split -> two branches."""

    def setUp(self):
        self.project = Project()
        self.fan = Node(
            node_type=NodeType.FAN,
            parameters=FanParameters(static_pressure=3.0, airflow=10000),
        )
        self.split = Node(
            node_type=NodeType.DUCT_SPLIT,
            parameters=DuctSplitParameters(pressure_drop=0.1),
        )
        self.sp1 = Node(node_type=NodeType.PRESSURE_OUTPUT,
                        parameters=PressureOutputParameters(label="Branch-A"))
        self.sp2 = Node(node_type=NodeType.PRESSURE_OUTPUT,
                        parameters=PressureOutputParameters(label="Branch-B"))

        for n in [self.fan, self.split, self.sp1, self.sp2]:
            self.project.add_node(n)

        # Fan -> Split (no duct loss)
        self.project.add_connector(Connector(
            source_id=self.fan.id, target_id=self.split.id, length=0))
        # Split -> SP1
        self.project.add_connector(Connector(
            source_id=self.split.id, target_id=self.sp1.id, length=100, friction_rate=0.1))
        # Split -> SP2
        self.project.add_connector(Connector(
            source_id=self.split.id, target_id=self.sp2.id, length=200, friction_rate=0.1))

    def test_airflow_split(self):
        result = run_analysis(self.project)
        # Split divides evenly between 2 branches
        self.assertEqual(result.airflows[self.sp1.id], 5000)
        self.assertEqual(result.airflows[self.sp2.id], 5000)

    def test_pressure_at_branches(self):
        result = run_analysis(self.project)
        # Fan: 3.0, split loss: 0.1 -> at split: 2.9
        self.assertAlmostEqual(result.pressures[self.split.id], 2.9)
        # SP1: 2.9 - (100*0.1/100) = 2.9 - 0.1 = 2.8
        self.assertAlmostEqual(result.pressures[self.sp1.id], 2.8)
        # SP2: 2.9 - (200*0.1/100) = 2.9 - 0.2 = 2.7
        self.assertAlmostEqual(result.pressures[self.sp2.id], 2.7)


class TestNoFans(unittest.TestCase):
    def test_warning_when_no_fans(self):
        project = Project()
        result = run_analysis(project)
        self.assertTrue(len(result.warnings) > 0)


class TestRunAllScenarios(unittest.TestCase):
    def test_multiple_scenarios(self):
        project = Project()
        fan = Node(node_type=NodeType.FAN,
                   parameters=FanParameters(static_pressure=2.0, airflow=4000))
        sp = Node(node_type=NodeType.PRESSURE_OUTPUT)
        project.add_node(fan)
        project.add_node(sp)
        project.add_connector(Connector(source_id=fan.id, target_id=sp.id, length=50, friction_rate=0.1))

        project.scenarios = [
            Scenario(name="Baseline"),
            Scenario(name="High Flow", fan_overrides={fan.id: {"airflow": 6000, "static_pressure": 3.0}}),
        ]
        results = run_all_scenarios(project)
        self.assertEqual(len(results), 2)
        self.assertAlmostEqual(results[0].pressures[fan.id], 2.0)
        self.assertAlmostEqual(results[1].pressures[fan.id], 3.0)


if __name__ == "__main__":
    unittest.main()
