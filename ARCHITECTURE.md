# GymBro v0.3 architecture

```text
LOCAL WORKOUT
OpenCV 5 camera/video capture -> MediaPipe pose -> pixel geometry
                              -> OpenCV 5 pyramidal LK consistency check
                              -> squat state + depth/heel cues + completed rep records
                              -> live OpenCV overlay

AFTER CAPTURE CLOSES
completed history + metadata -> local atomic JSON file (always)
                             -> optional bounded IAM-signed HTTPS upload
AWS
API Gateway REST (AWS_IAM) -> Lambda (validate + idempotency) -> DynamoDB
GET session by UUID       -> Lambda -> consistent DynamoDB read -> JSON
```

The AWS component provides durable workout-history storage and later retrieval,
not pose inference or a cosmetic health check. The app can retrieve results after
the camera process or computer has stopped, as long as the session ID is known.
No frames, landmark arrays, source filenames or credentials are stored in summaries.

`SquatTracker.rep_results` records only completed reps and survives R/S calibration
resets. Each record contains depth-target and possible heel-lift flags, minimum knee
angle, maximum depth ratio and timing. Form thresholds are unchanged. Completion
uses calibrated knee thresholds, a bounded hip-return allowance, explicit recovery,
and a 0.2-second/three-sample hold. The 0.6-second candidate-duration gate no longer
silently discards an early standing return. See README for the exact thresholds.
Flow contradictions require a strict majority of reliable patches including hip/knee.
`--debug-log` writes optional local per-frame gates and cancellation reasons; this
diagnostic data is separate from session JSON and never included in AWS uploads.
An interrupted candidate is excluded; the summary flags a candidate still active at
exit. Candidates canceled earlier by lost pose/flow are not counted or archived.

`session_store.py` builds versioned JSON with UUID, UTC timestamps, wall duration,
camera/video source kind, sides used, termination reason, rep results, aggregate
depth/heel counts and OpenCV/frame diagnostics. Save uses a temporary file, fsync
and atomic rename. The upload happens only after capture/writer cleanup. Failed disk
writes are reported without masking workout errors; AWS upload is skipped if saving
fails. Normal quit, EOF, frame limit, Ctrl+C and handled runtime errors after processed
frames save summaries. Force-kill/power loss cannot guarantee an end-of-session file.

`aws_client.py` uses optional Boto3/botocore credential resolution and SigV4 signing.
AWS packages are imported only for a cloud request. Automatic upload is bounded by
a 15-second subprocess timeout, including credential lookup. Saved files are the
retry mechanism; explicit `upload FILE`/`get UUID` commands support demos and recovery.
The CLI's HTTP timeout is 5 seconds; its credential provider is not subprocess-bounded
when invoked manually. Never put cloud operations inside the camera loop.

`aws/src/schema.py` validates types, sizes, timestamps, counters, flags and totals.
`aws/src/handler.py` stores one canonical JSON string under each session UUID. A
conditional put prevents overwrites; identical retries return success, conflicting
content returns 409. GET uses a strongly consistent read. There is no list/scan,
update, delete, user system, queue, dashboard or extra service.

`aws/template.yaml` packages only the Lambda source and provisions API Gateway,
one function with permission only to GetItem/PutItem on its table, an on-demand
DynamoDB table, and a seven-day log group. API IAM permissions are granted to the
operator separately; all authorized operators share this demo's data store.

Local tests establish logic and failure handling. A real deployment and signed
POST/GET round trip are required to establish AWS operation. No claim is made that
this alone satisfies unreviewed competition rules. Follow `aws/DEPLOY.md` for that
deployment, acceptance check and cleanup.
