# Broker client certificates

The client connects to the orchestrator's RabbitMQ over TLS with a client certificate.
These files are node credentials, so they are not in the repository — drop them into
`config/rabbitmq-certificates/` before `docker compose up`, under the filenames the
federation config repo ships:

```
rootCA_cert.pem                   the broker's CA
<FEM_NODE_NAME>_client_cert.pem
<FEM_NODE_NAME>_client_key.pem
```

`config.py` builds the two client paths from `FEM_NODE_NAME`, so renaming the node means
renaming the PEMs. If the key is encrypted, put its passphrase in `FEM_CERT_PHRASE`.

Only `FEM_SSL_ACTIVE=false` makes these unnecessary, and the orchestrator's broker does
not accept that.
