"""Shared summary validation for the optional client and Lambda."""
from datetime import datetime
import json
import math
from uuid import UUID

MAX_BYTES = 128_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, low, high):
    return type(value) in (int,float) and math.isfinite(value) and low <= value <= high


def validate_summary(s):
    require(isinstance(s,dict), 'summary must be an object')
    require(len(json.dumps(s,allow_nan=False).encode()) <= MAX_BYTES, 'summary too large')
    require(s.get('schema_version') == 1 and type(s.get('schema_version')) is int, 'unsupported schema')
    require(isinstance(s.get('session_id'),str) and str(UUID(s['session_id'])) == s['session_id'], 'invalid session_id')
    require(s.get('app_version') == '0.3', 'unsupported app version')
    dates = []
    for key in ('started_at','ended_at'):
        require(isinstance(s.get(key),str), 'missing timestamp')
        date = datetime.fromisoformat(s[key])
        require(date.tzinfo is not None, 'timestamps need timezone')
        dates.append(date)
    require(dates[1] >= dates[0], 'invalid timestamp order')
    require(number(s.get('duration_seconds'),0,604800), 'invalid duration')
    require(s.get('source_kind') in ('camera','video'), 'invalid source kind')
    require(s.get('termination') in ('completed','frame_limit','interrupted','error'), 'invalid termination')
    require(isinstance(s.get('sides_used'),list) and 1 <= len(s['sides_used']) <= 2
            and all(side in ('left','right') for side in s['sides_used']), 'invalid sides')
    require(type(s.get('incomplete_rep_discarded')) is bool, 'invalid incomplete flag')
    reps = s.get('rep_results')
    require(isinstance(reps,list) and len(reps) <= 1000, 'invalid rep list')
    require(type(s.get('rep_count')) is int and s['rep_count'] == len(reps), 'rep count mismatch')
    last_time = 0
    for i,r in enumerate(reps,1):
        require(isinstance(r,dict) and type(r.get('rep')) is int and r['rep'] == i, 'invalid rep sequence')
        require(type(r.get('depth_target_met')) is bool and type(r.get('heel_lift_warning')) is bool, 'invalid form flags')
        require(number(r.get('minimum_knee_degrees'),0,180)
                and number(r.get('maximum_depth_ratio'),-2,2), 'invalid geometry')
        require(number(r.get('duration_seconds'),0,30)
                and number(r.get('completed_at_seconds'),last_time,604800), 'invalid rep timing')
        last_time = r['completed_at_seconds']
    expected = {'depth_target_met':sum(r['depth_target_met'] for r in reps),
                'depth_target_missed':sum(not r['depth_target_met'] for r in reps),
                'heel_lift_warnings':sum(r['heel_lift_warning'] for r in reps)}
    require(s.get('form_summary') == expected and all(type(v) is int for v in s['form_summary'].values()),
            'form totals mismatch')
    analysis = s.get('analysis')
    require(isinstance(analysis,dict), 'missing analysis')
    for key in ('frames','pose_frames','usable_frames'):
        require(type(analysis.get(key)) is int and 0 <= analysis[key] <= 100_000_000, 'invalid frame count')
    require(analysis['usable_frames'] <= analysis['pose_frames'] <= analysis['frames'], 'frame totals mismatch')
    require(isinstance(analysis.get('opencv_version'),str) and len(analysis['opencv_version']) <= 40, 'invalid OpenCV version')
    counts = analysis.get('motion_frames')
    require(isinstance(counts,dict) and set(counts) == {'consistent','inconsistent','unavailable'}
            and all(type(v) is int and v >= 0 for v in counts.values())
            and sum(counts.values()) == analysis['frames'], 'invalid motion totals')
    return s
