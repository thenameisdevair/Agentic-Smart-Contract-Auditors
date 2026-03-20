"""
Tool implementations for the agent execution loop.

The agent calls these via OpenAI function calling. Each tool takes a dict of
arguments and returns a string result that goes back into the conversation.
"""

import json
import shutil
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

import agent.config as config


# ---------------------------------------------------------------------------
# Sandboxing helpers
# ---------------------------------------------------------------------------

def _resolve_path(raw: str) -> Path:
    """
    Resolve a path safely. Relative paths are anchored to the repo root.
    Absolute paths are used as-is but must still exist (or be in workspace).
    """
    p = Path(raw)
    if not p.is_absolute():
        p = config.REPO_ROOT / p
    return p.resolve()


def _assert_not_hidden(path: Path, challenge: dict) -> None:
    """
    Raise if the path resolves to a hidden file for the current challenge.
    """
    hidden = challenge.get("hidden_files", [])
    for h in hidden:
        hidden_resolved = _resolve_path(h)
        if path == hidden_resolved or str(path).startswith(str(hidden_resolved)):
            raise PermissionError(
                f"Access denied: '{path}' is a hidden file for this challenge. "
                "You must not read exploit solutions during blind analysis."
            )


def _assert_in_workspace(path: Path, workspace: str) -> None:
    """Raise if the path is not inside the challenge workspace."""
    ws = _resolve_path(workspace)
    try:
        path.relative_to(ws)
    except ValueError:
        raise PermissionError(
            f"write_file is sandboxed to the workspace directory '{workspace}'. "
            f"Attempted path '{path}' is outside it."
        )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def read_file(path: str, challenge: dict) -> str:
    resolved = _resolve_path(path)
    _assert_not_hidden(resolved, challenge)

    if not resolved.exists():
        return f"ERROR: File not found: {resolved}"
    if not resolved.is_file():
        return f"ERROR: Path is not a file: {resolved}"

    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
        # Cap at ~15k chars to stay within context budget
        if len(content) > 15_000:
            content = content[:15_000] + "\n\n[... TRUNCATED — file is large. Read specific sections if needed.]"
        return content
    except Exception as e:
        return f"ERROR reading file: {e}"


def list_files(directory: str, challenge: dict) -> str:
    resolved = _resolve_path(directory)
    _assert_not_hidden(resolved, challenge)

    if not resolved.exists():
        return f"ERROR: Directory not found: {resolved}"
    if not resolved.is_dir():
        return f"ERROR: Path is not a directory: {resolved}"

    files = sorted(resolved.rglob("*"))
    # Filter out hidden challenge files
    visible = []
    hidden_paths = [_resolve_path(h) for h in challenge.get("hidden_files", [])]
    for f in files:
        if f.is_file():
            skip = any(
                f == hp or str(f).startswith(str(hp))
                for hp in hidden_paths
            )
            if not skip:
                rel = f.relative_to(config.REPO_ROOT)
                visible.append(str(rel))

    if not visible:
        return "No files found (or all are hidden)."
    return "\n".join(visible)


def write_file(path: str, content: str, challenge: dict) -> str:
    workspace = challenge.get("workspace", "")
    resolved = _resolve_path(path)

    try:
        _assert_in_workspace(resolved, workspace)
    except PermissionError as e:
        return f"ERROR: {e}"

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"OK: Written {len(content)} chars to {resolved}"
    except Exception as e:
        return f"ERROR writing file: {e}"


def run_forge_test(
    test_file: str,
    challenge: dict,
    fork_block: int | None = None,
    verbosity: int = 3,
) -> str:
    """
    Run `forge test --contracts <test_file>` from the Foundry project root.
    Returns combined stdout + stderr capped at 8k chars.
    """
    foundry_root = config.FOUNDRY_ROOT
    if not (foundry_root / "foundry.toml").exists() and not (foundry_root / "forge.toml").exists():
        return (
            f"ERROR: No foundry.toml found at FOUNDRY_ROOT={foundry_root}. "
            "Set FOUNDRY_ROOT in your .env to your local Foundry project path "
            "(e.g. ~/aismartcontractagent/DeFiHackLabs)."
        )

    # Resolve test file — try multiple strategies in order:
    # 1. As given (absolute, or relative to foundry root)
    # 2. Prepend "/" in case the model dropped the leading slash
    # 3. Relative to REPO_ROOT (challenge workspace files)
    tf = Path(test_file)
    if not tf.is_absolute():
        tf = foundry_root / test_file

    if not tf.exists():
        # Strategy 2: model may have passed "home/user/..." instead of "/home/user/..."
        with_slash = Path("/" + test_file)
        if with_slash.exists():
            tf = with_slash

    if not tf.exists():
        # Strategy 3: written to challenge workspace under REPO_ROOT — copy into
        # foundry's test/ directory so forge can compile it in project context.
        alt = _resolve_path(test_file)
        # Also try with leading slash stripped for the REPO_ROOT lookup
        if not alt.exists() and test_file.startswith("/"):
            alt = _resolve_path(test_file.lstrip("/"))
        if alt.exists():
            dest = foundry_root / "test" / alt.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(alt, dest)
            tf = dest
        else:
            return f"ERROR: Test file not found: {tf}"

    # If the file is outside foundry_root, copy it in so forge can compile it.
    try:
        tf.relative_to(foundry_root)
    except ValueError:
        dest = foundry_root / "test" / tf.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tf, dest)
        tf = dest

    cmd = [
        "forge", "test",
        "--contracts", str(tf),
        f"-{'v' * verbosity}",
    ]

    if fork_block:
        cmd += ["--fork-block-number", str(fork_block)]

    # RPC URL: inject from env via --fork-url only if a fork block is specified
    rpc = config.MAINNET_RPC_URL
    if fork_block and rpc:
        cmd += ["--fork-url", rpc]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(foundry_root),
            timeout=120,
            env={**__import__("os").environ, "MAINNET_RPC_URL": rpc},
        )
        output = result.stdout + result.stderr
        # Cap output
        if len(output) > 8_000:
            output = output[:8_000] + "\n\n[... OUTPUT TRUNCATED]"
        passed = result.returncode == 0
        status = "PASSED" if passed else "FAILED"
        return f"[forge test {status} — exit code {result.returncode}]\n\n{output}"
    except subprocess.TimeoutExpired:
        return "ERROR: forge test timed out after 120 seconds."
    except FileNotFoundError:
        return "ERROR: `forge` not found. Make sure Foundry is installed and on PATH."
    except Exception as e:
        return f"ERROR running forge test: {e}"


