# Agentic Smart Contract Auditors

An autonomous smart contract security agent that finds and **verifies** exploits by writing and executing Foundry tests — not just generating text descriptions.

## How it works

The agent operates in a loop with a budget of tool calls:

```
read contracts → form hypothesis → write Foundry test → run on fork → observe result → revise → repeat
```

A finding is only valid if a Foundry test confirms it. This grounds the agent's reasoning in execution reality rather than pattern matching.

Every run saves a **trajectory** — the full sequence of reasoning, tool calls, and results — as training data for future fine-tuning.

## Blind challenge system

The agent is given contracts **without** the known exploit, then scored against the real attack after the run. This tests genuine reasoning, not recall.

Each challenge has:
- `visible/` — contracts the agent may read
- `workspace/` — where the agent writes its Foundry tests
- `hidden/` — the real exploit notes (used for scoring only, never shown to the agent)

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Fill in OPENAI_API_KEY, MAINNET_RPC_URL, and FOUNDRY_ROOT
```

`FOUNDRY_ROOT` should point to a local Foundry project (e.g. your DeFiHackLabs clone) where `forge` can run tests against a mainnet fork.

## Running a challenge

```bash
# Blind analysis + execution
python -m agent.main --challenge bybit_blind_001

# With reveal and interactive scoring
python -m agent.main --challenge bybit_blind_001 --reveal

# Override iteration budget
python -m agent.main --challenge bybit_blind_001 --max-iters 12
```

## Project structure

```
agent/
  main.py         # CLI entrypoint
  loop.py         # Execution loop (tool-calling agent)
  prompts.py      # System prompt + tool definitions
  tools.py        # read_file, write_file, list_files, run_forge_test
  trajectory.py   # Save/load trajectory data (training data)
  config.py       # Env + path config

challenges/
  bybit_blind_001/
    challenge.json          # metadata
    visible/                # contracts shown to agent
    workspace/              # agent writes tests here
    hidden/                 # real exploit notes (scoring only)

trajectories/     # saved run trajectories (training data)
results/          # final reports
```

## Challenges included

| ID | Protocol | Chain | Difficulty |
|----|----------|-------|------------|
| `bybit_blind_001` | Bybit Cold Wallet (Safe proxy) | Ethereum mainnet | Hard |

## Adding a new challenge

1. Create `challenges/<id>/` with `challenge.json`, `visible/`, `workspace/`, `hidden/`
2. Populate `visible/` with the target contracts (no exploit hints)
3. Write `hidden/notes.md` with the real exploit summary for scoring
4. Set `"max_iterations"` in `challenge.json` based on complexity

## Requirements

- Python 3.11+
- OpenAI API key (GPT-4o recommended)
- Ethereum archive RPC (Infura, Alchemy, etc.)
- [Foundry](https://getfoundry.sh/) installed locally
