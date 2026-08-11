from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from .diff import diff_bundles
from .model import PACKAGE_VERSION
from .policy import PolicyViolation
from .recorder import RunRecorder
from .verify import VerificationError, verify_bundle

# Inline cap for the recorded text preview; the digest always covers the exact bytes.
OUTPUT_CAP = 10_000


def _captured(raw: bytes) -> dict[str, Any]:
    """Evidence for one output stream: byte digest plus a capped UTF-8 preview."""
    text = raw.decode("utf-8", errors="replace")
    return {
        "text": text[:OUTPUT_CAP],
        "truncated": len(text) > OUTPUT_CAP,
        "length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _echo(stream: Any, raw: bytes) -> None:
    """Echo captured child output byte-exact, never failing the recorded run."""
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(raw.decode("utf-8", errors="replace"))
        return
    stream.flush()
    buffer.write(raw)
    buffer.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="proofline")
    parser.add_argument(
        "--version", action="version", version=f"proofline {PACKAGE_VERSION}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="execute a command and record a process bundle")
    run_parser.add_argument("--out", required=True, help="path to write the run bundle")
    run_parser.add_argument("cmd", nargs=argparse.REMAINDER, help="command after --")

    verify_parser = subparsers.add_parser("verify", help="validate a run bundle")
    verify_parser.add_argument("path", help="bundle path")

    diff_parser = subparsers.add_parser("diff", help="compare two bundles semantically")
    diff_parser.add_argument("left", help="left bundle path")
    diff_parser.add_argument("right", help="right bundle path")
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    argv = list(args.cmd)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print("no command given after --", file=sys.stderr)
        return 2

    returncode = 1
    metadata = {"entrypoint": "proofline run"}
    with RunRecorder(argv=argv, out_path=args.out, metadata=metadata) as recorder:
        process_name = Path(argv[0]).name or argv[0]
        with recorder.step("process", process_name, input={"argv": argv}) as handle:
            completed = subprocess.run(argv, check=False, capture_output=True)
            returncode = completed.returncode
            handle["output"] = {
                "returncode": returncode,
                "stdout": _captured(completed.stdout),
                "stderr": _captured(completed.stderr),
            }
            _echo(sys.stdout, completed.stdout)
            _echo(sys.stderr, completed.stderr)
            if returncode:
                handle["status"] = "error"
                handle["error"] = f"process exited with {returncode}"
    return returncode


def _cmd_verify(args: argparse.Namespace) -> int:
    errors = verify_bundle(args.path)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"OK {args.path}")
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    differences = diff_bundles(args.left, args.right)
    if not differences:
        print("no semantic differences")
        return 0
    for difference in differences:
        print(difference)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "verify":
            return _cmd_verify(args)
        if args.command == "diff":
            return _cmd_diff(args)
    except (PolicyViolation, VerificationError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