# ---------------------------------------------------------------------------
# Onchain contract source fetching
# ---------------------------------------------------------------------------

def fetch_contract_source(address: str, chain: str = "mainnet") -> str:
    """
    Fetch verified Solidity source code for a deployed contract.

    Tries cast etherscan-source first. Falls back to direct Etherscan API call.
    Returns the source as a string, capped at 20k chars.
    """
    address = address.strip()
    api_key = config.ETHERSCAN_API_KEY

    # --- Try cast etherscan-source first ---
    try:
        cmd = ["cast", "etherscan-source", address, "--chain", chain]
        if api_key:
            cmd += ["--etherscan-api-key", api_key]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = (result.stdout or "").strip()
        if output and result.returncode == 0:
            if len(output) > 20_000:
                output = output[:20_000] + "\n\n[... TRUNCATED]"
            return output
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # cast not available or timed out, fall through to API

    # --- Fallback: Etherscan API ---
    if not api_key:
        return (
            "ERROR: cast etherscan-source failed and no ETHERSCAN_API_KEY is set. "
            "Add ETHERSCAN_API_KEY to your .env to fetch contract source."
        )

    chain_ids = {
        "mainnet": 1,
        "arbitrum": 42161,
        "optimism": 10,
        "base": 8453,
        "polygon": 137,
    }
    chain_id = chain_ids.get(chain, 1)

    params = urllib.parse.urlencode({
        "chainid": chain_id,
        "module": "contract",
        "action": "getsourcecode",
        "address": address,
        "apikey": api_key,
    })
    url = f"https://api.etherscan.io/v2/api?{params}"

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        if data.get("status") != "1" or not data.get("result"):
            return f"ERROR: Etherscan API returned no source for {address}: {data.get('message', 'unknown error')}"

        result = data["result"][0]
        source = result.get("SourceCode", "")
        contract_name = result.get("ContractName", "Unknown")
        compiler = result.get("CompilerVersion", "unknown")

        if not source:
            return f"ERROR: Contract {address} is not verified on Etherscan."

        # SourceCode may be JSON-encoded multi-file source
        header = f"// Contract: {contract_name}\n// Compiler: {compiler}\n// Address: {address}\n\n"
        full = header + source

        if len(full) > 20_000:
            full = full[:20_000] + "\n\n[... TRUNCATED — use read_file on saved files for full source]"

        return full

    except Exception as e:
        return f"ERROR fetching contract source from Etherscan: {e}"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def dispatch(tool_name: str, args: dict, challenge: dict) -> str:
    """Route an OpenAI tool call to the correct implementation."""
    try:
        if tool_name == "read_file":
            return read_file(args["path"], challenge)
        elif tool_name == "list_files":
            return list_files(args["directory"], challenge)
        elif tool_name == "write_file":
            return write_file(args["path"], args["content"], challenge)
        elif tool_name == "fetch_contract_source":
            return fetch_contract_source(
                args["address"],
                chain=args.get("chain", "mainnet"),
            )
        elif tool_name == "run_forge_test":
            return run_forge_test(
                args["test_file"],
                challenge,
                fork_block=args.get("fork_block"),
                verbosity=args.get("verbosity", 3),
            )
        else:
            return f"ERROR: Unknown tool '{tool_name}'"
    except KeyError as e:
        return f"ERROR: Missing required argument {e} for tool '{tool_name}'"
    except Exception as e:
        return f"ERROR in tool '{tool_name}': {e}"
