"""Ground station: FSW telemetry (6001) and sim truth (6003) -> InfluxDB.

Decodes every packet, batch-writes it as line protocol (tag source=fsw|truth),
re-sends it to the relay port for other ground tools, and once a second writes
link health per source: packet rate, sequence-count gaps, decode errors.

Usage: uv run python ground/station.py
InfluxDB settings come from the environment (INFLUX_URL, INFLUX_ORG,
INFLUX_BUCKET, INFLUX_TOKEN), falling back to the repo's .env file.
"""

import selectors
import signal
import socket
import time

import ccsds
import params
import points
from influx import InfluxWriter

FLUSH_INTERVAL_S = 1.0
DRAIN_S = 2.0  # on stop, keep reading queued packets for at most this long
SOURCES = {params.PORT_TELEMETRY: "fsw", params.PORT_SIM_TRUTH: "truth"}


class LinkHealth:
    """Per-source packet counts, sequence gaps (per APID) and decode errors."""

    def __init__(self):
        self.window_packets = dict.fromkeys(SOURCES.values(), 0)
        self.gaps = dict.fromkeys(SOURCES.values(), 0)
        self.errors = dict.fromkeys(SOURCES.values(), 0)
        self.last_seq = {}  # (source, apid) -> seq count
        self.window_start = time.monotonic()

    def packet(self, source, apid, seq):
        self.window_packets[source] += 1
        last = self.last_seq.get((source, apid))
        if last is not None:
            self.gaps[source] += (seq - last - 1) & 0x3FFF
        self.last_seq[(source, apid)] = seq

    def lines(self, time_ns):
        now = time.monotonic()
        elapsed = max(now - self.window_start, 1e-6)
        out = [
            points.link_line(src, n / elapsed, self.gaps[src], self.errors[src], time_ns)
            for src, n in self.window_packets.items()
        ]
        self.window_packets = dict.fromkeys(self.window_packets, 0)
        self.window_start = now
        return out


def _stop(signum, frame):
    raise KeyboardInterrupt  # SIGINT and SIGTERM both take the flush-and-exit path


def receive(sock, source, relay, writer, health, last_ns):
    """Relay, decode and buffer one datagram. Returns the (unique) timestamp used:
    the clock ticks only every 1 us, and InfluxDB overwrites points with equal times."""
    data = sock.recv(4096)
    relay.sendto(data, ("127.0.0.1", params.PORT_GROUND_RELAY))
    try:
        packet = ccsds.decode_packet(data)
    except ccsds.DECODE_ERRORS:
        health.errors[source] += 1
        return last_ns
    health.packet(source, packet["apid"], packet["seq_count"])
    last_ns = max(time.time_ns(), last_ns + 1)
    writer.add(points.packet_to_lines(packet, last_ns))
    return last_ns


def main():
    for sig in (signal.SIGINT, signal.SIGTERM):  # scripts stop background jobs with SIGTERM
        signal.signal(sig, _stop)
    writer, health = InfluxWriter(), LinkHealth()
    relay = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sel = selectors.DefaultSelector()
    for port, source in SOURCES.items():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        sock.bind(("127.0.0.1", port))
        sel.register(sock, selectors.EVENT_READ, source)
    print(f"station: listening on {list(SOURCES)}, writing to {writer.url.split('?')[0]}")

    next_flush, last_ns = time.monotonic() + FLUSH_INTERVAL_S, 0
    try:
        while True:
            for key, _ in sel.select(timeout=0.2):
                last_ns = receive(key.fileobj, key.data, relay, writer, health, last_ns)
            if time.monotonic() >= next_flush:
                writer.add(health.lines(time.time_ns()))
                writer.flush()
                next_flush = time.monotonic() + FLUSH_INTERVAL_S
    except KeyboardInterrupt:
        for sig in (signal.SIGINT, signal.SIGTERM):  # a second signal must not cut the flush
            signal.signal(sig, signal.SIG_IGN)
        drain_until = time.monotonic() + DRAIN_S  # packets already queued in the sockets
        while time.monotonic() < drain_until and (ready := sel.select(timeout=0.1)):
            for key, _ in ready:
                last_ns = receive(key.fileobj, key.data, relay, writer, health, last_ns)
        writer.add(health.lines(time.time_ns()))
        writer.flush()
        print(f"station: stopped. seq gaps {health.gaps}, decode errors {health.errors}")


if __name__ == "__main__":
    main()
