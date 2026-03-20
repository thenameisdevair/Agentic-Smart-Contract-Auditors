"""
CLI entrypoint for the blind execution agent.

Usage:
  python -m agent.main --challenge bybit_blind_001
  python -m agent.main --challenge bybit_blind_001 --reveal
  python -m agent.main --challenge bybit_blind_001 --max-iters 12
"""

import argparse
import json
import sys
from pathlib import Path

import agent.config as config
from agent.loop import run_loop
from agent.trajectory import Score


def load_challenge(challenge_id: str) -> dict:
    path = config.CHALLENGES_DIR / challenge_id / "challenge.json"
    if not path.exists():
        print(f"ERROR: Challenge not found: {path}", file=sys.stderr)
        sys.exit(1)
    challenge = json.loads(path.read_text(encoding="utf-8"))

    # Resolve workspace to absolute path
    ws = challenge.get("workspace", f"challenges/{challenge_id}/workspace/")
    if not Path(ws).is_absolute():
        challenge["workspace"] = str(config.REPO_ROOT / ws)

    return challenge


def reveal_and_score(trajectory, challenge: dict) -> None:
    """Print a structured comparison of agent findings vs real exploit."""
    print("\n" + "=" * 60)
    print("REVEAL PHASE")
    print("=" * 60)

    reveal_files = challenge.get("reveal_files", [])
    reveal_text = ""
    for rf in reveal_files:
        p = config.REPO_ROOT / rf
        if p.exists():
            reveal_text += p.read_text(encoding="utf-8") + "\n\n"
        else:
            print(f"  [warn] Reveal file not found: {p}")

    if reveal_text:
        print("\n--- REAL EXPLOIT NOTES ---\n")
        print(reveal_text[:3000])
    else:
        print("  No reveal files found.")

    print("\n--- AGENT FINAL OUTPUT ---\n")
    print(trajectory.final_message[:3000] if trajectory.final_message else "(no final message)")

    print("\n--- SCORING ---")
    print("Score each criterion 0–3 (or press Enter to skip):")
    criteria = {
        "root_cause_hit": "Did the agent identify the correct root cause?       (0=miss, 1=partial, 2=close, 3=exact)",
        "attack_path_accuracy": "Was the attack path correct?                        (0=wrong, 1=partial, 2=mostly, 3=exact)",
        "false_positives": "False positives (lower is better)?                 (0=none, 1=minor, 2=major)",
        "poc_quality": "PoC quality — did a Foundry test pass or come close? (0=none, 1=attempted, 2=close, 3=passed)",
    }

    scores = {}
    for key, label in criteria.items():
        try:
            val = input(f"  {label}\n  Score: ").strip()
            scores[key] = int(val) if val else 0
        except (ValueError, EOFError):
            scores[key] = 0

    notes = ""
    try:
        notes = input("\n  Notes (optional): ").strip()
    except EOFError:
        pass

    total = scores.get("root_cause_hit", 0) + scores.get("attack_path_accuracy", 0) + scores.get("poc_quality", 0)
    # Subtract penalty for false positives
    total = max(0, total - scores.get("false_positives", 0))

    score = Score(
        root_cause_hit=scores.get("root_cause_hit", 0),
        attack_path_accuracy=scores.get("attack_path_accuracy", 0),
        false_positives=scores.get("false_positives", 0),
        poc_quality=scores.get("poc_quality", 0),
        total=total,
        notes=notes,
    )
    trajectory.set_score(score)

    print(f"\n  Total score: {total}/9")
    verdict_label = {
        "FINDING_CONFIRMED": "CONFIRMED by execution",
        "NO_FINDING": "no finding",
        "BUDGET_EXHAUSTED": "budget exhausted without verdict",
    }.get(trajectory.final_verdict, trajectory.final_verdict)
    print(f"  Agent verdict: {verdict_label}")
    print(f"  Iterations used: {trajectory.iterations_used}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a blind smart contract security challenge."
    )
    parser.add_argument(
        "--challenge", required=True,
        help="Challenge ID (folder name under challenges/)",
    )
    parser.add_argument(
        "--max-iters", type=int, default=None,
        help="Override iteration budget (default from challenge.json or config)",
    )
    parser.add_argument(
        "--reveal", action="store_true",
        help="After the run, reveal the real exploit and score the agent output",
    )
    args = parser.parse_args()

    config.validate()
    challenge = load_challenge(args.challenge)

    print(f"\nStarting blind challenge: {challenge['name']}")
    print(f"Workspace: {challenge['workspace']}")
    print(f"Foundry root: {config.FOUNDRY_ROOT}")

    trajectory = run_loop(challenge, max_iterations=args.max_iters)

    # Save trajectory
    saved_path = trajectory.save()
    print(f"\nTrajectory saved: {saved_path}")

    if args.reveal:
        reveal_and_score(trajectory, challenge)
        # Re-save with score
        saved_path = trajectory.save()
        print(f"Scored trajectory saved: {saved_path}")

    print(f"\nFinal verdict: {trajectory.final_verdict}")
    print(f"Iterations used: {trajectory.iterations_used}")


if __name__ == "__main__":
    main()
