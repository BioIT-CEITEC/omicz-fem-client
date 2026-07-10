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

### Installing  _jq_
In Ubuntu 14+ OS, follow these steps:
```
sudo apt update

sudo apt install jq
```

To test it's correctly installed:
```
echo '{ "name":"John", "age":31, "city":"New York" }' | jq .
```
The result should appear like so in your terminal:
```
{
  "name": "John",
  "age": 31,
  "city": "New York"
}
```

### Optional: GPU setup

This section is not mandatory, but if the host system is not correctly set up, the FEM-client will not be able to use the GPUs. 
Just in case, FEM-client is prepared to fallback to CPU usage if the configuration fails.

```
# Check if nvidia drivers and utils are installed in the system
nvidia-smi -L
```
Example of expected output (anything that's not an error):

`GPU 0: NVIDIA GeForce RTX 3060 (UUID: GPU-b90ebde0-2285-0f1e-249e-55dc6dd7abf1)`

```
nvidia-container-runtime --version
```

Example of expected output (anything that's not an error):

`Nvidia Container Runtime Hook Version 1.17.7
commit: bae3e7842ebe26812d8bd6a9be6a14a83dc91d8f`

```
docker info | grep -A5 Runtimes
```
Example of expected output (nvidia included in runtimes):
```
 Runtimes: oci runc io.containerd.runc.v2 nvidia
 Default Runtime: runc
 Init Binary: docker-init
 containerd version: 05044ec0a9a75232cad458027ca83437aae3f4da
 runc version: v1.1.14-0-g2c9f5602f0ba
 init version:
```

If any of the previous gives an error, install the needed packages, drivers or config from the ones provided: 
sudo apt update

```
# Install/Update nvidia drivers
### CAUTION: Updating NVIDIA drivers may affect existing GPU workloads or compatibility. Ensure you review driver requirements and test appropriately in your environment. ###
sudo apt install nvidia-driver-570-server
sudo apt install nvidia-utils-570-server

# Install the nvidia-container-toolkit
# Point to the necessary repositories:
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
	sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
	sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt install nvidia-container-toolkit

# Let docker allow nvidia as runtime:
sudo nano /etc/docker/daemon.json
```

Paste this inside: 
```
{
       "runtimes": {
        "nvidia": {
            "args": [],
            "path": "nvidia-container-runtime"
        }
   }
}
```
If any of the changes were made, restart the docker runner:
```
# Restart docker
sudo systemctl restart docker 

# Retry commands of previous block
```

## Installing FEM-client image

Download the image of this project: 

1. Download the image from the docker registry (for project-specific registries, follow project's instructions). 
In this GitLab repository, the credentials to log in are the same username and password used to access GitLab.
```
docker login gitlab.bsc.es
docker pull registry.gitlab.bsc.es/fl/fem-client:{version}
docker logout #optional, if you don't want to keep logged in in this machine
```
2. Once the download is finished, check that docker can find ir with the following command:
`docker images`

If the 'registry.gitlab.bsc.es/fl/fem-client' is listed there, follow steps **1-5 of the 'Getting started' section**.

## Getting Started

1. Clone the repository:

`git clone https://gitlab.bsc.es/fl/fem-client.git`

2. Navigate to the project directory:

`cd fem-client`

3. Prepare the configuration files:

Associated to each project/federation (and usually under restricted access), there exist a repository with the FEM-client config files already pre-configured to connect to the project/federation orchestrator node. Ask for instructions and access to your federation/project manager.

Within `fem-client/` folder, clone the given repository and follow its instructions:
 
```
git clone https://gitlab.bsc.es/fl/{project_name}-fem-client-config.git
```
The resulting structure after folowing the instructions should looks like:
```
fem-client/
├── config/
│   └── config.py
└── app/
│   └── [...]
├── Dockerfile

```


4. Start the Client
Once the config folder is set-up:
```
bash setup_service.sh
```

5. Monitor the receiver:
`docker logs -f fem-client`
















