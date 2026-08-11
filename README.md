# Proofline

[![CI](https://github.com/Powfu-zwx/proofline/actions/workflows/ci.yml/badge.svg)](https://github.com/Powfu-zwx/proofline/actions/workflows/ci.yml)

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

### OpenAI integration

```bash
python -m pip install -e ".[openai]"
```

```python
from openai import OpenAI
from proofline import RunRecorder
from proofline.openai import wrap

with RunRecorder(out_path="artifacts/openai.run.json") as recorder:
    client = wrap(OpenAI(), recorder)
    client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "ping"}],
    )
```

Each `chat.completions.create` call is recorded as a `model` step with the
request as input, the response as output, and token usage as cost. Run
`examples/openai_chat.py` for an end-to-end recorded call.

## Core invariant

A bundle is portable evidence. Any field that cannot affect replay decisions, such as wall-clock timestamps or a fresh run id, is excluded from the stable digest and from semantic diffs.
