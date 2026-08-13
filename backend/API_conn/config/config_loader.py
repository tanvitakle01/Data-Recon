import yaml


def load_config():
    with open("backend/API_conn/config/sap_config.yaml", "r") as f:
        return yaml.safe_load(f)


def resolve_verify(cfg: dict):
    """TLS verify setting for a `requests` call, from one SAP block of the
    config. Defaults to `True` (verify on) unless the block explicitly opts
    out via `skip_tls_verify: true`, or supplies `ca_bundle` (a path to a
    PEM/CRT file for a corporate/self-signed CA), in which case that path is
    passed straight to `verify=`.
    """
    if cfg.get("skip_tls_verify"):
        return False
    ca_bundle = cfg.get("ca_bundle")
    return ca_bundle if ca_bundle else True
