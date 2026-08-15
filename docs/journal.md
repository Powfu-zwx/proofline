# Crash-safe journaling

By default a `RunRecorder` holds evidence in memory and writes the bundle once, in `finalize()`. A process that dies mid-run — OOM kill, power loss, a stray `SIGKILL`, an uncaught `sys.exit` in a library — takes everything with it: no bundle, no partial evidence, nothing to audit.

Journal mode fixes that. Each completed step is appended — and fsynced — to a JSONL sidecar the moment it finishes, so the evidence for every finished step is on disk before your code moves on.

```python
from proofline import RunRecorder

with RunRecorder(out_path="artifacts/agent.run.json", journal=True) as recorder:
    ...  # a long agent run
```

If the process survives, `finalize()` rebuilds the bundle from the journal, writes it atomically, and removes the journal. If it does not:

```bash
proofline recover artifacts/agent.run.json.journal
# recovered 3 steps -> artifacts/agent.run.json
proofline verify artifacts/agent.run.json
# OK
```

`recover` writes the bundle next to the journal by default (`run.json.journal` -> `run.json`; pass `--out` to choose another path) and removes the journal only after the write succeeded, so a failed recovery never destroys the remaining evidence.

`proofline run --journal` records subprocess runs the same way.

## Guarantees

| Property | Guarantee |
|---|---|
| Completed steps | Durable (flush + fsync) before `step()` returns |
| In-flight step | Not recorded — same as memory mode; an unfinished step is not evidence |
| Torn final line | Detected and dropped (the crash happened mid-append) |
| Corrupt interior line | Hard error; silent loss in the middle would forge evidence |
| Recovered bundle | Sealed exactly like a live `finalize()` — same canonical JSON, same stable digest — and re-checks with `proofline verify` |
| Journal lifetime | Deleted only after the bundle write succeeds |

What journaling does **not** do: it is not a write-ahead log for your pipeline's side effects, and it cannot record work the process never completed. It preserves the evidence that existed at the moment of the crash.

## Journal format

One JSON object per line, LF-terminated:

```json
{"j":"proofline-journal","v":1,"created_at":"2026-08-15T09:00:00.000Z","run":{"schema_version":"0.1","run_id":"…","actor":{…},"project":{…},"invocation":{…},"metadata":{…},"metadata_redactions":["/metadata/api_key"]}}
{"t":"step","step":{…},"redactions":["/steps/0/input/api_key"]}
{"t":"step","step":{…},"redactions":[]}
```

- The first line is the header: run identity plus everything `finalize()` needs that is known at construction time. `created_at` is the run start, so a recovered bundle reports when the run began, not when it was recovered.
- Steps appear in completion order, already redacted, already carrying their `input_digest` / `output_digest`.
- `v` is the journal format version (independent of the bundle's `schema_version`). An unsupported version is rejected rather than guessed at.

Starting a new recorder with the same journal path truncates it — the journal belongs to one run.

## Long runs and memory

In journal mode, step payloads live on disk, not in the recorder: `recorder.steps` stays empty and memory is bounded by the largest step, not by the run length. At `finalize()` (or `recover`) the bundle is rebuilt from the journal and sealed with [`StableDigestBuilder`](#streaming-digest), which hashes each step as it is read instead of materializing the canonical JSON of the whole document. A ten-thousand-step run costs the memory of one step plus the final bundle write.

## Streaming digest

`StableDigestBuilder` (in `proofline.model`) computes `stable_digest` incrementally:

```python
from proofline.model import StableDigestBuilder

builder = StableDigestBuilder(header)   # every non-volatile field except steps, redactions final
for step in steps:
    builder.add_step(step)
builder.hexdigest()                     # == stable_digest({"steps": steps, **header})
```

The output is bit-identical to `stable_digest` — pinned by a property test — so the digest rules in the spec, and the TypeScript port's byte-level parity, are unchanged.

## Differences from memory mode

- `created_at` is recorded at construction instead of at `finalize()`.
- A step output that is not strict-JSON-serializable fails at the end of that step (where the journal append happens) instead of at `finalize()`. Both are errors; journaling surfaces them earlier, before more work piles on top.
- Steps cannot be recorded after `finalize()`: the journal is closed and sealed. Start a new recorder instead.
- `Policy.check_write_path` is enforced on the journal path at construction, so a policy violation fails before the run starts, not after it.
