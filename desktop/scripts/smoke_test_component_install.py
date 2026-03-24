#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the desktop component installer against a local manifest.")
    parser.add_argument("--component-id", default="local-transcription")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()

    from services.components import activate_component_runtime, get_install_task, install_component, list_components

    catalog = list_components()
    task = install_component(args.component_id)
    deadline = time.time() + args.timeout_seconds
    snapshot = task

    while snapshot["status"] in {"pending", "running"}:
        if time.time() >= deadline:
            raise SystemExit(
                json.dumps(
                    {
                        "catalog": catalog,
                        "task": snapshot,
                        "activated": False,
                        "error": f"Timed out waiting for {args.component_id} install task",
                    },
                    indent=2,
                )
            )
        time.sleep(0.25)
        snapshot = get_install_task(task["id"])

    activated = activate_component_runtime(args.component_id)
    result = {
        "catalog": catalog,
        "task": snapshot,
        "activated": activated,
    }
    print(json.dumps(result, indent=2))
    return 0 if snapshot["status"] == "completed" and activated else 1


if __name__ == "__main__":
    raise SystemExit(main())
