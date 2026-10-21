"""Run tool subprocesses in parallel with a timeout, recording each job's wall time,
CPU time and peak memory, and write those to InfluxDB (measurement "compute",
shown on the Compute Usage dashboard). Used by monte_carlo.py and fault_campaign.py.
"""

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "ground"))  # appended: ground/cmd.py must not shadow stdlib cmd
import points  # noqa: E402
from influx import InfluxWriter  # noqa: E402

POLL_S = 0.02
RSS_UNIT = 1 if sys.platform == "darwin" else 1024  # ru_maxrss: bytes on macOS, KiB on Linux


@dataclass
class JobStats:
    job: str
    wall_s: float
    cpu_s: float  # user + system time of the child
    peak_rss_MB: float
    returncode: int
    end_ns: int


def run_job(job, cmd, timeout_s):
    """Run cmd to completion (killed after timeout_s) and return its JobStats."""
    start = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL)
    while True:
        pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
        if pid:
            break
        if time.monotonic() - start > timeout_s:
            proc.kill()
            _, status, usage = os.wait4(proc.pid, 0)
            break
        time.sleep(POLL_S)
    proc.returncode = os.waitstatus_to_exitcode(status)  # reaped here, not by Popen
    return JobStats(job, time.monotonic() - start, usage.ru_utime + usage.ru_stime,
                    usage.ru_maxrss * RSS_UNIT / 2**20, proc.returncode, time.time_ns())


def run_all(jobs, timeout_s):
    """jobs: {name: cmd}. Runs in parallel; returns JobStats in the same order."""
    with ThreadPoolExecutor() as pool:
        futures = [pool.submit(run_job, name, cmd, timeout_s) for name, cmd in jobs.items()]
        return [f.result() for f in futures]


def stats_fields(s):
    """InfluxDB fields for one job (tags: runner, job)."""
    return {"wall_s": s.wall_s, "cpu_s": s.cpu_s, "peak_rss_MB": s.peak_rss_MB,
            "returncode": s.returncode}


def record(runner, stats, write=True):
    """Print a summary, write the stats to InfluxDB, and fail if any job failed."""
    total_cpu = sum(s.cpu_s for s in stats)
    print(f"{runner}: {len(stats)} jobs, {total_cpu:.1f} s CPU, "
          f"longest {max(s.wall_s for s in stats):.2f} s, "
          f"peak {max(s.peak_rss_MB for s in stats):.1f} MB")
    if write:
        writer = InfluxWriter()
        for i, s in enumerate(stats):
            # +i keeps timestamps unique: InfluxDB overwrites points with equal times
            tags = {"runner": runner, "job": s.job}
            writer.add([points.line("compute", tags, stats_fields(s), s.end_ns + i)])
        if writer.flush():
            print(f"{runner}: compute usage written to InfluxDB")
    failed = [s.job for s in stats if s.returncode != 0]
    if failed:
        sys.exit(f"{runner}: jobs failed or timed out: {', '.join(failed)}")
