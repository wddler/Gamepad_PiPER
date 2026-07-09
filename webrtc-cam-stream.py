#!/usr/bin/env python3
"""
WebRTC Camera Streamer using MediaMTX and FFmpeg.

This script:
1. Detects system architecture and downloads the matching MediaMTX binary.
2. Generates a self-signed SSL certificate for HTTPS (required for WebRTC on mobile/remote browsers).
3. Auto-detects USB camera devices (/dev/video*).
4. Generates mediamtx.yml with a path configured to capture the camera via FFmpeg.
5. Runs the server and provides local/network URLs to watch the stream.
"""

import os
import sys
import glob
import socket
import shutil
import signal
import tarfile
import platform
import argparse
import subprocess
import urllib.request

# Configuration
MEDIAMTX_VERSION = "1.19.2"
SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "mediamtx_server"))

def get_mediamtx_url():
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    if system != "linux":
        raise OSError(f"Unsupported OS: {system}. This script only supports Linux.")
        
    if machine in ["x86_64", "amd64"]:
        arch_suffix = "linux_amd64.tar.gz"
    elif machine in ["aarch64", "arm64"]:
        arch_suffix = "linux_arm64.tar.gz"
    elif machine in ["armv7l", "armhf"]:
        arch_suffix = "linux_armv7.tar.gz"
    else:
        raise OSError(f"Unsupported architecture: {machine}")
        
    return f"https://github.com/bluenviron/mediamtx/releases/download/v{MEDIAMTX_VERSION}/mediamtx_v{MEDIAMTX_VERSION}_{arch_suffix}"

