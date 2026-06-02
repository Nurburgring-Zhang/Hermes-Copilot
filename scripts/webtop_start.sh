#!/bin/bash
# =============================================================================
# Hermes WebTop - 浏览器桌面环境 (非Docker方案 - Wayland安全版)
# 架构: Xvfb + x11vnc + noVNC + websockify
# 格林主人 2026-05-08
# =============================================================================

# === Configuration ===
DISPLAY_NUM=99
DISPLAY=":${DISPLAY_NUM}"
VNC_PORT=5900
NOVNC_PORT=6080
RESOLUTION="1920x1080x24"
NOVNC_DIR="${HOME}/.hermes/noVNC"
PID_DIR="/tmp/hermes-webtop"

# === Critical: Force X11, not Wayland ===
unset WAYLAND_DISPLAY
export DISPLAY=${DISPLAY}
export XDG_SESSION_TYPE=x11
export QT_QPA_PLATFORM=xcb

# === Cleanup function ===
cleanup() {
    echo "[WebTop] Shutting down..."
    kill $(cat ${PID_DIR}/x11vnc.pid 2>/dev/null) 2>/dev/null
    kill $(cat ${PID_DIR}/websockify.pid 2>/dev/null) 2>/dev/null
    kill $(cat ${PID_DIR}/Xvfb.pid 2>/dev/null) 2>/dev/null
    rm -rf ${PID_DIR}
    echo "[WebTop] Stopped."
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

mkdir -p ${PID_DIR}

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              Hermes WebTop - 浏览器桌面环境                ║"
echo "║            Xvfb + x11vnc + noVNC + websockify              ║"
echo "╚══════════════════════════════════════════════════════════════╝"

# === Step 1: Start Xvfb (virtual framebuffer) ===
echo "[1/4] Starting Xvfb (virtual display ${DISPLAY}, ${RESOLUTION})..."
Xvfb ${DISPLAY} -screen 0 ${RESOLUTION} -ac &
XVFB_PID=$!
echo ${XVFB_PID} > ${PID_DIR}/Xvfb.pid
sleep 1

# Verify Xvfb is running
if ! kill -0 ${XVFB_PID} 2>/dev/null; then
    echo "[ERROR] Xvfb failed to start!"
    exit 1
fi
echo "       Xvfb running (PID: ${XVFB_PID})"

# === Step 2: Start window manager ===
echo "[2/4] Starting Xfce4 desktop..."
export DISPLAY=${DISPLAY}
startxfce4 &
sleep 3
echo "       Xfce4 desktop started"

# === Step 3: Start x11vnc (VNC server) ===
echo "[3/4] Starting x11vnc on port ${VNC_PORT}..."
x11vnc -display ${DISPLAY} -forever -shared -rfbport ${VNC_PORT} -no6 -noxrecord -noxdamage -noxfixes -repeat -noshm -nopw &
X11VNC_PID=$!
echo ${X11VNC_PID} > ${PID_DIR}/x11vnc.pid
sleep 1

if ! kill -0 ${X11VNC_PID} 2>/dev/null; then
    echo "[ERROR] x11vnc failed to start!"
    cleanup
fi
echo "       x11vnc running (PID: ${X11VNC_PID})"

# === Step 4: Start websockify (WebSocket proxy) + noVNC ===
echo "[4/4] Starting noVNC Web client on port ${NOVNC_PORT}..."
cd ${NOVNC_DIR}
websockify --web ${NOVNC_DIR} ${NOVNC_PORT} 127.0.0.1:${VNC_PORT} &
WEBSOCKIFY_PID=$!
echo ${WEBSOCKIFY_PID} > ${PID_DIR}/websockify.pid
sleep 1

if ! kill -0 ${WEBSOCKIFY_PID} 2>/dev/null; then
    echo "[ERROR] websockify failed to start!"
    cleanup
fi
echo "       websockify running (PID: ${WEBSOCKIFY_PID})"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ WebTop IS RUNNING!                                     ║"
echo "║                                                            ║"
echo "║  Access via browser: http://localhost:${NOVNC_PORT}/vnc_lite.html ║"
echo "║                                                            ║"
echo "║  To stop: kill \$(cat ${PID_DIR}/websockify.pid)            ║"
echo "║  Or just run: pkill -f webtop_start.sh                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"

# Keep running
while true; do
    sleep 10
    # Health check
    if ! kill -0 ${WEBSOCKIFY_PID} 2>/dev/null; then
        echo "[WARN] websockify died, restarting..."
        cd ${NOVNC_DIR}
        websockify --web ${NOVNC_DIR} ${NOVNC_PORT} 127.0.0.1:${VNC_PORT} &
        WEBSOCKIFY_PID=$!
        echo ${WEBSOCKIFY_PID} > ${PID_DIR}/websockify.pid
    fi
    if ! kill -0 ${X11VNC_PID} 2>/dev/null; then
        echo "[WARN] x11vnc died, restarting..."
        x11vnc -display ${DISPLAY} -forever -shared -rfbport ${VNC_PORT} -no6 -noxrecord -noxdamage -noxfixes -repeat -noshm -nopw &
        X11VNC_PID=$!
        echo ${X11VNC_PID} > ${PID_DIR}/x11vnc.pid
    fi
done
