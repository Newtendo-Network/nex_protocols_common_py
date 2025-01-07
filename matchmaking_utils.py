import os
from collections.abc import Mapping
from typing import Callable

import bson
from nintendo.nex import rmc, matchmaking, common, matchmaking_eagle, matchmaking_mk8d
from pymongo.collection import Collection


class GatheringFlags:
    MIGRATE_OWNERSHIP = 0x10
    LEAVE_PERSISTENT_GATHERING_ON_DISCONNECT = 0x40
    ALLOW_ZERO_PARTICIPANT = 0x80
    CAN_OWNERSHIP_BE_TAKEN_BY_PARTICIPANTS = 0x200
    SEND_NOTIFICATIONS_ON_PARTICIPATION = 0x400
    SEND_NOTIFICATIONS_ON_PARTICIPATION_AND_NEW = 0x800


def get_next_gid(col: Collection) -> int:
    gid = col.find_one_and_update({"_id": "gathering_id"}, {"$inc": {"seq": 1}})["seq"]
    if gid == 0xffffffff:
        col.update_one({"_id": "gathering_id"}, {"$set": {"seq": 0}})

    return gid


# ============= Gathering functions  =============


def is_object_gathering(obj) -> bool:
    return (isinstance(obj, matchmaking.Gathering)) or (isinstance(obj, matchmaking_mk8d.Gathering)) or (
        isinstance(obj, matchmaking_eagle.Gathering))


def gathering_to_document(obj: matchmaking.Gathering) -> dict:
    return {
        "type": "Gathering",
        "id": obj.id,
        "owner": obj.owner,
        "host": obj.host,
        "min_participants": obj.min_participants,
        "max_participants": obj.max_participants,
        "participation_policy": obj.participation_policy,
        "policy_argument": obj.policy_argument,
        "flags": obj.flags,
        "state": obj.state,
        "description": obj.description
    }


def gathering_from_document_impl(res: matchmaking.Gathering, obj: dict):
    res.id = obj["id"]
    res.owner = obj["owner"]
    res.host = obj["host"]
    res.min_participants = obj["min_participants"]
    res.max_participants = obj["max_participants"]
    res.participation_policy = obj["participation_policy"]
    res.policy_argument = obj["policy_argument"]
    res.flags = obj["flags"]
    res.state = obj["state"]
    res.description = obj["description"]


def gathering_from_document(obj: dict) -> matchmaking.Gathering:
    res = matchmaking.Gathering()
    gathering_from_document_impl(res, obj)
    return res


def create_gathering_from_obj(client: rmc.RMCClient, gathering: matchmaking.Gathering) -> matchmaking.Gathering:
    res = matchmaking.Gathering()
    res.owner = client.pid()
    res.host = client.pid()
    res.min_participants = gathering.min_participants
    res.max_participants = gathering.max_participants
    res.participation_policy = gathering.participation_policy
    res.policy_argument = gathering.policy_argument
    res.flags = gathering.flags
    res.state = 0
    res.description = gathering.description

    return res


# ============= MatchmakeSession functions  =============


def is_object_matchmake_session(obj) -> bool:
    return (isinstance(obj, matchmaking.MatchmakeSession)) or (isinstance(obj, matchmaking_mk8d.MatchmakeSession)) or (
        isinstance(obj, matchmaking_eagle.MatchmakeSession))


def matchmake_session_to_document(obj: matchmaking.MatchmakeSession) -> dict:
    res = gathering_to_document(obj)
    res.update({
        "type": "MatchmakeSession",
        "game_mode": obj.game_mode,
        "attribs": obj.attribs,
        "open_participation": obj.open_participation,
        "matchmake_system": 0,
        "application_data": bson.Binary(obj.application_data),
        "num_participants": obj.num_participants,
        "progress_score": obj.progress_score,
        "session_key": bson.Binary(obj.session_key),
        "option0": obj.option,
        "param": obj.param.param,
        "started_time": obj.started_time.value(),
        "user_password": obj.user_password,
        "refer_gid": obj.refer_gid,
        "user_password_enabled": obj.user_password_enabled,
        "system_password_enabled": obj.system_password_enabled,
        "codeword": obj.codeword
    })
    return res


