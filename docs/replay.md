# Replay: a bundle is a test fixture

Replay serves recorded model responses back through the proofline wrappers, so a pipeline re-runs deterministically, offline, and for free — while still being recorded. The baseline bundle becomes the fixture; the replayed run produces a fresh bundle you can diff.

```python
from proofline import RunRecorder
from proofline.openai import wrap
from proofline.replay import ReplaySource

recorder = RunRecorder(out_path="replayed.run.json")
client = wrap(OpenAI(), recorder, replay=ReplaySource("baseline.run.json"))
run_pipeline(client)  # answered from the baseline; the provider is never called
```

No code change needed in CI: set `PROOFLINE_REPLAY=baseline.run.json` and every `wrap()` call without an explicit `replay=` picks it up.

## Matching strategies

| Strategy | Behavior | Use it for |
|---|---|---|
| `strict` (default) | Each request must match a recorded step by name and redacted-input digest; any divergence raises `ReplayMismatch` with a pointer-level diff of the closest remaining step | Fixture tests: guarantee the pipeline sends exactly the recorded requests |
| `ordered` | Serves the next recorded step with the same name, whatever the request contains | Attribution: a changed pipeline still completes, and the bundle diff shows precisely what changed |

Each recorded step is served at most once; running out of steps raises `ReplayMismatch`.

## Attribution: our code, or the model?

After a behavior regression, two cheap runs answer the question no dashboard can:

| Run | Setup | Empty diff means | Non-empty diff means |
|---|---|---|---|
| Replay | new code + recorded responses (`ordered`) | code did not change behavior | the diff IS your code's behavior change, pointer by pointer |
| Live re-run | same code + real provider | model is stable | model drift (or nondeterminism you have not pinned) |

## Streaming

Wrappers record the individual text chunks (`output.chunks`, added in 0.2.0) alongside the accumulated content, and replay re-emits them chunk by chunk — consumer loops behave identically. Bundles recorded before 0.2.0 replay as a single chunk carrying the full content.

## Limitations

- Replayed responses support attribute access, indexing, and `model_dump()`. SDK-specific methods and lazily computed fields beyond the recorded JSON are not simulated.
- A recorded step with no output (a failed request) cannot be replayed and raises `ReplayMismatch`.
- Replayed bundles carry no automatic marker, by design: an empty diff against the baseline must stay empty. Record provenance in your own `metadata` if you need it.
- Mixing modes fails loudly: a live streamed call cannot be served from a non-streamed recording, and vice versa.
- `ReplaySource` is stateful and not thread-safe, like `RunRecorder`.
- Replay covers model steps served through the wrappers. Re-executing recorded `process` steps (`proofline run`) is out of scope.
