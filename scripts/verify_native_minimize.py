#!/usr/bin/env python3
"""Isolate macOS minimize/restore from resize and fullscreen transitions."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import queue
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    parser.add_argument("--focus-timeout", type=float, default=3.0)
    parser.add_argument("--minimize-timeout", type=float, default=8.0)
    parser.add_argument("--restore-timeout", type=float, default=5.0)
    args = parser.parse_args()

    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    responses = queue.Queue()
    with (artifacts / "native-minimize-probe.log").open("w") as log:
        process = subprocess.Popen(
            [str(args.binary), "run", "--agent-stdio"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
        )

        def read_responses():
            for line in process.stdout:
                try:
                    responses.put(json.loads(line))
                except json.JSONDecodeError as error:
                    responses.put(error)

        threading.Thread(target=read_responses, daemon=True).start()
        counter = 0

        def request(method, **params):
            nonlocal counter
            counter += 1
            process.stdin.write(
                json.dumps({"id": counter, "method": method, "params": params}) + "\n"
            )
            process.stdin.flush()
            response = responses.get(timeout=20)
            if isinstance(response, Exception):
                raise response
            assert response.get("id") == counter, response
            assert "result" in response, response
            return response["result"]

        def wait_for(key, expected, timeout):
            deadline = time.monotonic() + timeout
            state = request("get_window")
            while state.get(key) is not expected and time.monotonic() < deadline:
                time.sleep(0.1)
                state = request("get_window")
            return state

        try:
            initial = request("get_window")
            focused = wait_for("focused", True, args.focus_timeout)
            request("set_window", minimized=True)
            minimized = wait_for("minimized", True, args.minimize_timeout)
            request("set_window", minimized=False)
            restored = wait_for("minimized", False, args.restore_timeout)
            focus_after_restore = wait_for("focused", True, args.focus_timeout)
            request("shutdown")
            process.wait(timeout=20)

            result = {
                "binary": str(args.binary),
                "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                "host": platform.platform(),
                "focus_timeout_seconds": args.focus_timeout,
                "minimize_timeout_seconds": args.minimize_timeout,
                "restore_timeout_seconds": args.restore_timeout,
                "resize_or_fullscreen_used": False,
                "initial": initial,
                "focused_before_request": focused["focused"],
                "minimized_after_request": minimized,
                "restored_after_request": restored,
                "focused_after_restore": focus_after_restore["focused"],
                "shutdown": process.returncode == 0,
                "minimization_verified": focused["focused"] is True
                and minimized["minimized"] is True,
                "restore_verified": minimized["minimized"] is True
                and restored["minimized"] is False,
            }
            result["verified"] = (
                result["minimization_verified"]
                and result["restore_verified"]
                and result["shutdown"]
            )
            output = artifacts / "native-minimize-probe.json"
            output.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result))
            return 0 if result["verified"] else 1
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
