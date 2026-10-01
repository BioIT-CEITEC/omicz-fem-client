#!/usr/bin/env python3
"""GA4GH WES 1.1 client for the FEM launcher.

The launcher config only selects an action and forwards placeholders; all policy lives in
the site workflow catalogue (default /app/config/wes-catalogue.json, override with
WES_CATALOGUE or --catalogue).

Every subcommand prints a single JSON object on stdout, which is what run_tool forwards to
the orchestrator. Reply shapes match the previous docker launcher so no orchestrator-side
change is needed:

    submit  -> {"external_id": "<run_id>"}                       (or a rejection object)
    status  -> {"external_id": ..., "state": ..., "logs": ...}
    report  -> {"external_id": ..., "status": ..., "exit_code": ..., ...}
    cancel  -> {"status": "cancelled", "external_id": ...}
    info    -> service-info summary

Exit codes: 0 for a successful call or a policy rejection (the rejection *is* the answer),
1 for transport/HTTP/configuration failures.
"""
import argparse
import json
import os
import sys

import requests

DEFAULT_CATALOGUE = os.environ.get("WES_CATALOGUE", "/app/config/wes-catalogue.json")


# --------------------------------------------------------------------------- catalogue


def load_catalogue(path):
    with open(path, "r") as fh:
        doc = json.load(fh)
    workflows = doc.get("workflows")
    if not isinstance(workflows, dict):
        raise ValueError(f"catalogue {path} has no 'workflows' object")
    return workflows


def lookup(workflows, image):
    entry = workflows.get(image)
    if entry is None:
        raise Rejected(f"image {image} is not in the site workflow catalogue")
    for required in ("workflow_url", "workflow_type", "workflow_type_version"):
        if not entry.get(required):
            raise Rejected(f"catalogue entry for {image} is missing '{required}'")
    return entry


class Rejected(Exception):
    """Policy refusal: answered to the orchestrator, never sent to the WES."""


# --------------------------------------------------------------------------- parameters


def parse_task_command(task_command):
    """Turn the rendered %%TASK_COMMAND%% into a flag dict.

    Supports '--flag value' and '--flag=value'; the leading program name is discarded
    because the registered workflow, not the task, decides what runs.
    """
    flags = {}
    pending = None
    for token in (task_command or "").split():
        if token.startswith("-"):
            if pending is not None:
                flags[pending] = True
            name = token.lstrip("-")
            if "=" in name:
                key, value = name.split("=", 1)
                flags[key] = value
                pending = None
            else:
                pending = name
        elif pending is not None:
            flags[pending] = token
            pending = None
    if pending is not None:
        flags[pending] = True
    return flags


def coerce(value, kind):
    if kind == "int":
        return int(float(value))
    if kind == "float":
        return float(value)
    if kind == "bool":
        return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
    return value


def build_params(entry, flags, context):
    """Rename, whitelist, type-coerce, then merge defaults and injected site values."""
    mapping = entry.get("param_map", {})
    named = {mapping.get(key, key): value for key, value in flags.items()}

    allowed = entry.get("allowed_params")
    if allowed is not None:
        extra = sorted(set(named) - set(allowed))
        if extra and entry.get("strict_params", False):
            raise Rejected("parameters not allowed for this workflow: " + ", ".join(extra))
        named = {k: v for k, v in named.items() if k in allowed}

    types = entry.get("param_types", {})
    typed = {}
    for key, value in named.items():
        try:
            typed[key] = coerce(value, types.get(key))
        except (TypeError, ValueError):
            raise Rejected(f"parameter {key}={value!r} is not a valid {types.get(key)}")

    injected = {k: context.get(v[1:-1].lower(), v) if v.startswith("%") and v.endswith("%") else v
                for k, v in entry.get("param_inject", {}).items()}

    params = dict(entry.get("param_defaults", {}))
    params.update(typed)
    params.update(injected)
    return params


