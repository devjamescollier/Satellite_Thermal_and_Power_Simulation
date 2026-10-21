"""The ground end of the link: telecommands out on 6002, telemetry in on 6001.

The ground station owns 6001 (telemetry) and 6003 (sim truth) and re-sends every packet
it receives to the relay port, so other tools (decode.py, cmd.py, procedures) still see
the downlink while it runs: they bind the relay port instead.
"""

import socket
import time

import ccsds
import params


def _bind(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        sock.close()
        raise
    return sock


def bind_downlink(ports):
    """Sockets on the given downlink ports, or on the relay port if the station holds them."""
    try:
        socks = []
        for port in ports:
            socks.append(_bind(port))
        return socks, False
    except OSError:
        for s in socks:
            s.close()
        return [_bind(params.PORT_GROUND_RELAY)], True


class Link:
    """Sends telecommands and reads decoded FSW telemetry."""

    def __init__(self):
        (self.rx,), _ = bind_downlink((params.PORT_TELEMETRY,))  # bind before sending
        self.tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = int(time.time() * 1000) & 0x3FFF  # distinct across runs, to match acks

    def send(self, opcode_name, args=b""):
        """Sends one telecommand; returns its sequence count."""
        self.seq = (self.seq + 1) & 0x3FFF
        packet = ccsds.encode_command(ccsds.OPCODES[opcode_name], args, self.seq)
        self.tx.sendto(packet, ("127.0.0.1", params.PORT_TELECOMMANDS))
        return self.seq

    def receive(self, timeout_s):
        """The next decodable packet, or None if none arrives in timeout_s."""
        deadline = time.monotonic() + timeout_s
        while (left := deadline - time.monotonic()) > 0:
            self.rx.settimeout(left)
            try:
                return ccsds.decode_packet(self.rx.recv(4096))
            except TimeoutError:
                return None
            except ccsds.DECODE_ERRORS:
                continue
        return None

    def wait_for_reply(self, seq, timeout_s, on_packet=None):
        """The CMD_ACK / CMD_NACK event for command seq, or None on timeout. on_packet
        sees every packet received meanwhile."""
        deadline = time.monotonic() + timeout_s
        while (packet := self.receive(deadline - time.monotonic())) is not None:
            if on_packet:
                on_packet(packet)
            if packet.get("type") in ("CMD_ACK", "CMD_NACK") and packet["cmd_seq"] == seq:
                return packet
        return None

    def close(self):
        self.rx.close()
        self.tx.close()
