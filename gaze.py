"""Eye-gaze cursor control (EyeTrax) with blink-to-click and blink-to-confirm for the Guardian."""
import os
import threading
import time

import cv2
import pyautogui as pg

import agents

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
M1 = os.path.join(BASE_DIR, "gaze_lissajous.pkl")
M2 = os.path.join(BASE_DIR, "gaze_9point.pkl")

DELIBERATE_FRAMES = 3     # consecutive closed-eye frames that count as a deliberate blink
RIGHT_CLICK_FRAMES = 12   # a longer hold (about half a second) is a right click
CONFIRM_WINDOW = 2.0      # two deliberate blinks within this many seconds = confirm
CANCEL_HOLD = 1.6         # eyes held shut this long while a confirmation is pending = cancel


class GazeController:
    def __init__(self, on_event=None):
        self.est1 = self.est2 = None
        self.running = threading.Event()
        self.on_event = on_event or (lambda m: print(m))
        self.thread = None

    @property
    def calibrated(self) -> bool:
        return self.est1 is not None and self.est2 is not None

    def load_saved(self) -> bool:
        """Reuse a previous calibration so the demo doesn't need to recalibrate."""
        from eyetrax import GazeEstimator
        if os.path.exists(M1) and os.path.exists(M2):
            self.est1, self.est2 = GazeEstimator(), GazeEstimator()
            self.est1.load_model(M1)
            self.est2.load_model(M2)
            return True
        return False

    def calibrate(self):
        """MUST run on the main thread (OpenCV windows)."""
        from eyetrax import GazeEstimator, run_lissajous_calibration, run_9_point_calibration
        e1 = GazeEstimator()
        run_lissajous_calibration(e1)
        e2 = GazeEstimator()
        run_9_point_calibration(e2)
        e1.save_model(M1)
        e2.save_model(M2)
        self.est1, self.est2 = e1, e2

    def start(self):
        if not self.calibrated or self.running.is_set():
            return
        self.running.set()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running.clear()

    def _loop(self):
        cap = cv2.VideoCapture(0)
        sw, sh = pg.size()
        closed_frames, closed_since = 0, None
        blink_times, last_click = [], 0.0
        from eyetrax.filters import KalmanSmoother, make_kalman
        smoother = KalmanSmoother(make_kalman())  # Kalman filter keeps the cursor from jittering
        self.on_event("Gaze tracking on.")
        while self.running.is_set():
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            f1, b1 = self.est1.extract_features(frame)
            f2, b2 = self.est2.extract_features(frame)
            now = time.time()
            closed = bool(b1 and b2)

            if closed:
                closed_frames += 1
                closed_since = closed_since or now
                # long eye-closure while a transfer awaits approval = cancel
                if agents.gate.active and now - closed_since > CANCEL_HOLD:
                    agents.gate.resolve(False, "eye-close")
                    closed_since = None
                    closed_frames = 0
            else:
                if closed_frames >= DELIBERATE_FRAMES and now - last_click > 0.6:
                    last_click = now
                    if agents.gate.active:
                        blink_times = [t for t in blink_times if now - t < CONFIRM_WINDOW] + [now]
                        if len(blink_times) >= 2:  # double blink confirms
                            agents.gate.resolve(True, "double-blink")
                            blink_times = []
                    elif closed_frames >= RIGHT_CLICK_FRAMES:  # long hold = right click
                        pg.rightClick(_pause=False)
                    else:  # short deliberate blink = left click
                        pg.click(_pause=False)
                closed_frames, closed_since = 0, None

            if f1 is not None and f2 is not None and not closed:
                x1, y1 = self.est1.predict([f1])[0]
                x2, y2 = self.est2.predict([f2])[0]
                x = max(0, min(sw - 1, x1 * 0.6 + x2 * 0.4))
                y = max(0, min(sh - 1, y1 * 0.6 + y2 * 0.4))
                kx, ky = smoother.step(int(x), int(y))
                pg.moveTo(max(0, min(sw - 1, kx)), max(0, min(sh - 1, ky)), _pause=False)
            time.sleep(0.005)
        cap.release()
        self.on_event("Gaze tracking off.")
