from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from control_plane.pipeline import RunConfig, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed, replayable AI-assisted production change control plane."
    )
    parser.add_argument("--input-dir", type=Path, default=Path("input"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Reuse recorded LLM responses from outputs/llm_calls.jsonl; do not call a live model.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run execution authorization and simulated apply/verify/rollback for executable changes.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not call a live LLM. Fail closed unless a recorded response can be reused.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    records = run(
        RunConfig(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            replay=args.replay,
            execute=args.execute,
            allow_live_llm=not args.offline and not args.replay,
        )
    )
    for record in records:
        state = "" if record.state is None else record.state.value
        print(
            f"{record.request_id}\t{record.system_recommendation}\t{record.final_decision}\t"
            f"executable={record.executable}\t{state}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
