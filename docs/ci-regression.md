# CI regression gates with proofline

This guide shows the highest-leverage proofline workflow: record a baseline run bundle once, then fail CI whenever a code or prompt change alters what your LLM pipeline actually does.

## Why this works

`proofline diff` compares two bundles semantically. Run ids, timestamps, positional step ids, and derived digests are excluded by design, so two runs of the same logic produce an empty diff, and any reported difference is a real behavior change: different inputs sent to the model, different outputs, different tool calls, different costs. Step sequences are aligned first: an inserted or removed step reports once (`added step` / `removed step`) instead of shifting every following step out of alignment.

The gate is only as deterministic as your pipeline. For CI, remove the obvious noise sources first:

- pin `temperature=0` (and `seed` where the provider supports it), or better, run the pipeline against recorded/fake responses in CI;
- pin model identifiers instead of aliases that silently move;
- keep dynamic values (dates, uuids) out of prompts, or inject them as fixed fixtures in CI.

## Step 1: record a baseline

Your pipeline records itself with `RunRecorder` (SDK) or gets wrapped by `proofline run` (CLI). Record one blessed run and commit it:

```bash
python pipeline.py --out ci/baseline.run.json
proofline verify ci/baseline.run.json
git add ci/baseline.run.json
```

Bundles are redacted before writing, but review the baseline once before committing, like any fixture.

## Step 2: re-run and diff in CI

```bash
python pipeline.py --out ci/candidate.run.json
proofline verify ci/candidate.run.json
proofline diff ci/baseline.run.json ci/candidate.run.json
```

`diff` exits 1 and prints a pointer-by-pointer report when behavior changed. A prompt edit on a matched step looks like:

```
$.steps[1].input.messages[0].content: 'old prompt' != 'new prompt'
$.steps[2].output.text: '...' != '...'
```

An inserted or removed step reports once, by `(kind, name)`, instead of misaligning the rest of the run:

```
$.steps: length 3 != 4
$.steps[2]: added step (tool/extra)
```

## Step 3: wire it into GitHub Actions

```yaml
name: llm-regression

on:
  pull_request:

jobs:
  regression:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install proofline -r requirements.txt
      - run: python pipeline.py --out ci/candidate.run.json
      - run: proofline verify ci/candidate.run.json
      - run: proofline diff ci/baseline.run.json ci/candidate.run.json
```

When a change is intentional, the fix is one command: re-record the baseline and commit it. The PR diff then shows reviewers exactly what behavior changed, in the bundle itself.

## In pytest (or any test runner)

`proofline.testing.assert_matches_baseline` wraps the same gate as a snapshot-style assertion:

```python
from proofline import RunRecorder
from proofline.testing import assert_matches_baseline

def test_pipeline_behavior():
    recorder = RunRecorder(argv=["pytest"])
    run_pipeline(recorder)
    assert_matches_baseline(recorder.finalize(), "tests/baselines/pipeline.run.json")
```

Record or intentionally update the baseline with `PROOFLINE_UPDATE_BASELINES=1 pytest`, review the bundle diff in the PR, and commit it. Candidate and baseline are both verified before comparison, so a tampered or malformed bundle on either side fails the test — including a baseline edited by hand instead of re-recorded. The update variable itself is excluded from the comparison, so recording a baseline never makes it differ from the next run.

## What to do with expected variance

If part of your pipeline is legitimately nondeterministic (live retrieval, sampling above zero), split the pipeline: gate the deterministic stages with `diff`, and assert only invariants (citations resolve, schema of the answer, cost ceilings) on the nondeterministic ones. A bundle records both kinds of steps either way, so the audit trail stays complete even where the gate is soft.

The strongest option is [replay](replay.md): set `PROOFLINE_REPLAY=ci/baseline.run.json` in the CI job and the wrappers serve the baseline's recorded responses instead of calling the provider. The gated stages become fully deterministic, offline, and free — and any remaining diff is attributable to your code, not the model.

## Environment-dependent fields

Bundles record `invocation.cwd`, `invocation.env_keys`, `actor`, and `project.revision` as evidence. Between your laptop and CI these will differ and show up in the diff. Two options, in order of preference:

1. Record the baseline in CI itself (a dedicated `re-baseline` workflow or a make target run in the same container), so baseline and candidate share an environment.
2. Treat those specific pointers as known-context differences when reviewing the diff output.
