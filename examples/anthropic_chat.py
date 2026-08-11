"""Record a real Anthropic message as a verifiable run bundle.

Usage:
    pip install -e ".[anthropic]"
    set ANTHROPIC_API_KEY=sk-ant-...
    python examples/anthropic_chat.py --out artifacts/anthropic.run.json
"""

from __future__ import annotations

import argparse

from proofline import RunRecorder
from proofline.anthropic import wrap


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/anthropic.run.json")
    parser.add_argument("--model", default="claude-sonnet-4-5")
    parser.add_argument("--prompt", default="Explain in one sentence what a run bundle proves.")
    args = parser.parse_args()

    from anthropic import Anthropic

    with RunRecorder(out_path=args.out, metadata={"example": "anthropic_chat"}) as recorder:
        client = wrap(Anthropic(), recorder)
        response = client.messages.create(
            model=args.model,
            max_tokens=256,
            messages=[{"role": "user", "content": args.prompt}],
        )
        answer = "".join(
            block.text for block in response.content if getattr(block, "text", None)
        )
    print(args.out)
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
