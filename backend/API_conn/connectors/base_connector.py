class SAPConnector:
    def __init__(self, config):
        self.config = config

    def authenticate(self):
        pass

    def fetch(self):
        raise NotImplementedError