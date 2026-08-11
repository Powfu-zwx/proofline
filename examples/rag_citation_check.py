from __future__ import annotations

import argparse
from pathlib import Path

from proofline import RunRecorder

DOCS = {
    "d1": "Proofline excludes wall-clock timestamps from the stable bundle digest.",
    "d2": "Redaction paths are stored as JSON Pointers.",
}


def retrieve(question: str) -> list[dict[str, str]]:
    return [{"doc_id": "d1", "text": DOCS["d1"]}]


def draft_answer(question: str, docs: list[dict[str, str]]) -> dict[str, object]:
    return {
        "text": f"{docs[0]['text']} [d1]",
        "citations": ["d1"],
        "model": "deterministic-demo",
    }


def citations_resolve(answer: dict[str, object]) -> bool:
    return all(citation in DOCS for citation in answer["citations"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/rag-citation.run.json")
    parser.add_argument("--question", default="Why are two runs comparable?")
    args = parser.parse_args()

    out = Path(args.out)
    with RunRecorder(out_path=out, metadata={"example": "rag_citation_check"}) as recorder:
        with recorder.step("tool", "retrieve", input={"question": args.question}) as step:
            docs = retrieve(args.question)
            step["output"] = {"docs": docs}
        with recorder.step("model", "draft_answer", input={"question": args.question, "docs": docs}) as step:
            answer = draft_answer(args.question, docs)
            step["output"] = answer
            step["cost"] = {"input_tokens": 42, "output_tokens": 18, "usd": 0.0}
        with recorder.step("custom", "verify_citations", input={"answer": answer}) as step:
            ok = citations_resolve(answer)
            step["output"] = {"ok": ok}
            if not ok:
                step["status"] = "error"
                step["error"] = "unresolved citation"
    print(out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
