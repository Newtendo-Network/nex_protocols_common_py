from datetime import timezone, datetime

import bson
from anyio import Lock
from nintendo.nex import rmc, secure, common

from nex_protocols_common_py.context import Context


class CommonSecureConnectionServer(secure.SecureConnectionServer):
    def __init__(self, context: Context):

        super().__init__()
        self.context = context
        self.sessions_db = context.database["sessions"]
        self.reportdata_db = context.database["reportdata"]

        self.connection_id_counter = 1
        self.connection_id_lock = Lock()

        self.clients = {}

    async def logout(self, client):
        self.clients.pop(client.client.user_cid)
        print("Removing disconnected player %d session ... (RVCID %d)" % (client.pid(), client.client.user_cid))
        self.sessions_db.delete_one({"cid": client.client.user_cid})

    def get_client_by_cid(self, cid: int) -> rmc.RMCClient | None:
        return self.clients.get(cid, None)

    def get_client_by_pid(self, pid: int) -> rmc.RMCClient:
        for cid in self.clients.keys():
            client = self.clients[cid]
            if client.pid() == pid:
                return client

    # ============= Utility functions  =============

    def get_current_session_for_pid(self, pid: int):
        return self.sessions_db.find_one({"pid": pid})

    @staticmethod
    def transform_urls(urls: list[common.StationURL]) -> list[str]:
        return list(map(str, urls))

    def set_session_for_pid(self, pid: int, urls: list[common.StationURL], cid: int, addr: tuple[str, int]):
        url_list = self.transform_urls(urls)
        self.sessions_db.update_one({"pid": pid}, {"$set": {
            "pid": pid,
            "cid": cid,
            "urls": url_list,
            "ip": addr[0],
            "port": addr[1]
        }}, upsert=True)

    def replace_session_url_for_pid(self, pid: int, url: common.StationURL, new: common.StationURL):
        session = self.sessions_db.find_one({"pid": pid})
        if session:

            url = str(url)
            new = str(new)

            new_array = []
            old_array: list[str] = session["urls"]
            for i in range(len(old_array)):
                if old_array[i] == url:
                    new_array.append(new)
                else:
                    new_array.append(old_array[i])

            self.sessions_db.update_one({"pid": pid}, {"$set": {"urls": new_array}})

    # ============= Method implementations  =============

    async def register(self, client: rmc.RMCClient, urls: list[common.StationURL]):
        url_list = urls.copy()

        public_url = url_list[0].copy()

        """
            We use a lock to exclude other async calls to this method
            So that between the read and the increment the ConnectionID remains the same.
        """
        async with self.connection_id_lock:
            cid = self.connection_id_counter
            client.client.user_cid = cid
            self.clients[cid] = client

            self.connection_id_counter += 1

        remote_addr = client.remote_address()
        public_url["address"] = remote_addr[0]
        public_url["port"] = remote_addr[1]

        public_url["natf"] = 0
        public_url["natm"] = 0
        public_url["type"] = 3

        public_url["PID"] = client.pid()

        url_list.append(public_url)

        self.set_session_for_pid(client.pid(), url_list, cid, remote_addr)

        response = rmc.RMCResponse()
        response.result = common.Result.success()
        response.connection_id = cid
        response.public_station = public_url

        return response

    # Could be misused to get any user IP ...
    async def request_connection_data(self, client, cid, pid):
        raise common.RMCError("Core::AccessDenied")

    # Could be misused to get any user IP ...
    async def request_urls(self, client, cid, pid):
        raise common.RMCError("Core::AccessDenied")

    async def register_ex(self, client: rmc.RMCClient, urls: list[common.StationURL], login_data):
        return self.register(client, urls)

    async def test_connectivity(self, client):
        return

    async def update_urls(self, client: rmc.RMCClient, urls: list[common.StationURL]):
        remote_addr = client.remote_address()
        self.set_session_for_pid(client.pid(), urls, client.client.user_cid, remote_addr)

    async def replace_url(self, client: rmc.RMCClient, url: common.StationURL, new: common.StationURL):
        self.replace_session_url_for_pid(client.pid(), url, new)

    async def send_report(self, client, report_id, report_data):
        self.reportdata_db.update_one({
            "pid": client.pid(),
            "report_id": report_id
        }, {
            "$set": {
                "pid": client.pid(),
                "report_id": report_id,
                "report_data": bson.Binary(report_data),
                "report_size": len(report_data),
                "report_date": datetime.now(timezone.utc)
            }
        }, upsert=True)
