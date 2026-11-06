#!/usr/bin/env python3
"""Operator-only fixed runtime image builds. No submitted code; no automatic API builds."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("families", nargs="+", choices=("native", "java", "node"))
    parser.add_argument("--proxy-ca", type=Path, help="Optional trusted CA bundle, mounted only during image build")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for family in dict.fromkeys(args.families):
        tag = "agentshield-runtime-" + family + ":1"
        command = ["docker", "build", "--target", family, "--tag", tag]
        if args.proxy_ca:
            command += ["--secret", "id=proxy_ca,src=" + str(args.proxy_ca.resolve(strict=True))]
        command.append(str(root / "sandbox/runtime"))
        subprocess.run(command, check=True)
        # Only read immutable image ID/recipe labels; never container environment.
        output = subprocess.check_output(["docker", "image", "inspect", "--format", '{{json .Id}}', tag], text=True)
        image_id = json.loads(output)
        print("\nAdd to the ignored native backend/.env after review:")
        print("SANDBOX_" + family.upper() + "_IMAGE=" + image_id)


if __name__ == "__main__":
    main()
