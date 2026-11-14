"""Update POT/PO, check translator readiness, or compile runtime resources."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .gettext_catalogs import check_freshness, save_catalogs, updated_catalogs, validate_catalogs
from .translation_build import prepare_runtime


ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="WinZapp gettext translation workflow")
    parser.add_argument("command", choices=("update", "check", "compile"))
    parser.add_argument("--catalog-dir", type=Path, default=ROOT / "translations")
    parser.add_argument("--mo-dir", type=Path, help="Compiled destination; default client/languages")
    parser.add_argument("--allow-incomplete", action="store_true",
                        help="Check template/syntax while translations are in progress; never compile")
    args = parser.parse_args(argv)
    if args.allow_incomplete and args.command != "check":
        parser.error("--allow-incomplete is only valid with check")
    try:
        catalogs = updated_catalogs(ROOT, args.catalog_dir)
        if args.command == "update":
            validate_catalogs(catalogs, complete=False)
            save_catalogs(args.catalog_dir, catalogs)
        else:
            check_freshness(args.catalog_dir, catalogs)
            validate_catalogs(catalogs, complete=not args.allow_incomplete)
            if args.command == "compile":
                prepare_runtime(ROOT, args.mo_dir, folder=args.catalog_dir)
    except (OSError, ValueError, SyntaxError) as exc:
        print(f"Translation catalogs: {exc}", file=sys.stderr)
        return 1
    pending = sum(len(c.untranslated_entries()) + len(c.fuzzy_entries())
                  for p, c in catalogs.items() if p.suffix == ".po")
    print(f"Translation catalogs: {args.command} OK ({len(catalogs) - 1} locales; {pending} pending)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
