"""Tests for the Hardy-Cross iterative network solver."""

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
    RigidDuctParameters,
    Scenario,
)
from static_pressure_analysis.analysis_iterative import (
    run_iterative_analysis,
    run_all_iterative,
    _duct_resistance,
)


class TestDuctResistance(unittest.TestCase):
    """Verify the resistance coefficient calculation."""

    def test_zero_length_zero_resistance(self):
        self.assertEqual(_duct_resistance(0, 12, 0.08), 0.0)

    def test_positive_resistance(self):
        R = _duct_resistance(100, 12, 0.08)
        self.assertGreater(R, 0.0)

    def test_longer_duct_higher_resistance(self):
        R1 = _duct_resistance(100, 12, 0.08)
        R2 = _duct_resistance(200, 12, 0.08)
        self.assertGreater(R2, R1)

    def test_larger_diameter_lower_resistance(self):
        R_small = _duct_resistance(100, 8, 0.08)
        R_large = _duct_resistance(100, 18, 0.08)
        self.assertGreater(R_small, R_large)


class TestSimpleLinearNetwork(unittest.TestCase):
    """Fan -> Duct -> Damper -> Duct -> Pressure Output

    With a single path and no branches, the solver should produce
    results consistent with the BFS engine (pressure decreasing
    downstream).
    """

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

        self.project.add_connector(Connector(
            source_id=self.fan.id, target_id=self.damper.id,
            length=50, diameter=12, friction_rate=0.08,
        ))
        self.project.add_connector(Connector(
            source_id=self.damper.id, target_id=self.sp_out.id,
            length=100, diameter=12, friction_rate=0.08,
        ))

    def test_converges(self):
        result = run_iterative_analysis(self.project)
        self.assertTrue(result.converged)

    def test_fan_has_highest_pressure(self):
        result = run_iterative_analysis(self.project)
        self.assertIn(self.fan.id, result.pressures)
        self.assertIn(self.sp_out.id, result.pressures)
        self.assertGreater(
            result.pressures[self.fan.id],
            result.pressures[self.sp_out.id],
        )

    def test_pressure_decreases_downstream(self):
        result = run_iterative_analysis(self.project)
        p_fan = result.pressures[self.fan.id]
        p_damper = result.pressures[self.damper.id]
        p_out = result.pressures[self.sp_out.id]
        self.assertGreater(p_fan, p_damper)
        self.assertGreater(p_damper, p_out)

    def test_airflow_assigned(self):
        result = run_iterative_analysis(self.project)
        self.assertIn(self.fan.id, result.airflows)
        self.assertGreater(result.airflows[self.fan.id], 0)


class TestDuctSplitNetwork(unittest.TestCase):
    """Fan -> Duct Split -> two branches with different lengths.

    The iterative solver should auto-balance: more flow goes through
    the shorter (lower-resistance) branch.
    """

    def setUp(self):
        self.project = Project()
        self.fan = Node(
            node_type=NodeType.FAN,
            parameters=FanParameters(static_pressure=3.0, airflow=10000),
        )
        self.split = Node(
            node_type=NodeType.DUCT_SPLIT,
            parameters=DuctSplitParameters(pressure_drop=0.0),
        )
        self.sp_short = Node(
            node_type=NodeType.PRESSURE_OUTPUT,
            parameters=PressureOutputParameters(label="Short"),
        )
        self.sp_long = Node(
            node_type=NodeType.PRESSURE_OUTPUT,
            parameters=PressureOutputParameters(label="Long"),
        )
        for n in [self.fan, self.split, self.sp_short, self.sp_long]:
            self.project.add_node(n)

        # Fan -> Split
        self.project.add_connector(Connector(
            source_id=self.fan.id, target_id=self.split.id,
            length=10, diameter=18, friction_rate=0.08,
        ))
        # Split -> Short branch (50 ft)
        self.project.add_connector(Connector(
            source_id=self.split.id, target_id=self.sp_short.id,
            length=50, diameter=12, friction_rate=0.08,
        ))
        # Split -> Long branch (200 ft)
        self.project.add_connector(Connector(
            source_id=self.split.id, target_id=self.sp_long.id,
            length=200, diameter=12, friction_rate=0.08,
        ))

    def test_converges(self):
        result = run_iterative_analysis(self.project)
        self.assertTrue(result.converged)

    def test_more_flow_through_shorter_branch(self):
        """The shorter duct should carry more airflow."""
        result = run_iterative_analysis(self.project)
        af_short = result.airflows.get(self.sp_short.id, 0)
        af_long = result.airflows.get(self.sp_long.id, 0)
        self.assertGreater(af_short, af_long,
                           "Shorter branch should carry more airflow")

    def test_total_flow_conserved(self):
        """Total branch airflow should approximate the fan's rated flow."""
        result = run_iterative_analysis(self.project)
        af_short = result.airflows.get(self.sp_short.id, 0)
        af_long = result.airflows.get(self.sp_long.id, 0)
        total = af_short + af_long
        # Should be reasonably close to 10000 CFM
        self.assertGreater(total, 5000)
        self.assertLess(total, 20000)