def matchmake_session_from_document_impl(res: matchmaking.MatchmakeSession, obj: dict):
    res.game_mode = obj["game_mode"]
    res.attribs = obj["attribs"]
    res.open_participation = obj["open_participation"]
    res.matchmake_system = obj["matchmake_system"]
    res.application_data = obj["application_data"]
    res.num_participants = obj["num_participants"]
    res.progress_score = obj["progress_score"]
    res.session_key = obj["session_key"]
    res.option = obj["option0"]
    res.param = matchmaking.MatchmakeParam()
    res.param.param = obj["param"]
    res.started_time = common.DateTime(obj["started_time"])
    res.user_password = obj["user_password"]
    res.refer_gid = obj["refer_gid"]
    res.user_password_enabled = obj["user_password_enabled"]
    res.system_password_enabled = obj["system_password_enabled"]
    res.codeword = obj["codeword"]


def matchmake_session_from_document(obj: dict) -> matchmaking.MatchmakeSession:
    res = matchmaking.MatchmakeSession()
    gathering_from_document_impl(res, obj)
    matchmake_session_from_document_impl(res, obj)
    return res


def create_matchmake_session_from_obj(client: rmc.RMCClient,
                                      gathering: matchmaking.MatchmakeSession) -> matchmaking.MatchmakeSession:
    res = matchmaking.MatchmakeSession()
    res.owner = client.pid()
    res.host = client.pid()
    res.min_participants = gathering.min_participants
    res.max_participants = gathering.max_participants
    res.participation_policy = gathering.participation_policy
    res.policy_argument = gathering.policy_argument
    res.flags = gathering.flags
    res.state = 0
    res.description = gathering.description

    res.game_mode = gathering.game_mode
    res.attribs = gathering.attribs
    res.open_participation = gathering.open_participation
    res.matchmake_system = gathering.matchmake_system
    res.application_data = gathering.application_data
    res.progress_score = 0
    res.num_participants = 0
    res.session_key = os.urandom(32)
    res.param = gathering.param
    res.started_time = common.DateTime.now()
    res.user_password = gathering.user_password
    res.refer_gid = gathering.refer_gid
    res.user_password_enabled = gathering.user_password_enabled
    res.codeword = gathering.codeword

    return res


# ============= PersistentGathering functions  =============


def is_object_persistent_gathering(obj) -> bool:
    return (isinstance(obj, matchmaking.PersistentGathering)) or (
        isinstance(obj, matchmaking_mk8d.PersistentGathering)) or (
        isinstance(obj, matchmaking_eagle.PersistentGathering))


def persistent_gathering_to_document(obj: matchmaking.PersistentGathering) -> dict:
    res = gathering_to_document(obj)
    res.update({
        "type": "PersistentGathering",
        "password": obj.password,
        "attribs": obj.attribs,
        "application_data": bson.Binary(obj.application_buffer),
        "start_time": obj.participation_start.value(),
        "end_time": obj.participation_end.value(),
        "matchmake_session_count": obj.matchmake_session_count,
        "num_participants": obj.num_participants
    })
    return res


def persistent_gathering_from_document_impl(res: matchmaking.PersistentGathering, obj: dict):
    res.password = obj["password"]
    res.attribs = obj["attribs"]
    res.application_buffer = obj["application_data"]
    res.participation_start = common.DateTime(obj["start_time"])
    res.participation_end = common.DateTime(obj["end_time"])
    res.matchmake_session_count = obj["matchmake_session_count"]
    res.num_participants = obj["num_participants"]


def persistent_gathering_from_document(obj: dict) -> matchmaking.PersistentGathering:
    res = matchmaking.PersistentGathering()
    gathering_from_document_impl(res, obj)
    persistent_gathering_from_document_impl(res, obj)
    return res


