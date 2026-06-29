import math
import time
import numpy as np
import transforms3d as t3d
from teleop import Teleop
from piper_sdk import *

# ── Phone orientation guide ────────────────────────────────────────────────────
#
#  HOW TO HOLD THE PHONE:
#  ┌─────────────────────────────────────────────────────┐
#  │  Hold the phone UPRIGHT, screen facing you,         │
#  │  like reading a text message. That is the           │
#  │  "natural" orientation ([0, 0, 0]).                  │
#  │                                                     │
#  │  Press and HOLD the on-screen "Move" button to      │
#  │  enable motion. Release it to pause (pose is        │
#  │  remembered). This lets you re-grip without drift.  │
#  └─────────────────────────────────────────────────────┘
#
# ── GripperCtrl parameters ────────────────────────────────────────────────────
#  GripperCtrl(gripper_angle, gripper_effort, gripper_code, set_zero)
#    gripper_angle  : int, unit 0.001 mm (0 = open, 70_000 = fully closed ~70mm)
#    gripper_effort : int, unit 0.001 N/m, range 0-5000
#    gripper_code   : 0x00=disable, 0x01=enable, 0x02=disable+clear, 0x03=enable+clear
#    set_zero       : 0x00=no-op, 0xAE=set current position as zero
# ──────────────────────────────────────────────────────────────────────────────

GRIPPER_OPEN_POS   = 0        # fully open  (0.001 mm units)
GRIPPER_CLOSED_POS = 70_000   # fully closed (~70 mm stroke)
GRIPPER_EFFORT     = 1000     # 0.001 N/m — moderate grip force


class PiperGripper:
    """
    Thin wrapper around piper_sdk GripperCtrl.
    Sends commands only on state transitions to avoid spamming the CAN bus.
    """
    def __init__(self, robot):
        self._robot = robot
        self._last_state: str | None = None   # 'open' or 'close'

    def update(self, state: str) -> None:
        """Call with 'open' or 'close' each teleop callback tick."""
        if state == self._last_state:
            return                             # no change – skip
        self._last_state = state
        if state == "close":
            pos = GRIPPER_CLOSED_POS
        else:
            pos = GRIPPER_OPEN_POS
        print(f"Gripper → {'CLOSE' if state == 'close' else 'OPEN'} ({pos})")
        # gripper_code=0x01 is REQUIRED to enable the gripper actuator
        self._robot.GripperCtrl(pos, GRIPPER_EFFORT, 0x01, 0)


def read_current_pose(robot) -> np.ndarray:
    """
    Read the current end-effector pose from the robot and return it as a 4×4
    SE(3) matrix in metres (FLU convention), suitable for teleop.set_pose().

    EndPoseMsgs fields are in 0.001 mm (XYZ) and 0.001 deg (RX/RY/RZ).
    """
    msgs = robot.GetArmEndPoseMsgs()
    # msgs.end_pose has: X_axis, Y_axis, Z_axis (0.001 mm)
    #                    RX_axis, RY_axis, RZ_axis (0.001 deg)
    ep = msgs.end_pose
    x_m  = ep.X_axis  * 1e-6   # 0.001 mm → metres
    y_m  = ep.Y_axis  * 1e-6
    z_m  = ep.Z_axis  * 1e-6
    rx_r = math.radians(ep.RX_axis * 1e-3)   # 0.001 deg → radians
    ry_r = math.radians(ep.RY_axis * 1e-3)
    rz_r = math.radians(ep.RZ_axis * 1e-3)

    R = t3d.euler.euler2mat(rx_r, ry_r, rz_r, axes='sxyz')
    pose = np.eye(4)
    pose[:3, :3] = R
    pose[:3, 3]  = [x_m, y_m, z_m]
    return pose


