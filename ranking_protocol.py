import functools
from datetime import datetime, timezone
from typing import Callable

import bson
import pymongo
from nintendo.nex import rmc, ranking, common
from pymongo.collection import Collection

from nex_protocols_common_py.context import Context


class RankingManager:
    def __init__(self, context: Context):
        self.context = context
        self.rankings_db = context.database["rankings"]
        self.redis_db = context.redis_client
        self.commondata_db = context.database["commondata"]

        self.rankings_db.create_index([("pid", pymongo.ASCENDING), ("category", pymongo.ASCENDING)])

        self.standard_rank_by_score_script = self.redis_db.register_script("""
            local sum = 0
            local z = redis.call('ZRANGE', KEYS[1], 1, '+inf', 'BYSCORE', 'WITHSCORES')
            local is_desc = (ARGV[1] == 'REV') and true or false
            local comp_score = tonumber(ARGV[2])
            for i=2, #z, 2
            do
                if is_desc then
                    if tonumber(z[i-1]) > comp_score then
                        sum=sum+z[i]
                    end
                else
                    if tonumber(z[i-1]) < comp_score then
                        sum=sum+z[i]
                    end
                end
            end

            return sum
        """)

    @staticmethod
    def get_redis_member_name(category: int, unique: bool = False):
        if unique:
            return "leaderboard_unique:%d" % category
        else:
            return "leaderboard:%d" % category

    @staticmethod
    def revert_original_object_id_order(target: list, orig: list):
        def sort_lambda(a, b):
            a_idx = orig.index(a["_id"])
            b_idx = orig.index(b["_id"])

            if a_idx > b_idx:
                return 1
            elif a_idx < b_idx:
                return -1
            else:
                return 0

        target.sort(key=functools.cmp_to_key(sort_lambda))

    def get_standard_rank_by_score(self, category: int, score: int, desc: bool = False):
        return self.standard_rank_by_score_script([self.get_redis_member_name(category, True)],
                                                  ['REV' if desc else '', score]) + 1

    def set_score(self, client: rmc.RMCClient, score_data: ranking.RankingScoreData, unique_id: int,
                  replace_all: bool = True):
        """Insert a user score in the database (MongoDB and Redis)

        Args:
            client (rmc.RMCClient): The caller client
            score_data (ranking.RankingScoreData): The score data
            unique_id (int): Unique ID (unused.)
            replace_all (bool, optional): Delete all previous scores. Defaults to True.
        """

        self.set_score_for_pid(client.pid(), score_data, unique_id, replace_all)

    def set_score_for_pid(self,
                          pid: int,
                          score_data: ranking.RankingScoreData,
                          unique_id: int,
                          replace_all: bool = True):
        """Insert a user score in the database based on PID (MongoDB and Redis)

        Args:
            pid (int): The score owner
            score_data (ranking.RankingScoreData): The score data
            unique_id (int): Unique ID (unused.)
            replace_all (bool, optional): Delete all previous scores. Defaults to True.
        """

        if replace_all:
            self.delete_scores(pid, score_data.category)

        insert_result = self.rankings_db.insert_one({
            "pid": pid,
            "category": score_data.category,
            "score": score_data.score,
            "groups": score_data.groups,
            "insert_time": datetime.now(timezone.utc)
        })

        pipeline = self.redis_db.pipeline()
        pipeline.zadd(self.get_redis_member_name(score_data.category),
                      {str(insert_result.inserted_id): score_data.score})
        pipeline.zadd(self.get_redis_member_name(score_data.category, True), {str(score_data.score): 1}, incr=True)

        pipeline.execute()

    def delete_scores(self, pid: int, category: int):
        registered_scores = list(self.rankings_db.find({"pid": pid, "category": category}))
        self.rankings_db.delete_many({"pid": pid, "category": category})

        pipeline = self.redis_db.pipeline()
        id_list = list(map(lambda x: str(x["_id"]), registered_scores))
        if len(id_list) > 0:
            pipeline.zrem(self.get_redis_member_name(category), *id_list)

        for score in registered_scores:
            pipeline.zadd(self.get_redis_member_name(category, True), {str(score["score"]): -1}, incr=True)

        pipeline.execute()

    def delete_all_scores(self, pid: int):
        registered_scores = list(self.rankings_db.find({"pid": pid}))
        categories = list(map(lambda x: x["category"], registered_scores))

        for category in categories:
            self.delete_scores(pid, category)

    def get_scores_document_by_query(self, query: dict, desc: bool = False, limit: int = 200) -> list:
        return list(self.rankings_db.aggregate([
            {
                "$match": query
            },  # Match by query
            {
                "$limit": limit
            },  # Limit number of entries
            {
                "$sort": {
                    "score": -1 if desc else 1
                }
            },  # Sort entries
            {
                "$lookup": {
                    "from": self.commondata_db.name,
                    "localField": "pid",
                    "foreignField": "pid",
                    "as": "user_common_data"
                },
            },  # Join user ranking common data
            {
                "$unwind": "$user_common_data"
            },  # Don't put the user data in an array
            {
                "$project": {
                    "pid": 1,
                    "category": 1,
                    "score": 1,
                    "groups": 1,
                    "insert_time": 1,
                    "data": "$user_common_data.data",
                }
            },  # Projection settings
        ]))

    """

        Examples of the ranking system used by Nintendo (assuming Ascending ordering)

        Standard ranking:

        +-------+------+
        | score | rank |
        +-------+------+
        | 123   | 1    |
        | 178   | 2    |
        | 178   | 2    |
        | 196   | 4    |
        +-------+------+

        Ordinal ranking:

        If same score, order by time (older > younger), Redis insertion orders should maintain that (?)

        +-------+------+
        | score | rank |
        +-------+------+
        | 123   | 1    |
        | 178   | 2    | Score made in 2022
        | 178   | 3    | Score made in 2023
        | 196   | 4    |
        +-------+------+

    """

    def get_scores_by_range(self,
                            category: int,
                            offset: int,
                            count: int,
                            desc: bool = False,
                            additional_query=None):
        if additional_query is None:
            additional_query = {}

        leaders = self.redis_db.zrange(self.get_redis_member_name(category), offset, offset + count - 1, desc)
        oid_list = list(map(lambda x: bson.ObjectId(x.decode()), leaders))

        query = {"_id": {"$in": oid_list}}
        query.update(additional_query)

        score_list = self.get_scores_document_by_query(query, desc)
        RankingManager.revert_original_object_id_order(score_list, oid_list)

        return score_list

    def get_scores_by_range_standard(self,
                                     category: int,
                                     offset: int,
                                     count: int,
                                     desc: bool = False,
                                     additional_query=None) -> list[dict]:

        score_list = self.get_scores_by_range(category, offset, count, desc, additional_query)

        res = []
        if len(score_list) > 0:
            base_rank = self.get_standard_rank_by_score(category, score_list[0]["score"], desc)
            count = 0
            last_score = score_list[0]["score"]
            for i in range(0, len(score_list)):
                if score_list[i]["score"] == last_score:
                    count += 1
                else:
                    base_rank += count
                    count = 1

                last_score = score_list[i]["score"]
                res.append({base_rank: score_list[i]})

        return res

    def get_scores_by_range_ordinal(self,
                                    category: int,
                                    offset: int,
                                    count: int,
                                    desc: bool = False,
                                    additional_query=None) -> list[dict]:

        score_list = self.get_scores_by_range(category, offset, count, desc, additional_query)

        res = []
        for i in range(len(score_list)):
            res.append({offset + 1 + i: score_list[i]})

        return res

    def get_top_score_for_pid_standard(self,
                                       pid: int,
                                       category: int,
                                       desc: bool,
                                       additional_query=None) -> list[dict]:

        if additional_query is None:
            additional_query = {}

        query = {"pid": pid, "category": category}
        query.update(additional_query)

        best_score = self.get_scores_document_by_query(query, desc, 1)
        if len(best_score) > 0:
            return [{self.get_standard_rank_by_score(category, best_score[0]["score"], desc): best_score[0]}]

        return []

    def get_top_score_for_pid_ordinal(self,
                                      pid: int,
                                      category: int,
                                      desc: bool,
                                      additional_query=None) -> list[dict]:

        if additional_query is None:
            additional_query = {}

        query = {"pid": pid, "category": category}
        query.update(additional_query)

        best_score = self.get_scores_document_by_query(query, desc, 1)
        if len(best_score) > 0:
            if desc:
                rank = self.redis_db.zrevrank(self.get_redis_member_name(category), str(best_score[0]["_id"]))
            else:
                rank = self.redis_db.zrank(self.get_redis_member_name(category), str(best_score[0]["_id"]))

            return [{rank + 1: best_score[0]}]

        return []

    def get_scores_around_user_standard(self,
                                        pid: int,
                                        category: int,
                                        num: int,
                                        desc: bool = False,
                                        additional_query=None) -> list[dict]:
        if additional_query is None:
            additional_query = {}

        res = []
        best_score = self.get_top_score_for_pid_ordinal(pid, category, desc, additional_query)
        if best_score:

            rank = list(best_score[0].keys())[0]
            start_offset = rank - (num // 2) - (num % 2)
            if start_offset < 0:
                start_offset = 0

            scores = self.get_scores_by_range_ordinal(category, start_offset, num, desc, additional_query)
            score_list = list(map(lambda x: list(x.values())[0], scores))

            if len(score_list) > 0:
                base_rank = self.get_standard_rank_by_score(category, score_list[0]["score"], desc)
                count = 0
                last_score = score_list[0]["score"]
                for i in range(0, len(score_list)):
                    if score_list[i]["score"] == last_score:
                        count += 1
                    else:
                        base_rank += count
                        count = 1

                    last_score = score_list[i]["score"]
                    res.append({base_rank: score_list[i]})

        return res

    def get_scores_around_user_ordinal(self,
                                       pid: int,
                                       category: int,
                                       num: int,
                                       desc: bool = False,
                                       additional_query=None) -> list[dict]:
        if additional_query is None:
            additional_query = {}

        best_score = self.get_top_score_for_pid_ordinal(pid, category, desc, additional_query)
        if best_score:

            rank = list(best_score[0].keys())[0]
            start_offset = rank - (num // 2) - (num % 2)
            if start_offset < 0:
                start_offset = 0

            return self.get_scores_by_range_ordinal(category, start_offset, num, desc, additional_query)

        return []


class CommonRankingServer(ranking.RankingServer):
    def __init__(self,
                 context: Context,
                 common_data_handler: Callable[[Collection, int, bytes, int], bool],
                 rankings_category: dict[int, bool]):
        super().__init__()
        self.context = Context

        self.rankings_db = context.database["rankings"]
        self.commondata_db = context.database["commondata"]
        self.redis_instance = context.redis_client
        self.common_data_handler = common_data_handler
        self.rankings_category = rankings_category

        self.ranking_mgr = RankingManager(context)

    # ============= Utility functions  =============

    # Implement and Raise a RMCError if the score is invalid.
    @staticmethod
    def validate_ranking_score(client, score_data: ranking.RankingScoreData, unique_id: int) -> bool:
        return True

    def is_category_ordered_desc(self, category: int) -> bool:
        if category in self.rankings_category.keys() and self.rankings_category[category] == False:
            return False
        return True

    def store_common_data_for_pid(self, pid: int, data: bytes, unique_id: int):
        self.commondata_db.find_one_and_replace({"pid": pid}, {
            "pid": pid,
            "data": bson.Binary(data),
            "size": len(data),
            "unique_id": unique_id,
            "last_update": datetime.now(timezone.utc)
        }, upsert=True)

    # ============= Method implementations  =============

    async def upload_score(self, client, score_data: ranking.RankingScoreData, unique_id):
        self.validate_ranking_score(client, score_data, unique_id)
        self.ranking_mgr.set_score(client, score_data, unique_id, score_data.update_mode == 1)

    async def get_ranking(self, client, mode: ranking.RankingMode, category: int, order: ranking.RankingOrderParam,
                          unique_id, pid) -> ranking.RankingResult:

        if order.count > 1000:
            raise common.RMCError("Core::InvalidArgument")

        query = {}
        if order.group_index in [0, 1]:
            query.update({"groups.%d" % order.group_index: order.group_num})

        desc = True if self.is_category_ordered_desc(category) else False

        res = ranking.RankingResult()
        res.data = []
        res.total = 1337
        res.since_time = common.DateTime.make(year=2011)

        lookup_pid = pid if pid != 0 else client.pid()
        if mode == ranking.RankingMode.GLOBAL:
            if order.order_calc == 0:
                scores = self.ranking_mgr.get_scores_by_range_standard(category, order.offset, order.count, desc, query)
            else:
                scores = self.ranking_mgr.get_scores_by_range_ordinal(category, order.offset, order.count, desc, query)
        elif mode == ranking.RankingMode.SELF:
            if order.order_calc == 0:
                scores = self.ranking_mgr.get_top_score_for_pid_standard(lookup_pid, category, desc)
            else:
                scores = self.ranking_mgr.get_top_score_for_pid_ordinal(lookup_pid, category, desc)
        elif mode == ranking.RankingMode.GLOBAL_AROUND_SELF:
            if order.order_calc == 0:
                scores = self.ranking_mgr.get_scores_around_user_standard(lookup_pid, category, order.count, desc)
            else:
                scores = self.ranking_mgr.get_scores_around_user_ordinal(lookup_pid, category, order.count, desc)
        else:
            raise common.RMCError("Core::NotImplemented")

        for score in scores:
            rank = list(score.keys())[0]
            score_data = list(score.values())[0]
            rk_data = ranking.RankingRankData()
            rk_data.pid = score_data["pid"]
            rk_data.unique_id = 0
            rk_data.rank = rank
            rk_data.category = category
            rk_data.score = score_data["score"]
            rk_data.groups = score_data["groups"]
            rk_data.param = 0
            rk_data.common_data = score_data["data"]
            rk_data.update_time = common.DateTime.fromtimestamp(datetime.timestamp(score_data["insert_time"]))
            res.data.append(rk_data)

        return res

    async def upload_common_data(self, client: rmc.RMCClient, common_data: bytes, unique_id: int):

        if len(common_data) > 0x200:
            raise common.RMCError("Ranking::InvalidDataSize")

        if (not self.common_data_handler) or not self.common_data_handler(self.commondata_db, client.pid(), common_data,
                                                                          unique_id):
            self.store_common_data_for_pid(client.pid(), common_data, unique_id)
