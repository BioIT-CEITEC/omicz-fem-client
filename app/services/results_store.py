#!/usr/bin/env python3
"""Client for the omicz result storage service, and the run-id ledger that addresses it.

A WES run's outputs never land on this node: the executor tars them and PUTs the archive to
the result service under the run's own id (`omiczwes/executor.py:_results_url` →
`PUT /data/{run_id}`). So `list_files` and `send_files` read a *remote* archive, not the
local sandbox, and the only thing the node still keeps on disk is what the orchestrator
pushed in with `receive_files` — the workflow attachments, which are inputs.

Addressing those archives needs the run ids of an execution, and the orchestrator's file
actions carry none: `run_tool` calls them with `task_info=None`, so `%%EXTERNAL_ID%%` cannot
be resolved for them the way it is for `run_status`. The submitting call is the only place
that ever sees the id, so it appends it to a ledger in the execution's sandbox folder and
the file actions read it back.
"""
import json
import os
import tarfile
import tempfile

import requests

LEDGER_NAME = ".wes_runs.json"
CHUNK_BYTES = 1 << 20


class ResultNotFound(Exception):
    """The result service has no archive for this run id."""


# --------------------------------------------------------------------------- ledger


def ledger_path(sandbox_fem, user_id, execution_id):
    return os.path.join(sandbox_fem, str(user_id), str(execution_id), LEDGER_NAME)


def recorded_runs(sandbox_fem, user_id, execution_id):
    """The execution's runs, oldest first. An execution that never submitted has none."""
    if not sandbox_fem or not user_id or not execution_id:
        return []
    try:
        with open(ledger_path(sandbox_fem, user_id, execution_id), "r") as fh:
            entries = json.load(fh)
    except (OSError, ValueError):
        return []
    return [e for e in entries if isinstance(e, dict) and e.get("run_id")]


def record_run(sandbox_fem, user_id, execution_id, run_id, task_id=""):
    """Append a run id to the execution's ledger, keeping submission order.

    Re-submitting the same run id is a no-op rather than a duplicate: the orchestrator
    retries a task without the node getting to forget the first attempt.
    """
    if not (sandbox_fem and user_id and execution_id and run_id):
        return
    path = ledger_path(sandbox_fem, user_id, execution_id)
    entries = recorded_runs(sandbox_fem, user_id, execution_id)
    if any(e["run_id"] == run_id for e in entries):
        return
    entries.append({"run_id": run_id, "task_id": task_id})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(entries, fh)


# --------------------------------------------------------------------------- archives


def safe_member_name(name):
    """Archive member names are written to disk by whoever receives this payload.

    An absolute path or a `..` segment would escape the directory they are unpacked into,
    so such a member is not listed and not sent at all.
    """
    parts = name.split("/") if name else []
    if not parts or any(part in ("", ".", "..") for part in parts):
        return None
    return name


def _download(results_url, run_id, passports, timeout):
    """Spool `{run_id}.tar.gz` to a temp file and hand back an open handle.

    The download is a POST because that is where the result service takes its passports
    (`POST /data/{run_id}`, body `{"passports": [...]}`); with `VISA_CHECK_ENABLED=false`
    it reads none and an empty list is accepted. It is streamed to disk rather than held in
    memory: a stored archive may be tens of gigabytes.
    """
    url = f"{results_url.rstrip('/')}/data/{run_id}"
    spool = tempfile.TemporaryFile()
    try:
        with requests.post(
            url,
            json={"passports": list(passports or [])},
            stream=True,
            timeout=timeout,
        ) as response:
            if response.status_code == 404:
                raise ResultNotFound(f"no stored result for run {run_id}")
            response.raise_for_status()
            for chunk in response.iter_content(CHUNK_BYTES):
                spool.write(chunk)
    except BaseException:
        spool.close()
        raise
    spool.seek(0)
    return spool


def read_members(results_url, run_id, passports, timeout, match=None, with_content=True):
    """Members of a run's result archive as `(archive_path, bytes | None)`.

    `match(run_id, archive_path)` selects; without it every regular file is returned. It
    takes the run id because the caller's names for a member may carry it — two runs of one
    execution can produce the same file — and it is a predicate rather than a name because
    the caller decides what a member is called on the way out.
    """
    spool = _download(results_url, run_id, passports, timeout)
    try:
        with tarfile.open(fileobj=spool, mode="r:gz") as archive:
            members = []
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                name = safe_member_name(member.name)
                if name is None:
                    continue
                if match and not match(run_id, name):
                    continue
                content = None
                if with_content:
                    handle = archive.extractfile(member)
                    content = handle.read() if handle else b""
                members.append((name, content))
            return members
    finally:
        spool.close()


def execution_members(
    results_url, sandbox_fem, user_id, execution_id, passports, timeout,
    match=None, with_content=True,
):
    """Every stored member of every run of one execution, plus the runs that stored nothing.

    Returned as `(run_id, archive_path, bytes | None)`. The run id travels with the member
    because an execution can hold several runs carrying the same file name — a resubmitted
    task does — and it is the only thing that tells two such members apart; what the file is
    finally called is the caller's business.

    A run with no archive is not an error: a workflow that declares no outputs, or a run
    that declares no datasets, uploads nothing (`omiczwes/executor.py:store_outputs`), and
    an execution may still have other runs that did store results.
    """
    runs = recorded_runs(sandbox_fem, user_id, execution_id)
    if not runs:
        raise FileNotFoundError(
            f"no WES run is recorded for execution {execution_id}; nothing was submitted "
            "from this node"
        )

    members = []
    empty = []
    for entry in runs:
        run_id = entry["run_id"]
        try:
            found = read_members(results_url, run_id, passports, timeout, match, with_content)
        except ResultNotFound:
            empty.append(run_id)
            continue
        members.extend((run_id, name, content) for name, content in found)
    return members, empty


def passports_from(values):
    """Passports for the result service, from the request and from nowhere else.

    The only passport a download may use is the one the orchestrator sent with the
    request: it names the caller, and the result service audits the download under that
    subject. A passport configured on the node would answer every caller's request with
    one identity, which is an impersonation, and it would outlive the request that
    justified it.
    """
    return [v for v in (values or []) if v]


def results_url_from(value):
    url = (value or "").strip() or os.environ.get("FEM_RESULTS_URL", "").strip()
    if not url:
        raise ValueError(
            "result service address is unset: pass --results_url or set FEM_RESULTS_URL"
        )
    return url
