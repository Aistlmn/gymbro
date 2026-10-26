# Verification record — 2026-09-09

## Live completion robustness — 2026-10-27

Diagnosis was performed against the saved old implementation and controlled
geometry, not an observed live workout. Each sequence calibrated upright first,
performed a candidate movement, and returned to standing. Old/new counts:

| Reproduced condition | Previous | Updated |
| --- | --- | --- |
| Knee returns to 160 degrees and stays there | 0 | 1 |
| Hip returns 0.22 calibrated thigh lengths below starting height | 0 | 1 |
| Shallow movement reaches 142-degree knee with real hip descent | 0 | 1 (depth cue retained) |
| Early standing return before the 0.6-second gate, then waiting | 0 | 1 |

The first two previously stayed blocked by absolute thresholds. The latter two
were silently disarmed by the standing-return branch before satisfying its nested
minimum-bend/duration gate. Waiting afterward could not resurrect that candidate.
Which of these (or pose/flow interruption) affected the user's webcam remains
unconfirmed without a live diagnostic log.

Updated completion uses calibrated return angles, hysteresis, bounded hip tolerance,
explicit hip/knee recovery and a 0.2-second/three-sample standing hold. Small dips,
partial returns, single-frame spikes and duplicate counts are covered by negative
tests. Duration waits rather than silently disarming an early return. Optical-flow
veto now requires a strict majority of valid tracks including hip/knee; strong
contradictions still cancel, and missing flow still falls back to pose logic.

- All **44 tests passed**, including all previous tests and 12 new completion tests.
  Imperfect returns were exercised at 10, 15, 30 and 60 fps.
- Final full-video regression: **614 frames, 614 usable poses, 2 reps**; LK reports
  **613 consistent, 0 inconsistent, 1 unavailable**. AWS disabled during regression.
- JSONL diagnostics parsed successfully for 614 frames; both rep transitions have
  all required completion gates satisfied. Overlay visually checked on annotated
  video. Per-rep session persistence and AWS tests continue passing.
- Live telemetry is opt-in via `--debug-log`. It includes old/new gate diagnostics
  and reset/cancellation reasons, with no images or AWS upload. Use a new filename.

Remaining verification: reproduce a short workout on the user's actual camera and
inspect the resulting log if counts still fail. These tests do not establish that
the heuristic cannot produce false counts on other movement/camera conditions.

## Session persistence update — 2026-10-26

- All 32 tests passed with optional AWS client dependencies installed; `pip check`
  reported no broken requirements. The four backend/client tests skip when Boto3
  is absent, so core/local operation retains its original dependency requirements.
- New tests cover completed rep history across reset, form totals, local atomic
  JSON round trip, disk failure, AWS-disabled behavior, failed/timed-out uploads
  retaining the file, payload validation, Lambda create/read/duplicate/conflict,
  malformed/base64/oversized bodies, missing records, storage errors and actual
  SigV4 signing with dummy credentials and mocked HTTP transport. No cloud calls.
- Original 614-frame side-view regression still counted 2 reps with 613 consistent
  LK checks. It now emitted schema-valid local JSON containing both rep records,
  2 depth-target misses and 2 possible heel-lift warnings, matching the existing
  heuristic feedback. These are not expert-validated form labels.
- Full blank-video app run with invalid AWS endpoint configuration: normal exit,
  10 processed frames, zero reps, JSON preserved, readable upload-failure notice.
- Source SAM template passed cfn-lint 1.58.0. AWS SAM Translator 1.115.0 expanded
  it offline (using a dummy S3 packaging URI); both generated API operations were
  checked for AWS_IAM/SigV4 security and resource-based Lambda invocation. Expanded
  CloudFormation also passed cfn-lint. No AWS credentials/resources were used.
- Optional client exercised with Boto3 1.43.118; Lambda uses its runtime SDK.

**Pending:** actual deployment, runtime IAM-policy assignment, signed POST/GET,
unsigned-request denial on the deployed API, and DynamoDB console verification.
`aws/DEPLOY.md` contains these commands. Backend unit tests mock storage and do not
prove cloud availability or competition eligibility. No resources were deployed
and no spending was initiated.

