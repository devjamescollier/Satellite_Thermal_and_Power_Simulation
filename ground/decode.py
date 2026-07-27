"""Listen for FSW telemetry (6001) and sim truth (6003) and print decoded packets.

Usage: uv run python ground/decode.py [--every N]
Events are always printed; housekeeping, estimator and truth only every Nth packet.
If the ground station is running it owns those ports, so this listens on its relay port.
"""

import argparse
import selectors

import ccsds
import params
from downlink import bind_downlink


def format_packet(p):
    head = f"MET {p['met_s']:9.1f}  APID 0x{p['apid']:02X} #{p['seq_count']:<5}"
    body = {k: v for k, v in p.items() if k not in ("apid", "is_command", "seq_count", "met_s")}
    if "thermistor_K" in body:
        body["thermistor_K"] = {k: round(v, 1) for k, v in body["thermistor_K"].items()}
    if "temp_K" in body:
        body["temp_K"] = {k: round(v, 2) for k, v in body["temp_K"].items()}
    if "sigma" in body:
        body["sigma"] = {k: float(f"{v:.2g}") for k, v in body["sigma"].items()}
    fields = "  ".join(f"{k}={round(v, 3) if isinstance(v, float) else v}" for k, v in body.items())
    return f"{head}  {fields}"


def listen(every):
    sel = selectors.DefaultSelector()
    socks, relayed = bind_downlink((params.PORT_TELEMETRY, params.PORT_SIM_TRUTH))
    for sock in socks:
        sel.register(sock, selectors.EVENT_READ)
    ports = [s.getsockname()[1] for s in socks]
    print(f"listening on {ports}" + (" (ground station relay)" if relayed else ""))

    counts = {}
    while True:
        for key, _ in sel.select():
            try:
                packet = ccsds.decode_packet(key.fileobj.recv(4096))
            except ccsds.DECODE_ERRORS as err:
                print(f"bad packet: {err}")
                continue
            n = counts[packet["apid"]] = counts.get(packet["apid"], 0) + 1
            if packet["apid"] == ccsds.APID_EVENTS or (n - 1) % every == 0:
                print(format_packet(packet), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--every", type=int, default=1, help="print every Nth periodic packet")
    try:
        listen(max(parser.parse_args().every, 1))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
