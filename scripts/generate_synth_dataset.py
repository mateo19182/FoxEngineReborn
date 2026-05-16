#!/usr/bin/env python3
"""Generate synthetic lead files (CSV, JSONL, or two-column email/password CSV)."""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

DOMAINS = ("example.com", "example.org", "test.invalid")


def rand_email(i: int, rng: random.Random) -> str:
    return f"user{i:08d}@{rng.choice(DOMAINS)}".lower()


def rand_phone(i: int, rng: random.Random) -> str:
    n = 2000000000 + (i % 799_999_999)
    return f"+1{n:010d}"


def row_full(i: int, rng: random.Random) -> dict[str, object]:
    return {
        "email": rand_email(i, rng),
        "phone": rand_phone(i, rng),
        "username": f"usr{i}",
        "id_card": "",
        "full_name": f"Person {i}",
        "city": rng.choice(("NYC", "LA", "Chicago", "Miami")),
        "country": "US",
        "password": f"pw{i % 10000}",
        "extras": {"source": "synth", "idx": str(i)},
    }


def row_minimal(i: int, rng: random.Random) -> dict[str, object]:
    return {"email": rand_email(i, rng)}


def write_csv(path: Path, rows: int, rng: random.Random, profile: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pick = row_full if profile == "full" else row_minimal
    sample = pick(0, rng)
    fieldnames = list(sample.keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for i in range(rows):
            r = pick(i, rng)
            if "extras" in r and isinstance(r["extras"], dict):
                r = dict(r)
                r["extras"] = json.dumps(r["extras"])
            w.writerow(r)


def write_jsonl(path: Path, rows: int, rng: random.Random, profile: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pick = row_full if profile == "full" else row_minimal
    with path.open("w", encoding="utf-8") as f:
        for i in range(rows):
            f.write(json.dumps(pick(i, rng), sort_keys=True) + "\n")


def write_csv_twocol(path: Path, rows: int, rng: random.Random) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["email", "password"])
        for i in range(rows):
            w.writerow([rand_email(i, rng), f"s{rng.randint(0, 99999):05d}"])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rows", type=int, required=True, help="Number of records")
    p.add_argument(
        "--format",
        choices=("csv", "jsonl", "csv_twocol"),
        required=True,
        help="csv / jsonl use --profile; csv_twocol writes email,password",
    )
    p.add_argument("--output", type=Path, required=True, help="Output file path")
    p.add_argument(
        "--profile",
        choices=("full", "minimal"),
        default="full",
        help="Row shape for csv and jsonl",
    )
    p.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    args = p.parse_args()
    if args.rows < 1:
        p.error("--rows must be >= 1")
    rng = random.Random(args.seed)
    if args.format == "csv":
        write_csv(args.output, args.rows, rng, args.profile)
    elif args.format == "jsonl":
        write_jsonl(args.output, args.rows, rng, args.profile)
    else:
        write_csv_twocol(args.output, args.rows, rng)
    print(f"wrote {args.rows} rows to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
