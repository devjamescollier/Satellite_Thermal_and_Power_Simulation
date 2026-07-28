"""Send one telecommand to the flight software and wait for its ack or nack.

Usage:
  uv run python ground/cmd.py noop
  uv run python ground/cmd.py set-mode nominal|load_shed|safe
  uv run python ground/cmd.py payload-on
  uv run python ground/cmd.py payload-off
  uv run python ground/cmd.py set-heater ON_BELOW_K OFF_ABOVE_K
Options: --timeout S (default 5). Exit status: 0 ack, 1 nack, 2 no reply.

FSW executes commands at its next cycle, so the sim must be running for a reply.
"""

import argparse
import struct
import sys

import ccsds
from downlink import Link

# Every telecommand in docs/icd.md: CLI name -> (opcode name, argument builder).
COMMANDS = {
    "noop": ("NOOP", lambda a: b""),
    "set-mode": ("SET_MODE", lambda a: bytes([ccsds.MODES.index(a.mode.upper())])),
    "payload-on": ("PAYLOAD_ON", lambda a: b""),
    "payload-off": ("PAYLOAD_OFF", lambda a: b""),
    "set-heater": (
        "SET_HEATER_SETPOINTS",
        lambda a: struct.pack(">2f", a.on_below_K, a.off_above_K),
    ),
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=float, default=5.0, help="seconds to wait for the ack")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("noop", "payload-on", "payload-off"):
        sub.add_parser(name)
    mode = sub.add_parser("set-mode")
    mode.add_argument("mode", choices=[m.lower() for m in ccsds.MODES])
    heater = sub.add_parser("set-heater")
    heater.add_argument("on_below_K", type=float)
    heater.add_argument("off_above_K", type=float)
    return parser.parse_args()


def main():
    args = parse_args()
    opcode_name, build_args = COMMANDS[args.command]
    link = Link()
    seq = link.send(opcode_name, build_args(args))
    print(f"sent {opcode_name} (seq {seq})")
    reply = link.wait_for_reply(seq, args.timeout)
    link.close()
    if reply is None:
        print(f"no ack within {args.timeout:g} s (is the sim running?)")
        sys.exit(2)
    if reply["type"] == "CMD_NACK":
        print(f"NACK at MET {reply['met_s']:.0f} s: {reply['reason']}")
        sys.exit(1)
    print(f"ACK at MET {reply['met_s']:.0f} s")


if __name__ == "__main__":
    main()
