"""
Execution loop for the blind challenge agent.

The loop:
  1. Sends the challenge context + system prompt to the model
  2. The model responds with reasoning and tool calls
  3. Tools are dispatched and results appended to the conversation
  4. Repeat until: FINDING_CONFIRMED, NO_FINDING, or max_iterations reached
  5. Returns a completed Trajectory
"""

import json

from openai import OpenAI

import agent.config as config
from agent.prompts import SYSTEM_PROMPT, TOOL_DEFINITIONS, build_initial_message
from agent.tools import dispatch
from agent.trajectory import Trajectory, ToolCall


def run_loop(challenge: dict, max_iterations: int | None = None) -> Trajectory:
    """
    Run the agent loop for one challenge.

    Args:
        challenge: Loaded challenge.json dict.
        max_iterations: Override the default iteration budget.

    Returns:
        A completed Trajectory (not yet saved — caller saves it).
    """
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    model = config.DEFAULT_MODEL
    budget = max_iterations or challenge.get("max_iterations", config.MAX_ITERATIONS)

    trajectory = Trajectory(
        challenge_id=challenge["challenge_id"],
        challenge_name=challenge["name"],
        model=model,
    )

    # Build the initial conversation
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_initial_message(challenge)},
    ]

    print(f"\n{'='*60}")
    print(f"Challenge: {challenge['name']}")
    print(f"Model: {model}  |  Budget: {budget} iterations")
    print(f"{'='*60}\n")

    for iteration in range(1, budget + 1):
        print(f"--- Iteration {iteration}/{budget} ---")

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            temperature=config.TEMPERATURE,
        )

        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        reasoning_text = message.content or ""
        tool_calls_made: list[ToolCall] = []

        if reasoning_text:
            print(f"[Model] {reasoning_text[:500]}{'...' if len(reasoning_text) > 500 else ''}")

        # Check for terminal signal in the model's text
        verdict, done = _check_verdict(reasoning_text)

        # Append assistant message to conversation
        messages.append({"role": "assistant", "content": message.content, "tool_calls": _serialize_tool_calls(message.tool_calls)})

        # Process tool calls if any
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                print(f"  [Tool] {tool_name}({_summarize_args(args)})")
                result = dispatch(tool_name, args, challenge)
                print(f"  [Result] {result[:200]}{'...' if len(result) > 200 else ''}\n")

                tool_calls_made.append(ToolCall(
                    tool_name=tool_name,
                    arguments=args,
                    result=result,
                ))

                # Append tool result to conversation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        trajectory.add_step(
            iteration=iteration,
            model_reasoning=reasoning_text,
            tool_calls=tool_calls_made,
        )

        if done:
            trajectory.set_verdict(verdict, reasoning_text, iteration)
            print(f"\n[Loop] Agent signalled: {verdict}")
            return trajectory

        # If no tool calls and no verdict signal, the model is done thinking
        if finish_reason == "stop" and not message.tool_calls:
            trajectory.set_verdict("BUDGET_EXHAUSTED", reasoning_text, iteration)
            print(f"\n[Loop] Model stopped without verdict after iteration {iteration}.")
            return trajectory

    # Budget exhausted
    last_text = messages[-1].get("content", "") if messages else ""
    trajectory.set_verdict("BUDGET_EXHAUSTED", last_text, budget)
    print(f"\n[Loop] Budget of {budget} iterations exhausted.")
    return trajectory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_verdict(text: str) -> tuple[str, bool]:
    """Return (verdict, is_terminal) based on model text."""
    if not text:
        return "", False
    upper = text.upper()
    if "FINDING_CONFIRMED" in upper:
        return "FINDING_CONFIRMED", True
    if "NO_FINDING" in upper:
        return "NO_FINDING", True
    return "", False


def _serialize_tool_calls(tool_calls) -> list[dict] | None:
    """Convert OpenAI tool_call objects to plain dicts for message history."""
    if not tool_calls:
        return None
    return [
        {
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        }
        for tc in tool_calls
    ]


def _summarize_args(args: dict) -> str:
    """Short single-line summary of tool args for logging."""
    parts = []
    for k, v in args.items():
        sv = str(v)
        if len(sv) > 60:
            sv = sv[:57] + "..."
        parts.append(f"{k}={sv!r}")
    return ", ".join(parts)
