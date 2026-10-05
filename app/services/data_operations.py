import os
import logging
import base64
from config import config
import json
import argparse
import sys
from fnmatch import fnmatch

from services.results_store import execution_members, passports_from, results_url_from

DEFAULT_TIMEOUT = 300.0


def _rename_rules():
    """`FEM_RESULT_NAMES`: `{"<glob over the archive path>": "<delivered file name>"}`.

    A workflow names its outputs for itself (`federated_results/round_0_counts.csv`); the
    federation expects the deliverable under a name of its own (`goe-counts.CZE.csv`).
    The mapping is deployment configuration, not something either end can be asked to
    change, and it is a table rather than one name because a workflow has more than one
    deliverable — round 0 publishes counts, later rounds publish a passing list.
    """
    raw = os.environ.get("FEM_RESULT_NAMES", "").strip()
    if not raw:
        return {}
    try:
        rules = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"FEM_RESULT_NAMES is not valid JSON: {exc}") from None
    if not isinstance(rules, dict):
        raise ValueError("FEM_RESULT_NAMES must be an object of glob -> file name")
    return rules


def _renamed(archive_path):
    """The rename rule's name for a member, before the node prefix, or `None` if no rule
    matches."""
    for pattern, replacement in _rename_rules().items():
        if fnmatch(archive_path, pattern) or fnmatch(os.path.basename(archive_path), pattern):
            try:
                return replacement.format(node=config.node_name)
            except (KeyError, IndexError) as exc:
                # A bare KeyError('site') reaches the orchestrator as {"error": "'site'"},
                # which says nothing about where it came from.
                named = f"{{{exc.args[0]}}}" if isinstance(exc, KeyError) else "a positional {}"
                raise ValueError(
                    f"FEM_RESULT_NAMES rule {pattern!r} -> {replacement!r} uses unknown "
                    f"placeholder {named}; only {{node}} is available"
                ) from None
    return None


def _member_name(archive_path):
    """A result file's own name — what `list_files` shows and `send_files --file` takes.

    No node prefix: the reference node lists `goe-counts.CZE.csv` and is then asked for
    exactly that, and only the answer carries the prefix. The archive path is flattened to
    one segment because the receiving end creates no parent directories.
    """
    return _renamed(archive_path) or "_".join(archive_path.split("/"))


def _qualified(name, run_id):
    """`goe-counts.CZE.csv` + run -> `goe-counts.CZE.<run_id>.csv`, extension kept last."""
    stem, ext = os.path.splitext(name)
    return f"{stem}.{run_id}{ext}"


def _member_names(members, requested=None):
    """Names for `(run_id, archive_path, content)` members, kept distinct.

    Two runs of one execution produce the same file name — a resubmitted task does, and a
    rename rule collapses differing paths onto one name on purpose. Those, and only those,
    are qualified with the run id; a name that occurs once is left exactly as named. A
    member asked for by its qualified name keeps it, so what was listed is what comes back
    even though the request narrowed the collision away.
    """
    names = [_member_name(path) for _, path, _ in members]
    repeated = {name for name in names if names.count(name) > 1}
    unique = []
    for (run_id, _, _), name in zip(members, names):
        qualified = _qualified(name, run_id)
        if name in repeated or requested in (qualified, _node_prefixed(qualified)):
            name = qualified
        unique.append(name)
    return unique


def _matcher(wanted):
    """Select one member by any name it is known under: its own name, the name it is
    delivered under, either of those qualified by the run id, the archive path, or the bare
    file name."""
    if not wanted:
        return None

    def match(run_id, path):
        name = _member_name(path)
        qualified = _qualified(name, run_id)
        return wanted in (
            path,
            os.path.basename(path),
            name,
            _node_prefixed(name),
            qualified,
            _node_prefixed(qualified),
        )

    return match


def _tree_from_names(names):
    """The directory tree shape the orchestrator already parses: nested dicts of "files"."""
    tree = {}
    for name in names:
        parts = name.split("/")
        current = tree
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current.setdefault("files", []).append(parts[-1])
    return tree


