# Proofline

Proofline is a model-agnostic protocol and reference implementation for verifiable AI runs.

A run bundle records the inputs, code revision, model/tool steps, outputs, costs, redactions, and hashes needed to replay, diff, and audit LLM or agent executions. The core is a versioned schema; SDKs, storage backends, and framework adapters are replaceable layers around it.

## Non-goals

- Not another chat UI or agent framework.
- Not a model provider or prompt registry.
- Not a claim that reruns are bit-identical when the underlying model or tools are nondeterministic.

## Quickstart

```bash
python -m pip install -e .
proofline run --out artifacts/demo.run.json -- python examples/code_fix_agent.py --out artifacts/agent-sdk.run.json
proofline verify artifacts/demo.run.json
proofline diff artifacts/demo.run.json artifacts/agent-sdk.run.json
```

For SDK usage, see `examples/rag_citation_check.py` and `examples/code_fix_agent.py`.

## Core invariant

A bundle is portable evidence. Any field that cannot affect replay decisions, such as wall-clock timestamps or a fresh run id, is excluded from the stable digest and from semantic diffs.
