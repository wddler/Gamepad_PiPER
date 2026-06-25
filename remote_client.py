import argparse
import asyncio
import json
import pygame
import websockets


class RemoteGamepadClient:
    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        pygame.init()
        pygame.joystick.init()
        self.joystick = None
        self.button_map = {}
        self.axis_map = {}
        self.hat_map = {}
        self._setup_platform_mappings()
        self._connect_joystick()

    def _setup_platform_mappings(self):
        driver = pygame.display.get_driver()
        if driver == "windows":
            self.button_map = {
                'a': 0, 'b': 1, 'x': 2, 'y': 3,
                'lb': 4, 'rb': 5, 'back': 6, 'start': 7,
                'l3': 8, 'r3': 9, 'home': 10,
            }
            self.axis_map = {
                'left_x': 0, 'left_y': 1, 'right_x': 2, 'right_y': 3,
                'left_trigger': 4, 'right_trigger': 5,
            }
            self.hat_map = {'dpad': 0}
        else:
            self.button_map = {
                'a': 0, 'b': 1, 'x': 2, 'y': 3,
                'lb': 4, 'rb': 5, 'back': 6, 'start': 7,
                'home': 8, 'l3': 9, 'r3': 10,
            }
            self.axis_map = {
                'left_x': 0, 'left_y': 1, 'right_x': 3, 'right_y': 4,
                'left_trigger': 2, 'right_trigger': 5,
            }
            self.hat_map = {'dpad': 0}

    def _connect_joystick(self):
        if pygame.joystick.get_count() > 0:
            try:
                self.joystick = pygame.joystick.Joystick(0)
                self.joystick.init()
            except Exception:
                self.joystick = None

    def _get_axis_value(self, axis_name):
        if self.joystick is None or axis_name not in self.axis_map:
            return 0.0
        axis_index = self.axis_map[axis_name]
        if axis_index >= self.joystick.get_numaxes():
            return 0.0
        value = self.joystick.get_axis(axis_index)
        if axis_name in ['left_trigger', 'right_trigger']:
            return (value + 1) / 2
        return float(value)

    def _get_button_state(self, button_name):
        if self.joystick is None or button_name not in self.button_map:
            return False
        button_index = self.button_map[button_name]
        if button_index >= self.joystick.get_numbuttons():
            return False
        return bool(self.joystick.get_button(button_index))

    def _get_hat_value(self, hat_name):
        if self.joystick is None or hat_name not in self.hat_map:
            return (0, 0)
        hat_index = self.hat_map[hat_name]
        if hat_index >= self.joystick.get_numhats():
            return (0, 0)
        return tuple(self.joystick.get_hat(hat_index))

    def get_remote_payload(self):
        pygame.event.pump()
        axes = {name: self._get_axis_value(name) for name in self.axis_map}
        buttons = {name: self._get_button_state(name) for name in self.button_map}
        hat = {'dpad': self._get_hat_value('dpad')}
        return {
            'axes': axes,
            'buttons': buttons,
            'hat': hat,
        }

    async def run(self):
        uri = f"ws://{self.host}:{self.port}"
        print(f"Connecting to remote server at {uri}")
        async with websockets.connect(uri) as websocket:
            print("Connected to remote server")
            try:
                while True:
                    payload = self.get_remote_payload()
                    await websocket.send(json.dumps(payload))
                    await asyncio.sleep(0.02)
            except KeyboardInterrupt:
                print("Client exiting")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remote gamepad client for websocket control")
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=8765, help="Server port")
    args = parser.parse_args()

    client = RemoteGamepadClient(args.host, args.port)
    import websockets
    asyncio.run(client.run())