def download_mediamtx():
    os.makedirs(SERVER_DIR, exist_ok=True)
    binary_path = os.path.join(SERVER_DIR, "mediamtx")
    
    if os.path.exists(binary_path):
        print(f"MediaMTX binary already exists at: {binary_path}")
        return binary_path
        
    url = get_mediamtx_url()
    tarball_path = os.path.join(SERVER_DIR, "mediamtx.tar.gz")
    
    print(f"Downloading MediaMTX v{MEDIAMTX_VERSION}...")
    print(f"Source: {url}")
    try:
        # Set a user-agent to avoid potential blockings
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response, open(tarball_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
    except Exception as e:
        print(f"ERROR: Failed to download MediaMTX: {e}")
        print("Please check your internet connection or download it manually.")
        sys.exit(1)
        
    print("Extracting archive...")
    try:
        with tarfile.open(tarball_path, "r:gz") as tar:
            tar.extractall(path=SERVER_DIR)
        os.remove(tarball_path)
        # Set executable permission
        os.chmod(binary_path, 0o755)
        print("MediaMTX extraction complete.")
    except Exception as e:
        print(f"ERROR: Failed to extract MediaMTX: {e}")
        if os.path.exists(tarball_path):
            os.remove(tarball_path)
        sys.exit(1)
        
    return binary_path

def generate_ssl_certs():
    key_path = os.path.join(SERVER_DIR, "server.key")
    cert_path = os.path.join(SERVER_DIR, "server.crt")
    
    if os.path.exists(key_path) and os.path.exists(cert_path):
        print("SSL Certificate and Key already exist.")
        return key_path, cert_path
        
    print("Generating self-signed SSL certificate for WebRTC HTTPS signaling...")
    
    if not shutil.which("openssl"):
        print("WARNING: 'openssl' command not found. Cannot generate SSL certificates automatically.")
        print("WebRTC over network HTTPS will not be available. Falling back to HTTP.")
        return None, None
        
    try:
        cmd = [
            "openssl", "req", "-new", "-x509", "-sha256",
            "-days", "3650", "-nodes",
            "-subj", "/CN=MediaMTX",
            "-keyout", key_path,
            "-out", cert_path
        ]
        # Run openssl silently
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("SSL certificates generated successfully.")
        return key_path, cert_path
    except Exception as e:
        print(f"WARNING: Failed to generate SSL certificates: {e}")
        print("Falling back to HTTP (no encryption).")
        # Clean up any partial files
        if os.path.exists(key_path): os.remove(key_path)
        if os.path.exists(cert_path): os.remove(cert_path)
        return None, None

def get_camera_devices():
    devices = glob.glob("/dev/video*")
    devices.sort()
    return devices

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # connect to external server to determine outbound interface IP (no packets actually sent)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def write_mediamtx_config(device, width, height, fps, input_format, key_path, cert_path):
    config_path = os.path.join(SERVER_DIR, "mediamtx.yml")
    
    # Check if FFmpeg is installed
    if not shutil.which("ffmpeg"):
        print("\nERROR: 'ffmpeg' was not found in your system's PATH.")
        print("FFmpeg is required to capture the USB camera stream.")
        print("Please install it using your package manager. On Ubuntu/Debian:")
        print("  sudo apt update && sudo apt install ffmpeg")
        print("\nExit.")
        sys.exit(1)
        
    # Build FFmpeg command
    ffmpeg_parts = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-f", "v4l2"]
    
    # Input options (must be before -i)
    if input_format != "auto":
        ffmpeg_parts.extend(["-input_format", input_format])
        
    if width and height:
        ffmpeg_parts.extend(["-video_size", f"{width}x{height}"])
        
    if fps:
        ffmpeg_parts.extend(["-framerate", str(fps)])
        
    ffmpeg_parts.extend(["-i", device])
    
    # Encoding & output options (optimized for low-latency WebRTC compatibility)
    ffmpeg_parts.extend([
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-f", "rtsp",
        "rtsp://localhost:$RTSP_PORT/$MTX_PATH"
    ])
    
    ffmpeg_cmd = " ".join(ffmpeg_parts)
    print(f"Configured camera device: {device}")
    print(f"FFmpeg command: {ffmpeg_cmd}")
    
    # SSL/TLS encryption setup
    webrtc_encryption = "no"
    ssl_key = "server.key"
    ssl_cert = "server.crt"
    
    if key_path and cert_path:
        webrtc_encryption = "yes"
        ssl_key = os.path.basename(key_path)
        ssl_cert = os.path.basename(cert_path)
        
    # Write a clean mediamtx configuration file
    config_content = f"""# MediaMTX Configuration
# Auto-generated by webrtc-cam-stream.py

logLevel: info

# RTSP server configuration (FFmpeg publishes here)
rtsp: yes
rtspAddress: :8554

# WebRTC server configuration (Clients watch here)
webrtc: yes
webrtcAddress: :8889
webrtcLocalUDPAddress: :8189
webrtcEncryption: {webrtc_encryption}
webrtcServerKey: {ssl_key}
webrtcServerCert: {ssl_cert}

# Disable unused protocols to avoid port conflicts
rtmp: no
hls: no
srt: no

paths:
  cam:
    runOnInit: {ffmpeg_cmd}
    runOnInitRestart: yes
"""
    try:
        with open(config_path, "w") as f:
            f.write(config_content)
        print(f"Wrote config to: {config_path}")
    except Exception as e:
        print(f"ERROR: Failed to write mediamtx.yml: {e}")
        sys.exit(1)

def main():
    # Detect default camera device
    devices = get_camera_devices()
    default_device = devices[0] if devices else "/dev/video0"
    
    parser = argparse.ArgumentParser(
        description="Launch a MediaMTX server and stream a USB camera over low-latency WebRTC.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-d", "--device", default=default_device, help="USB Camera device path")
    parser.add_argument("--width", type=int, help="Camera width resolution (e.g. 1280)")
    parser.add_argument("--height", type=int, help="Camera height resolution (e.g. 720)")
    parser.add_argument("--fps", type=int, help="Camera framerate (e.g. 30)")
    parser.add_argument("--format", choices=["mjpeg", "yuyv422", "auto"], default="auto", 
                        help="Camera capture format (mjpeg is recommended for higher resolution over USB 2.0)")
    parser.add_argument("--no-ssl", action="store_true", help="Disable SSL/HTTPS encryption (forces HTTP)")
    
    args = parser.parse_args()
    
    # 1. Download MediaMTX binary if needed
    binary_path = download_mediamtx()
    
    # 2. SSL Setup
    key_path, cert_path = None, None
    if not args.no_ssl:
        key_path, cert_path = generate_ssl_certs()
        
    # 3. Create config
    write_mediamtx_config(
        device=args.device,
        width=args.width,
        height=args.height,
        fps=args.fps,
        input_format=args.format,
        key_path=key_path,
        cert_path=cert_path
    )
    
    # Get local IP and determine scheme
    local_ip = get_local_ip()
    scheme = "https" if (key_path and cert_path) else "http"
    
    print("\n" + "="*70)
    print("               WEBRTC CAMERA STREAMER IS RUNNING               ")
    print("="*70)
    print(f"Local Access:   {scheme}://localhost:8889/cam")
    print(f"Network Access: {scheme}://{local_ip}:8889/cam")
    print("-"*70)
    if scheme == "https":
        print("IMPORTANT (Network / Phone Access):")
        print("1. When you open the HTTPS URL on your phone or other device,")
        print("   your browser will warn you about a self-signed certificate.")
        print("2. You MUST click 'Advanced' and 'Proceed to <IP>' to view the stream.")
        print("3. WebRTC will NOT work on mobile/remote devices without HTTPS.")
    else:
        print("WARNING: Running without SSL (HTTP mode).")
        print("Some browsers will block WebRTC connections on HTTP unless accessed")
        print("from localhost. For network access, run without --no-ssl.")
    print("="*70 + "\n")
    print("Press Ctrl+C to stop streaming.\n")
    
    # 4. Start the server process
    try:
        process = subprocess.Popen(
            [binary_path],
            cwd=SERVER_DIR,
            stdout=sys.stdout,
            stderr=sys.stderr
        )
        
        # Shutdown handler
        def signal_handler(sig, frame):
            print("\nStopping WebRTC camera stream server...")
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            print("Server stopped.")
            sys.exit(0)
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        process.wait()
        
    except KeyboardInterrupt:
        print("\nStopping WebRTC camera stream server...")
        try:
            process.terminate()
            process.wait(timeout=3)
        except Exception:
            pass
        print("Server stopped.")

if __name__ == "__main__":
    main()
