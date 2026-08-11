"""Record a real OpenAI chat completion as a verifiable run bundle.

Usage:
    pip install -e ".[openai]"
    set OPENAI_API_KEY=sk-...
    python examples/openai_chat.py --out artifacts/openai.run.json
"""

from __future__ import annotations

import argparse

from proofline import RunRecorder
from proofline.openai import wrap


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/openai.run.json")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--prompt", default="Explain in one sentence what a run bundle proves.")
    args = parser.parse_args()

    from openai import OpenAI

    with RunRecorder(out_path=args.out, metadata={"example": "openai_chat"}) as recorder:
        client = wrap(OpenAI(), recorder)
        response = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": args.prompt}],
        )
        answer = response.choices[0].message.content
    print(args.out)
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