class TestRigidDuctNode(unittest.TestCase):
    """Fan -> Rigid Duct (riser) -> Pressure Output

    Verify that a Rigid Duct node adds pressure loss proportional
    to its length/diameter/friction.
    """

    def setUp(self):
        self.project = Project()
        self.fan = Node(
            node_type=NodeType.FAN,
            parameters=FanParameters(static_pressure=2.0, airflow=3000),
        )
        self.riser = Node(
            node_type=NodeType.RIGID_DUCT,
            parameters=RigidDuctParameters(
                length=100, diameter=14, friction_rate=0.08, elevation=50,
            ),
        )
        self.sp_out = Node(
            node_type=NodeType.PRESSURE_OUTPUT,
            parameters=PressureOutputParameters(label="Top"),
        )
        for n in [self.fan, self.riser, self.sp_out]:
            self.project.add_node(n)

        # Short connectors (zero-length) to isolate the riser's effect
        self.project.add_connector(Connector(
            source_id=self.fan.id, target_id=self.riser.id,
            length=0, diameter=14, friction_rate=0.08,
        ))
        self.project.add_connector(Connector(
            source_id=self.riser.id, target_id=self.sp_out.id,
            length=0, diameter=14, friction_rate=0.08,
        ))

    def test_converges(self):
        result = run_iterative_analysis(self.project)
        self.assertTrue(result.converged)

    def test_riser_causes_pressure_drop(self):
        result = run_iterative_analysis(self.project)
        p_fan = result.pressures[self.fan.id]
        p_out = result.pressures[self.sp_out.id]
        self.assertGreater(p_fan, p_out,
                           "Riser should cause a pressure drop")


