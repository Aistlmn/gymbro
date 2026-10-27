# GymBro v0.3

Local Python webcam prototype: pose landmarks, knee/hip angles, squat phases,
repetition counting, OpenCV optical-flow motion validation, and two experimental
cues (depth and possible heel lift).
No training or cloud inference. Model download needs internet once; camera frames
stay local. Video is recorded only with `--output`. On exit, workout results are
saved as local JSON; an optional AWS backend stores/retrieves those summaries.

## Verified results

- OpenCV **5.0.0**.
- **44 automated tests passing**.
- **614-frame saved-video regression: 2 reps counted**.
- **Clean live-camera test: 2/2 reps counted**; both met the depth target, with
  **0 heel-lift warnings**.
- **AWS session upload and retrieval verified**.
- **Retry/idempotency verified**, returning `duplicate=true`.

## Session history and optional AWS

Every run with processed frames writes `sessions/<UUID>.json` beside the app. It
contains completed reps, per-rep depth/heel-lift flags and geometry, form totals,
timestamps, duration, source kind, sides used, exit reason and OpenCV diagnostics.
Recalibration preserves completed history. Incomplete reps are not counted.
Depth and heel results remain heuristic cues, not medical/safety assessments.

Set `GYMBRO_SESSIONS_DIR` to choose another local folder. With `GYMBRO_API_URL`
unset, AWS is completely disabled and no AWS packages or credentials are needed.
With it set, the saved summary is uploaded only after the camera closes; failure
or timeout retains the local file and leaves the workout app functional.

The backend is API Gateway + one Python Lambda + DynamoDB, protected by IAM-signed
requests. See [deployment, configuration and cloud verification](aws/DEPLOY.md)
and [architecture](ARCHITECTURE.md). AWS upload, retrieval and idempotent retry
have been verified on the deployed backend.
After deployment, install optional `requirements-aws.txt`, set `GYMBRO_API_URL` to
the stack's ApiUrl and `AWS_PROFILE` to your authorized runtime profile. No cloud
credentials belong in source code. Manual retry/retrieval from this folder:

```powershell
.\.venv\Scripts\python.exe aws_client.py upload sessions\SESSION_UUID.json
.\.venv\Scripts\python.exe aws_client.py get SESSION_UUID
```

Identical uploads are idempotent; cloud failure never deletes the local JSON.

## Run locally

After cloning, open a terminal in the folder containing this README, `app.py` and
`requirements.txt`. Complete the installation steps below, then run:

```powershell
.\.venv\Scripts\python.exe app.py
```

Use `--source 1` for another camera. Press Q to quit, R to recalibrate, S to
switch anatomical sides. The preview is not mirrored. A clean live webcam test
counted 2/2 squats successfully; both met the depth target with 0 heel-lift warnings.

## Installation (Python 3.12, 64-bit recommended)

