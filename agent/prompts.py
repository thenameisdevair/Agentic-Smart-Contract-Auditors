"""
Prompts and OpenAI tool definitions for the blind execution agent.
"""

SYSTEM_PROMPT = """
You are an autonomous smart contract security agent.

Your mission: find and VERIFY exploits in Solidity systems by writing and executing Foundry tests.

You operate in a loop with a budget of tool calls. Use them wisely.

--- HOW TO WORK ---

Step 1 — UNDERSTAND the system.
  Use read_file to inspect the provided Solidity files.
  Use list_files to discover what is available in the visible directory.

Step 2 — FORM a hypothesis.
  Think adversarially. Consider:
  - Proxy/upgradeability patterns (masterCopy slot, delegatecall, storage layout)
  - Access control gaps (who can call what, under what conditions)
  - State transition abuse (ordering of operations, re-entrancy, flash loans)
  - Trust assumptions (msg.sender through delegatecall changes, module validation)
  - EVM behavior (storage slots, fallback/receive, selector collisions)
  - Economic attacks (price manipulation, share inflation, liquidation paths)

Step 3 — WRITE a Foundry test.
  Use write_file to create a .t.sol file in the workspace directory.
  The test must:
  - Use `forge-std/Test.sol` and `vm.createSelectFork`
  - Set up the forked state to match attack preconditions
  - Execute the attack path
  - Assert that the attack succeeded (e.g., balance increased, state changed)
  Keep the test minimal — focus on confirming the hypothesis, not perfection.

Step 4 — RUN the test.
  Use run_forge_test to execute your test file.
  Observe the result: pass, fail, revert reason, logs, traces.

Step 5 — REVISE.
  If the test fails:
  - Read the error carefully
  - Fix the test or revise your hypothesis
  - Try again
  If the test passes:
  - You have a confirmed finding
  - Output FINDING_CONFIRMED

--- RULES ---

- NEVER claim a vulnerability is real without a passing Foundry test.
- Do not invent functions, addresses, or behaviors not supported by the code.
- Treat a failing test as useful data, not a dead end — diagnose the failure.
- Separate facts (from code) from assumptions (unverified).
- When you exhaust your budget without confirmation, output NO_FINDING with a summary of what you tried and why each attempt failed.
- Be explicit about required preconditions for any exploit.

--- FINAL OUTPUT FORMAT ---

If you confirm a finding:
FINDING_CONFIRMED
- Root cause: <one sentence>
- Affected component: <contract/function>
- Attack path: <numbered steps>
- Test file: <workspace path>
- Impact: <what an attacker gains>

If you do not confirm:
NO_FINDING
- Hypotheses tried: <list>
- Why each failed: <brief per-hypothesis explanation>
- What would help: <what additional context/access could change this>
""".strip()


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_contract_source",
            "description": "Fetch the verified Solidity source code of a deployed contract from Etherscan by address. Use this as your FIRST action to inspect the real onchain contracts before forming hypotheses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {
                        "type": "string",
                        "description": "The contract address to fetch source for, e.g. '0x1db92e2eebc8e0c075a02bea49a2935bcd2dfcf4'",
                    },
                    "chain": {
                        "type": "string",
                        "description": "Chain name: mainnet, arbitrum, optimism, base, polygon. Default: mainnet",
                    },
                },
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file by path. Use this to inspect Solidity contracts, interfaces, configs, or test files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file, relative to the repository root or absolute.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List all files in a directory recursively. Use this to discover what contracts and files are available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Directory path to list, relative to repository root or absolute.",
                    }
                },
                "required": ["directory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file in the challenge workspace directory. Use this to create or update Foundry test files (.t.sol). Files must be written to the workspace path provided in the challenge.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path within the workspace directory. Example: 'workspace/ExploitTest.t.sol'",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full file content to write.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_forge_test",
            "description": "Run a Foundry test file using `forge test`. Returns stdout, stderr, and pass/fail status. Use this after writing a test to verify your hypothesis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_file": {
                        "type": "string",
                        "description": "Path to the .t.sol test file, relative to the Foundry project root.",
                    },
                    "fork_block": {
                        "type": "integer",
                        "description": "Block number to fork at. Required for fork tests.",
                    },
                    "verbosity": {
                        "type": "integer",
                        "description": "Verbosity level for forge test output (2=basic, 3=traces, 4=full traces). Default is 3.",
                    },
                },
                "required": ["test_file"],
            },
        },
    },
]


def build_initial_message(challenge: dict) -> str:
    """Build the opening user message for a challenge."""
    lines = [
        f"Challenge: {challenge['name']}",
        f"Chain: {challenge['chain']}",
        f"Fork block: {challenge['block_number']}",
        f"Workspace (write your tests here): {challenge['workspace']}",
        "",
        f"Goal: {challenge['goal']}",
        "",
    ]

    # Target contracts (fetch from chain)
    target_contracts = challenge.get("target_contracts", [])
    if target_contracts:
        lines.append("Target contracts — fetch their source using fetch_contract_source:")
        for c in target_contracts:
            lines.append(f"  - {c['address']}  ({c.get('label', '')})")
        lines += [
            "",
            "Start by calling fetch_contract_source on each target contract to read the real onchain code.",
        ]
    elif challenge.get("visible_files"):
        lines.append("Visible files you may read:")
        for f in challenge.get("visible_files", []):
            lines.append(f"  - {f}")
        lines += [
            "",
            "Start by reading the visible files to understand the system.",
        ]

    lines.append("Remember: a finding is only valid if your Foundry test passes.")
    return "\n".join(lines)
