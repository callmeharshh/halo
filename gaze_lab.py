"""Eye-tracking accuracy lab. Run:  python gaze_lab.py
1) loads (or runs) calibration, 2) shows 9 targets and measures how far off the gaze prediction is,
3) tests double-blink detection (hits) and natural blinking (false alarms). Results: gaze_lab_results.json.
Needs Camera permission for your terminal/VS Code. Sit where you will sit during the demo, with the same lighting."""
import json, os, sys, time
import cv2
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from gaze import GazeController, DELIBERATE_FRAMES, CONFIRM_WINDOW
from eyetrax.utils.screen import get_screen_size

g = GazeController()
if not g.load_saved():
    print("No saved calibration: starting calibration (follow the dots)…")
    g.calibrate()
sw, sh = get_screen_size()
cap = cv2.VideoCapture(0)
if not cap.isOpened():
    sys.exit("Camera not available. Allow Camera for your terminal/VS Code in System Settings → Privacy & Security.")

WIN = "Halo gaze lab"
cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
cv2.setWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

def predict(frame):
    f1, b1 = g.est1.extract_features(frame)
    f2, b2 = g.est2.extract_features(frame)
    closed = bool(b1 and b2)
    if f1 is None or f2 is None or closed:
        return None, closed
    x1, y1 = g.est1.predict([f1])[0]
    x2, y2 = g.est2.predict([f2])[0]
    return (x1 * 0.6 + x2 * 0.4, y1 * 0.6 + y2 * 0.4), closed

def show(canvas, text=None, wait=1):
    if text:
        cv2.putText(canvas, text, (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imshow(WIN, canvas)
    return cv2.waitKey(wait) & 0xFF

# ── 1. accuracy on 9 targets ─────────────────────────────────────────────────
targets = [(fx, fy) for fy in (0.15, 0.5, 0.85) for fx in (0.15, 0.5, 0.85)]
errors, rows = [], []
for fx, fy in targets:
    tx, ty = int(fx * sw), int(fy * sh)
    t0, preds = time.time(), []
    while time.time() - t0 < 3.2:
        ok, frame = cap.read()
        if not ok:
            continue
        p, closed = predict(frame)
        if p and time.time() - t0 > 1.2:  # give the eye 1.2 s to settle on the target
            preds.append(p)
        canvas = np.zeros((sh, sw, 3), np.uint8)
        cv2.circle(canvas, (tx, ty), 26, (255, 255, 255), 2)
        cv2.circle(canvas, (tx, ty), 6, (0, 255, 120), -1)
        if p:
            cv2.circle(canvas, (int(p[0]), int(p[1])), 12, (60, 60, 255), -1)  # where we think you look
        show(canvas, "Look at the white circle. Red dot = where Halo thinks you are looking.")
    if preds:
        mx, my = np.median([p[0] for p in preds]), np.median([p[1] for p in preds])
        e = float(np.hypot(mx - tx, my - ty))
    else:
        e = float("nan")
    errors.append(e); rows.append({"target": [tx, ty], "error_px": None if np.isnan(e) else round(e)})
good = [e for e in errors if not np.isnan(e)]
mean_err = float(np.mean(good)) if good else float("nan")
diag = float(np.hypot(sw, sh))

# ── 2. double-blink hits ─────────────────────────────────────────────────────
def blink_session(seconds, prompt):
    """Counts 'confirm' events using the SAME rule as the live controller (2 deliberate blinks within CONFIRM_WINDOW)."""
    t0, closed_frames, blinks, events = time.time(), 0, [], 0
    while time.time() - t0 < seconds:
        ok, frame = cap.read()
        if not ok:
            continue
        _, closed = predict(frame)
        now = time.time()
        if closed:
            closed_frames += 1
        else:
            if closed_frames >= DELIBERATE_FRAMES:
                blinks = [t for t in blinks if now - t < CONFIRM_WINDOW] + [now]
                if len(blinks) >= 2:
                    events += 1; blinks = []
            closed_frames = 0
        canvas = np.zeros((sh, sw, 3), np.uint8)
        cv2.putText(canvas, f"{prompt}   confirm events: {events}", (40, sh // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, f"{max(0, int(seconds - (now - t0)))}s", (40, sh // 2 + 70), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 255, 120), 3, cv2.LINE_AA)
        show(canvas)
    return events

hits = blink_session(15, "DOUBLE-BLINK deliberately 5 times (pause between each)")
false_alarms = blink_session(12, "Now just look at the screen and blink NORMALLY")
cap.release(); cv2.destroyAllWindows()

res = {"mean_error_px": round(mean_err), "mean_error_pct_of_diagonal": round(100 * mean_err / diag, 1),
       "targets": rows, "double_blink_hits_of_5": hits, "false_confirms_in_12s_natural_blinking": false_alarms,
       "screen": [sw, sh]}
json.dump(res, open(os.path.join(ROOT, "gaze_lab_results.json"), "w"), indent=1)
print(json.dumps(res, indent=1))
print(f"\nGaze error ≈ {mean_err:.0f}px ({100*mean_err/diag:.1f}% of the screen diagonal). Under ~8% is comfortable for large buttons.")
print(f"Double-blink hits: {hits}/5. False confirms while blinking naturally: {false_alarms} (want 0).")
