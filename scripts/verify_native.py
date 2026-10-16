#!/usr/bin/env python3
"""Exercise the real native window and automation at frame boundaries."""
import argparse
import json
from pathlib import Path
import queue
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=ROOT / "target/debug/engine-lab")
    args = parser.parse_args()
    (ROOT / "artifacts").mkdir(exist_ok=True)
    with (ROOT / "artifacts/native-check.log").open("w") as log:
        process = subprocess.Popen([str(args.binary), "run", "--agent-stdio"], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
        responses = queue.Queue()

        def read_responses():
            for line in process.stdout:
                responses.put(json.loads(line))

        threading.Thread(target=read_responses, daemon=True).start()
        counter = 0

        def request(method, **params):
            nonlocal counter
            counter += 1
            process.stdin.write(json.dumps({"id": counter, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            result = responses.get(timeout=20)
            assert result["id"] == counter, result
            assert "result" in result, result
            return result["result"]

        try:
            initial = request("get_window")
            time.sleep(2.0)
            request("set_window", size=[900, 600])
            time.sleep(0.3)
            resized = request("get_window")
            assert resized["physical_size"] != initial["physical_size"], resized
            request("set_window", minimized=True)
            time.sleep(1.0)
            minimized = request("get_window")
            minimization_verified = minimized["minimized"] is True
            request("set_window", minimized=False)
            request("set_window", fullscreen=True)
            time.sleep(0.5)
            assert request("get_window")["fullscreen"] is True
            request("set_window", fullscreen=False)
            request("step", ticks=120)
            capture = request("capture_frame", path=str(ROOT / "artifacts/native-acceptance.png"), scale=1)
            assert capture["tick"] == 120
            assert (ROOT / "artifacts/native-acceptance.png").is_file()
            request("shutdown")
            process.wait(timeout=20)
            assert process.returncode == 0
            result = {"native_verified": minimization_verified, "resize_fullscreen_capture_verified": True, "minimization_verified": minimization_verified, "initial": initial, "resized": resized, "minimized": minimized, "capture": capture}
            (ROOT / "artifacts/native-verification.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result))
            assert minimization_verified, "OS did not confirm minimization; other native checks passed (see artifacts/native-verification.json)"
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
