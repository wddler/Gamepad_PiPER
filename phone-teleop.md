# Creative Project: Controlling a Robotic Arm with a Smartphone Gyroscope

## Abstract
This project implements controlling a robotic arm using smartphone sensor data (accelerometer, gyroscope, magnetometer). The data is transmitted in real-time from the smartphone to a local Python script via WebSockets, and the script controls the robotic arm's movement after solving the attitude/orientation.

## Tags
Smartphone Sensors, Attitude Teleoperation, Gyroscope, Attitude Estimation, EKF

## Code Repository
GitHub Link: [https://github.com/agilexrobotics/Agilex-College/tree/master/piper/mobilePhoneCtl](https://github.com/agilexrobotics/Agilex-College/tree/master/piper/mobilePhoneCtl)

## Demo

[![](https://i.ytimg.com/vi/WMK5KRgzJXU/oar2.jpg?sqp=-oaymwEoCJgDENAFSFqQAgHyq4qpAxcIARUAAIhC2AEB4gEKCBgQAhgGOAFAAQ==&rs=AOn4CLAjvJ9nijQAz4FoncwwMIaFZuV94g)](https://www.youtube.com/shorts/WMK5KRgzJXU)

## Environment Configuration

- Operating System: Ubuntu (Ubuntu 18.04 or higher recommended)
- Python Environment: Python 3.7 or higher

- Clone the project:

    ```bash
    git clone https://github.com/agilexrobotics/Agilex-College.git
    cd Agilex-College/piper/mobilePhoneCtl/
    ```

- Install dependencies:

    ```bash
    pip install -r requirements.txt --upgrade
    ```

- Ensure that `piper_sdk` and its hardware dependencies are correctly installed and configured.

## Smartphone App Installation

This project recommends using [Sensor Stream IMU+](https://www.sensorstream.app/) (paid App) for data collection and streaming on the phone.

- Go to the official website or app store to purchase and install Sensor Stream IMU+.
- This App supports both iOS and Android.

## App Usage Instructions

1. Open the Sensor Stream IMU+ App.
2. Enter the IP address and port (default 5000) of the computer running this script in "Set IP Address", e.g., `192.168.1.100:5000`.
3. Select the sensors to stream (Accelerometer, Gyroscope, Magnetometer).
4. Set an appropriate update interval (e.g., 20ms).
5. Tap "Start Streaming" to start sending data.

## Python Script Usage

1. Connect the robotic arm and bring up the CAN interface.

    ```bash
    sudo ip link set can0 up type can bitrate 1000000
    ```

2. Run `main.py` in this directory:

    ```bash
    python3 main.py
    ```

3. Once started, the script will display the local IP address and port. Enter these exact values in the App.
4. When the App starts streaming data, the script will automatically compute the orientation and control the robotic arm's end-effector attitude via `piper_sdk`.

## Data Transmission and Robotic Arm Control Details

- The smartphone sends 3-axis accelerometer, gyroscope, and magnetometer data in real-time to the Python script via WebSockets.
- The script uses the Extended Kalman Filter (EKF) algorithm for attitude estimation to obtain Euler angles (roll, pitch, yaw).
- The computed orientation is sent in real-time to the robotic arm via the `EndPoseCtrl` interface of `piper_sdk` to achieve attitude control.

## Important Notes

- Make sure that the smartphone and the computer are on the same local area network (LAN), and that the firewall allows communication on port 5000.
- Please ensure safety before moving the robotic arm to avoid any collisions.
- If you need to modify the port or the initial position, edit the corresponding parameters in [`main.py`](main.py).

## References

- [Attitude and Heading Reference System (AHRS) based on EKF](https://zhuanlan.zhihu.com/p/103617763)