def collect_attachments(entry, rundir):
    """Only whitelisted filenames, only those actually staged in the execution folder."""
    found = []
    for name in entry.get("attachments", []):
        path = os.path.join(rundir, name)
        if os.path.isfile(path):
            found.append((name, path))
    return found


# --------------------------------------------------------------------------- http


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


def wes_get(url, token, timeout):
    response = requests.get(url, headers=auth_headers(token), timeout=timeout)
    response.raise_for_status()
    return response.json()


# --------------------------------------------------------------------------- actions


def action_submit(args):
    workflows = load_catalogue(args.catalogue)
    entry = lookup(workflows, args.image)

    # %%sandbox_execution%% is unreliable here: run_tool only expands it to the remote
    # <root>/<user>/<execution> form when the command literally contains "curl -X".
    # --sandbox-remote is therefore the remote *root* and the per-run path is joined here.
    remote_rundir = os.path.join(args.sandbox_remote, args.user_id, args.execution_id)
    context = {
        "sandbox": remote_rundir,
        "sandbox_root": args.sandbox_remote,
        "data": args.data_remote,
        "execution_id": args.execution_id,
        "user_id": args.user_id,
        "task_id": args.task_id,
    }
    params = build_params(entry, parse_task_command(args.task_command), context)

    rundir = os.path.join(args.sandbox_local, args.user_id, args.execution_id)
    attachments = collect_attachments(entry, rundir)

    tags = {
        "fem_node": args.node,
        "fem_task_id": args.task_id,
        "fem_execution_id": args.execution_id,
        "fem_user_id": args.user_id,
        "fem_image": args.image,
    }
    tags.update(entry.get("tags", {}))

    form = {
        "workflow_url": entry["workflow_url"],
        "workflow_type": entry["workflow_type"],
        "workflow_type_version": entry["workflow_type_version"],
        "workflow_params": json.dumps(params),
        "tags": json.dumps(tags),
    }
    for optional in ("workflow_engine", "workflow_engine_version"):
        if entry.get(optional):
            form[optional] = entry[optional]
    if entry.get("workflow_engine_parameters"):
        form["workflow_engine_parameters"] = json.dumps(entry["workflow_engine_parameters"])

    files = [("workflow_attachment", (name, open(path, "rb"), "application/octet-stream"))
             for name, path in attachments]
    try:
        response = requests.post(
            f"{args.wes_url}/runs",
            headers=auth_headers(args.token),
            data=form,
            files=files or None,
            timeout=args.timeout,
        )
    finally:
        for _, handle in files:
            handle[1].close()

    response.raise_for_status()
    return {"external_id": response.json().get("run_id")}


def action_status(args):
    run = wes_get(f"{args.wes_url}/runs/{args.external_id}", args.token, args.timeout)
    logs = ""
    stdout_url = (run.get("run_log") or {}).get("stdout")
    if stdout_url:
        try:
            fetched = requests.get(stdout_url, headers=auth_headers(args.token), timeout=args.timeout)
            fetched.raise_for_status()
            logs = fetched.text
        except requests.RequestException as exc:
            logs = f"<could not fetch stdout: {exc}>"

    if args.sandbox_local and args.user_id and args.execution_id:
        rundir = os.path.join(args.sandbox_local, args.user_id, args.execution_id)
        try:
            os.makedirs(rundir, exist_ok=True)
            with open(os.path.join(rundir, f"{args.task_id}.log"), "w") as fh:
                fh.write(logs)
        except OSError as exc:
            print(f"could not write log file: {exc}", file=sys.stderr)

    return {"external_id": run.get("run_id", args.external_id), "state": run.get("state"), "logs": logs}


FAILED_STATES = {"EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED", "CANCELING", "PREEMPTED"}


