from __future__ import annotations

import argparse
from pathlib import Path

from proofline import RunRecorder

SOURCE = "def add(a, b):\n    return a - b\n"


def locate_fault(source: str) -> dict[str, object]:
    return {"symbol": "add", "line": 2, "observation": "subtraction used where addition was intended"}


def propose_patch(source: str, fault: dict[str, object]) -> dict[str, object]:
    return {
        "patch": source.replace("return a - b", "return a + b"),
        "rationale": "restore the arithmetic operator promised by the function name",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/code-fix.run.json")
    args = parser.parse_args()

    out = Path(args.out)
    with RunRecorder(out_path=out, metadata={"example": "code_fix_agent"}) as recorder:
        with recorder.step("tool", "locate_fault", input={"source": SOURCE}) as step:
            fault = locate_fault(SOURCE)
            step["output"] = fault
        with recorder.step("model", "propose_patch", input={"source": SOURCE, "fault": fault}) as step:
            proposal = propose_patch(SOURCE, fault)
            step["output"] = proposal
            step["cost"] = {"input_tokens": 87, "output_tokens": 31, "usd": 0.0}
        with recorder.step("custom", "check_patch", input={"patch": proposal["patch"]}) as step:
            fixed = "return a + b" in proposal["patch"]
            step["output"] = {"fixed": fixed}
            if not fixed:
                step["status"] = "error"
                step["error"] = "patch did not contain the expected fix"
    print(out)
    return 0 if fixed else 1


if __name__ == "__main__":
    raise SystemExit(main())