def create_persistent_gathering_from_obj(client: rmc.RMCClient,
                                         gathering: matchmaking.PersistentGathering) -> matchmaking.PersistentGathering:
    res = matchmaking.PersistentGathering()
    res.owner = client.pid()
    res.host = client.pid()
    res.min_participants = gathering.min_participants
    res.max_participants = gathering.max_participants
    res.participation_policy = gathering.participation_policy
    res.policy_argument = gathering.policy_argument
    res.flags = gathering.flags
    res.state = 0
    res.description = gathering.description

    res.password = gathering.password
    res.attribs = gathering.attribs
    res.application_buffer = gathering.application_buffer
    res.participation_start = gathering.participation_start
    res.participation_end = gathering.participation_end
    res.matchmake_session_count = gathering.matchmake_session_count
    res.num_participants = 0

    return res


# ============= Generic functions  =============


def gathering_type_to_name(obj) -> str:
    if is_object_matchmake_session(obj):
        return "MatchmakeSession"
    elif is_object_persistent_gathering(obj):
        return "PersistentGathering"
    elif is_object_gathering(obj):
        return "Gathering"


def gathering_type_to_document(obj) -> dict:
    if is_object_matchmake_session(obj):
        return matchmake_session_to_document(obj)
    elif is_object_persistent_gathering(obj):
        return persistent_gathering_to_document(obj)
    elif is_object_gathering(obj):
        return gathering_to_document(obj)

    raise common.RMCError("Core::InvalidArgument")


def gathering_type_from_document(obj: dict):
    if obj["type"] == "MatchmakeSession":
        return matchmake_session_from_document(obj)
    elif obj["type"] == "PersistentGathering":
        return persistent_gathering_from_document(obj)
    elif obj["type"] == "Gathering":
        return gathering_from_document(obj)

    raise common.RMCError("Core::InvalidArgument")


def create_gathering_type_from_document(client: rmc.RMCClient, obj: any):
    if is_object_matchmake_session(obj):
        return create_matchmake_session_from_obj(client, obj)
    elif is_object_persistent_gathering(obj):
        return create_persistent_gathering_from_obj(client, obj)
    elif is_object_gathering(obj):
        return create_gathering_from_obj(client, obj)

    raise common.RMCError("Core::InvalidArgument")


# ============= Verification functions  =============


def verify_search_criterias(search_criterias: list[matchmaking.MatchmakeSessionSearchCriteria]):
    for criteria in search_criterias:

        for attrib in criteria.attribs:
            if len(attrib) > 16:
                raise common.RMCError("Core::InvalidArgument")

        if len(criteria.game_mode) > 16:
            raise common.RMCError("Core::InvalidArgument")

        if len(criteria.min_participants) > 12:
            raise common.RMCError("Core::InvalidArgument")

        if len(criteria.max_participants) > 12:
            raise common.RMCError("Core::InvalidArgument")

        if len(criteria.matchmake_system) > 8:
            raise common.RMCError("Core::InvalidArgument")


def verify_gathering_type(obj):
    if obj.max_participants < obj.min_participants:
        raise common.RMCError("Core::InvalidArgument")

    if len(obj.description) > 128:
        raise common.RMCError("Core::InvalidArgument")

    if is_object_persistent_gathering(obj):
        if len(obj.password) > 64:
            raise common.RMCError("Core::InvalidArgument")

        if len(obj.application_buffer) > 256:
            raise common.RMCError("Core::InvalidArgument")

    if is_object_matchmake_session(obj):
        if len(obj.session_key) != 16 and len(obj.session_key) != 0:
            raise common.RMCError("Core::InvalidArgument")

        if len(obj.application_data) > 256:
            raise common.RMCError("Core::InvalidArgument")

        if len(obj.user_password) > 64:
            raise common.RMCError("Core::InvalidArgument")

        if len(obj.codeword) > 64:
            raise common.RMCError("Core::InvalidArgument")


# ============= Find / Create / Delete gatherings base functions  =============