From this folder on Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe download_model.py
.\.venv\Scripts\python.exe app.py
```

On macOS/Linux use `python3 -m venv .venv` and `.venv/bin/python` instead.
Those platforms have not been tested. Use only the contrib OpenCV package listed
in requirements: installing multiple OpenCV packages can make their shared `cv2`
module conflict. Dependency versions were exercised on Windows/Python 3.12.

## Camera setup and first test

1. Put the camera at about hip height, level, perpendicular to your side.
   Keep it stationary, with your whole body and shoes visible, in good light.
2. Face sideways with your left anatomical side towards the camera (or pass
   `--side right`). Use one person, an unobstructed background, and visible feet.
3. Stand upright and still, heels down, for 1.2 seconds until Ready appears.
4. Perform a few slow bodyweight squats in place, returning upright between reps.
   Check that the skeleton follows your visible leg and that the counter advances
   once per completed movement. Press R after moving the camera or changing position.
5. Try a deliberately shallow movement within your comfortable range: the return
   phase should show the depth cue. A visible, sustained heel rise can trigger the
   heel cue; this cue is particularly sensitive to footwear and occlusion.
6. Step out of frame. Feedback should report an unclear pose and require calibration
   again, without counting the interrupted movement.

If the camera fails: close other camera apps, enable Windows camera access for
desktop apps, and try `--source 1`. Send the terminal error or describe the observed
state/count so we can complete the webcam debugging.

## Video and tests

```powershell
.\.venv\Scripts\python.exe app.py --source "C:\path\squats.mp4" --side left
.\.venv\Scripts\python.exe app.py --source "C:\path\squats.mp4" --headless --output annotated.mp4
.\.venv\Scripts\python.exe -m unittest -v
```

Videos must also begin with a stable standing interval. `--max-frames 100` limits
a run. Headless mode prints counts on exit. Output filenames must be new. An output
video contains no audio. Video playback can be slower than real time on slow CPUs;
state timing uses source FPS. Live camera timing uses a monotonic clock.

## What OpenCV 5 contributes

The tested runtime reports `cv2.__version__ == '5.0.0'`; the installed distribution
is pinned as `opencv-contrib-python==5.0.0.93`. No dependencies were added.

OpenCV performs **image-based motion analysis used by the squat counter**, as well
as video capture, color conversion, resizing, overlays, preview and optional video
encoding. MediaPipe still performs neural-network person/landmark inference.
Optical flow is classical computer vision, not a new trained model or an algorithm
exclusive to OpenCV 5. This documents the implementation, not an assurance of
competition eligibility.

`motion.py` runs `cv2.calcOpticalFlowPyrLK` on consecutive, unannotated grayscale
frames at the selected side's shoulder, hip, knee, ankle, heel and toe positions.
The 21x21 patches and pyramid levels 0 through 3 allow tracking at multiple scales.
A second LK pass tracks the result back to the previous frame. A track is usable
only when both passes succeed, its endpoint is in-frame, all values are finite,
the mean patch error is at most 20 (8-bit grayscale units), and the round-trip
position error is at most 1.5 pixels. OpenCV also rejects weak image gradients via
`minEigThreshold=1e-4`.

At least three valid tracks, including hip or knee, are required. Their predicted
positions are compared with the new MediaPipe positions. If a strict majority disagree
by more than `max(8 pixels, 0.12 * previous thigh length)`, including hip or knee,
the measurement is **inconsistent** (at least two tracks). Before any phase, angle smoothing, form-rule,
or rep-count update, `SquatTracker` discards that candidate and requests standing
recalibration. Completed reps remain intact. Two noisy patches out of six no longer
override four agreeing tracks. Thus an apparent pose jump unsupported
by image motion cannot immediately start or complete a rep. A single bad point
does not trigger the veto.

When flow is consistent, existing squat/form logic runs unchanged. When flow is
unavailable (first frame, weak texture, failed tracking), it falls back to the same
pose rules; unavailable does **not** mean stationary. No positions are synthesized
through missing poses. Tracks are re-seeded every frame to prevent long-term drift.
Missing pose, side change, image-size change, non-increasing time, gaps over 0.25
seconds, and R/S controls restart flow history. These checks use image coordinates
before display annotations, so overlays cannot become tracked features.

The preview reports `OpenCV LK` status, valid-track count, median pixel displacement
and median disagreement. The JSON summary includes `opencv_version` and counts of
consistent, inconsistent and unavailable frame pairs. A median is only diagnostic;
the veto uses the individual hip/knee and other track disagreements described above.

Limits: LK tracks appearance near a joint, not the anatomical joint itself. Loose
clothing, occlusion, blur, lighting changes and camera movement can cause fallback
or an unnecessary recalibration. This is a conservative consistency veto, not
independent proof of a correct squat; small gradual pose errors may pass it. The
camera must still stay fixed. Thresholds are prototype heuristics. Prefer the
brief recalibration over counting a candidate contradicted by reliable pixel flow.

For a quick live regression, perform several normal reps, check that the count
increments as before, then press R and S and step out of frame. The original form
cues and keys remain available. If frequent recalibration occurs, report the LK
status and camera conditions before changing thresholds.

## How it works

`app.py`: OpenCV reads a frame and converts BGR colors to RGB. MediaPipe's pretrained
Pose Landmarker Lite neural network locates the person and produces 33 landmarks.
That is the machine learning component. We use its current Tasks API, not the older
`mp.solutions` API. VIDEO mode processes camera frames synchronously with increasing
timestamps, keeping this prototype in one straightforward loop.
After pose measurement, `motion.py` validates inter-frame image movement with
OpenCV before `squat.py` updates its state.

`geometry.py`: chooses one consistent anatomical side, rejects missing/uncertain
or clipped landmarks, converts normalized positions to pixels, and calculates
angles using a dot product and arccos. Angles use pixel coordinates because x and y
normalized to different image dimensions would distort geometry on wide images.
Depth is `(hip_y - knee_y) / thigh_length`; screen y increases downward.
Heel height is `(toe_y - heel_y) / foot_length`. These are dimensionless ratios.

`squat.py`: calibrates standing position and projected knee angle, smooths the knee
angle, and tracks standing, descending, bottom/pause, ascending and returning/hold.
A start needs knee flexion below `min(145, standing_knee - 20)`, hip flexion, and hip
descent. Calibration still requires an upright knee >=160 and hip >=155 for 1.2s.
The baseline stays fixed until recalibration; the app never learns a crouch as upright.

Completion now requires all of the following:

- Smoothed knee reaches `clamp(standing_knee - 12, 150, 158)` degrees. Once return
  starts, a 4-degree hysteresis margin tolerates small fluctuations.
- Hip is within a bounded allowance of calibration: the larger of 25% thigh length
  or 20% of the candidate's maximum hip descent, capped at 35% thigh length. During
  the return hold, a further 4% thigh-length margin avoids threshold flicker.
- At least 65% of the measured hip descent has been recovered and the knee has
  extended at least 15 degrees from its lowest angle. A half-return cannot count
  merely because the absolute hip tolerance is more forgiving.
- Knee reached `min(145, standing_knee - 25)` or lower, with hip descent at least
  25% of calibrated thigh length. This admits a shallow squat with a depth warning,
  but rejects tiny dips. The depth/form warning thresholds themselves are unchanged.
- At least 0.6 seconds since candidate start, plus a return hold of 0.2 seconds and
  at least three samples. An early return waits instead of silently discarding the
  candidate. The minimum duration includes this return hold; it is not a tempo score.

One completion disarms the candidate; a new descent is needed for another count.
Low-confidence frames or strong flow contradictions still discard a candidate.
These are heuristic robustness improvements, not proof against every false count.

## Diagnose a missed live rep

Run from this folder, using a new log filename each time:

```powershell
.\.venv\Scripts\python.exe app.py --debug-log sessions\live-debug-01.jsonl
```

The overlay shows `Waiting:` followed by failed gates: `knee_ok`, `hip_ok`,
`recovery_ok`, `bend_ok`, `duration_ok`, `settled`. It also shows the current return
threshold and normalized hip offset. `settled` means the standing hold is still
pending. `Counter:` exposes calibration, counting, insufficient movement, pose loss,
time gap and `flow_rejected` events so a canceled candidate is not mistaken for a
standing-threshold failure. R/S resets still clear the candidate intentionally.

The optional JSONL records one diagnostic snapshot per frame: raw/filtered knee,
phase, count, last event, motion status, thresholds, hip offset/recovery, minimum
knee, elapsed/hold time and each completion gate. `legacy_*` gates show what the
previous 163-degree / 15%-hip / 140-degree logic would have done. There are no images
in the log, and it is not sent to AWS. It grows with session length; use it for a
short debugging workout. Existing files are not overwritten. If a rep is missed,
send that log and roughly when the squat occurred; without it, your actual failing
webcam condition cannot be determined from the symptom alone.

The two cues are ordinary Python rules:

- **Depth target missed:** maximum depth stayed below -0.10 (hip center more than
  one tenth of a thigh length above the knee). Evaluated on ascent/completion, not
  during normal descent. This is a configurable prototype target, not a universal
  prescription or a competition depth judgment.
- **Possible heel lift:** heel-height ratio rises more than 0.18 above standing
  calibration for at least 0.25 seconds. Repetition feedback remembers that event.

`download_model.py`: fetches the pretrained model from Google with an atomic file
replacement and basic bundle validation. `test_logic.py`: deterministic tests of
geometry, calibration, repetitions, cues, noise, and failure recovery.
`test_motion.py` exercises real LK on translated/stationary textured images,
contradictory pose motion, textureless fallback, forward/backward failures, resets,
and counter integration. `test_model.py` covers the full blank-video pipeline.

## Assumptions and limits

Facts: the app runs a pretrained model locally and measures projected 2D geometry.
Assumptions: side-on camera, stationary viewpoint, one person, visible body and feet,
flat-footed initial stance. Camera angle is instructed, not automatically verified.
Uncertainties: landmark bias, clothing, footwear, occlusion, individual proportions,
and actual webcam frame rate. Fixed thresholds have not been validated on a labeled
dataset. Heel lift is the weaker cue; foot rotation can produce a false alarm.
Judgment: two narrow, explicitly approximate cues are preferable to unsupported
claims about spinal rounding, knee valgus, injury risk, or overall squat safety.
This recognizes squat-like movements; sitting down can look similar. It is not a
general exercise classifier. No detected issue does not mean perfect form.

## References

- [Google Pose Landmarker Python guide](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python)
- [Google model overview](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker)
- [MediaPipe source and license](https://github.com/google-ai-edge/mediapipe)
- [OpenCV source and license](https://github.com/opencv/opencv)
- [OpenCV Lucas–Kanade API](https://docs.opencv.org/4.x/dc/d6b/group__video__track.html)
  (published API reference; this implementation is executed and tested on 5.0.0).