## OpenCV motion-validation update — 2026-10-26

The user has confirmed that the original webcam app works. The following checks
cover the new optical-flow addition; the historical build record follows below.

- Runtime queried directly: OpenCV `5.0.0`. Dependencies unchanged.
- Before editing: all original 12 tests passed.
- After editing: all 23 tests passed, including real pyramidal Lucas–Kanade on
  stationary and translated image texture, false landmark jumps on stationary
  pixels, low-texture fallback, forward/backward failure filtering, photometric
  error rejection, feet-only evidence rejection, resets, and rep-gate integration.
- Controlled translations of (4, 6) and (-3, -5) pixels produced median displacement
  magnitudes 7.2110 and 5.8312 pixels; median pose/flow residuals were below 0.001
  pixels. Four tracks survived reliability checks in each translated example;
  tests require sufficient reliable tracks, not success of every patch.
- The original 614-frame right-side squat video still produced **2 reps**, with
  614 detected/usable poses, **613 consistent flow checks**, **0 inconsistent**,
  and **1 unavailable** (initial frame). Annotated output was visually inspected;
  phase, rep count, form cue, and LK diagnostics remain readable.
- The full app's blank-video and missing-input checks still pass.
- A synthetic reliable flow/pose conflict prevents start/completion, discards the
  candidate, preserves prior counts, and permits counting after recalibration.

No new live webcam or latency benchmark was performed. The pixel tests establish
the implemented consistency check, not general accuracy across clothing, lighting,
occlusions or camera movement. A short live regression is the remaining check.
Competition eligibility has not been independently verified against official rules.

## Original build record

Environment: Windows, Python 3.12.14, MediaPipe 1.0.1, OpenCV contrib 5.0.0.93.
The virtual environment and downloaded Pose Landmarker Lite bundle are present.
`pip check` reports no broken requirements.

## Executed checks

- Ten deterministic logic tests passed: 90/180-degree angles and degenerate points;
  pixel aspect-ratio handling, confidence/NaN rejection; full and shallow reps;
  sustained heel cue versus short noise; duplicate prevention; interruption;
  hip-drop requirement; calibration while crouched; time-gap/timeout recovery.
- Actual model inference on Google's `mediapipe-assets/pose.jpg` detected one person
  with 33 landmarks. This is a model smoke test, not squat ground truth.
- Actual model inference on a black frame returned no pose.
- Blank MP4 through the actual app: 10 frames, 0 poses, 0 reps, normal exit.
- A nonexistent video and camera index 0 both produced readable errors, exit 1,
  without a Python traceback. No webcam frames could be captured.
- [Public front-view clip](https://github.com/Careless-Caramel/squat-counter/blob/main/video.mp4):
  363 decoded frames, 363 pose detections, 354 usable left-side measurements, 0 reps.
  It is outside the specified camera setup; this does not validate front-view use.
- [Public side-view clip](https://github.com/rohanx01/Squat-Analysis-Model/blob/main/squat.mp4):
  614 decoded frames, 614 pose detections, 614 usable right-side measurements, 2 reps.
  The occluded left side was correctly rejected when explicitly selected in an
  earlier run. An annotated output contact sheet was visually inspected for
  skeleton alignment, readable text, phase progression, and completed counts.
  Both reps produced depth and possible heel-lift cues. These labels have **not**
  been established as true form errors by an expert or labeled dataset.
- `test_model.py` adds repeatable blank-video/model/output and missing-input checks.
  Final `python -m unittest -v` run: all 12 tests passed (3.373 seconds).

Remote sample files were downloaded only as test inputs under the workspace's
`work/` folder. They are not bundled as product assets. No external project code
was copied. Test clips were processed locally.

## Pending acceptance

Physical webcam capture, visible window/key interaction, actual live latency,
and cue accuracy on the user's side-view bodyweight squats remain unverified.
The local prototype and file-video pipeline work; full user-environment acceptance
is pending these checks. Follow the README's first-test steps and report errors
or incorrect behavior. Fixed thresholds are heuristic, not validated form scoring.