class TestToiletExhaustGXFanRiser(unittest.TestCase):
    """
    Real-world scenario: Toilet exhaust fan feeding into a GX fan which
    ALSO pulls from a duct riser.

    Network topology:
        Toilet Exhaust Fan ---+
                              |---> GX Fan ---> Pressure Output
        Riser (Rigid Duct) ---+

    The toilet exhaust fan creates positive pressure in the shared
    junction, while the GX fan creates suction.  The solver should
    find the balance point and show the pressure effect on the riser.
    """

    def setUp(self):
        self.project = Project()

        # Toilet exhaust fan (small, pushes air into main)
        self.toilet_fan = Node(
            node_type=NodeType.FAN,
            parameters=FanParameters(
                bhp=0.5, static_pressure=0.75, airflow=200,
            ),
        )
        # GX fan (larger, pulls from both sources)
        self.gx_fan = Node(
            node_type=NodeType.FAN,
            parameters=FanParameters(
                bhp=3.0, static_pressure=2.0, airflow=2000,
            ),
        )
        # Mixing plenum where toilet exhaust and riser meet
        self.plenum = Node(
            node_type=NodeType.MIXING_PLENUM,
            parameters=MixingPlenumParameters(pressure_drop=0.05),
        )
        # Riser as a rigid duct node (vertical shaft)
        self.riser = Node(
            node_type=NodeType.RIGID_DUCT,
            parameters=RigidDuctParameters(
                length=60, diameter=16, friction_rate=0.06, elevation=60,
            ),
        )
        # Pressure measurement at top of riser
        self.riser_tap = Node(
            node_type=NodeType.PRESSURE_OUTPUT,
            parameters=PressureOutputParameters(label="Riser SP"),
        )
        # Exhaust output
        self.exhaust_out = Node(
            node_type=NodeType.PRESSURE_OUTPUT,
            parameters=PressureOutputParameters(label="Exhaust Out"),
        )

        for n in [self.toilet_fan, self.gx_fan, self.plenum,
                  self.riser, self.riser_tap, self.exhaust_out]:
            self.project.add_node(n)

        # Toilet fan -> Plenum  (short duct)
        self.project.add_connector(Connector(
            source_id=self.toilet_fan.id, target_id=self.plenum.id,
            length=20, diameter=8, friction_rate=0.1,
        ))
        # Riser -> Riser tap (measure before it enters plenum)
        self.project.add_connector(Connector(
            source_id=self.riser.id, target_id=self.riser_tap.id,
            length=5, diameter=16, friction_rate=0.06,
        ))
        # Riser tap -> Plenum  (connects riser path to the plenum)
        self.project.add_connector(Connector(
            source_id=self.riser_tap.id, target_id=self.plenum.id,
            length=5, diameter=16, friction_rate=0.06,
        ))
        # Plenum -> GX Fan
        self.project.add_connector(Connector(
            source_id=self.plenum.id, target_id=self.gx_fan.id,
            length=10, diameter=18, friction_rate=0.06,
        ))
        # GX Fan -> Exhaust Output
        self.project.add_connector(Connector(
            source_id=self.gx_fan.id, target_id=self.exhaust_out.id,
            length=30, diameter=18, friction_rate=0.06,
        ))
        # Atmosphere -> Riser inlet (represented by a zero-length connector
        # from the riser node — the riser is open to atmosphere at the bottom)
        # The riser node itself carries the duct loss

    def test_converges(self):
        result = run_iterative_analysis(self.project)
        self.assertTrue(result.converged,
                        f"Warnings: {result.warnings}")

    def test_gx_fan_has_pressure(self):
        result = run_iterative_analysis(self.project)
        self.assertIn(self.gx_fan.id, result.pressures)
        # GX fan discharge should be positive (above atmospheric ref)
        self.assertGreater(result.pressures[self.gx_fan.id], 0)

    def test_riser_has_pressure_reading(self):
        result = run_iterative_analysis(self.project)
        self.assertIn(self.riser_tap.id, result.pressures)
        # The riser measurement should exist — this is the key result
        # the user wants: "what is the static pressure effect on the riser?"

    def test_riser_pressure_different_from_fan(self):
        """The riser should show a different pressure than the GX fan
        discharge — it's upstream and on a different resistance path."""
        result = run_iterative_analysis(self.project)
        p_riser = result.pressures.get(self.riser_tap.id, 0)
        p_gx = result.pressures.get(self.gx_fan.id, 0)
        self.assertNotAlmostEqual(p_riser, p_gx, places=1)

    def test_both_fans_contribute_airflow(self):
        """Both the toilet fan and the riser path should carry airflow."""
        result = run_iterative_analysis(self.project)
        af_toilet = result.airflows.get(self.toilet_fan.id, 0)
        af_gx = result.airflows.get(self.gx_fan.id, 0)
        self.assertGreater(af_toilet, 0, "Toilet fan should have airflow")
        self.assertGreater(af_gx, 0, "GX fan should have airflow")


class TestScenarioOverride(unittest.TestCase):
    """Verify scenario overrides work with the iterative solver."""

    def test_scenario_changes_pressure(self):
        project = Project()
        fan = Node(
            node_type=NodeType.FAN,
            parameters=FanParameters(static_pressure=2.0, airflow=4000),
        )
        sp = Node(node_type=NodeType.PRESSURE_OUTPUT)
        project.add_node(fan)
        project.add_node(sp)
        project.add_connector(Connector(
            source_id=fan.id, target_id=sp.id,
            length=50, diameter=12, friction_rate=0.08,
        ))

        baseline = run_iterative_analysis(project)
        override = Scenario(
            name="High",
            fan_overrides={fan.id: {"static_pressure": 4.0, "airflow": 8000}},
        )
        high = run_iterative_analysis(project, override)

        self.assertGreater(
            high.pressures[fan.id],
            baseline.pressures[fan.id],
        )


class TestRunAllIterative(unittest.TestCase):
    def test_multiple_scenarios(self):
        project = Project()
        fan = Node(
            node_type=NodeType.FAN,
            parameters=FanParameters(static_pressure=2.0, airflow=4000),
        )
        sp = Node(node_type=NodeType.PRESSURE_OUTPUT)
        project.add_node(fan)
        project.add_node(sp)
        project.add_connector(Connector(
            source_id=fan.id, target_id=sp.id,
            length=50, diameter=12, friction_rate=0.08,
        ))
        project.scenarios = [
            Scenario(name="Baseline"),
            Scenario(name="High", fan_overrides={
                fan.id: {"static_pressure": 3.0, "airflow": 6000},
            }),
        ]
        results = run_all_iterative(project)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.converged for r in results))


class TestNoFans(unittest.TestCase):
    def test_warning_when_no_fans(self):
        project = Project()
        result = run_iterative_analysis(project)
        self.assertTrue(len(result.warnings) > 0)


if __name__ == "__main__":
    unittest.main()
