from backend.API_conn.connectors.s4_connector import S4SalesOrderConnector
from backend.API_conn.connectors.ibp_connector import IBPDemandConnector


class ReconciliationService:

    def get_source_data(self):
        return S4SalesOrderConnector().fetch()

    def get_target_data(self):
        return IBPDemandConnector().fetch()