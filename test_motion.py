"""Real OpenCV flow on controlled pixels, plus counter reliability integration."""
from dataclasses import replace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from geometry import Metrics
from motion import LandmarkMotion, MotionCheck
from squat import SquatTracker


class MotionTests(unittest.TestCase):
    def setUp(self):
        # Deterministic textured image: actual LK, no downloaded test fixtures.
        rng = np.random.default_rng(42)
        gray = rng.integers(0, 256, (240, 320), dtype=np.uint8)
        self.frame = cv2.cvtColor(cv2.GaussianBlur(gray, (3,3), 0), cv2.COLOR_GRAY2BGR)
        self.points = np.float32([(80,50),(100,90),(120,130),(100,180),(80,195),(135,195)])
        self.m = Metrics(175,175,-1,90,100,0,self.points.tolist())
        self.flow = LandmarkMotion()

    def translated(self, dx, dy):
        frame = cv2.warpAffine(self.frame, np.float32([[1,0,dx],[0,1,dy]]), (320,240))
        return frame, replace(self.m, points=(self.points+[dx,dy]).tolist())

    def test_actual_lk_translation_and_stationary(self):
        for dx,dy in [(0,0),(4,6),(-3,-5)]:
            with self.subTest(dx=dx,dy=dy):
                self.flow.reset()
                self.assertEqual(self.flow.update(self.frame,self.m,0,'left').status,'unavailable')
                frame,m = self.translated(dx,dy)
                result = self.flow.update(frame,m,1/30,'left')
                self.assertEqual(result.status,'consistent')
                # Forward/backward filtering may discard individual patches.
                self.assertGreaterEqual(result.tracked,3)
                self.assertAlmostEqual(result.displacement_px,float(np.hypot(dx,dy)),delta=.3)
                self.assertLess(result.disagreement_px,.3)

    def test_pose_jump_on_stationary_pixels_rejected(self):
        self.flow.update(self.frame,self.m,0,'left')
        jumped = replace(self.m, points=(self.points+[0,30]).tolist())
        result = self.flow.update(self.frame,jumped,1/30,'left')
        self.assertEqual(result.status,'inconsistent')
        self.assertLess(result.displacement_px,.1)
        self.assertGreater(result.disagreement_px,29)
        self.assertIsNone(self.flow.previous)

    def test_single_noisy_landmark_does_not_cancel(self):
        self.flow.update(self.frame,self.m,0,'left')
        points = self.points.copy()
        points[1] += [0,30]
        result = self.flow.update(self.frame,replace(self.m,points=points),1/30,'left')
        self.assertEqual(result.status,'consistent')

    def test_textureless_fallback(self):
        blank = np.zeros_like(self.frame)
        self.flow.update(blank,self.m,0,'left')
        result = self.flow.update(blank,self.m,1/30,'left')
        self.assertEqual(result.status,'unavailable')
        self.assertEqual(result.tracked,0)

    def test_reverse_check_rejects_unreliable_tracks(self):
        self.flow.update(self.frame,self.m,0,'left')
        pts = self.points.reshape(-1,1,2)
        status = np.ones((6,1),np.uint8)
        errors = np.zeros((6,1),np.float32)
        with patch('motion.cv2.calcOpticalFlowPyrLK',side_effect=[
                (pts,status,errors),(pts+10,status,errors)]):
            result = self.flow.update(self.frame,self.m,1/30,'left')
        self.assertEqual(result.status,'unavailable')

    def test_failures_fall_back(self):
        for answer in [None, 'error', 'nan']:
            with self.subTest(answer=answer):
                self.flow.reset()
                self.flow.update(self.frame,self.m,0,'left')
                with patch('motion.cv2.calcOpticalFlowPyrLK') as lk:
                    if answer == 'error':
                        lk.side_effect = cv2.error('test flow failure')
                    elif answer == 'nan':
                        lk.return_value = (np.full((6,1,2),np.nan,np.float32),
                                           np.ones((6,1),np.uint8),np.zeros((6,1),np.float32))
                    else:
                        lk.return_value = (None,None,None)
                    result = self.flow.update(self.frame,self.m,1/30,'left')
                self.assertEqual(result.status,'unavailable')

    def test_photometric_error_and_feet_only_fall_back(self):
        for statuses,errors in [(np.ones((6,1),np.uint8),np.full((6,1),30,np.float32)),
                                 (np.array([[0],[0],[0],[1],[1],[1]],np.uint8),np.zeros((6,1),np.float32))]:
            self.flow.reset()
            self.flow.update(self.frame,self.m,0,'left')
            with patch('motion.cv2.calcOpticalFlowPyrLK',return_value=(
                    self.points.reshape(-1,1,2),statuses,errors)):
                result = self.flow.update(self.frame,self.m,1/30,'left')
            self.assertEqual(result.status,'unavailable')

    def test_side_size_time_loss_and_manual_resets(self):
        for now,side,frame in [(1/30,'right',self.frame),(.5,'left',self.frame),
                               (0,'left',self.frame),(-1,'left',self.frame),
                               (1/30,'left',self.frame[:220])]:
            self.flow.reset()
            self.flow.update(self.frame,self.m,0,'left')
            self.assertEqual(self.flow.update(frame,self.m,now,side).status,'unavailable')
        self.flow.update(self.frame,None,1,'left')
        self.assertIsNone(self.flow.previous)
        self.flow.update(self.frame,self.m,2,'left')
        self.flow.reset()
        self.assertIsNone(self.flow.previous)

    def run_rep(self, final_motion):
        tracker = SquatTracker()
        now = 0
        for m,frames,motion in [(self.m,45,MotionCheck()),
                (replace(self.m,knee=100,hip=100,hip_y=180,depth=0),30,MotionCheck('consistent')),
                (self.m,25,final_motion)]:
            for _ in range(frames):
                now += 1/30
                tracker.update(m,now,motion)
        return tracker

    def test_consistent_and_unavailable_preserve_rep(self):
        for motion in [None,MotionCheck(),MotionCheck('consistent')]:
            self.assertEqual(self.run_rep(motion).reps,1)

    def test_real_flow_conflict_prevents_false_completion(self):
        self.flow.update(self.frame,self.m,0,'left')
        conflict = self.flow.update(self.frame,
            replace(self.m,points=(self.points+[0,30]).tolist()),1/30,'left')
        self.assertEqual(conflict.status,'inconsistent')
        tracker = self.run_rep(conflict)
        self.assertEqual(tracker.reps,0)
        self.assertFalse(tracker.active)
        self.assertIsNone(tracker.baseline)
        tracker.reps = 2
        tracker.update(self.m,5,conflict)
        self.assertEqual(tracker.reps,2)

    def test_conflict_blocks_start_and_recovers_after_calibration(self):
        tracker = SquatTracker()
        now = 0
        for _ in range(45):
            now += 1/30
            tracker.update(self.m,now)
        crouch = replace(self.m,knee=100,hip=100,hip_y=180,depth=0)
        now += 1/30
        tracker.update(crouch,now,MotionCheck('inconsistent'))
        self.assertFalse(tracker.active)
        self.assertEqual(tracker.state,'calibrating')
        for m,frames in [(self.m,45),(crouch,30),(self.m,25)]:
            for _ in range(frames):
                now += 1/30
                tracker.update(m,now,MotionCheck('consistent'))
        self.assertEqual(tracker.reps,1)


if __name__ == '__main__':
    unittest.main()
