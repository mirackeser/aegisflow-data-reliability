from pathlib import Path
from .registry import load_catalog

if __name__ == "__main__":
    catalog = load_catalog(Path(__file__).resolve().parents[2] / "docs/agent-catalog.json")
    print(f"{len(catalog)} planned specialist roles; runtime not implemented.")
