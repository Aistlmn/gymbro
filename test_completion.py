"""Imperfect webcam returns and false-count protection, using controlled geometry."""
import unittest
from dataclasses import replace

from motion import MotionCheck, LandmarkMotion
from squat import SquatTracker
from test_logic import metric
import test_motion


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.t = SquatTracker()
        self.now = 0

    def hold(self, m, duration, fps=30, motion=None):
        for _ in range(round(duration*fps)):
            self.now += 1/fps
            self.t.update(m,self.now,motion)

    def calibrate(self, knee=175):
        self.hold(replace(metric(),knee=knee),1.5)

    def crouch(self):
        self.hold(metric(100,-.2,180),.8)

    def test_return_below_legacy_knee_cutoff(self):
        self.calibrate()
        self.crouch()
        self.hold(replace(metric(),knee=160),1)
        self.assertEqual(self.t.reps,1)
        self.assertFalse(self.t.completion_debug['legacy_knee_ok'])
        self.hold(replace(metric(),knee=160),2)
        self.assertEqual(self.t.reps,1)

    def test_hip_offset_above_legacy_limit(self):
        self.calibrate()
        self.crouch()
        self.hold(metric(y=122),1)
        self.assertEqual(self.t.reps,1)
        self.assertFalse(self.t.completion_debug['legacy_hip_ok'])

    def test_calibration_adapts_to_projected_standing_angle(self):
        self.calibrate(162)
        self.assertEqual(self.t.return_knee,150)
        self.crouch()
        self.hold(replace(metric(y=120),knee=154),1)
        self.assertEqual(self.t.reps,1)

    def test_combined_imperfect_return_at_multiple_frame_rates(self):
        for fps in (10,15,30,60):
            with self.subTest(fps=fps):
                self.t = SquatTracker()
                self.now = 0
                self.hold(metric(),1.5,fps)
                self.hold(metric(100,-.2,180),.8,fps)
                self.hold(replace(metric(y=122),knee=160),1,fps)
                self.assertEqual(self.t.reps,1)

    def test_partial_return_does_not_count(self):
        self.calibrate()
        self.crouch()
        self.hold(replace(metric(y=140),knee=155),2)
        self.assertEqual(self.t.reps,0)
        self.assertFalse(self.t.completion_debug['hip_ok'])
        self.assertFalse(self.t.completion_debug['knee_ok'])

    def test_single_standing_spike_and_bouncing_not_counted(self):
        self.calibrate()
        self.crouch()
        for _ in range(5):
            self.hold(metric(),1/30)
            self.hold(metric(100,-.2,180),.2)
        self.assertEqual(self.t.reps,0)
        self.hold(metric(),1)
        self.assertEqual(self.t.reps,1)

    def test_small_dip_cannot_use_relaxed_return_to_count(self):
        self.calibrate()
        self.hold(metric(142,-.6,120),.8)
        self.hold(metric(),1)
        self.assertEqual(self.t.reps,0)
        self.assertEqual(self.t.last_event,'candidate_rejected_small_movement')

    def test_shallow_but_real_movement_above_legacy_bend_cutoff(self):
        self.calibrate()
        self.hold(metric(142,-.5,140),1.2)
        self.hold(metric(),1)
        self.assertEqual(self.t.reps,1)
        self.assertFalse(self.t.rep_results[0]['depth_target_met'])
        self.assertFalse(self.t.completion_debug['legacy_bend_ok'])

    def test_duration_gate_waits_instead_of_silently_discarding(self):
        self.calibrate()
        self.hold(metric(90,0,180),.1)
        self.hold(metric(),.1)
        self.assertEqual(self.t.reps,0)
        self.assertTrue(self.t.active)
        self.assertFalse(self.t.completion_debug['duration_ok'])
        self.hold(metric(),.6)
        self.assertEqual(self.t.reps,1)

    def test_diagnostics_identify_tracking_cancellation(self):
        self.calibrate()
        self.crouch()
        self.hold(metric(),1/30,motion=MotionCheck('inconsistent'))
        self.assertEqual(self.t.debug_snapshot(metric(),self.now)['last_event'],'flow_rejected')
        self.assertEqual(self.t.reps,0)
        self.t.update(None,self.now+1/30)
        self.assertEqual(self.t.last_event,'pose_lost')

    def test_hysteresis_tolerates_small_knee_jitter(self):
        self.calibrate()
        self.crouch()
        # Let the smoothed knee actually cross the entry threshold first.
        self.hold(replace(metric(),knee=160),.45)
        for i in range(15):
            self.hold(replace(metric(),knee=156 if i%2 else 159),1/30)
        self.assertEqual(self.t.reps,1)

    def test_two_noisy_flow_patches_do_not_veto_majority(self):
        fixture = test_motion.MotionTests()
        fixture.setUp()
        flow = LandmarkMotion()
        flow.update(fixture.frame,fixture.m,0,'left')
        points = fixture.points.copy()
        points[0:2] += [0,30]
        result = flow.update(fixture.frame,replace(fixture.m,points=points),1/30,'left')
        self.assertEqual(result.tracked,6)
        self.assertEqual(result.status,'consistent')


if __name__ == '__main__':
    unittest.main()
