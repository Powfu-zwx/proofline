"""A guided tour of semantic diff — with the naive diff as the control group.

Deterministic and offline (every "model" is a canned function), so the
transcript is reproducible by anyone:

    python examples/semantic_diff_demo.py [--artifacts DIR]

Four scenes:

1. The same pipeline runs twice: a plain text diff reports a pile of noise
   (run ids, timestamps); proofline reports nothing, because nothing
   semantic happened.
2. One line of the system prompt changes: the naive diff is hex churn;
   proofline names the exact field, with old and new values.
3. A tool call is inserted mid-run: the step sequence is aligned, so the
   insertion is reported once instead of misaligning everything after it.
4. Someone edits a recorded answer by hand: verify catches it, survives a
   digest re-seal, and only the signature tells the truth.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

from proofline import RunRecorder, verify_bundle
from proofline.diff import diff_bundles
from proofline.model import sha256_json, stable_digest
from proofline.storage import read_bundle, write_bundle

SYSTEM_V1 = "Answer with citations."
SYSTEM_V2 = "Answer with citations. Prefer primary sources."
DOCS = {"d1": "Digests ignore run ids and timestamps."}

HEX = re.compile(r"\b[0-9a-f]{16,}\b")


def _color_on() -> bool:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    os.system("")  # enable ANSI escapes on Windows terminals
    return True


COLOR = _color_on()


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def bold(text: str) -> str:
    return paint(text, "1")


def dim(text: str) -> str:
    return paint(text, "2")


def green(text: str) -> str:
    return paint(text, "32")


def red(text: str) -> str:
    return paint(text, "31")


def yellow(text: str) -> str:
    return paint(text, "33")


def cyan(text: str) -> str:
    return paint(text, "36")


def scene(number: int, title: str) -> None:
    print()
    print(cyan("━" * 62))
    print(cyan(f" {number}. {title}"))
    print(cyan("━" * 62))


def record_run(out: Path, *, system: str, extra_search: bool = False) -> None:
    with RunRecorder(out_path=out, argv=["python", "agent.py"]) as recorder:
        with recorder.step("model", "plan", input={"system": system, "task": "answer"}) as step:
            step["output"] = {"plan": ["retrieve", "draft", "check"]}
        if extra_search:
            with recorder.step("tool", "search_docs", input={"query": "digest rules"}) as step:
                step["output"] = {"hits": ["d1"]}
        with recorder.step("tool", "retrieve", input={"query": "digest rules"}) as step:
            step["output"] = {"docs": [{"doc_id": "d1"}]}
        with recorder.step(
            "model", "draft_answer", input={"system": system, "docs": ["d1"]}
        ) as step:
            step["output"] = {"text": f"{DOCS['d1']} [d1]", "citations": ["d1"]}
            step["cost"] = {"input_tokens": 42, "output_tokens": 18}
        with recorder.step("custom", "check_citations", input={"citations": ["d1"]}) as step:
            step["output"] = {"ok": True}


def naive_changed_lines(left: Path, right: Path) -> list[str]:
    """What a plain text diff of the two JSON files reports."""
    a = json.dumps(read_bundle(left), indent=2, sort_keys=True).splitlines()
    b = json.dumps(read_bundle(right), indent=2, sort_keys=True).splitlines()
    return [
        line
        for line in difflib.unified_diff(a, b, lineterm="")
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def preview_naive(lines: list[str], limit: int = 4) -> None:
    print(f"    {bold('plain JSON diff')} sees {red(str(len(lines)))} changed lines:")
    for line in lines[:limit]:
        text = HEX.sub(lambda m: m.group(0)[:8] + "…", line)
        print(f"      {dim(text)}")
    if len(lines) > limit:
        print(f"      {dim(f'… and {len(lines) - limit} more')}")


def show_proofline(left: Path, right: Path) -> None:
    differences = diff_bundles(left, right)
    if not differences:
        print(f"    {bold('proofline diff')} sees: {green('no semantic differences')}")
    else:
        print(f"    {bold('proofline diff')} sees:")
        for difference in differences:
            print(f"      {yellow(difference)}")


def timeline(names: list[str]) -> str:
    return " → ".join(f"[{name}]" for name in names)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", default="artifacts/semantic-diff-demo")
    args = parser.parse_args()
    base = Path(args.artifacts)
    base.mkdir(parents=True, exist_ok=True)

    print(bold("proofline semantic diff — a guided tour"))
    print(dim("one agent pipeline, recorded as verifiable bundles, then compared"))

    rerun_a, rerun_b = base / "rerun-a.run.json", base / "rerun-b.run.json"
    record_run(rerun_a, system=SYSTEM_V1)
    record_run(rerun_b, system=SYSTEM_V1)

    scene(1, "The same agent runs twice")
    print(f"  {dim(timeline(['plan', 'retrieve', 'draft', 'check']))} — run A")
    run_b_note = " — run B (fresh run id, fresh timestamps)"
    print(f"  {dim(timeline(['plan', 'retrieve', 'draft', 'check']))}{dim(run_b_note)}")
    print()
    preview_naive(naive_changed_lines(rerun_a, rerun_b))
    show_proofline(rerun_a, rerun_b)
    print(f"\n  {dim('Identical work should diff to nothing. It does.')}")

    scene(2, "One line of the system prompt changes")
    prompt_change = base / "prompt-change.run.json"
    record_run(prompt_change, system=SYSTEM_V2)
    print(f"  {dim(repr(SYSTEM_V1))}")
    print(f"  {dim(repr(SYSTEM_V2))}")
    print()
    preview_naive(naive_changed_lines(rerun_a, prompt_change))
    show_proofline(rerun_a, prompt_change)
    print(f"\n  {dim('The naive diff drowns one changed sentence in 30 lines of noise;')}")
    print(f"  {dim('proofline names the field, in every step that received it.')}")

    scene(3, "A tool call is inserted mid-run")
    inserted = base / "inserted-step.run.json"
    record_run(inserted, system=SYSTEM_V1, extra_search=True)
    print(f"  {dim(timeline(['plan', 'retrieve', 'draft', 'check']))} — baseline")
    print(f"  {dim(timeline(['plan', 'search_docs', 'retrieve', 'draft', 'check']))} — new run")
    print()
    show_proofline(rerun_a, inserted)
    note = "Aligned as sequences: one insertion, one line — not four misaligned steps."
    print(f"\n  {dim(note)}")

    scene(4, "Someone edits the transcript")
    evidence = base / "evidence.run.json"
    record_run(evidence, system=SYSTEM_V1)
    honest_bytes = evidence.read_bytes()

    try:
        from proofline.sign import generate_keypair, sign_bundle

        keys = base / ".keys"
        private_key, _public = generate_keypair(keys)
        sign_bundle(evidence, private_key)
        print(f"  {dim('The run was signed; now the tampering begins.')}")
    except RuntimeError:
        private_key = None
        print(f"  {dim('(sign extra not installed — scene 4 shows digest checks only)')}")

    forged = " [REDACTED BY ORDER OF MANAGEMENT]"
    print(f"\n  {bold('tamper')}: steps[2].output.text")
    print(f"    {dim('+ appended:')} {red(repr(forged))}")
    bundle = read_bundle(evidence)
    bundle["steps"][2]["output"]["text"] += forged
    write_bundle(evidence, bundle)
    errors = verify_bundle(evidence)
    print("  $ proofline verify evidence.run.json")
    for error in errors:
        print(f"    {red('✗')} {error}")

    print(f"\n  {bold('re-seal')}: {dim('the attacker recomputes both digests to hide the edit')}")
    bundle = read_bundle(evidence)
    bundle["steps"][2]["output_digest"] = sha256_json(bundle["steps"][2]["output"])
    bundle["bundle_digest"] = stable_digest(bundle)
    write_bundle(evidence, bundle)
    errors = verify_bundle(evidence)
    print("  $ proofline verify evidence.run.json")
    for error in errors:
        print(f"    {red('✗')} {error}")
    if not errors:
        re_seal_note = "a full re-seal defeats digests — that is what signing is for"
        print(f"    {yellow(f'✗ {re_seal_note}')}")

    print()
    evidence.write_bytes(honest_bytes)
    restored = verify_bundle(evidence) == []
    print(f"  {dim('restored the honest bundle:')} {green(restored and '✓ verify OK')}")

    print()
    print(dim("reproduce: python examples/semantic_diff_demo.py"))
    print(dim("docs: docs/journal.md · spec/run-bundle-v0.1.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
