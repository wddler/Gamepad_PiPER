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
GRIPPER_STEP       = 2_000    # 0.001 mm per frame ≈ 2 mm/frame while held


class PiperGripper:
    """
    Gripper controller supporting:
      - Binary toggle  : 'open' / 'close' from the gripper toggle button
      - Gradual open   : button A held → decrements position toward 0
      - Gradual close  : button B held → increments position toward GRIPPER_CLOSED_POS

    Sends GripperCtrl only when the position actually changes.
    """
    def __init__(self, robot):
        self._robot = robot
        self._pos: int = GRIPPER_OPEN_POS      # current position (0.001 mm)
        self._last_sent_pos: int | None = None  # last position sent to robot

    def _send(self, pos: int) -> None:
        pos = max(GRIPPER_OPEN_POS, min(GRIPPER_CLOSED_POS, pos))
        if pos == self._last_sent_pos:
            return
        self._pos = pos
        self._last_sent_pos = pos
        print(f"Gripper pos={pos}")
        self._robot.GripperCtrl(pos, GRIPPER_EFFORT, 0x01, 0)

    @property
    def pos(self) -> int:
        return self._pos

    def update(self, state: str, btn_a: bool, btn_b: bool) -> None:
        """
        Call every teleop frame.

        state – 'open' or 'close' from the binary toggle button
        btn_a – True while A is held  → gradually OPEN  (position decreases)
        btn_b – True while B is held  → gradually CLOSE (position increases)
        """
        if btn_a:
            self._send(self._pos - GRIPPER_STEP)
        elif btn_b:
            self._send(self._pos + GRIPPER_STEP)
        else:
            # Binary toggle: only act on transitions
            target = GRIPPER_OPEN_POS if state == "open" else GRIPPER_CLOSED_POS
            self._send(target)


def read_current_pose(robot, retries: int = 20, delay: float = 0.1) -> np.ndarray:
    """
    Read the current end-effector pose from the robot and return it as a 4×4
    SE(3) matrix in metres (FLU convention), suitable for teleop.set_pose().

    Retries until the CAN bus returns a non-zero Z position (the arm needs
    a moment after enabling before feedback is available).

    EndPoseMsgs fields: X/Y/Z in 0.001 mm, RX/RY/RZ in 0.001 deg.
    """
    for attempt in range(retries):
        msgs = robot.GetArmEndPoseMsgs()
        ep = msgs.end_pose
        # Z == 0 almost certainly means feedback not ready yet
        if ep.Z_axis != 0:
            break
        print(f"Waiting for arm pose feedback… ({attempt+1}/{retries})")
        time.sleep(delay)

    x_m  = ep.X_axis  * 1e-6          # 0.001 mm → metres
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
        # Toggle button: 'open' / 'close'
        # A button (hold): gradually open   (position decreases)
        # B button (hold): gradually close  (position increases)
        gripper_state = message.get("gripper", "open")
        btn_a = bool(message.get("reservedButtonA", False))
        btn_b = bool(message.get("reservedButtonB", False))
        gripper.update(gripper_state, btn_a, btn_b)

        # ── Arm pose ───────────────────────────────────────────────────────────
        x, y, z, rx, ry, rz = pose_matrix_to_piper_ctl(pose)

        moving = message.get("move", False)
        print(
            f"{'MOVE' if moving else 'HOLD'} | "
            f"X={x:+8d} Y={y:+8d} Z={z:+8d} | "
            f"RX={rx:+7d} RY={ry:+7d} RZ={rz:+7d} | "
            f"Grip={gripper.pos} A={btn_a} B={btn_b}"
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