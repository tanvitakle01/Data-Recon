import yaml

def load_config():
    with open("API_conn/config/sap_config.yaml", "r") as f:
        return yaml.safe_load(f)