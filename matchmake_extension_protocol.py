from typing import Callable

from nintendo.nex import rmc, common, matchmaking, streams, notification

import matchmaking_utils
from context import Context
from secure_connection_protocol import CommonSecureConnectionServer


class CommonMatchmakeExtensionServer(matchmaking.MatchmakeExtensionServer):

    # ============= Fixing functions (their definition in the original library was wrong/mistyped) =============

    async def handle_auto_matchmake_with_search_criteria_postpone(self, client, input, output):
        matchmaking.logger.info("MatchmakeExtensionServer.auto_matchmake_with_search_criteria_postpone()")
        # --- request ---
        search_criteria = input.list(matchmaking.MatchmakeSessionSearchCriteria)
        gathering = input.anydata()
        message = input.string()
        response = await self.auto_matchmake_with_search_criteria_postpone(client, search_criteria, gathering, message)

        # --- response ---
        output.anydata(response)

    def __init__(self,
                 context: Context,
                 get_friend_pids_func: Callable[[int], list[int]],
                 secure_connection_server: CommonSecureConnectionServer):

        super().__init__()
        self.context = context
        self.gatherings_db = context.database["gatherings"]
        self.sequence_db = context.database["sequence"]

        self.get_friend_pids = get_friend_pids_func
        self.secure_connection_server = secure_connection_server

    async def logout(self, client):
        pass

    # You can implement this in the parent class to add MongoDB query filters.
    @staticmethod
    def extension_filters(client, filter) -> dict:
        return {}

    # ============= Utility functions  =============

    def can_user_join_gathering(self, client: rmc.RMCClient, gathering) -> bool:
        if gathering["participation_policy"] == 98:  # Only WiiU friends can participate (MK8)
            friend_pids = self.get_friend_pids(gathering["owner"])
            return client.pid() in friend_pids
        return True

    def verify_search_criterias(self, search_criteria: list[matchmaking.MatchmakeSessionSearchCriteria]):
        matchmaking_utils.verify_search_criterias(search_criteria)

    def verify_gathering_type(self, gathering):
        matchmaking_utils.verify_gathering_type(gathering)

    # ============= Method implementations  =============

    async def create_matchmake_session(self, client, gathering, description: str, num_participants: int):
        if len(description) > 128:
            raise common.RMCError("Core::InvalidArgument")

        if num_participants > 256:
            raise common.RMCError("Core::InvalidArgument")

        if not matchmaking_utils.is_object_matchmake_session(gathering):
            raise common.RMCError("Core::InvalidArgument")

        self.verify_gathering_type(gathering)

        res = matchmaking_utils.create_gathering_type_from_document(client, gathering)
        res.description = description

        created_gathering = matchmaking_utils.create_gathering(self.gatherings_db, self.sequence_db, client, res)
        matchmaking_utils.add_user_to_gathering(self.gatherings_db, client, created_gathering.id, "", num_participants)

        response = rmc.RMCResponse()
        response.gid = created_gathering.id
        response.session_key = created_gathering.session_key

        return response

    async def auto_matchmake_with_search_criteria_postpone(self, client, search_criteria: list[
        matchmaking.MatchmakeSessionSearchCriteria], gathering, message):

        if len(message) > 128:
            raise common.RMCError("Core::InvalidArgument")

        self.verify_search_criterias(search_criteria)
        self.verify_gathering_type(gathering)

        num_players = 1
        if len(search_criteria) > 0:
            num_players = search_criteria[0].vacant_participants

        res_gathering = matchmaking_utils.find_gathering(self.gatherings_db, self.sequence_db, client,
                                                         search_criteria, gathering, 40, self.extension_filters)[0]

        tmp_gathering = self.gatherings_db.find_one({"id": res_gathering.id})
        if not self.can_user_join_gathering(client, tmp_gathering):
            raise common.RMCError("RendezVous::NotFriend")

        matchmaking_utils.add_user_to_gathering_ex(self.gatherings_db, client, tmp_gathering, "", num_players)
        return res_gathering

    async def get_simple_playing_session(self, client, pids: list[int], include_login_user: bool):

        lst_pids = pids.copy()
        if client.pid() in lst_pids:
            lst_pids.remove(client.pid())

        if include_login_user:
            lst_pids.append(client.pid())

        res = []

        gatherings = list(self.gatherings_db.find({"players": {"$in": lst_pids}}))
        for pid in lst_pids:
            for gathering in gatherings:
                if pid in gathering["players"]:
                    playing_session = matchmaking.SimplePlayingSession()
                    playing_session.pid = pid
                    playing_session.gid = gathering["id"]
                    playing_session.game_mode = gathering["game_mode"]
                    playing_session.attribute = gathering["attribs"][0]
                    res.append(playing_session)
        return res

    async def update_progress_score(self, client, gid, score):
        if score > 100:
            raise common.RMCError("Core::InvalidArgument")

        gathering = self.gatherings_db.find_one({"id": gid})
        if not gathering:
            raise common.RMCError("RendezVous::SessionVoid")

        if gathering["owner"] != client.pid():
            raise common.RMCError("RendezVous::PermissionDenied")

        self.gatherings_db.update_one({"id": gid}, {"$set": {"progress_score": score}})

    async def create_matchmake_session_with_param(self, client, param: matchmaking.CreateMatchmakeSessionParam):
        if len(param.join_message) > 256:
            raise common.RMCError("Core::InvalidArgument")

        if len(param.additional_participants) + 1 > param.session.max_participants:
            raise common.RMCError("Core::InvalidArgument")

        if len(param.additional_participants) > 0 and param.gid_for_participation_check == 0:
            raise common.RMCError("RendezVous::NotParticipatedGathering")

        self.verify_gathering_type(param.session)

        # Check the additional participants are all in the same exisiting gathering
        if len(param.additional_participants) > 0:
            additional_gathering = self.gatherings_db.find_one({"id": param.gid_for_participation_check})
            if not additional_gathering:
                raise common.RMCError("RendezVous::NotParticipatedGathering")

            if not (set(param.additional_participants).issubset(additional_gathering["players"])):
                raise common.RMCError("RendezVous::NotParticipatedGathering")

        # Create a gathering, add the host then the additional participants
        res = matchmaking_utils.create_gathering_type_from_document(client, param.session)
        created_gathering = matchmaking_utils.create_gathering(self.gatherings_db, self.sequence_db, client, res)
        created_gathering_doc = matchmaking_utils.gathering_type_to_document(created_gathering)

        created_gathering_doc = matchmaking_utils.add_user_to_gathering_ex(self.gatherings_db, client,
                                                                           created_gathering_doc, "", 1)
        if len(param.additional_participants) > 0:
            matchmaking_utils.add_user_to_gathering_ex_by_pids(
                self.gatherings_db, client, created_gathering_doc, param.join_message, param.additional_participants)

        # Send "Switch gathering" notification to the additional participants
        for pid in param.additional_participants:
            target_client = self.secure_connection_server.get_client_by_pid(pid)
            if target_client:
                stream = streams.StreamOut(self.context.settings)
                event = notification.NotificationEvent()
                event.pid = client.pid()
                event.type = 122000  # Switch gathering
                event.param1 = created_gathering.id
                event.param2 = pid
                stream.add(event)
                message = rmc.RMCMessage.request(
                    self.context.settings,
                    notification.NotificationProtocol.PROTOCOL_ID,
                    notification.NotificationProtocol.METHOD_PROCESS_NOTIFICATION_EVENT,
                    0xffff0000 + client.call_id,
                    stream.get()
                )
                await target_client.client.send(message.encode())

        return created_gathering