def find_gathering(gatherings_db: Collection,
                   sequence_db: Collection,
                   client: rmc.RMCClient,
                   search_criteria: list[matchmaking.MatchmakeSessionSearchCriteria],
                   gathering: matchmaking.Gathering | matchmaking.MatchmakeSession,
                   limit: int,
                   add_extra_filters: Callable[[rmc.RMCClient, object], dict]) -> list:
    """
    Find a gathering and returns a list of Gathering type objects

    Args:
        gatherings_db (Collection): The MongoDB collection where the gatherings are stored
        sequence_db (Collection): The MongoDB collection where the sequence IDs are stored (auto-increment)
        client (rmc.RMCClient): The caller client
        search_criteria (list[matchmaking.MatchmakeSessionSearchCriteria]): Optional list of search criterias
        gathering (_type_): Gathering object used to filter the search if no search criterias provided
        limit (int): Maximum number of gatherings in the queries
        add_extra_filters (Callable[[rmc.RMCClient, object], dict]): Function to add extra filters (for example to check the attributes)

    Returns:
        list: List of joinable gatherings
    """
    res_list = []
    gathering_type = gathering_type_to_name(gathering)

    conditions = {"players": {"$nin": [client.pid()]}}
    conditions.update(add_extra_filters(client, gathering))
    if search_criteria and (len(search_criteria) > 0):
        # Matchmaking code with search criterias
        for sc in search_criteria:
            num_players = sc.vacant_participants

            conditions.update({"type": "MatchmakeSession", "game_mode": int(sc.game_mode)})
            if sc.game_mode != "":
                conditions.update({"game_mode": int(sc.game_mode)})

            # If search criteria has a "minimum participant" requirement, parse the string
            if sc.min_participants != "":
                if ',' in sc.min_participants:
                    low, high = sc.min_participants.split(",")
                    conditions.update({"min_participants": {"$gte": int(low), "$lte": int(high)}})
                else:
                    conditions.update({"min_participants": int(sc.min_participants)})

            # If search criteria has a "maximum participant" requirement, parse the string
            if sc.max_participants != "":
                if ',' in sc.max_participants:
                    low, high = sc.max_participants.split(",")
                    conditions.update({"max_participants": {"$gte": int(low), "$lte": int(high)}})
                else:
                    conditions.update({"max_participants": int(sc.max_participants)})

            # Make sure there's enough place for the number of players specified by the SearchCriteria
            conditions.update(
                {"$expr": {"$gte": ["$max_participants", {"$add": [{"$size": "$players"}, num_players]}]}})

            res = gatherings_db.find(conditions).limit(limit)
            res_list += list(map(gathering_type_from_document, res))
    else:
        # Matchmaking code if no search criteria is passed (None or [])
        conditions.update({
            "type": gathering_type,
            "min_participants": gathering.min_participants,
            "max_participants": gathering.max_participants
        })
        if gathering_type == "MatchmakeSession":
            conditions.update({
                "game_mode": gathering.game_mode,
            })

        # Make sure there's enough place for the player making the request
        conditions.update({"$expr": {"$gte": ["$max_participants", {"$add": [{"$size": "$players"}, 1]}]}})

        res = gatherings_db.find(conditions).limit(limit)
        res_list = list(map(gathering_type_from_document, res))

    # If no gathering match the conditions, create a new gathering for the caller
    if len(res_list) == 0:
        return [create_gathering(gatherings_db, sequence_db, client, gathering)]

    return res_list


def create_gathering(gatherings_db: Collection,
                     sequence_db: Collection,
                     client: rmc.RMCClient,
                     gathering):
    """
    Create a Gathering and returns the object

    Args:
        gatherings_db (Collection): The MongoDB collection where the gatherings are stored
        sequence_db (Collection): The MongoDB collection where the sequence IDs are stored (auto-increment)
        client (rmc.RMCClient): The caller client
        gathering (Gathering | MatchmakeSession | PersistentGathering): Base gathering sent by the client with the default settings

    Returns:
        Gathering | MatchmakeSession | PersistentGathering: The created gathering
    """

    res = create_gathering_type_from_document(client, gathering)
    res.id = get_next_gid(sequence_db)

    doc = gathering_type_to_document(res)
    doc.update({"players": []})

    gatherings_db.insert_one(doc)

    return res


def delete_gathering_for_client(gatherings_db: Collection, client: rmc.RMCClient, gid: int):
    """
        Delete a Gathering (fetched by ID), expected to be called by the specified client.

    Args:
        gatherings_db (Collection): The MongoDB collection where the gatherings are stored
        client (rmc.RMCClient): The caller client
        gid (int): The Gathering ID

    Raises:
        RendezVous::SessionVoid: The session with the specified GID doesn't exist
        RendezVous::PermissionDenied: The session isn't owned by the caller client.
    """
    gathering = gatherings_db.find_one({"id": gid})
    if not gathering:
        raise common.RMCError("RendezVous::SessionVoid")

    if gathering["owner"] != client.pid():
        raise common.RMCError("RendezVous::PermissionDenied")

    gatherings_db.delete_one({"id": gid})


