import yaml

def load_config():
    with open("backend/API_conn/config/sap_config.yaml", "r") as f:
        return yaml.safe_load(f)