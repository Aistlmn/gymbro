"""GymBro v0.3: capture -> pretrained pose model -> geometry -> rules -> overlay."""
import argparse
import json
from pathlib import Path
import time
import textwrap

from download_model import MODEL
from geometry import measure
from squat import SquatTracker
from session_store import utc_now, build_summary, finish_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='0', help='Camera index or video filename')
    parser.add_argument('--side', choices=['left', 'right'], default='left', help='Anatomical side facing the camera')
    parser.add_argument('--model', type=Path, default=MODEL)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--max-frames', type=int, default=0)
    parser.add_argument('--debug-log', type=Path, help='New local JSONL file with per-frame completion gates')
    parser.add_argument('--output', type=Path, help='Optional annotated .mp4; video only, no audio')
    args = parser.parse_args()
    if args.max_frames < 0:
        parser.error('--max-frames must be nonnegative')
    if not args.model.exists():
        parser.exit(1, 'Model missing. Run: python download_model.py\n')
    try:
        import cv2
        import mediapipe as mp
        from motion import LandmarkMotion
    except ImportError as error:
        parser.exit(1, f'Dependency missing: {error}. Run: python -m pip install -r requirements.txt\n')
    source = int(args.source) if args.source.isdecimal() else args.source
    if args.output and isinstance(source, str) and args.output.resolve() == Path(source).resolve():
        parser.error('Output must differ from input')
    if args.output and args.output.exists():
        parser.error('Output already exists; choose another filename')
    capture = cv2.VideoCapture(source)
    debug_file = None
    writer = None
    count = detected = usable = 0
    tracker = SquatTracker()
    motion_tracker = LandmarkMotion()
    motion_counts = dict(consistent=0, inconsistent=0, unavailable=0)
    started = time.monotonic()
    started_at = utc_now()
    sides_used = {args.side}
    termination = 'completed'
    previous_ms = -1
    try:
        if args.debug_log:
            args.debug_log.parent.mkdir(parents=True, exist_ok=True)
            debug_file = args.debug_log.open('x', encoding='utf-8')
        if not capture.isOpened():
            raise RuntimeError(f'Cannot open {args.source!r}. Check camera permissions/index or video path.')
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not 1 <= fps <= 240:
            fps = 30
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(args.model)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_poses=1, min_pose_detection_confidence=.6,
            min_pose_presence_confidence=.6, min_tracking_confidence=.6)
        with mp.tasks.vision.PoseLandmarker.create_from_options(options) as detector:
            while True:
                ok, frame = capture.read()
                if not ok:
                    if count == 0 or isinstance(source, int):
                        raise RuntimeError('No frame received; camera disconnected, busy, or input unreadable.')
                    break
                now = count/fps if isinstance(source, str) else time.monotonic()-started
                timestamp = max(previous_ms+1, round(now*1000))
                previous_ms = timestamp
                # Keep original aspect ratio: angles need matching x/y pixel units.
                h, w = frame.shape[:2]
                if w > 960:
                    frame = cv2.resize(frame, (960, round(h*960/w)))
                h, w = frame.shape[:2]
                result = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                    data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), timestamp)
                landmarks = result.pose_landmarks[0] if result.pose_landmarks else None
                detected += landmarks is not None
                m = measure(landmarks, w, h, args.side)
                usable += m is not None
                # Optical flow must see raw video, before skeleton/text drawing.
                motion = motion_tracker.update(frame, m, now, args.side)
                motion_counts[motion.status] += 1
                feedback = tracker.update(m, now, motion)
                diagnostic = tracker.debug_snapshot(m, now, motion)
                if debug_file:
                    debug_file.write(json.dumps(diagnostic)+'\n')
                    debug_file.flush()
                count += 1
                if m:
                    pts = [(round(x), round(y)) for x, y in m.points]
                    for a, b in [(0,1),(1,2),(2,3),(3,4),(4,5),(3,5)]:
                        cv2.line(frame, pts[a], pts[b], (50,220,100), 3)
                    for p in pts:
                        cv2.circle(frame, p, 5, (0,230,255), -1)
                # Separate panel keeps guidance readable without covering the body.
                frame = cv2.copyMakeBorder(frame, 270, 0, 0, max(0, 800-w), cv2.BORDER_CONSTANT, value=(25,25,25))
                lines = [f'GymBro v0.3 | {tracker.state} | Reps: {tracker.reps}',
                         f'Side: {args.side} | Q: quit | R: recalibrate | S: switch side',
                         f'Knee: {m.knee:.0f} deg | Hip: {m.hip:.0f} deg' if m else 'No usable side pose',
                         (f'OpenCV LK: {motion.status} | tracks {motion.tracked}/6 | '
                          f'move {motion.displacement_px:.1f}px | residual {motion.disagreement_px:.1f}px')
                         if motion.status != 'unavailable' else 'OpenCV LK: unavailable - using pose rules']
                for message in feedback:
                    lines.extend(textwrap.wrap(message, width=85))
                gates = diagnostic['completion']
                if tracker.active and gates:
                    blocked = [name for name in ('knee_ok','hip_ok','recovery_ok','bend_ok','duration_ok','settled') if not gates[name]]
                    lines.append('Waiting: ' + ', '.join(blocked))
                    lines.append(f"Return knee >= {gates['return_knee_enter']:.0f} | hip offset {gates['hip_offset_ratio']:.2f} / {gates['hip_limit_ratio']:.2f}")
                else:
                    lines.append('Counter: ' + tracker.last_event)
                lines.append('Side view only. Experimental cues, not a safety assessment.')
                for i, line in enumerate(lines[:11]):
                    cv2.putText(frame, line, (12,24+i*23), cv2.FONT_HERSHEY_SIMPLEX, .52, (240,240,240), 1, cv2.LINE_AA)
                if args.output:
                    if writer is None:
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*'mp4v'), fps,
                                                 (frame.shape[1], frame.shape[0]))
                        if not writer.isOpened():
                            raise RuntimeError('Cannot create output video')
                    writer.write(frame)
                if not args.headless:
                    cv2.imshow('GymBro v0.3', frame)
                    key = cv2.waitKey(max(1, round(1000/fps)) if isinstance(source, str) else 1) & 255
                    if key == ord('q') or cv2.getWindowProperty('GymBro v0.3', cv2.WND_PROP_VISIBLE) < 1:
                        break
                    if key == ord('r'):
                        tracker.reset()
                        motion_tracker.reset()
                    if key == ord('s'):
                        args.side = 'right' if args.side == 'left' else 'left'
                        sides_used.add(args.side)
                        tracker.reset()
                        motion_tracker.reset()
                if args.max_frames and count >= args.max_frames:
                    termination = 'frame_limit'
                    break
        print(json.dumps({'frames': count, 'pose_frames': detected, 'usable_frames': usable,
                          'reps': tracker.reps, 'opencv_version': cv2.__version__,
                          'motion_frames': motion_counts}))
    except (RuntimeError, ValueError, OSError, cv2.error) as error:
        termination = 'error'
        parser.exit(1, f'GymBro: {error}\n')
    except KeyboardInterrupt:
        termination = 'interrupted'
    finally:
        if debug_file:
            debug_file.close()
        capture.release()
        if writer is not None:
            writer.release()
        if not args.headless:
            cv2.destroyAllWindows()
        if count:
            finish_session(build_summary(tracker, started_at, time.monotonic()-started,
                'camera' if isinstance(source, int) else 'video', sides_used,
                {'frames': count, 'pose_frames': detected, 'usable_frames': usable,
                 'opencv_version': cv2.__version__, 'motion_frames': motion_counts}, termination))


if __name__ == '__main__':
    main()
