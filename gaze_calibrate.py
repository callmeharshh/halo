"""Run eye-tracking calibration in its own process (OpenCV windows need a main thread). Saves gaze_*.pkl."""
from gaze import GazeController

if __name__ == "__main__":
    GazeController().calibrate()
    print("Calibration saved.")