# ============= Add / Remove in gatherings functions  =============


def add_user_to_gathering(gatherings_db: Collection, client: rmc.RMCClient, gid: int, message: str,
                          num_added: int = 1) -> Mapping[str, any]:
    """
    Add a client to a gathering (fetched by ID)

    Args:
        gatherings_db (Collection): The MongoDB collection where the gatherings are stored
        client (rmc.RMCClient): The caller client to be added in the gathering
        gid (int): The Gathering ID that the user will be added to
        message (str): The join message
        num_added (int): The number of players that will join (multiple controllers, guest, etc...)

    Returns:
        dict: The gathering with the changes applied to it

    Raises:
        RendezVous::SessionVoid: The session with the specified Gathering ID doesn't exist
        RendezVous::SessionFull: The session is full and cannot be joined with the specified amount of players
        RendezVous::AlreadyParticipatedGathering: The client is already participating in the Gathering
    """
    gathering = gatherings_db.find_one({"id": gid})
    if not gathering:
        raise common.RMCError("RendezVous::SessionVoid")

    return add_user_to_gathering_ex(gatherings_db, client, gathering, message, num_added)


def add_user_to_gathering_ex(gatherings_db: Collection, client: rmc.RMCClient, gathering: Mapping[str, any],
                             message: str, num_added: int = 1) -> Mapping[str, any]:
    """
    Add a user to the gathering (represented by a collection document)

    Args:
        gatherings_db (Collection): The MongoDB collection where the gatherings are stored
        client (rmc.RMCClient): The caller client to be added in the gathering
        gathering (dict): The document representing the gathering
        message (str): The join message
        num_added (int): The number of players that will join (multiple controllers, guest, etc...)

    Returns:
        dict: The gathering with the changes applied to it

    Raises:
        RendezVous::SessionVoid: The session with the specified Gathering ID doesn't exist
        RendezVous::SessionFull: The session is full and cannot be joined with the specified amount of players
        RendezVous::AlreadyParticipatedGathering: The client is already participating in the Gathering
    """
    if (len(gathering["players"]) + num_added) > gathering["max_participants"]:
        raise common.RMCError("RendezVous::SessionFull")

    if client.pid() in gathering["players"]:
        raise common.RMCError("RendezVous::AlreadyParticipatedGathering")

    pid_list = [client.pid()]
    for i in range(num_added - 1):
        pid_list.append(-client.pid())

    action = {"$push": {"players": {"$each": pid_list}}}
    if "num_participants" in gathering:
        action.update({"$inc": {"num_participants": num_added}})

    res = gatherings_db.update_one({"id": gathering["id"]}, action)
    if res.matched_count == 0:
        raise common.RMCError("RendezVous::SessionVoid")

    gathering["players"] += pid_list
    if "num_participants" in gathering:
        gathering["num_participants"] += num_added

    return gathering


def add_user_to_gathering_ex_by_pids(gatherings_db: Collection, client: rmc.RMCClient, gathering: Mapping[str, any], message: str,
                                     pids: list[int]) -> Mapping[str, any]:
    """
    Add users (by PID) to the gathering (represented by a collection document)

    Args:
        gatherings_db (Collection): The MongoDB collection where the gatherings are stored
        client (rmc.RMCClient): The caller client
        gathering (dict): _description_
        message (str): The join message
        pids (list[int]): The list of players that will join (multiple controllers, guest, etc...)

    Returns:
        dict: The gathering with the changes applied to it

    Raises:
        RendezVous::SessionVoid: The session with the specified Gathering ID doesn't exist
        RendezVous::SessionFull: The session is full and cannot be joined with the specified amount of players
    """
    num_added = len(pids)
    if (len(gathering["players"]) + num_added) > gathering["max_participants"]:
        raise common.RMCError("RendezVous::SessionFull")

    pid_list = pids
    action = {"$push": {"players": {"$each": pid_list}}}
    if "num_participants" in gathering:
        action.update({"$inc": {"num_participants": num_added}})

    res = gatherings_db.update_one({"id": gathering["id"]}, action)
    if res.matched_count == 0:
        raise common.RMCError("RendezVous::SessionVoid")

    gathering["players"] += pid_list
    if "num_participants" in gathering:
        gathering["num_participants"] += num_added

    return gathering


