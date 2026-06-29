import math
import time
import numpy as np
import transforms3d as t3d
from teleop import Teleop
from piper_sdk import *


def pose_matrix_to_piper_ctl(pose: np.ndarray, position_scale_mm: float = 1000.0):
    """
    Convert a 4x4 SE(3) pose matrix to PiPER EndPoseCtrl parameters.

    The teleop package delivers pose in metres (FLU convention).
    PiPER EndPoseCtrl expects:
      X, Y, Z  – in 0.001 mm  (i.e. metres * 1_000_000)
      RX, RY, RZ – in 0.001 deg (i.e. degrees * 1000)

    Args:
        pose: 4x4 numpy transformation matrix (metres, FLU)
        position_scale_mm: multiply position by this to map robot workspace;
                           default 1000 maps 1 m phone motion → 1 m robot motion.

    Returns:
        (x, y, z, rx, ry, rz) tuple of integers ready for EndPoseCtrl
    """
    x_m, y_m, z_m = pose[:3, 3]

    # Extract roll, pitch, yaw from the rotation matrix
    # transforms3d uses (ai, aj, ak) = (roll, pitch, yaw) in 'sxyz' convention
    roll, pitch, yaw = t3d.euler.mat2euler(pose[:3, :3], axes='sxyz')

    x   = round(x_m   * position_scale_mm * 1000)   # metres → 0.001 mm
    y   = round(y_m   * position_scale_mm * 1000)
    z   = round(z_m   * position_scale_mm * 1000)
    rx  = round(math.degrees(roll)  * 1000)           # rad → 0.001 deg
    ry  = round(math.degrees(pitch) * 1000)
    rz  = round(math.degrees(yaw)   * 1000)

    return x, y, z, rx, ry, rz


if __name__ == "__main__":
    # ── Robot setup ────────────────────────────────────────────────────────────
    robot = C_PiperInterface_V2()
    robot.ConnectPort()

    # Enable PiPER
    while not robot.EnablePiper():
        time.sleep(0.01)

    # Set Cartesian end-pose control mode
    mode = 0xAD
    spd  = 10
    robot.MotionCtrl_2(0x01, 0x00, spd, mode)
    time.sleep(0.1)
    robot.MotionCtrl_2(0x01, 0x00, spd, mode)

    # Move to a safe initial position (X=0 mm, Y=0 mm, Z=500 mm, no rotation)
    initial_position_m = np.array([0.0, 0.0, 0.5])   # metres
    robot.EndPoseCtrl(
        round(initial_position_m[0] * 1_000_000),     # X  (0.001 mm)
        round(initial_position_m[1] * 1_000_000),     # Y
        round(initial_position_m[2] * 1_000_000),     # Z
        0,                                             # RX (0.001 deg)
        0,                                             # RY
        0,                                             # RZ
    )

    # Build the initial 4×4 pose to hand to the teleop package
    initial_pose = np.eye(4)
    initial_pose[:3, 3] = initial_position_m

    # ── Teleop setup ───────────────────────────────────────────────────────────
    # The Teleop class starts an HTTPS server that serves a WebXR page.
    # Open https://<your-PC-IP>:4443 on your phone browser to start streaming.
    # No paid app required – the phone's motion sensor data is sent via WebSocket.

    def on_pose(pose: np.ndarray, message: dict) -> None:
        """
        Called every time the phone sends a new pose update.

        pose    – 4×4 SE(3) transformation matrix (metres, FLU convention)
        message – raw message dict from the WebXR frontend
        """
        print("─" * 60)
        print(f"Pose matrix (metres / FLU):\n{np.round(pose, 4)}")

        x, y, z, rx, ry, rz = pose_matrix_to_piper_ctl(pose)
        print(f"PiPER EndPoseCtrl → X={x}, Y={y}, Z={z}, RX={rx}, RY={ry}, RZ={rz}")

        robot.EndPoseCtrl(x, y, z, rx, ry, rz)

    teleop = Teleop(
        host="0.0.0.0",
        port=4443,
    )
    teleop.set_pose(initial_pose)   # tell the teleop lib the robot's current pose
    teleop.subscribe(on_pose)

    # run() is blocking – it starts the uvicorn HTTPS server
    teleop.run()