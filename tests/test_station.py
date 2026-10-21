"""ground/station.py against a fake InfluxDB: it writes what it receives and,
on SIGTERM or SIGINT, flushes and exits 0. Every wait has a timeout."""

import http.server
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import params

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "housekeeping.bin"


class FakeInflux(http.server.BaseHTTPRequestHandler):
    bodies = []

    def do_POST(self):  # noqa: N802 (http.server naming)
        self.bodies.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def ports_free():
    for port in (params.PORT_TELEMETRY, params.PORT_SIM_TRUTH):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                return False
    return True


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_station_writes_then_flushes_on_signal(sig):
    if not ports_free():
        pytest.skip("downlink ports busy (is a station or demo running?)")
    FakeInflux.bodies = []
    server = http.server.HTTPServer(("127.0.0.1", 0), FakeInflux)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {"INFLUX_URL": f"http://127.0.0.1:{server.server_port}", "INFLUX_ORG": "o",
           "INFLUX_BUCKET": "b", "INFLUX_TOKEN": "t", "PATH": ""}
    cmd = [sys.executable, "-u", str(ROOT / "ground" / "station.py")]
    station = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True)
    try:
        assert select.select([station.stdout], [], [], 10)[0], "station did not start"
        assert "listening" in station.stdout.readline()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
            tx.sendto(FIXTURE.read_bytes(), ("127.0.0.1", params.PORT_TELEMETRY))
            tx.sendto(b"garbage", ("127.0.0.1", params.PORT_SIM_TRUTH))
        time.sleep(0.3)
        station.send_signal(sig)
        out, _ = station.communicate(timeout=10)
    finally:
        if station.poll() is None:
            station.kill()
            station.wait(timeout=5)
        server.shutdown()
    assert station.returncode == 0, out
    assert "stopped" in out
    written = "\n".join(FakeInflux.bodies)
    assert "housekeeping,source=fsw " in written
    assert "link,source=truth packet_rate_hz=" in written and "decode_errors=1i" in written
