import argparse
import sys
from pathlib import Path

try:
    from src.research_core import DEFAULT_DIGEST_DIR, DEFAULT_PORTFOLIO, run_digest
except ModuleNotFoundError:
    from research_core import DEFAULT_DIGEST_DIR, DEFAULT_PORTFOLIO, run_digest


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Generate a daily investment research digest.")
    parser.add_argument("--portfolio", type=Path, default=DEFAULT_PORTFOLIO)
    parser.add_argument("--out", type=Path, default=DEFAULT_DIGEST_DIR)
    args = parser.parse_args(argv)

    output_path = run_digest(args.portfolio, args.out)
    print(f"Wrote digest: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
