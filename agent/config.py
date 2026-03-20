import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# API keys
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
MAINNET_RPC_URL: str = os.getenv("MAINNET_RPC_URL", "")
ETHERSCAN_API_KEY: str = os.getenv("ETHERSCAN_API_KEY", "")

# Model settings
DEFAULT_MODEL: str = os.getenv("MODEL", "gpt-4o")
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.2"))
MAX_ITERATIONS: int = int(os.getenv("MAX_ITERATIONS", "10"))

# Paths
REPO_ROOT = Path(__file__).parent.parent
CHALLENGES_DIR = REPO_ROOT / "challenges"
TRAJECTORIES_DIR = REPO_ROOT / "trajectories"
RESULTS_DIR = REPO_ROOT / "results"

# Path to a local Foundry project root (where forge is run from).
# Point this at your DeFiHackLabs clone or any Foundry project.
FOUNDRY_ROOT: Path = Path(os.getenv("FOUNDRY_ROOT", str(REPO_ROOT)))


def validate() -> None:
    """Raise if required config is missing."""
    if not OPENAI_API_KEY:
        raise EnvironmentError("OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in.")
    if not MAINNET_RPC_URL:
        raise EnvironmentError("MAINNET_RPC_URL is not set.")