def pose_matrix_to_piper_ctl(pose: np.ndarray):
    """
    Convert a 4×4 SE(3) pose matrix (metres, FLU) to PiPER EndPoseCtrl ints.

    PiPER EndPoseCtrl expects:
      X, Y, Z    – int, unit 0.001 mm  (metres × 1_000_000)
      RX, RY, RZ – int, unit 0.001 deg (degrees × 1000)
    """
    x_m, y_m, z_m = pose[:3, 3]
    roll, pitch, yaw = t3d.euler.mat2euler(pose[:3, :3], axes='sxyz')

    x  = round(x_m  * 1_000_000)
    y  = round(y_m  * 1_000_000)
    z  = round(z_m  * 1_000_000)
    rx = round(math.degrees(roll)  * 1000)
    ry = round(math.degrees(pitch) * 1000)
    rz = round(math.degrees(yaw)   * 1000)

    return x, y, z, rx, ry, rz


if __name__ == "__main__":
    # ── Robot setup ────────────────────────────────────────────────────────────
    robot = C_PiperInterface_V2()
    robot.ConnectPort()

    # Enable all 6 joints + gripper (motor 7 = all)
    while not robot.EnablePiper():
        time.sleep(0.01)

    # Enable gripper actuator (must be done before any GripperCtrl position cmd)
    robot.GripperCtrl(GRIPPER_OPEN_POS, GRIPPER_EFFORT, 0x01, 0)
    time.sleep(0.1)

    # Set end-pose control mode (MOVE P = 0x00, no MIT = 0x00)
    # ── DO NOT move to a fixed initial position ─────────────────────────────
    # The robot stays wherever it currently is.
    # You should position it manually to a comfortable starting pose first.
    spd = 30
    robot.MotionCtrl_2(0x01, 0x00, spd, 0x00)
    time.sleep(0.1)
    robot.MotionCtrl_2(0x01, 0x00, spd, 0x00)

    # Read the current end-effector pose so teleop starts from where we are
    time.sleep(0.2)   # give the CAN bus time to return state
    initial_pose = read_current_pose(robot)
    print(f"Starting pose (metres):\n{np.round(initial_pose, 4)}")

    gripper = PiperGripper(robot)

    # ── Teleop setup ───────────────────────────────────────────────────────────
    # Open https://<your-PC-IP>:4443 in your phone browser.
    # Hold the phone UPRIGHT (portrait, screen facing you) – neutral pose.
    # Press and hold "Move" on screen to enable arm motion.

    def on_pose(pose: np.ndarray, message: dict) -> None:
        """
        Called on every WebXR frame (~100 Hz).

        pose    – 4×4 SE(3) matrix (metres, FLU)
        message – raw dict from phone:
                    'move'    : bool  – True while Move button is held
                    'gripper' : str   – 'open' or 'close'
                    'scale'   : float – motion scale (0.2 … 1.0)
        """
        # ── Gripper ────────────────────────────────────────────────────────────
        gripper_state = message.get("gripper", "open")
        gripper.update(gripper_state)

        # ── Arm pose ───────────────────────────────────────────────────────────
        x, y, z, rx, ry, rz = pose_matrix_to_piper_ctl(pose)

        moving = message.get("move", False)
        print(
            f"{'MOVE' if moving else 'HOLD'} | "
            f"X={x:+8d} Y={y:+8d} Z={z:+8d} | "
            f"RX={rx:+7d} RY={ry:+7d} RZ={rz:+7d} | "
            f"Gripper={gripper_state}"
        )

        # Re-send the mode command every tick – same pattern as official SDK demo
        robot.MotionCtrl_2(0x01, 0x00, spd, 0x00)
        robot.EndPoseCtrl(x, y, z, rx, ry, rz)

    teleop = Teleop(
        host="0.0.0.0",
        port=4443,
        # Phone held UPRIGHT (portrait, screen toward you) = zero pose.
        natural_phone_orientation_euler=[0, 0, 0],
    )
    teleop.set_pose(initial_pose)
    teleop.subscribe(on_pose)

    # run() is blocking – starts the uvicorn HTTPS server
    teleop.run()