def _dataset_tree(sub_path):
    """`/data` answered from `config.datasets`, not from a directory.

    The datasets are mounted by the WES workers, never by this container, so there is
    nothing here to walk: what the federation may see is what the node declares.
    """
    datasets = getattr(config, "datasets", None) or {}
    if not sub_path:
        return {name: {"files": list(files)} for name, files in datasets.items()}

    dataset, _, inner = sub_path.partition("/")
    if dataset not in datasets:
        raise FileNotFoundError(f"Dataset {dataset!r} is not available on this node")
    if inner:
        raise ValueError(
            f"{dataset!r} has no subdirectories here: a dataset's layout is known to the "
            "WES workers that mount it, not to this node"
        )
    return {"files": list(datasets[dataset])}


def list_files(user_id, execution_id, path, sandbox_fem, results_url=None, passports=None,
               timeout=DEFAULT_TIMEOUT):
    """List an execution's results, or the datasets this node offers.

    Neither is a directory on this node any more. A run's outputs are archived by the WES
    executor and stored in the result service, so `/sandbox` is an archive's member list;
    the datasets are mounted by the WES workers, so `/data` is the `config.datasets`
    declaration.
    """
    try:
        path = os.path.normpath(path)

        if path.startswith("/sandbox"):
            if not user_id or not execution_id:
                raise ValueError("user_id and execution_id are required for /sandbox paths.")
            members, empty = execution_members(
                results_url_from(results_url),
                sandbox_fem,
                str(user_id),
                str(execution_id),
                passports_from(passports),
                timeout,
                with_content=False,
            )
            if empty:
                logging.info(f"Runs with no stored result: {', '.join(empty)}")
            # The listed name is the name `send_files --file` is then called with, which is
            # the file's own name, not the prefixed one the answer carries.
            return _tree_from_names(_member_names(members))

        if path.startswith("/data"):
            return _dataset_tree(path[5:].strip("/"))

        raise ValueError("Path must start with /sandbox or /data.")

    except Exception as e:
        return {"error": str(e)}


def send_files_as_json(user_id: str, execution_id: str, sandbox_fem: str, file: str = None,
                       results_url=None, passports=None, timeout=DEFAULT_TIMEOUT) -> str:
    """
    Prepares an execution's results as the base64 payload the orchestrator expects over
    RabbitMQ.

    Results come from the result service: the WES executor uploaded them there as one
    `.tar.gz` per run, and the members of those archives are the files sent back. `file`
    selects a single member by any name it is listed under; without it the whole execution
    is sent. A `/data` path has nothing to send — those datasets never reach this node.

    Returns:
        dict: {"base_dir": ..., "files": [{"relative_path", "content_b64"}, ...]}
    """

    try:

        if execution_id:
            if not user_id:
                raise ValueError("user_id and execution_id are required for /sandbox paths.")

            wanted = file if file and file != "None" else None
            members, empty = execution_members(
                results_url_from(results_url),
                sandbox_fem,
                str(user_id),
                str(execution_id),
                passports_from(passports),
                timeout,
                match=_matcher(wanted),
            )
            if empty:
                logging.info(f"Runs with no stored result: {', '.join(empty)}")
            if not members:
                raise FileNotFoundError(
                    f"No stored result file matches {wanted!r} in execution {execution_id}"
                    if wanted
                    else f"Execution {execution_id} has no stored result files"
                )

            files_payload = [
                {
                    "relative_path": _node_prefixed(name),
                    "content_b64": base64.b64encode(content).decode("utf-8"),
                }
                for name, (_, _, content) in zip(_member_names(members, wanted), members)
            ]

            # `base_dir` is the execution id, as the reference deployment delivers it. The
            # results of one execution are one folder on the orchestrator's side whether
            # they came from one run or several, and whether one file was named or all.
            return {"base_dir": str(execution_id), "files": files_payload}

        if file and file.startswith("/data"):
            # The datasets are mounted by the WES workers, not here, so this node has no
            # bytes to send. Answered as an error rather than an empty payload: a caller
            # that asked for a dataset file needs to know it will never arrive, and a node
            # that shipped controlled-access data back to the orchestrator would be a
            # worse answer than a refusal.
            raise ValueError(
                f"{file!r} is a dataset path: datasets stay on the WES workers and are "
                "never read by this node. list_files /data names what is available; a "
                "workflow reads it through the input_dir the catalogue injects"
            )

        raise ValueError("Path must start with /sandbox or /data.")

    except Exception as e:
        return {"error": str(e)}


