"""Local-first summaries. AWS is optional and runs only after capture ends."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def build_summary(tracker, started_at, duration, source_kind, sides, stats, termination):
    results = [dict(rep) for rep in tracker.rep_results]
    return {
        'schema_version': 1, 'session_id': str(uuid4()), 'app_version': '0.3',
        'started_at': started_at, 'ended_at': utc_now(),
        'duration_seconds': round(duration, 3), 'source_kind': source_kind,
        'sides_used': sorted(sides), 'termination': termination,
        'rep_count': len(results), 'rep_results': results,
        'form_summary': {
            'depth_target_met': sum(r['depth_target_met'] for r in results),
            'depth_target_missed': sum(not r['depth_target_met'] for r in results),
            'heel_lift_warnings': sum(r['heel_lift_warning'] for r in results),
        },
        'incomplete_rep_discarded': bool(tracker.active), 'analysis': stats,
    }


def save_summary(summary, directory=None):
    directory = Path(directory or os.environ.get('GYMBRO_SESSIONS_DIR')
                     or Path(__file__).parent / 'sessions')
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (summary['session_id'] + '.json')
    temporary = directory / (summary['session_id'] + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as out:
            json.dump(summary, out, indent=2, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination.resolve()


def upload_saved(path):
    """Bound even credential-provider hangs; failed uploads leave JSON intact."""
    if not os.environ.get('GYMBRO_API_URL'):
        return 'AWS disabled; session saved locally.'
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('aws_client.py')),
                                 'upload', str(path)], capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return 'AWS session stored (or already present).'
        return 'AWS upload failed; local JSON retained. Retry with aws_client.py upload.'
    except (OSError, subprocess.TimeoutExpired):
        return 'AWS upload unavailable/timed out; local JSON retained for retry.'


def finish_session(summary):
    try:
        path = save_summary(summary)
    except (OSError, ValueError) as error:
        print(f'Session could not be saved locally: {error}', file=sys.stderr)
        return
    print(f'Session JSON: {path}', file=sys.stderr)
    print(upload_saved(path), file=sys.stderr)
