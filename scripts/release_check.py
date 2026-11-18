"""Run preflight, practice and offline smoke checks in separate service processes."""

import argparse
import json
import tempfile
from pathlib import Path

from verify import MODES, add_arguments, process_exit, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    args = parser.parse_args()
    reports = args.out.resolve() / "release"
    reports.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=reports))

    checks = {}
    exit_code = 0
    for mode in MODES:
        code, directory = verify(mode, args)
        checks[mode] = {"exit_code": code, "summary": str(directory / "summary.json")}
        if not exit_code:
            exit_code = code
    summary = run / "summary.json"
    summary.write_text(json.dumps({"exit_code": exit_code, "checks": checks}, indent=2) + "\n", encoding="utf-8")
    print(f"Release check exit {exit_code}. Summary in {summary}")
    return process_exit(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
