"""CLI: uv run python process_song.py "<youtube url | spotify url | search text>" [--cache DIR]"""
from __future__ import annotations

import argparse
import json
import logging
import time

from karaoke import resolver
from karaoke.cache import Cache
from karaoke.pipeline import process
from karaoke.tls import use_system_trust


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", help="omit with --restem-all")
    ap.add_argument("--restem-all", action="store_true", help="redo stems of every cached song (keeps lyrics)")
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--fast", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    use_system_trust()
    t = time.time()
    if args.restem_all:
        from karaoke.pipeline import restem

        cache = Cache(args.cache)
        for vid in cache.list_complete():
            m = restem(vid, cache, "fast" if args.fast else "quality")
            print(f"{vid}: {m['separator_model']} in {m['timings']['separate']}s — {m['title']}", flush=True)
        print(f"total {time.time() - t:.0f}s")
        return
    if not args.input:
        ap.error("input is required unless --restem-all")
    vid = resolver.resolve(args.input)
    print(f"resolved -> {vid}")
    meta = process(vid, Cache(args.cache), status=lambda s, p=None: print(f"  {s}" + (f" {p:.0%}" if p else "")), mode="fast" if args.fast else "quality")
    print(json.dumps({k: meta[k] for k in ("title", "duration", "language", "lyrics_mode", "lyrics_source", "lyrics_offset", "align_prob", "timings")}, ensure_ascii=False, indent=2))
    print(f"total {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
