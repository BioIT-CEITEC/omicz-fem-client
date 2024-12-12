# Federated Execution Manager (FEM) - Client

The Federated Execution Manager (FEM) is a software component designed to coordinate and manage the execution of distributed processes in a federated leaning (FL) or decentralised compute environment where multiple devices or clients, i.e. the federated data nodes (FDN) provide compute and data resources.

# What is FEM?

FEM is responsible for controlling and orchestrating the lifecycle of the federated tasks. It consists of two parts:
- an **orchestrator module** (FEM-orchestrator) that ensures tasks reach the multiple FDNs in a secure and coordinated manner
- a **client module** (FEM-client) installed at the participating FDN that pulls such tasks and allocates them in the local infrastructure.

In short, the *FEM-client* interact with the FEM-orchestrator via a message broker (RabbitMQ) and pulls the federated task details.   across multiple Federated Data Nodes (FDNs). The FEM Client works in conjunction with the central FEM Orchestrator to manage distributed computing workflows, such as federated learning (FL) experiments and other data processing tasks.

![arch](docs/images/arch.png)

## Wha is FEM-client?
The key functions of the FEM client include:
- **Task reception**: it ensures secure interactions between the FDN and the central orchestrator via a message broker (RabbitMQ) and pulls the federated task details.
- **Task stage-in**: it prepares the working enviroment, handling data volumes, container image pulling and source code Git syncronizations.
- **Task execution**: it executes tasks in the local infraestructure delegating the resources managment the customizable executors or launchers. Default executor: "docker".
- **Task stage-out**: it exchanging the necessary task outfiles and logging files with the central orchestrator.

## Prerequisites

For deploying either an FEM server or client, the minimal technical requirements are:
- Unix-based S.O. 
- Docker and Docker Compose
- 2CPUs and 4GB

> Please, consider that tools, pipelines or FL frameworks triggered by FEM have their on connectivity requirements.

The minimal client connectivity requirements to be part of an FEM-enabled federation are:
- Outgoing connection to RabbitMQ server
   - Default port: 5671 (AMQPS 1.0 over TLS)
   - Destination: FEM server IP or FQDN 

> Please, consider that tools, pipelines or FL frameworks triggered by FEM (e.g. Flower, etc) have their on connectivity requirements.

## Getting Started

1. Clone the repository:
`git clone https://gitlab.bsc.es/fl/fem-client.git`

2. Navigate to the project directory:
`cd fem-client`

3. Setup config file (clone the config repository that was shared with you and follow the instructions writen on its README file):
```
git clone https://gitlab.bsc.es/fl/{project_name}-fem-client-config.git
```
Once the config folder is set-up:

4. Start the Client
```
bash setup_service.sh
```

5. Monitor the receiver:
`docker logs -f fem-client`


## Installing from the image

If the process fails during the 'docker build', there is an option to download the pre-built image of this project: 

1. Download the image from the docker registry. The credentials to log in are the same username and password used to access GitLab.
```
docker login gitlab.bsc.es
docker pull registry.gitlab.bsc.es/fl/fem-client:v1.0
docker logout #optional, if you don't want to keep logged in in this machine
```
2. Once the download is finished, check that docker can find ir with the following command:
`docker images`

If the 'registry.gitlab.bsc.es/fl/fem-client' is listed there, follow steps **1-5 of the 'Getting started' section**, and the docker-copose will run the project from the image instead of building it from scratch.


## How to set up a new FEM tool

If you are an AI developer and want to run a new AI tool using FEM, follow these steps:

1. **Create a Docker image for your model and share it with the FEM team.**

2. **Fill in the JSON template for your model:**
   - You can find a tool plan and task template along the schemas in the docs/templates folder so you can fill and provide the necessary details about your tool, including Docker image information or Git repository.

3. **Follow the standard FEM client setup instructions:**

4. **Execute the FEM client:**
   - Start the federated learning process with your model calling the API.


















