from nintendo.nex import common, matchmaking

import matchmaking_utils
from context import Context


class CommonMatchMakingServerExt(matchmaking.MatchMakingServerExt):
    def __init__(self,
                 context: Context):

        super().__init__()
        self.context = context
        self.gatherings_db = context.database["gatherings"]
        self.sequence_db = context.database["sequence"]

    async def logout(self, client):
        gatherings = list(self.gatherings_db.find({"players": {"$in": [client.pid()]}}))
        print("Removing disconnected player %d from %d gatherings ... " % (client.pid(), len(gatherings)))
        for gathering in gatherings:
            matchmaking_utils.remove_user_from_gathering_ex(self.gatherings_db, client, gathering, "")

    # ============= Utility functions  =============

    # ============= Method implementations  =============

    async def end_participation(self, client, gid, message):

        if len(message) > 256:
            raise common.RMCError("Core::InvalidArgument")

        matchmaking_utils.remove_user_from_gathering(self.gatherings_db, client, gid, message)
        return True
