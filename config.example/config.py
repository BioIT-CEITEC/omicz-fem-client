"""FEM client configuration, mounted at /app/config and imported as `from config import config`.

Copy the directory this file lives in before editing it:

    cp -r config.example config

Everything that identifies this node — broker, credentials, queue name — comes from the
environment, which docker-compose.yml fills from .env. What is written out here is site
policy that no environment variable should be able to change silently: the datasets this
node offers, and the orchestrator's DB schema.

This is the same configuration `k8s/configmap.yaml` carries for the Kubernetes deployment;
keep the two in step.
"""
import os

# --- RabbitMQ ------------------------------------------------------------
node_name = os.environ["FEM_NODE_NAME"]              # also the queue name
node_user = os.environ["FEM_RABBIT_USER"]
node_password = os.environ["FEM_RABBIT_PASSWORD"]
central_server_ip = os.environ["FEM_RABBIT_HOST"]
ssl_central_server_port = int(os.environ["FEM_RABBIT_PORT"])
central_rabbitmq_vhost = os.environ["FEM_RABBIT_VHOST"]
ssl_active = os.environ["FEM_SSL_ACTIVE"].lower() == "true"

# The PEMs keep the exact filenames the federation config repo ships, so the files drop
# into rabbitmq-certificates/ unrenamed. The directory name is hardcoded in
# services/check_resources.py and must stay rabbitmq-certificates.
rabbitmq_folder = "/app/config/rabbitmq-certificates"
ssl_cafile_path = f"{rabbitmq_folder}/rootCA_cert.pem"
ssl_client_cert_path = f"{rabbitmq_folder}/{node_name}_client_cert.pem"
ssl_client_keys_path = f"{rabbitmq_folder}/{node_name}_client_key.pem"
# Passphrase protecting the client key (cert_phrase in the federation config.py). Unset
# for an unencrypted key; receiver.py passes it to SSLContext.load_cert_chain.
cert_phrase = os.environ.get("FEM_CERT_PHRASE") or None

# --- Paths ---------------------------------------------------------------
# sandbox_path is the sandbox as the WES workers see it, which is what
# services/wes_client.py injects into workflow_params as %SANDBOX%. SANDBOX_PATH in the
# container env is this container's own mount; there is no DATA_PATH -- see `datasets`.
sandbox_path = os.environ["FEM_SANDBOX_REMOTE_PATH"]
# Only a catalogue entry that injects %DATA% needs this, and none does here: a run names
# its datasets by id and the WES stages them itself. Unset is therefore not a
# misconfiguration, so it does not fail at import.
data_path = os.environ.get("FEM_DATA_REMOTE_PATH", "")

# --- Datasets this node offers -------------------------------------------
# The datasets live on the WES workers, never in this container, so `list_files /data`
# answers from this declaration instead of walking a directory. Keyed by the dataset id a
# workflow is run against (omicz-wes takes them as its `datasets` list); the value names
# the files in it, and may be empty when the node publishes only the id. Nothing here is
# read for its contents -- the FEM client cannot send a dataset's bytes, only name what is
# available.
#
# A dataset named here must exist in the WES stack's object store, or a run over it fails
# in the executor.
datasets = {
    "goe_dataset": [],
}

api_base_url = os.environ["FEM_API_BASE_URL"]        # FEM orchestrator API
json_launcher = "/app/config/launcher.json"

# --- %%PLACEHOLDER%% -> key (or key path) inside task_info ---------------
# Verbatim from the federation-provided config.py: these key paths are the orchestrator's
# DB schema, not a local choice. EXTERNAL_ID is top-level, so whatever submit_run prints
# as {"external_id": ...} must be echoed back in the process_info entry under that name.
task_info_vars = {
    "MEMORY": "memory",
    "DOCKER_IMAGE_REPO": ["image", "repository"],
    "DOCKER_IMAGE_NAME": ["image", "name"],
    "DOCKER_IMAGE_TAG": ["image", "tag"],
    "EXTERNAL_ID": "external_id",
}
