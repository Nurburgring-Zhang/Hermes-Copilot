#!/usr/bin/env python3
"""
Hermes Agent Web UI Auto-Start Script
=====================================
Starts the Hermes Agent Web UI server on port 9120 (0.0.0.0).
This script is designed to be called from the gateway startup.
"""
import sys
import os

# Add hermes-agent to path
AGENT_ROOT = "/home/administrator/.hermes/hermes-agent"
sys.path.insert(0, AGENT_ROOT)
os.chdir(AGENT_ROOT)

from hermes_cli.web_server import app
import uvicorn
import threading
import signal

_running = True

def signal_handler(sig, frame):
    global _running
    _running = False

def run_server():
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    uvicorn.run(app, host="0.0.0.0", port=9120, log_level="error")

if __name__ == "__main__":
    print("Starting Hermes Agent Web UI on 0.0.0.0:9120...")
    run_server()
