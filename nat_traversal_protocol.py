from nintendo.nex import rmc, nattraversal, common, streams

from context import Context
from secure_connection_protocol import CommonSecureConnectionServer


class CommonNATTraversalServer(nattraversal.NATTraversalServer):
    def __init__(self,
                 context: Context,
                 secure_connection_server: CommonSecureConnectionServer):
        super().__init__()
        self.context = context

        self.sessions_db = context.database["sessions"]
        self.secure_connection_server = secure_connection_server

    # ============= Utility functions  =============

    # ============= Method implementations  =============

    async def report_nat_properties(self, client, natm, natf, rtt):
        client_session = self.sessions_db.find_one({"pid": client.pid()})
        if client_session:
            new_urls = []
            for url in client_session["urls"]:
                station_url = common.StationURL.parse(url)
                if station_url["type"] == 3:
                    station_url["natm"] = natm
                    station_url["natf"] = natf
                station_url["PID"] = client.pid()
                station_url["RVCID"] = client.client.user_cid
                new_urls.append(station_url)

            self.sessions_db.update_one({"pid": client.pid()}, {"$set": {"urls": list(map(str, new_urls))}})

    async def request_probe_initiation_ext(self, client: rmc.RMCClient, target_urls, station_to_probe):
        for url in target_urls:
            target_client = self.secure_connection_server.get_client_by_cid(url["RVCID"])
            if target_client:
                stream = streams.StreamOut(self.context.settings)
                stream.stationurl(station_to_probe)
                message = rmc.RMCMessage.request(
                    self.context.settings,
                    self.PROTOCOL_ID,
                    self.METHOD_INITIATE_PROBE,
                    0xffff0000 + client.call_id,
                    stream.get()
                )
                await target_client.client.send(message.encode())

    async def report_nat_traversal_result(self, *args):
        pass
