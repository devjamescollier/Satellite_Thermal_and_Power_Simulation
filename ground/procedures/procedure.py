"""Shared helper for operations procedures: send a command and wait for its ack, wait for a
telemetry condition, record every step, and write a pass/fail report to docs/reports/.

Every wait has a timeout. Condition timeouts are in mission time (MET), so a procedure
means the same at any sim speed; a wall-clock cap of the same length plus 30 s stops it
if telemetry stops. The first failed step ends the procedure.
"""

import sys
import time
from datetime import UTC, datetime
from pathlib import Path

GROUND = Path(__file__).resolve().parent.parent
sys.path.append(str(GROUND))  # appended: ground/cmd.py must not shadow stdlib cmd
import ccsds  # noqa: E402
from downlink import Link  # noqa: E402

REPORTS = GROUND.parent / "docs" / "reports"
ACK_TIMEOUT_S = 10.0  # wall clock: FSW answers at its next cycle


class StepFailed(Exception):
    pass


class Procedure:
    def __init__(self, name, title):
        self.name, self.title = name, title
        self.link = Link()
        self.hk = None  # latest housekeeping packet
        self.steps = []  # (step, passed, met_s, detail)

    def _track(self, packet):
        if packet["apid"] == ccsds.APID_HOUSEKEEPING:
            self.hk = packet

    def _record(self, step, passed, detail):
        met = self.hk["met_s"] if self.hk else float("nan")
        self.steps.append((step, passed, met, detail))
        print(f"{'PASS' if passed else 'FAIL'}  {step}: {detail}")
        if not passed:
            raise StepFailed(step)

    def check(self, step, passed, detail):
        self._record(step, passed, detail)

    def send(self, step, opcode_name, args=b"", expect="CMD_ACK", reason=None):
        """Send a command; pass if the reply is `expect` (and the NACK `reason`, if given)."""
        seq = self.link.send(opcode_name, args)
        reply = self.link.wait_for_reply(seq, ACK_TIMEOUT_S, self._track)
        if reply is None:
            self._record(step, False, f"{opcode_name}: no reply within {ACK_TIMEOUT_S:g} s")
        got = reply["type"] + (f" {reply['reason']}" if reply["type"] == "CMD_NACK" else "")
        ok = reply["type"] == expect and (reason is None or reply["reason"] == reason)
        self._record(step, ok, f"{opcode_name} -> {got}")

    def wait_for(self, step, condition, met_timeout_s, describe, fail_if=None):
        """Wait until condition(housekeeping) holds; fail on timeout or if fail_if holds."""
        wall_deadline = time.monotonic() + met_timeout_s + 30.0
        start_met = None
        while time.monotonic() < wall_deadline:
            packet = self.link.receive(wall_deadline - time.monotonic())
            if packet is None:
                break
            self._track(packet)
            if packet["apid"] != ccsds.APID_HOUSEKEEPING:
                continue
            start_met = packet["met_s"] if start_met is None else start_met
            if fail_if and fail_if(packet):
                self._record(step, False, f"aborted: {describe(packet)}")
            if condition(packet):
                elapsed = packet["met_s"] - start_met
                after = f" after {elapsed:.0f} s MET" if elapsed >= 1 else ""
                self._record(step, True, describe(packet) + after)
                return packet
            if packet["met_s"] - start_met > met_timeout_s:
                break
        last = describe(self.hk) if self.hk else "no telemetry"
        self._record(step, False, f"timed out after {met_timeout_s:g} s MET; {last}")

    def run(self, body):
        """Run body(self), write the report, and exit 0 on pass, 1 on fail."""
        try:
            body(self)
            passed = True
        except StepFailed:
            passed = False
        finally:
            self.link.close()
        self.write_report(passed)
        print(f"{self.title}: {'PASS' if passed else 'FAIL'} (report {self.report_path()})")
        sys.exit(0 if passed else 1)

    def report_path(self):
        return REPORTS / f"{self.name}.md"

    def write_report(self, passed):
        rows = "\n".join(f"| {i} | {step} | {'PASS' if ok else '**FAIL**'} | {met:.0f} | {detail} |"
                         for i, (step, ok, met, detail) in enumerate(self.steps, start=1))
        REPORTS.mkdir(parents=True, exist_ok=True)
        self.report_path().write_text(f"""# {self.title}: {'PASS' if passed else 'FAIL'}

Written by `ground/procedures/{self.name}.py` on {datetime.now(UTC):%Y-%m-%d %H:%M} UTC.
The procedure stops at the first failed step.

| # | Step | Result | MET (s) | Detail |
|---|---|---|---|---|
{rows}
""")


def temps(hk):
    return ", ".join(f"{n} {t:.1f} K" for n, t in hk["thermistor_K"].items())