def remove_user_from_gathering(gatherings_db: Collection, client: rmc.RMCClient, gid: int, message: str) -> Mapping[
    str, any]:
    """
    Remove a user from the Gathering (specified by ID)

    Args:
        gatherings_db (Collection): The MongoDB collection where the gatherings are stored
        client (rmc.RMCClient): The caller client to be removed from the gathering
        gid (int): The Gathering ID that the user will be removed from
        message(str): The leaving message

    Returns:
        dict: The gathering with the changes applied to it

    Raises:
        RendezVous::SessionVoid: The session doesn't exist or doesn't contain the caller client
    """
    gathering = gatherings_db.find_one({"id": gid, "players": {"$in": [client.pid()]}})
    if not gathering:
        raise common.RMCError("RendezVous::SessionVoid")

    match_pid = [client.pid(), -client.pid()]
    num_appearance = 0
    for player in gathering["players"]:
        if player in match_pid:
            num_appearance += 1

    action = {"$pull": {"players": {"$in": match_pid}}}
    if "num_participants" in gathering:
        action.update({"$inc": {"num_participants": -num_appearance}})

    update_result = gatherings_db.update_one({"id": gid}, action)
    if update_result.modified_count != 0:
        while client.pid() in gathering["players"]:
            gathering["players"].remove(client.pid())
        while -client.pid() in gathering["players"]:
            gathering["players"].remove(-client.pid())
        gathering["num_participants"] -= num_appearance

        handle_gathering_player_removal(gatherings_db, client, gathering)

    return gathering


def remove_user_from_gathering_ex(gatherings_db: Collection, client: rmc.RMCClient, gathering: dict,
                                  message: str) -> dict:
    """
    Remove a user from the Gathering (specified by an exisiting Gathering document)

    Args:
        gatherings_db (Collection): The MongoDB collection where the gatherings are stored
        client (rmc.RMCClient): The caller client to be removed from the gathering
        gathering (dict): A document (dict) representing the gathering the player will be removed from
        message(str): The leaving message

    Returns:
        dict: The gathering with the changes applied to it
    """
    match_pid = [client.pid(), -client.pid()]
    num_appearance = 0
    for player in gathering["players"]:
        if player in match_pid:
            num_appearance += 1

    action = {"$pull": {"players": {"$in": match_pid}}}
    if "num_participants" in gathering:
        action.update({"$inc": {"num_participants": -num_appearance}})

    update_result = gatherings_db.update_one({"id": gathering["id"]}, action)
    if update_result.modified_count != 0:
        while client.pid() in gathering["players"]:
            gathering["players"].remove(client.pid())
        while -client.pid() in gathering["players"]:
            gathering["players"].remove(-client.pid())

        gathering["num_participants"] -= num_appearance

        handle_gathering_player_removal(gatherings_db, client, gathering)

    return gathering


def handle_gathering_player_removal(gatherings_db: Collection, client: rmc.RMCClient, gathering: Mapping[str, any]):
    if gathering["type"] == "PersistentGathering":
        if len(gathering["players"]) == 0:
            if gathering["flags"] & GatheringFlags.ALLOW_ZERO_PARTICIPANT:
                pass
            else:
                gatherings_db.delete_one({"id": gathering["id"]})
    else:
        if len(gathering["players"]) == 0:
            gatherings_db.delete_one({"id": gathering["id"]})
        elif client.pid() == gathering["owner"]:
            # Update owner if the old one disconnected
            # TODO: Trigger notifications ...
            # Not really an issue, because the clients handle that between each other
            gatherings_db.update_one({"id": gathering["id"]}, {"$set": {
                "owner": gathering["players"][0]
            }})
