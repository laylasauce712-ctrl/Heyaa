#!/usr/bin/env python3
"""Explicitly approve a verified Heyaa run/edit and copy it into output/releases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.heyaa.release import ReleaseApprovalError, approve_release


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Approve one technically verified Heyaa MP4. The video must live under "
            "output/runs/ and have a passing Agent Report, Inspector and EDL."
        )
    )
    parser.add_argument(
        "video",
        type=Path,
        help="Path to a run MP4 (for example output/runs/<run-id>/edits/edit_01/final_phonk_20s.mp4).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicitly confirm that you reviewed and approve this exact render for the local releases folder.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("output"),
        help="Local Heyaa output root (default: output).",
    )
    args = parser.parse_args(argv)
    try:
        result = approve_release(
            args.video,
            confirm=args.confirm,
            output_root=args.output_root,
        )
    except ReleaseApprovalError as exc:
        parser.exit(2, f"Approval refused: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
