import argparse
import asyncio
import json
import os
import time
import traceback

import numpy as np
import websockets
from piper_sdk import C_PiperInterface_V2

from main import Teleop


async def websocket_handler(websocket, path, controller):
    """Handle websocket client state updates."""
    print(f"Remote client connected: {websocket.remote_address}")
    controller.enable_remote_input(True)

    try:
        async for message in websocket:
            try:
                payload = json.loads(message)
                controller.set_remote_inputs(payload)
            except json.JSONDecodeError:
                print("Invalid json payload received from remote client")
            except Exception as e:
                print(f"Error parsing remote input: {e}")
                traceback.print_exc()
    except websockets.exceptions.ConnectionClosed as e:
        print(f"Websocket connection closed: {e}")
    except Exception as e:
        print(f"Unexpected websocket handler error: {e}")
        traceback.print_exc()
    finally:
        print("Remote client disconnected")
        controller.enable_remote_input(False)


async def control_loop(controller, robot_interface, interval=0.05):
    """Run the robot control loop while remote inputs are active."""
    while True:
        try:
            controller.update()
            state = controller.get_state()
            controller.print_state()

            if state["arm_connected"] and state["arm_enabled"]:
                move_speed = state["movement_speed"]
                cmd_mode = state["command_mode"]
                low_level_mode = state["low_level_mode"]

                if low_level_mode == "joint":
                    joints = state["joints"]
                    joints_ctl = np.round(np.degrees(joints[:6]) * 1000).astype(int).tolist()
                    robot_interface.ModeCtrl(0x01, 0x01, move_speed, cmd_mode)
                    robot_interface.JointCtrl(*joints_ctl)
                elif low_level_mode == "pose":
                    xyz_rpy = state["xyz_rpy"].copy()
                    xyz_rpy[:3] = np.round(xyz_rpy[:3] * 1e6)
                    xyz_rpy[3:] = np.round(xyz_rpy[3:] * 1000)
                    xyz_rpy = xyz_rpy.astype(int).tolist()
                    robot_interface.ModeCtrl(0x01, 0x00, move_speed, cmd_mode)
                    robot_interface.EndPoseCtrl(*xyz_rpy)

                gripper_state = state["gripper"]
                gripper_value = int(controller.gripper_max_width * gripper_state * 1e4)
                robot_interface.GripperCtrl(gripper_value, 3000, 0x01, 0)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error in control loop: {e}")
            traceback.print_exc()
            await asyncio.sleep(1.0)
        finally:
            await asyncio.sleep(interval)


def get_current_path():
    return os.path.dirname(os.path.realpath(__file__))


async def main():
    parser = argparse.ArgumentParser(description="Websocket server for remote gamepad control")
    parser.add_argument("--host", default="0.0.0.0", help="Server host to bind")
    parser.add_argument("--port", type=int, default=8765, help="Server port")
    parser.add_argument("--urdf", default=os.path.join(get_current_path(), "piper/piper.urdf"), help="URDF file path")
    parser.add_argument("--mesh", default=os.path.join(get_current_path(), "piper/meshes/"), help="Mesh folder path")
    parser.add_argument("--root", default="/base_link", help="Root name for visualization")
    parser.add_argument("--target", default="link6", help="Target link name")
    args = parser.parse_args()

    robot_interface = C_PiperInterface_V2()
    controller = Teleop(robot_interface, args.urdf, args.mesh, args.root, args.target)

    websocket_server = await websockets.serve(
        lambda ws, path: websocket_handler(ws, path, controller),
        args.host,
        args.port,
    )

    print(f"Remote websocket server listening on ws://{args.host}:{args.port}")
    print("Waiting for remote gamepad client...")

    control_task = asyncio.create_task(control_loop(controller, robot_interface))

    try:
        await websocket_server.wait_closed()
    except KeyboardInterrupt:
        pass
    finally:
        control_task.cancel()
        await control_task


if __name__ == "__main__":
    asyncio.run(main())
