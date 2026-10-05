# Federated Execution Manager (FEM) - Client

The Federated Execution Manager (FEM) is a software component designed to coordinate and manage the execution of distributed processes in a federated leaning (FL) or decentralised compute environment where multiple devices or clients, i.e. the federated data nodes (FDN) provide compute and data resources.

# What is FEM?

FEM is responsible for controlling and orchestrating the lifecycle of the federated tasks. It consists of two parts:
- an **orchestrator module** (FEM-orchestrator) that ensures tasks reach the multiple FDNs in a secure and coordinated manner
- a **client module** (FEM-client) installed at the participating FDN that pulls such tasks and allocates them in the local infrastructure.

In short, the *FEM-client* interact with the FEM-orchestrator via a message broker (RabbitMQ) and pulls the federated task details.   across multiple Federated Data Nodes (FDNs). The FEM Client works in conjunction with the central FEM Orchestrator to manage distributed computing workflows, such as federated learning (FL) experiments and other data processing tasks.

![arch](docs/images/arch.png)

## What is FEM-client?
The key functions of the FEM client include:
- **Task reception**: it ensures secure interactions between the FDN and the central orchestrator via a message broker (RabbitMQ) and pulls the federated task details.
- **Task stage-in**: it prepares the working enviroment, handling data volumes, container image pulling and source code Git syncronizations.
- **Task execution**: it executes tasks in the local infraestructure delegating the resources managment the customizable executors or launchers. Default executor: "docker".
- **Task stage-out**: it exchanging the necessary task outfiles and logging files with the central orchestrator.

## Minimal Infrastructure Requirements
- To run the FEM-client, the deploying node must provide a basic computational environment capable of executing federated tasks locally:
  - Minimal technical requirements:
    - Unix-based S.O. 
    - Docker and Docker Compose (>= v2)
    - 2CPUs and 4GB
    - _jq_ must be installed in the system that hosts FEM client (see instructions below)
  - Minimal client connectivity requirements:
    - Outgoing connection to RabbitMQ server
    - Default port: 5671 (AMQPS 1.0 over TLS)
    - Destination: FEM server IP or FQDN 
- FEM-client includes a TES-like (Task Execution Service) interface that communicates via RabbitMQ.
- The node is expected to:
    - Use its local computing resources (e.g., cluster, server, HPC node, etc.).
    - Map standard TES actions (e.g., submit job, check status, list jobs, delete job) to its local infrastructure.
    - This mapping is done via the localconfig file in the FEM-client, which links TES actions to either: local APIs, or Command-line tools/scripts already in use at the site.
This flexible architecture ensures the FEM-client can be integrated with a wide variety of systems while maintaining data locality and autonomy.

> Please, consider that tools, pipelines or FL frameworks triggered by FEM have their on connectivity requirements.

## Delegating execution to a GA4GH WES endpoint

`app/services/wes_client.py` submits and monitors runs on a WES 1.1 service instead of the
local Docker daemon, and a finished run's outputs are read back from the omicz result
service rather than from local disk. Which registered workflow a task may run, which
parameters it may pass and which files it may upload is site policy, declared in
`config.example/wes-catalogue.json`; `config.example/launcher.json` is the matching
launcher config. See `docs/wes-mapping.md`.

`docker-compose.yml` runs that configuration — the receiver, nothing else. It starts no
containers of its own, so it gets no Docker socket, and it reads no datasets, so it gets no
`/data` mount:

```
cp .env.example .env            # then set at least FEM_RABBIT_PASSWORD
cp -r config.example config     # then add the broker PEMs to config/rabbitmq-certificates/
docker compose up -d
docker logs -f fem-client
```

`.env` carries the node's identity, the broker, and the WES / result service addresses;
`config/` carries site policy and is gitignored — `config.example/` is the committed copy
to start from, and `k8s/configmap.yaml` carries the same content for the cluster. The
defaults address an `omicz-wes` compose stack on the same host (`wes` and `results` on the
`omicz-wes-edge` network) — point `WES_URL`, `RESULTS_URL` and `FEM_NETWORK` elsewhere for
any other arrangement.

`Dockerfile` builds the one image both this compose file and the `k8s/` manifests run. It
carries no docker CLI and no entrypoint script: the container runs as uid 1000, starts no
containers and writes only to its mounts.

```
docker build --platform linux/amd64 -t <repo>/fem-client:dev .
```

`--platform linux/amd64` because `psutil==5.9.0` ships no arm64 wheel and the slim base
image has no compiler; drop it when building on amd64.
















