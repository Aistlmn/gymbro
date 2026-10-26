import unittest
from types import SimpleNamespace
from geometry import angle, measure, Metrics, SIDES
from squat import SquatTracker


def metric(knee=175, depth=-1, y=100, heel=0):
    return Metrics(knee, 175 if knee > 160 else 100, depth, y, 100, heel, [])


class LogicTests(unittest.TestCase):
    def test_angles(self):
        self.assertAlmostEqual(angle((1,0), (0,0), (0,1)), 90)
        self.assertAlmostEqual(angle((-1,0), (0,0), (1,0)), 180)
        with self.assertRaises(ValueError):
            angle((0,0), (0,0), (1,1))

    def test_pixel_scaling_and_confidence(self):
        landmarks = [SimpleNamespace(x=.5, y=.5, visibility=1, presence=1) for _ in range(33)]
        coords = [(200,50),(200,150),(300,150),(300,250),(285,260),(340,260)]
        for i, (x,y) in zip(SIDES['left'], coords):
            landmarks[i].x, landmarks[i].y = x/800, y/400
        m = measure(landmarks,800,400,'left')
        self.assertAlmostEqual(m.knee,90)
        self.assertAlmostEqual(m.hip,90)
        self.assertAlmostEqual(m.depth,0)
        landmarks[25].visibility = .3
        self.assertIsNone(measure(landmarks,800,400,'left'))
        landmarks[25].visibility = 1
        landmarks[25].x = float('nan')
        self.assertIsNone(measure(landmarks,800,400,'left'))
        self.assertIsNone(measure([],800,400,'left'))

    def setUp(self):
        self.t = SquatTracker()
        self.now = 0

    def hold(self, m, seconds):
        for _ in range(round(seconds*30)):
            self.now += 1/30
            result = self.t.update(m, self.now)
        return result

    def calibrate(self):
        self.hold(metric(),1.5)
        self.assertEqual(self.t.state,'standing')

    def rep(self, depth=0, heel=0):
        self.hold(metric(130,-.5,140,heel),.5)
        self.assertTrue(self.t.active)
        self.hold(metric(90,depth,190,heel),.6)
        self.assertEqual(self.t.state,'bottom / pause')
        result = self.hold(metric(135,depth,150,heel),.3)
        self.assertEqual(self.t.state,'ascending')
        self.hold(metric(),.7)
        return result

    def test_full_rep_and_no_duplicate_count(self):
        self.calibrate()
        self.rep()
        self.assertEqual(self.t.reps,1)
        self.assertIn('target reached',self.t.last_result)
        self.hold(metric(),3)
        self.assertEqual(self.t.reps,1)

    def test_shallow_rep_feedback(self):
        self.calibrate()
        self.rep(depth=-.4)
        self.assertIn('Depth target missed',self.t.last_result)

    def test_sustained_heel_feedback(self):
        self.calibrate()
        feedback = self.rep(heel=.3)
        self.assertTrue(any('heel' in s for s in feedback))
        self.assertIn('heel lift',self.t.last_result)

    def test_brief_heel_noise_ignored(self):
        self.calibrate()
        self.hold(metric(120,-.4,150),.4)
        self.hold(metric(90,0,190,.3),.1)
        self.hold(metric(90,0,190),.4)
        self.hold(metric(),.8)
        self.assertNotIn('possible heel lift',self.t.last_result)

    def test_tracking_loss_discards_rep(self):
        self.calibrate()
        self.hold(metric(100,0,180),.5)
        self.t.update(None,self.now+.01)
        self.hold(metric(),2)
        self.assertEqual(self.t.reps,0)

    def test_knee_bend_without_hip_drop_not_counted(self):
        self.calibrate()
        self.hold(metric(110,0,100),1)
        self.hold(metric(),1)
        self.assertEqual(self.t.reps,0)

    def test_initial_crouch_cannot_calibrate(self):
        self.hold(metric(90,0,180),2)
        self.assertIsNone(self.t.baseline)

    def test_time_gap_and_timeout(self):
        self.calibrate()
        self.hold(metric(100,0,180),.5)
        self.now += 2
        self.hold(metric(),.1)
        self.assertIsNone(self.t.baseline)
        self.calibrate()
        self.hold(metric(100,0,180),21)
        self.assertFalse(self.t.active)
        self.assertEqual(self.t.reps,0)


if __name__ == '__main__':
    unittest.main()
