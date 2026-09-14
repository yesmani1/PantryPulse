"""Build a deployable PantryPulse Lambda zip from the pinned requirements."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="dist/pantrypulse-uat.zip")
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        raise SystemExit(
            "Build this Lambda artifact from Linux (AWS CloudShell or Docker). "
            "Building on Windows produces incompatible native dependencies."
        )
    output = (ROOT / args.output).resolve()
    staging = output.with_suffix("")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    # The editable project entry is copied from ``src`` below, so dependencies
    # are the only requirements installed into the Lambda artifact.
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    deploy_requirements = [line for line in requirements if line.strip() and not line.lstrip().startswith("-e ")]
    requirements_path = staging / "lambda-requirements.txt"
    requirements_path.write_text("\n".join(deploy_requirements) + "\n", encoding="utf-8")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-compile",
                "--target",
                str(staging),
                "-r",
                str(requirements_path),
            ],
            check=True,
        )
    finally:
        requirements_path.unlink(missing_ok=True)
    shutil.copytree(ROOT / "src" / "pantrypulse", staging / "pantrypulse")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.make_archive(str(output.with_suffix("")), "zip", staging)
    shutil.rmtree(staging)
    print(f"Created {output}")


if __name__ == "__main__":
    main()
