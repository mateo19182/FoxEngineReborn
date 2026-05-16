#!/usr/bin/env python3
"""Drive FoxEngine ingest/export jobs over HTTP and print timing + job stats.

Requires API + worker running (Procrastinate jobs must execute).

  cd backend && uv run python ../scripts/benchmark_jobs.py ingest \\
    --rows 5000 --username admin --password PASS
  cd backend && uv run python ../scripts/benchmark_jobs.py export \\
    --dsl 'country:US' --username admin --password PASS
  cd backend && uv run python ../scripts/benchmark_jobs.py run \\
    --rows 10000 --tag-names mybench --username admin --password PASS

Auth: --token (Bearer JWT or API key) or --username + --password.
Env: FOXENGINE_BENCHMARK_BASE_URL, FOXENGINE_BENCHMARK_TOKEN,
FOXENGINE_BENCHMARK_USERNAME, FOXENGINE_BENCHMARK_PASSWORD.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _synth_script() -> Path:
    return Path(__file__).resolve().parent / "generate_synth_dataset.py"


def _strip_api_base(url: str) -> str:
    return url.rstrip("/")


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(client: httpx.Client, base: str, username: str, password: str) -> str:
    r = client.post(f"{base}/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token")
    if not isinstance(token, str):
        raise RuntimeError("login response missing access_token")
    return token


async def _login_async(client: httpx.AsyncClient, base: str, username: str, password: str) -> str:
    r = await client.post(f"{base}/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token")
    if not isinstance(token, str):
        raise RuntimeError("login response missing access_token")
    return token


def _poll_job(
    client: httpx.Client,
    base: str,
    token: str,
    job_id: str,
    *,
    interval: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout
    last: dict[str, Any] = {}
    while time.perf_counter() < deadline:
        r = client.get(f"{base}/jobs/{job_id}", headers=_auth_headers(token))
        r.raise_for_status()
        last = r.json()
        state = last.get("state")
        if state in ("done", "failed"):
            return last
        time.sleep(interval)
    raise TimeoutError(
        f"job {job_id} not terminal within {timeout}s (last state={last.get('state')!r})"
    )


def _generate_synth(
    out: Path,
    rows: int,
    fmt: str,
    profile: str,
    seed: int | None,
) -> None:
    cmd = [
        sys.executable,
        str(_synth_script()),
        "--rows",
        str(rows),
        "--format",
        fmt,
        "--output",
        str(out),
        "--profile",
        profile,
    ]
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
    subprocess.run(cmd, check=True)


def _bench_ingest(
    client: httpx.Client,
    base: str,
    token: str,
    path: Path,
    *,
    ingest_format: str,
    tag_names: str,
    poll_interval: float,
    poll_timeout: float,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    with path.open("rb") as fh:
        r = client.post(
            f"{base}/ingest/file",
            headers=_auth_headers(token),
            files={"file": (path.name, fh, "application/octet-stream")},
            data={
                "format": ingest_format,
                "tag_names": tag_names,
                "merge_archive": "false",
            },
        )
    r.raise_for_status()
    body = r.json()
    t_after_http = time.perf_counter()
    job_id = body.get("job_id")
    if not isinstance(job_id, str):
        items = body.get("items")
        if isinstance(items, list) and items:
            job_id = items[0].get("job_id")  # type: ignore[union-attr]
    if not isinstance(job_id, str):
        raise RuntimeError(f"unexpected ingest response: {body!r}")
    job = _poll_job(
        client,
        base,
        token,
        job_id,
        interval=poll_interval,
        timeout=poll_timeout,
    )
    t1 = time.perf_counter()
    return {
        "kind": "ingest",
        "job_id": job_id,
        "upload_and_queue_s": t_after_http - t0,
        "queue_through_done_s": t1 - t_after_http,
        "total_s": t1 - t0,
        "http_status": r.status_code,
        "job": job,
    }


def _bench_export(
    client: httpx.Client,
    base: str,
    token: str,
    dsl: str,
    export_format: str,
    *,
    poll_interval: float,
    poll_timeout: float,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    r = client.post(
        f"{base}/export",
        headers=_auth_headers(token),
        json={"dsl": dsl, "format": export_format},
    )
    r.raise_for_status()
    body = r.json()
    t_after_http = time.perf_counter()
    job_id = body.get("job_id")
    if not isinstance(job_id, str):
        raise RuntimeError(f"unexpected export response: {body!r}")
    job = _poll_job(
        client,
        base,
        token,
        job_id,
        interval=poll_interval,
        timeout=poll_timeout,
    )
    t1 = time.perf_counter()
    return {
        "kind": "export",
        "job_id": job_id,
        "dsl": dsl,
        "export_format": export_format,
        "queue_and_create_s": t_after_http - t0,
        "queue_through_done_s": t1 - t_after_http,
        "total_s": t1 - t0,
        "http_status": r.status_code,
        "job": job,
    }


def _add_auth(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("auth")
    g.add_argument(
        "--base-url",
        default=os.environ.get("FOXENGINE_BENCHMARK_BASE_URL", "http://127.0.0.1:8000/api"),
        help="API prefix including /api (env FOXENGINE_BENCHMARK_BASE_URL)",
    )
    g.add_argument(
        "--token",
        default=os.environ.get("FOXENGINE_BENCHMARK_TOKEN"),
        help="Bearer token",
    )
    g.add_argument("--username", default=os.environ.get("FOXENGINE_BENCHMARK_USERNAME"))
    g.add_argument("--password", default=os.environ.get("FOXENGINE_BENCHMARK_PASSWORD"))
    g.add_argument(
        "--insecure",
        action="store_true",
        help="disable TLS verification (for dev HTTPS)",
    )


def _resolve_token(args: argparse.Namespace, client: httpx.Client, base: str) -> str:
    if args.token:
        return args.token
    if args.username and args.password:
        return _login(client, base, args.username, args.password)
    raise SystemExit("provide --token or both --username and --password (or matching env vars)")


async def _resolve_token_async(
    args: argparse.Namespace,
    client: httpx.AsyncClient,
    base: str,
) -> str:
    if args.token:
        return args.token
    if args.username and args.password:
        return await _login_async(client, base, args.username, args.password)
    raise SystemExit("provide --token or both --username and --password (or matching env vars)")


def _client_kwargs(args: argparse.Namespace, timeout: float) -> dict[str, Any]:
    return {"timeout": httpx.Timeout(timeout), "verify": not args.insecure}


def cmd_ingest(args: argparse.Namespace) -> int:
    base = _strip_api_base(args.base_url)
    timeout = max(args.poll_timeout, args.upload_timeout)
    gen_path: Path | None = None
    try:
        if args.file:
            path = Path(args.file).resolve()
        else:
            if args.rows is None:
                raise SystemExit(
                    "ingest: pass --file or --rows (synthetic data is generated automatically)"
                )
            ext = "csv" if args.generate_format == "csv" else "jsonl"
            gen_path = Path(args.tmp_dir) / f"foxbench-ingest-{os.getpid()}.{ext}"
            _generate_synth(gen_path, args.rows, args.generate_format, args.profile, args.seed)
            path = gen_path

        with httpx.Client(**_client_kwargs(args, timeout=timeout)) as client:
            token = _resolve_token(args, client, base)
            out = _bench_ingest(
                client,
                base,
                token,
                path,
                ingest_format=args.ingest_format,
                tag_names=args.tag_names,
                poll_interval=args.poll_interval,
                poll_timeout=args.poll_timeout,
            )
    finally:
        if gen_path is not None and gen_path.is_file() and not args.keep_tmp:
            gen_path.unlink(missing_ok=True)

    _print_result(out, args.compact_json)
    job = out["job"]
    return 0 if job.get("state") == "done" else 1


def cmd_export(args: argparse.Namespace) -> int:
    base = _strip_api_base(args.base_url)
    timeout = max(args.poll_timeout, 120.0)

    def one_run() -> dict[str, Any]:
        with httpx.Client(**_client_kwargs(args, timeout=timeout)) as client:
            token = _resolve_token(args, client, base)
            return _bench_export(
                client,
                base,
                token,
                args.dsl,
                args.export_format,
                poll_interval=args.poll_interval,
                poll_timeout=args.poll_timeout,
            )

    if args.parallel <= 1:
        out = one_run()
        results = [out]
    else:

        async def arun() -> list[dict[str, Any]]:
            async with httpx.AsyncClient(**_client_kwargs(args, timeout=timeout)) as client:
                token = await _resolve_token_async(args, client, base)

                async def one() -> dict[str, Any]:
                    t0 = time.perf_counter()
                    r = await client.post(
                        f"{base}/export",
                        headers=_auth_headers(token),
                        json={"dsl": args.dsl, "format": args.export_format},
                    )
                    r.raise_for_status()
                    body = r.json()
                    t_after_http = time.perf_counter()
                    job_id = body.get("job_id")
                    if not isinstance(job_id, str):
                        raise RuntimeError(f"unexpected export response: {body!r}")

                    deadline = time.perf_counter() + args.poll_timeout
                    last: dict[str, Any] = {}
                    while time.perf_counter() < deadline:
                        jr = await client.get(
                            f"{base}/jobs/{job_id}",
                            headers=_auth_headers(token),
                        )
                        jr.raise_for_status()
                        last = jr.json()
                        if last.get("state") in ("done", "failed"):
                            break
                        await asyncio.sleep(args.poll_interval)
                    else:
                        raise TimeoutError(
                            f"job {job_id} not terminal within {args.poll_timeout}s "
                            f"(last state={last.get('state')!r})"
                        )
                    t1 = time.perf_counter()
                    return {
                        "kind": "export",
                        "job_id": job_id,
                        "dsl": args.dsl,
                        "export_format": args.export_format,
                        "queue_and_create_s": t_after_http - t0,
                        "queue_through_done_s": t1 - t_after_http,
                        "total_s": t1 - t0,
                        "http_status": r.status_code,
                        "job": last,
                    }

                return await asyncio.gather(*[one() for _ in range(args.parallel)])

        results = asyncio.run(arun())

    bundle = {
        "kind": "export_parallel" if args.parallel > 1 else "export",
        "parallel": args.parallel,
        "runs": results,
    }
    _print_result(bundle, args.compact_json)
    failed = sum(1 for r in results if r["job"].get("state") != "done")
    return 1 if failed else 0


def cmd_run(args: argparse.Namespace) -> int:
    """ingest synthetic (or file) with a tag, then export rows with that tag."""
    base = _strip_api_base(args.base_url)
    timeout = max(args.poll_timeout, args.upload_timeout, 120.0)
    gen_path: Path | None = None
    try:
        if args.file:
            path = Path(args.file).resolve()
        else:
            if args.rows is None:
                raise SystemExit("run: pass --file or --rows with generate options")
            ext = "csv" if args.generate_format == "csv" else "jsonl"
            gen_path = Path(args.tmp_dir) / f"foxbench-run-{os.getpid()}.{ext}"
            _generate_synth(gen_path, args.rows, args.generate_format, args.profile, args.seed)
            path = gen_path

        with httpx.Client(**_client_kwargs(args, timeout=timeout)) as client:
            token = _resolve_token(args, client, base)
            ing = _bench_ingest(
                client,
                base,
                token,
                path,
                ingest_format=args.ingest_format,
                tag_names=args.tag_names,
                poll_interval=args.poll_interval,
                poll_timeout=args.poll_timeout,
            )
            if ing["job"].get("state") != "done":
                _print_result({"ingest": ing, "export": None}, args.compact_json)
                return 1
            tags = [x.strip() for x in args.tag_names.split(",") if x.strip()]
            if not tags:
                raise SystemExit("run: --tag-names must include at least one non-empty tag")
            dsl = f"tag:{tags[0]}"
            exp = _bench_export(
                client,
                base,
                token,
                dsl,
                args.export_format,
                poll_interval=args.poll_interval,
                poll_timeout=args.poll_timeout,
            )
    finally:
        if gen_path is not None and gen_path.is_file() and not args.keep_tmp:
            gen_path.unlink(missing_ok=True)

    bundle = {"ingest": ing, "export": exp}
    _print_result(bundle, args.compact_json)
    ok = ing["job"].get("state") == "done" and exp["job"].get("state") == "done"
    return 0 if ok else 1


def _print_result(obj: dict[str, Any], compact: bool) -> None:
    if compact:
        print(json.dumps(obj, separators=(",", ":")))
    else:
        print(json.dumps(obj, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    _add_auth(common)
    common.add_argument("--poll-interval", type=float, default=0.5, help="seconds between job GETs")
    common.add_argument(
        "--poll-timeout",
        type=float,
        default=3600.0,
        help="max seconds to wait for job",
    )
    common.add_argument(
        "--compact-json",
        action="store_true",
        help="single-line JSON (default is indented)",
    )
    common.add_argument(
        "--tmp-dir",
        default=str(_repo_root() / ".benchmark_tmp"),
        help="temp directory for generated files",
    )
    common.add_argument("--keep-tmp", action="store_true", help="do not delete generated files")

    pi = sub.add_parser(
        "ingest",
        parents=[common],
        help="upload one file and wait for ingest_file job",
    )
    pi.add_argument("--file", help="path to CSV/JSONL (else use --rows)")
    pi.add_argument("--rows", type=int, help="with --generate-format: synthetic row count")
    pi.add_argument(
        "--generate-format",
        choices=("csv", "jsonl"),
        default="csv",
        help="when generating without --file",
    )
    pi.add_argument("--profile", choices=("full", "minimal"), default="full")
    pi.add_argument("--seed", type=int, default=None)
    pi.add_argument(
        "--ingest-format",
        default="auto",
        help="form field format= (auto, jsonl, csv, combo)",
    )
    pi.add_argument("--tag-names", default="", help="comma-separated tags (optional)")
    pi.add_argument(
        "--upload-timeout",
        type=float,
        default=600.0,
        help="HTTP timeout for upload POST",
    )
    pi.set_defaults(func=cmd_ingest)

    pe = sub.add_parser("export", parents=[common], help="queue export job and wait until done")
    pe.add_argument("--dsl", required=True, help='e.g. country:US or tag:mytag')
    pe.add_argument("--export-format", choices=("csv", "jsonl"), default="csv")
    pe.add_argument("--parallel", type=int, default=1, help="concurrent export jobs (async)")
    pe.set_defaults(func=cmd_export)

    pr = sub.add_parser(
        "run",
        parents=[common],
        help="ingest with a tag then export tag:<first tag> (isolated pipeline bench)",
    )
    pr.add_argument("--file")
    pr.add_argument("--rows", type=int)
    pr.add_argument("--generate-format", choices=("csv", "jsonl"), default="csv")
    pr.add_argument("--profile", choices=("full", "minimal"), default="full")
    pr.add_argument("--seed", type=int, default=None)
    pr.add_argument("--ingest-format", default="auto")
    pr.add_argument(
        "--tag-names",
        default="foxbench",
        help="comma-separated; export uses tag:<first name>",
    )
    pr.add_argument("--export-format", choices=("csv", "jsonl"), default="csv")
    pr.add_argument("--upload-timeout", type=float, default=600.0)
    pr.set_defaults(func=cmd_run)

    args = p.parse_args()
    Path(args.tmp_dir).mkdir(parents=True, exist_ok=True)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