def action_report(args):
    run = wes_get(f"{args.wes_url}/runs/{args.external_id}", args.token, args.timeout)
    run_log = run.get("run_log") or {}
    request = run.get("request") or {}
    state = run.get("state")

    elapsed = None
    start, stop = run_log.get("start_time"), run_log.get("end_time")
    if start and stop:
        try:
            from datetime import datetime

            fmt = "%Y-%m-%dT%H:%M:%S%z"
            parse = lambda value: datetime.strptime(value.replace("Z", "+0000"), fmt)
            elapsed = int((parse(stop) - parse(start)).total_seconds())
        except ValueError:
            elapsed = None

    return {
        "external_id": run.get("run_id", args.external_id),
        "status": state,
        "exit_code": run_log.get("exit_code"),
        "command": run_log.get("cmd"),
        "image": (request.get("tags") or {}).get("fem_image"),
        "workflow": request.get("workflow_url"),
        "start_time": start,
        "stop_time": stop,
        "elapsed_time_sec": elapsed,
        "error": state if state in FAILED_STATES else "",
        "host": {"server_name": args.wes_url},
        "parameters": request.get("workflow_params"),
        "outputs": run.get("outputs") or {},
        "task_logs_url": run.get("task_logs_url"),
    }


def action_cancel(args):
    response = requests.post(
        f"{args.wes_url}/runs/{args.external_id}/cancel",
        headers=auth_headers(args.token),
        timeout=args.timeout,
    )
    response.raise_for_status()
    return {"status": "cancelled", "external_id": response.json().get("run_id", args.external_id)}


def action_info(args):
    info = wes_get(f"{args.wes_url}/service-info", args.token, args.timeout)
    summary = {
        "supported_wes_versions": info.get("supported_wes_versions", []),
        "workflow_type_versions": info.get("workflow_type_versions", {}),
        "workflow_engine_versions": info.get("workflow_engine_versions", {}),
        "system_state_counts": info.get("system_state_counts", {}),
    }
    try:
        summary["registered_workflows"] = sorted(
            entry["workflow_url"] for entry in load_catalogue(args.catalogue).values()
        )
    except (OSError, ValueError) as exc:
        summary["registered_workflows"] = {"error": str(exc)}
    return summary


ACTIONS = {
    "submit": action_submit,
    "status": action_status,
    "report": action_report,
    "cancel": action_cancel,
    "info": action_info,
}


def build_parser():
    parser = argparse.ArgumentParser(description="GA4GH WES client for the FEM launcher")
    parser.add_argument("action", choices=sorted(ACTIONS))
    parser.add_argument("--wes-url", required=True, help="WES base URL, e.g. https://host/ga4gh/wes/v1")
    parser.add_argument("--token", default="")
    parser.add_argument("--catalogue", default=DEFAULT_CATALOGUE)
    parser.add_argument("--timeout", type=float, default=120.0)

    parser.add_argument("--image", help="submit: catalogue key")
    parser.add_argument("--task-command", default="", help="submit: rendered %%TASK_COMMAND%%")
    parser.add_argument("--external-id", help="status/report/cancel: WES run_id")

    parser.add_argument("--task-id", default="")
    parser.add_argument("--execution-id", default="")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--node", default="")
    parser.add_argument("--sandbox-local", default="", help="sandbox root inside this container")
    parser.add_argument("--sandbox-remote", default="", help="sandbox ROOT as the WES workers see it")
    parser.add_argument("--data-remote", default="", help="data path as the WES workers see it")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.action == "submit" and not args.image:
        print(json.dumps({"error": "--image is required for submit"}))
        return 1
    if args.action in ("status", "report", "cancel") and not args.external_id:
        print(json.dumps({"error": f"--external-id is required for {args.action}"}))
        return 1

    try:
        print(json.dumps(ACTIONS[args.action](args)))
        return 0
    except Rejected as exc:
        print(json.dumps({"external_id": "", "status": "rejected", "error": str(exc)}))
        return 0
    except requests.HTTPError as exc:
        body = exc.response.text[:2000] if exc.response is not None else ""
        code = exc.response.status_code if exc.response is not None else None
        print(json.dumps({"error": f"WES returned HTTP {code}", "body": body}))
        return 1
    except requests.RequestException as exc:
        print(json.dumps({"error": f"WES request failed: {exc}"}))
        return 1
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
