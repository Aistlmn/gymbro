"""Conservative squat-like movement detector; thresholds are prototype heuristics."""
from statistics import median


class SquatTracker:
    def __init__(self):
        self.reps = 0
        self.rep_results = []  # completed history survives recalibration
        self.reset()

    def reset(self, reason='manual_reset'):
        """Recalibrate without erasing completed repetitions."""
        self.state = 'calibrating'
        self.samples = []
        self.baseline = None
        self.last_time = None
        self.filtered = None
        self.active = False
        self.last_result = ''
        self.result_until = 0
        self.heel_since = None
        self.return_since = None
        self.return_frames = 0
        self.completion_debug = {}
        self.last_event = reason

    def debug_snapshot(self, m, now, motion=None):
        """Numeric local diagnostics; no images or landmark arrays."""
        return {'time_seconds': round(now, 3), 'state': self.state,
                'active': self.active, 'reps': self.reps, 'last_event': self.last_event,
                'raw_knee': None if m is None else round(m.knee, 2),
                'filtered_knee': None if self.filtered is None else round(self.filtered, 2),
                'motion': 'not_supplied' if motion is None else motion.status,
                'completion': dict(self.completion_debug)}

    def update(self, m, now, motion=None):
        if m is None:
            self.reset('pose_lost')  # no counting across occlusions or different people
            return ['Pose unclear: show shoulder, hip, knee and entire foot.']
        if motion is not None and motion.status == 'inconsistent':
            # Pixel motion contradicts pose motion: do not update angles, phases,
            # form extrema or the count using this measurement. Keep prior reps.
            self.reset('flow_rejected')
            return ['Motion disagrees with pose. Stand still to recalibrate.']
        if self.last_time is not None and (now <= self.last_time or now-self.last_time > .75):
            self.reset('time_gap')
        dt = .033 if self.last_time is None else now-self.last_time
        self.last_time = now
        old = self.filtered
        alpha = 1 - pow(2.718281828, -dt/.12)
        self.filtered = m.knee if old is None else old + alpha*(m.knee-old)
        k = self.filtered
        velocity = 0 if old is None else (k-old)/dt
        if self.baseline is None:
            if m.knee < 160 or m.hip < 155:
                self.samples = []
                return ['Stand upright, side-on, with heels down to calibrate.']
            self.samples.append((now, m.hip_y, m.scale, m.heel, m.knee))
            if now-self.samples[0][0] < 1.2:
                return ['Hold still, upright, heels down (1.2 seconds).']
            ys = [s[1] for s in self.samples]
            scale = median(s[2] for s in self.samples)
            if max(ys)-min(ys) > .12*scale:
                self.samples = []
                return ['Hold still for calibration.']
            self.baseline = (median(ys), scale, median(s[3] for s in self.samples))
            self.standing_knee = median(s[4] for s in self.samples)
            # Learn the user's projected upright angle, but never learn a crouch.
            # Separate enter/exit thresholds plus dwell prevent a one-frame count.
            self.return_knee = max(150, min(158, self.standing_knee-12))
            self.start_knee = min(145, self.standing_knee-20)
            self.bend_knee = min(145, self.standing_knee-25)
            self.state = 'standing'
            self.last_event = 'calibrated'
        y0, scale, heel0 = self.baseline
        if not self.active:
            if k < self.start_knee and m.hip_y-y0 > .12*scale and m.hip < 155:
                self.active = True
                self.start = now
                self.lowest_knee = k
                self.max_depth = m.depth
                self.heel_seen = False
                self.peak_hip_drop = m.hip_y-y0
                self.return_since = None
                self.return_frames = 0
                self.completion_debug = {}
                self.last_event = 'candidate_started'
                self.state = 'descending'
            else:
                self.state = 'standing' if k >= self.return_knee else 'ready'
                return [self.last_result if now < self.result_until else 'Ready: squat slowly in place.']
        self.max_depth = max(self.max_depth, m.depth)
        self.lowest_knee = min(self.lowest_knee, k)
        self.peak_hip_drop = max(self.peak_hip_drop, m.hip_y-y0)
        if m.heel-heel0 > .18:
            if self.heel_since is None:
                self.heel_since = now
            if now-self.heel_since >= .25:
                self.heel_seen = True
        else:
            self.heel_since = None
        feedback = []
        if self.heel_since is not None and now-self.heel_since >= .25:
            feedback.append('Possible heel lift: try keeping the heel grounded.')
        elapsed = now-self.start
        hip_drop = m.hip_y-y0
        # Allow modest calibration drift, but require real recovery from the bottom.
        hip_limit = min(.35*scale, max(.25*scale, .20*self.peak_hip_drop))
        hip_recovered = (self.peak_hip_drop-hip_drop) / self.peak_hip_drop
        holding = self.return_since is not None
        knee_ok = k >= self.return_knee-(4 if holding else 0)
        hip_ok = abs(hip_drop) <= hip_limit + (.04*scale if holding else 0)
        recovery_ok = hip_recovered >= .65 and k-self.lowest_knee >= 15
        bend_ok = self.lowest_knee <= self.bend_knee and self.peak_hip_drop >= .25*scale
        duration_ok = elapsed >= .6
        if knee_ok and hip_ok and recovery_ok:
            if self.return_since is None:
                self.return_since = now
            self.return_frames += 1
        else:
            self.return_since = None
            self.return_frames = 0
        settled = (self.return_since is not None and now-self.return_since >= .2
                   and self.return_frames >= 3)
        self.completion_debug = {
            'standing_knee': round(self.standing_knee,2),
            'return_knee_enter': round(self.return_knee,2),
            'return_knee_exit': round(self.return_knee-4,2),
            'hip_offset_ratio': round(hip_drop/scale,3),
            'hip_limit_ratio': round(hip_limit/scale,3),
            'hip_exit_limit_ratio': round(hip_limit/scale+.04,3),
            'peak_hip_drop_ratio': round(self.peak_hip_drop/scale,3),
            'hip_recovered_fraction': round(hip_recovered,3),
            'lowest_knee': round(self.lowest_knee,2), 'bend_limit': round(self.bend_knee,2),
            'elapsed_seconds': round(elapsed,3),
            'hold_seconds': round(0 if self.return_since is None else now-self.return_since,3),
            'knee_ok': knee_ok, 'hip_ok': hip_ok, 'recovery_ok': recovery_ok,
            'bend_ok': bend_ok, 'duration_ok': duration_ok, 'settled': settled,
            'legacy_knee_ok': k > 163, 'legacy_hip_ok': hip_drop < .15*scale,
            'legacy_bend_ok': self.lowest_knee < 140,
        }
        if elapsed > 20:
            self.reset('movement_timeout')
            return ['Movement timed out. Stand upright to recalibrate.']
        if settled and duration_ok:
            if bend_ok:
                self.reps += 1
                self.rep_results.append({
                    'rep': self.reps,
                    'completed_at_seconds': round(now, 3),
                    'duration_seconds': round(now-self.start, 3),
                    'minimum_knee_degrees': round(self.lowest_knee, 2),
                    'maximum_depth_ratio': round(self.max_depth, 4),
                    'depth_target_met': self.max_depth >= -.10,
                    'heel_lift_warning': bool(self.heel_seen),
                })
                issues = []
                if self.max_depth < -.10:
                    issues.append('Depth target missed: hip stayed above knee')
                if self.heel_seen:
                    issues.append('possible heel lift')
                self.last_result = f'Rep {self.reps}: ' + ('; '.join(issues) if issues else 'depth target reached; no heel cue')
                self.result_until = now+4
                self.last_event = 'rep_counted'
            else:
                self.last_event = 'candidate_rejected_small_movement'
                self.last_result = 'Not counted: insufficient knee bend or hip descent.'
                self.result_until = now+4
            self.active = False
            self.heel_since = None
            self.state = 'standing'
            return [self.last_result or 'Ready: squat slowly in place.']
        if self.return_since is not None:
            self.state = 'returning / hold'
        elif velocity > 10 and k > self.lowest_knee+5:
            self.state = 'ascending'
        elif velocity < -10:
            self.state = 'descending'
        else:
            self.state = 'bottom / pause'
        if self.state == 'ascending' and self.max_depth < -.10:
            feedback.append('Hip stayed above knee: depth target not reached.')
        return feedback or ['Depth target reached.' if self.max_depth >= -.10 else 'Squat in progress.']