def _node_prefixed(relative_path):
    """Stamp the node name onto the file name: results of one execution arrive at the
    orchestrator from several nodes and would otherwise overwrite each other."""
    dir_part, file_part = os.path.split(relative_path)
    return f"{dir_part}/{config.node_name}_{file_part}" if dir_part else f"{config.node_name}_{file_part}"


def receive_files(user_id: str, execution_id:str, incoming_files:list, sandbox_fem:str) -> dict:
    """
    Receives base64-encoded files and stores them on disk.
    Expected format:
        - list of files: [{"relative_path": ..., "content_b64": ...}, ...]

    This is the one data operation that still uses the local filesystem, and it is
    temporary storage: `<sandbox_fem>/<user_id>/<execution_id>` is the staging directory
    `services/wes_client.py:collect_attachments` reads, so a file pushed here is what gets
    sent to the WES as a `workflow_attachment` on the next `submit_run` for this execution.
    Nothing here is an output — those go to the result service.
    """

    if isinstance(incoming_files, str):
        incoming_files = json.loads(incoming_files)

    if not sandbox_fem:
        raise ValueError("Missing 'sandbox_fem' needed to store outputs")

    dest_dir = os.path.join(sandbox_fem, user_id, execution_id)

    try:
        # Build destination directory
        logging.info(f"Storing received file in: {dest_dir}")

        # Create directory if it doesn't exist
        os.makedirs(dest_dir, exist_ok=True)

    except Exception as e:
        logging.error(f"Could not create directory {dest_dir}: {e}")
        return {"error": str(e)}

    stored_files = []

    # Process each file entry
    for file_entry in incoming_files:
        try:
            file_name = file_entry.get("relative_path")
            content_b64 = file_entry.get("content_b64")

            if not file_name or not content_b64:
                raise ValueError("Missing 'relative_path' or 'content_b64' in a file entry")

            # Compute full storage path. A relative path may name a subdirectory, and it
            # comes from off-node, so it may not climb out of the staging directory either.
            dest_path = os.path.normpath(os.path.join(dest_dir, file_name))
            if os.path.commonpath((os.path.abspath(dest_dir), os.path.abspath(dest_path))) != os.path.abspath(dest_dir):
                raise ValueError(f"relative_path {file_name!r} escapes the execution folder")
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            # Decode Base64
            file_bytes = base64.b64decode(content_b64)

            # Write file to disk
            with open(dest_path, "wb") as f:
                f.write(file_bytes)

            logging.info(f"Stored file: {dest_path}")
            stored_files.append(dest_path)

        except Exception as e:
            logging.error(f"Error storing file {file_entry}: {e}")
            stored_files.append({"file_name": file_entry.get("file_name"), "error": str(e)})

    return {
        "status": "success",
        "files_stored": stored_files
    }


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Data operations CLI")

    # Command
    parser.add_argument("command", choices=[
        "list_files",
        "send_files",
        "receive_files"
    ])

    # All possible arguments (defined once)
    parser.add_argument("--user_id")
    parser.add_argument("--execution_id")
    parser.add_argument("--sandbox_fem")
    parser.add_argument("--path")
    parser.add_argument("--file")
    parser.add_argument("--incoming_files")
    parser.add_argument("--results_url", default="", help="result service base URL")
    parser.add_argument("--passport", action="append", default=[],
                        help="GA4GH passport for the result service; repeatable")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)

    args = parser.parse_args()

    try:
        if args.command == "list_files":
            result = list_files(
                args.user_id,
                args.execution_id,
                args.path,
                args.sandbox_fem,
                results_url=args.results_url,
                passports=args.passport,
                timeout=args.timeout,
            )

        elif args.command == "send_files":
            result = send_files_as_json(
                args.user_id,
                args.execution_id,
                args.sandbox_fem,
                args.file,
                results_url=args.results_url,
                passports=args.passport,
                timeout=args.timeout,
            )

        elif args.command == "receive_files":
            result = receive_files(
                args.user_id,
                args.execution_id,
                args.incoming_files,
                args.sandbox_fem
            )

        # Always output valid JSON to stdout
        print(json.dumps(result), flush=True)

        # If your function signals error via dict, exit non-zero
        if isinstance(result, dict) and "error" in result:
            sys.exit(1)
        else:
            sys.exit(0)

    except Exception as e:
        # Log to stderr (not stdout!)
        logging.exception("Unhandled error")

        error_output = {"error": str(e)}
        print(json.dumps(error_output), file=sys.stdout, flush=True)

        sys.exit(1)