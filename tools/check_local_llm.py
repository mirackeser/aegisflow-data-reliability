# SPDX-License-Identifier: Apache-2.0
"""Opt-in check of the local model (not run in CI): one tiny schema-constrained request over loopback.

Needs a running Ollama on 127.0.0.1:11434 with the model pulled. Prints the model, latency, token usage and whether
the reply satisfied the schema; exits 0 when it did and 1 otherwise. Sends no file contents, only a fixed prompt.
"""
import argparse
import json
import sys

from aegisflow_dr.agents.llm import LocalModel

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["answer"],
          "properties": {"answer": {"enum": ["yes", "no"]}}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:4b")
    arguments = parser.parse_args(argv)
    result = LocalModel(model=arguments.model).complete(
        "Reply with JSON only.", 'Is 2 greater than 1? Answer "yes" or "no".', SCHEMA, max_tokens=32)
    print(json.dumps({"model": result.model, "valid": result.ok, "error_code": result.error_code,
                      "latency_ms": result.latency_ms, "tokens_in": result.tokens_in, "tokens_out": result.tokens_out,
                      "prompt_sha256": result.prompt_sha256}, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
