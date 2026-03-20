"""
Trajectory: the full record of one agent run.

A trajectory captures every step the agent took:
  - The model messages and reasoning
  - Every tool call and its result
  - The final verdict (FINDING_CONFIRMED or NO_FINDING)
  - Optional score (filled in after reveal)

Trajectories are the training data for future fine-tuning.
Each run produces one trajectory JSON in the trajectories/ directory.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import agent.config as config


@dataclass
class ToolCall:
    tool_name: str
    arguments: dict
    result: str


@dataclass
class Step:
    iteration: int
    model_reasoning: str          # The assistant message text before tool calls
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class Score:
    root_cause_hit: int = 0       # 0–3
    attack_path_accuracy: int = 0  # 0–3
    false_positives: int = 0       # 0 = none, 1 = minor, 2 = major (lower is better)
    poc_quality: int = 0           # 0–3 (did PoC actually run/pass?)
    total: int = 0
    notes: str = ""


@dataclass
class Trajectory:
    challenge_id: str
    challenge_name: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    model: str = ""
    steps: list[Step] = field(default_factory=list)
    final_verdict: str = ""       # "FINDING_CONFIRMED" | "NO_FINDING" | "BUDGET_EXHAUSTED"
    final_message: str = ""       # The agent's last message
    iterations_used: int = 0
    score: Optional[Score] = None

    # -----------------------------------------------------------------------

    def add_step(
        self,
        iteration: int,
        model_reasoning: str,
        tool_calls: list[ToolCall] | None = None,
    ) -> None:
        self.steps.append(
            Step(
                iteration=iteration,
                model_reasoning=model_reasoning,
                tool_calls=tool_calls or [],
            )
        )

    def set_verdict(self, verdict: str, final_message: str, iterations_used: int) -> None:
        self.final_verdict = verdict
        self.final_message = final_message
        self.iterations_used = iterations_used

    def set_score(self, score: Score) -> None:
        self.score = score

    # -----------------------------------------------------------------------

    def to_dict(self) -> dict:
        d = asdict(self)
        # Convert ToolCall dataclasses inside steps
        return d

    def save(self) -> Path:
        config.TRAJECTORIES_DIR.mkdir(parents=True, exist_ok=True)
        ts = self.timestamp.replace(":", "-").replace("+", "").replace(".", "-")
        filename = f"{self.challenge_id}_{ts}.json"
        path = config.TRAJECTORIES_DIR / filename
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "Trajectory":
        data = json.loads(path.read_text(encoding="utf-8"))
        steps = []
        for s in data.get("steps", []):
            tcs = [ToolCall(**tc) for tc in s.get("tool_calls", [])]
            steps.append(Step(
                iteration=s["iteration"],
                model_reasoning=s["model_reasoning"],
                tool_calls=tcs,
            ))
        score = None
        if data.get("score"):
            score = Score(**data["score"])
        return cls(
            challenge_id=data["challenge_id"],
            challenge_name=data["challenge_name"],
            timestamp=data["timestamp"],
            model=data.get("model", ""),
            steps=steps,
            final_verdict=data.get("final_verdict", ""),
            final_message=data.get("final_message", ""),
            iterations_used=data.get("iterations_used", 0),
            score=score,
        )
