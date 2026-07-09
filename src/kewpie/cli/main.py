"""The `kewpie` command-line interface: collect | extract | doctor | fetch."""
from __future__ import annotations

import argparse
import json
import logging
import sys


def _add_collect(sub):
    p = sub.add_parser("collect", help="fetch every configured source -> raw docs")
    p.add_argument("--sources", default=None, help="sources.json path")
    p.add_argument("--out", default=None, help="output dir for raw parquet")
    p.add_argument("--state", default=None, help="state dir (cache/policy)")
    p.add_argument("--max-items", type=int, default=25)
    p.add_argument("--since-hours", type=float, default=None)
    p.add_argument("--vocab", default=None, help="vocabulary.json (for --prefilter)")
    p.add_argument("--prefilter", action="store_true",
                   help="apply the vocabulary's default fetch-time prefilter")
    p.add_argument("--cassette", choices=("off", "record", "replay"), default="off")
    p.add_argument("--max-tier", choices=("cheap", "impersonate", "browser"),
                   default=None)
    return p


def _add_extract(sub):
    p = sub.add_parser("extract", help="vocabulary extraction over stored raw docs")
    p.add_argument("--vocab", default=None, help="vocabulary.json path")
    p.add_argument("--raw-dir", default=None, help="dir of raw parquet")
    p.add_argument("--out", default=None, help="output dir for signal parquet")
    p.add_argument("--since-days", type=float, default=None)
    return p


def _add_doctor(sub):
    p = sub.add_parser("doctor", help="fingerprint-coherence + config self-test")
    p.add_argument("--reflector", default=None, help="JA3/JA4/HTTP2 reflector URL")
    return p


def _add_fetch(sub):
    p = sub.add_parser("fetch", help="one-shot ladder fetch of a single URL")
    p.add_argument("url")
    p.add_argument("--tier", choices=("auto", "cheap", "impersonate", "browser"),
                   default="auto")
    p.add_argument("--state", default=None)
    p.add_argument("--json", action="store_true", help="print the response as JSON")
    p.add_argument("--cassette", choices=("off", "record", "replay"), default="off")
    return p


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="kewpie",
                                     description="Kewpie Crawler")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_collect(sub)
    _add_extract(sub)
    _add_doctor(sub)
    _add_fetch(sub)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "collect":
        from ..pipeline import collect
        summary = collect(
            sources=args.sources, out_dir=args.out, state=args.state,
            max_items=args.max_items, since_hours=args.since_hours,
            prefilter=args.prefilter, vocab=args.vocab,
            cassette_mode=args.cassette, max_tier=args.max_tier)
        print(json.dumps(summary, indent=2))
        return 0

    if args.command == "extract":
        from ..pipeline import extract
        summary = extract(vocab=args.vocab, raw_dir=args.raw_dir,
                          out_dir=args.out, since_days=args.since_days)
        print(json.dumps(summary, indent=2))
        return 0

    if args.command == "doctor":
        from . import doctor
        return doctor.run(reflector=args.reflector)

    if args.command == "fetch":
        return _run_fetch(args)

    parser.error(f"unknown command {args.command}")
    return 2


def _run_fetch(args) -> int:
    from ..config.loader import state_dir
    from ..escalation.ladder import EscalatingFetcher

    st = state_dir(args.state)
    fetcher = EscalatingFetcher(cache_dir=st / "cache", cassette_mode=args.cassette,
                                state_dir=st)
    try:
        max_tier = None if args.tier == "auto" else args.tier
        result = fetcher.fetch(args.url, max_tier=max_tier)
    finally:
        fetcher.close()

    v = result.verdict
    print(f"tier={result.tier} status={result.status_code} "
          f"from_cache={result.from_cache} elapsed={result.elapsed_s:.2f}s")
    if v is not None:
        print(f"verdict: blocked={v.blocked} vendor={v.vendor} kind={v.kind} "
              f"evidence={v.evidence}")
    if args.json:
        try:
            print(json.dumps(result.json(), indent=2)[:4000])
        except Exception as e:  # noqa: BLE001
            print(f"(not JSON: {e})")
            print((result.text or "")[:2000])
    else:
        print("-" * 60)
        print((result.text or "")[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
