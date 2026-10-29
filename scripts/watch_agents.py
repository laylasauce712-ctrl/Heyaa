#!/usr/bin/env python3
"""Human-readable viewer for Heyaa's evidence-linked agent and render event trace."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


IMPORTANT_DETAIL_STAGES = {
    "source_preparation", "source_selection_scope", "source_selection",
    "media_analysis", "beat_analysis", "reference_analysis", "clip_planning",
    "edl_validation", "render_critique", "director_decision", "export_storage",
}


def latest_run_dir(output_root: str | Path = "output") -> Path | None:
    """Return the newest timestamped run directory, if one exists."""
    root = Path(output_root) / "runs"
    if not root.is_dir():
        return None
    candidates = [item for item in root.iterdir() if item.is_dir()]
    return max(candidates, key=lambda item: item.name) if candidates else None


def _json_preview(value: Any, limit: int = 1400) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(rendered) > limit:
        return rendered[:limit] + "... [display truncated; full evidence is in the JSON report]"
    return rendered


def _timestamp(event: dict[str, Any]) -> str:
    value = str(event.get("timestamp", ""))
    if "T" in value:
        return value.split("T", 1)[1].removesuffix("Z")
    return value


def format_progress_event(event: dict[str, Any]) -> list[str]:
    """Format one JSONL progress event, including agent findings and evidence."""
    if not isinstance(event, dict):
        return ["[WARN] Ignored non-object progress event."]
    stage = str(event.get("stage", "unknown"))
    status = str(event.get("status", "unknown"))
    summary = str(event.get("summary", ""))
    details = event.get("details") if isinstance(event.get("details"), dict) else {}
    timestamp = _timestamp(event)
    lines = [f"{timestamp} [{stage}] {status}: {summary}".strip()]

    if stage == "pre_render_agent_review":
        speaker = details.get("speaker", "Agent")
        target = details.get("to", "Planner")
        lines.append(f"  REVIEW: {speaker} -> {target}")
        evidence = details.get("evidence")
        if evidence:
            lines.append(f"  Evidence: {_json_preview(evidence, 900)}")
        return lines

    if stage.startswith("agent:"):
        agent_event = details.get("agent_event")
        if not isinstance(agent_event, dict):
            return lines
        data = agent_event.get("data") if isinstance(agent_event.get("data"), dict) else {}
        for finding in data.get("findings", [])[:6]:
            lines.append(f"  Finding: {finding}")
        for recommendation in data.get("recommendations", [])[:5]:
            lines.append(f"  Recommendation: {recommendation}")
        evidence = data.get("evidence")
        if evidence:
            lines.append(f"  Evidence: {_json_preview(evidence, 1600)}")
        confidence = data.get("confidence")
        score = data.get("score")
        if confidence is not None or score is not None:
            lines.append(f"  Score={score}; confidence={confidence}")
        return lines

    if stage in IMPORTANT_DETAIL_STAGES and details:
        lines.append(f"  Details: {_json_preview(details, 1200)}")
    return lines


def format_agent_report(report: dict[str, Any]) -> list[str]:
    """Render the final structured report without inventing missing agent thoughts."""
    lines = [
        "=== HEYAA AGENT REPORT ===",
        f"Decision: {report.get('status', 'unknown')}",
        f"Summary: {report.get('summary', 'No summary recorded.')}",
        f"Human review required: {report.get('human_review_required', 'unknown')}",
    ]
    results = report.get("results", {})
    if isinstance(results, dict):
        for name, result in results.items():
            if not isinstance(result, dict):
                continue
            lines.append("")
            lines.append(f"[{name}] status={result.get('status', 'unknown')}")
            if result.get("score") is not None or result.get("confidence") is not None:
                lines.append(f"  score={result.get('score')}; confidence={result.get('confidence')}")
            for finding in result.get("findings", [])[:8]:
                lines.append(f"  Finding: {finding}")
            for recommendation in result.get("recommendations", [])[:6]:
                lines.append(f"  Recommendation: {recommendation}")
            evidence = result.get("evidence")
            if evidence:
                lines.append(f"  Evidence: {_json_preview(evidence, 1800)}")

    preflight = report.get("pre_render_review", [])
    if isinstance(preflight, list) and preflight:
        lines.extend(["", "=== PRE-RENDER REVIEW ==="])
        for turn in preflight:
            if isinstance(turn, dict):
                lines.append(
                    f"[{turn.get('speaker', 'Agent')} -> {turn.get('to', 'Planner')}] "
                    f"{turn.get('message', '')}"
                )

    dialogue = report.get("agent_dialogue", [])
    if isinstance(dialogue, list) and dialogue:
        lines.extend(["", "=== POST-RENDER EVIDENCE CONFERENCE ==="])
        for turn in dialogue:
            if isinstance(turn, dict):
                lines.append(
                    f"[{turn.get('speaker', 'Agent')} -> {turn.get('to', 'Director')}] "
                    f"{turn.get('message', '')}"
                )
                evidence = turn.get("evidence")
                if evidence:
                    lines.append(f"  Evidence: {_json_preview(evidence, 1000)}")
    lines.append("")
    lines.append("Note: these are rule-based, evidence-linked rationales, not private LLM chain-of-thought.")
    return lines


def _read_report(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "agent_report.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def show_report(run_dir: Path) -> int:
    report = _read_report(run_dir)
    if report is None:
        print(f"No complete agent_report.json found in {run_dir}", file=sys.stderr)
        progress = run_dir / "progress.jsonl"
        if progress.is_file():
            print(f"Live/progress trace is available at {progress}", file=sys.stderr)
        return 1
    print(f"Run directory: {run_dir}")
    for line in format_agent_report(report):
        print(line)
    return 0


def watch_progress(run_dir: Path, poll_seconds: float = 0.35) -> int:
    """Tail progress.jsonl until interrupted; tolerate missing file and log rotation."""
    path = run_dir / "progress.jsonl"
    print(f"Watching Heyaa activity: {path}")
    print("Press Ctrl+C to stop. Completed agent events include findings, recommendations and evidence.")
    offset = 0
    file_identity: tuple[int, int] | None = None
    warned_missing = False
    try:
        while True:
            if not path.is_file():
                if not warned_missing:
                    print("Waiting for progress.jsonl to be created...", flush=True)
                    warned_missing = True
                time.sleep(max(0.1, poll_seconds))
                continue
            try:
                stat = path.stat()
                identity = (stat.st_dev, stat.st_ino)
                if file_identity != identity or stat.st_size < offset:
                    offset = 0
                    file_identity = identity
                with path.open("r", encoding="utf-8") as handle:
                    handle.seek(offset)
                    while True:
                        raw = handle.readline()
                        if not raw:
                            break
                        offset = handle.tell()
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            print("[WARN] Skipped an incomplete progress line.", flush=True)
                            continue
                        for line in format_progress_event(event):
                            print(line, flush=True)
            except OSError as exc:
                print(f"[WARN] Could not read {path}: {exc}", flush=True)
            time.sleep(max(0.1, poll_seconds))
    except KeyboardInterrupt:
        print("\nStopped watching agent activity.")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Watch or inspect Heyaa's evidence-linked agent activity."
    )
    parser.add_argument(
        "--run-dir", type=Path, default=None,
        help="Run directory, e.g. output/runs/20261029-141004-964652; defaults to the newest run.",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Print the final agent report and exit instead of following progress.jsonl.",
    )
    parser.add_argument(
        "--poll-seconds", type=float, default=0.35,
        help="Polling interval for live mode (default: 0.35 seconds).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.poll_seconds <= 0:
        print("--poll-seconds must be positive.", file=sys.stderr)
        return 2

    run_dir = args.run_dir
    if run_dir is None:
        if args.once and Path("output/latest").is_dir():
            run_dir = Path("output/latest")
        else:
            run_dir = latest_run_dir()
    if run_dir is None or not run_dir.is_dir():
        print("No render run directory found. Start a render or pass --run-dir PATH.", file=sys.stderr)
        return 2
    return show_report(run_dir) if args.once else watch_progress(run_dir, args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
