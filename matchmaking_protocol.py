from nintendo.nex import rmc, matchmaking, common

from . import matchmaking_utils
from .context import Context
from .matchmaking_utils import GatheringFlags


class CommonMatchMakingServer(matchmaking.MatchMakingServer):

    def __init__(self, context: Context):
        super().__init__()
        self.context = context

        self.gatherings_db = context.database["gatherings"]
        self.sessions_db = context.database["sessions"]
        self.sequence_db = context.database["sequence"]

    # ============= Utility functions  =============

    # ============= Method implementations  =============

    async def unregister_gathering(self, client, gid):
        gathering = self.gatherings_db.find_one({"id": gid})
        if not gathering:
            raise common.RMCError("RendezVous::SessionVoid")

        if gathering["owner"] != client.pid():
            raise common.RMCError("RendezVous::PermissionDenied")

        self.gatherings_db.delete_one({"id": gid})
        return True

    async def get_session_urls(self, client, gid):
        gathering = self.gatherings_db.find_one({"id": gid})
        if not gathering:
            raise common.RMCError("RendezVous::SessionVoid")

        if client.pid() not in gathering["players"]:
            raise common.RMCError("RendezVous::PermissionDenied")

        host_session = self.sessions_db.find_one({"pid": gathering["host"]})

        res = []
        for url in host_session["urls"]:
            res.append(common.StationURL.parse(url))

        return res

    async def find_by_single_id(self, client, gid):
        gathering = self.gatherings_db.find_one({"id": gid})
        if not gathering:
            raise common.RMCError("RendezVous::SessionVoid")

        response = rmc.RMCResponse()
        response.result = True
        response.gathering = matchmaking_utils.gathering_type_from_document(gathering)
        return response

    async def update_session_host_v1(self, client, gid: int):
        gathering = self.gatherings_db.find_one({"id": gid})
        if not gathering:
            raise common.RMCError("RendezVous::SessionVoid")

        if client.pid() not in gathering["players"]:
            raise common.RMCError("RendezVous::PermissionDenied")

        updates = {"host": client.pid()}
        if gathering["flags"] & GatheringFlags.CAN_OWNERSHIP_BE_TAKEN_BY_PARTICIPANTS:
            updates.update({"owner": client.pid()})

        self.gatherings_db.update_one({"id": gid}, {"$set": updates})

        if gathering["flags"] & GatheringFlags.CAN_OWNERSHIP_BE_TAKEN_BY_PARTICIPANTS:
            for pid in gathering["players"]:
                pass  # TODO: Send notification 4000
