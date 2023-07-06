from nintendo.nex import datastore, rmc, common
from pymongo.collection import Collection
from typing import Callable
import datetime
import pymongo


class CommonDataStoreServer(datastore.DataStoreServer):
    def __init__(self,
                 settings,
                 s3_client,
                 s3_endpoint_domain: str,
                 s3_bucket: str,
                 datastore_db: Collection,
                 sequence_db: Collection,
                 head_object_by_key: Callable[[str], tuple[bool, int, str]],
                 calculate_s3_object_key: Callable[[Collection, rmc.RMCClient, int, int], str],
                 calculate_s3_object_key_ex: Callable[[Collection, int, int, int], str]):
        super().__init__()
        self.settings = settings
        self.s3_client = s3_client
        self.s3_endpoint_domain = s3_endpoint_domain
        self.s3_bucket = s3_bucket
        self.datastore_db = datastore_db
        self.sequence_db = sequence_db
        self.head_object_by_key = head_object_by_key
        self.calculate_s3_object_key = calculate_s3_object_key
        self.calculate_s3_object_key_ex = calculate_s3_object_key_ex

        self.datastore_db.delete_many({"is_validated": False})

    def get_next_datastore_object_id(self) -> int:
        obj_id = self.sequence_db.find_one_and_update({"_id": "datastore_object_id"}, {"$inc": {"seq": 1}})["seq"]
        if obj_id == 0xffffffff:
            self.sequence_db.update_one({"_id": "datastore_object_id"}, {"$set": {"seq": 0}})

        return obj_id

    def validate_prepare_post_param(self, client, param: datastore.DataStorePreparePostParam):
        return True

    # ==================================================================================

    async def prepare_post_object(self, client, param: datastore.DataStorePreparePostParam) -> datastore.DataStoreReqPostInfo:

        self.validate_prepare_post_param(client, param)

        doc = {
            "id": self.get_next_datastore_object_id(),
            "owner": client.pid(),
            "data_type": param.data_type,
            "extra_data": param.extra_data,
            "flag": param.flag,
            "meta_binary": param.meta_binary,
            "name": param.name,
            "period": param.period,
            "refer_data_id": param.refer_data_id,
            "size": param.size,
            "tags": param.tags,
            "delete_permission": {
                "permission": param.delete_permission.permission,
                "recipients": param.delete_permission.recipients,
            },
            "access_permission": {
                "permission": param.permission.permission,
                "recipients": param.permission.recipients,
            },
            "persistence_id": param.persistence_init_param.persistence_id,
            "is_validated": False,
            "create_time": datetime.datetime.utcnow(),
            "update_time": datetime.datetime.utcnow(),
            "referred_time": datetime.datetime.utcnow(),
            "expire_time": datetime.datetime(9999, 12, 31),
        }

        ratings = []
        for rating in param.rating_init_param:
            ratings.append({
                "slot": rating.slot,
                "initial_value": rating.param.initial_value,
                "value": rating.param.initial_value,
                "min_val": rating.param.range_min,
                "max_val": rating.param.range_max,
                "lock_type": rating.param.lock_type,
                "period_duration": rating.param.period_duration,
                "period_hour": rating.param.period_hour,
                "count": 0,
            })

        doc.update({"ratings": ratings})

        self.datastore_db.insert_one(doc)

        s3_key = self.calculate_s3_object_key(self.datastore_db, client, param.persistence_init_param.persistence_id, doc["id"])
        response = self.s3_client.generate_presigned_post(Bucket=self.s3_bucket,
                                                          Key=s3_key,
                                                          ExpiresIn=(15 * 60),
                                                          Conditions=[["content-length-range", param.size, param.size], {"x-amz-security-token": ""}])

        fields = response["fields"]

        res = datastore.DataStoreReqPostInfo()
        res.url = "https://%s.%s" % (self.s3_bucket, self.s3_endpoint_domain)
        res.form = []
        res.headers = []
        res.data_id = doc["id"]
        res.root_ca_cert = b""

        field_key = datastore.DataStoreKeyValue()
        field_key.key = "key"
        field_key.value = fields["key"]

        field_credential = datastore.DataStoreKeyValue()
        field_credential.key = "X-Amz-Credential"
        field_credential.value = fields["x-amz-credential"]

        field_date = datastore.DataStoreKeyValue()
        field_date.key = "X-Amz-Date"
        field_date.value = fields["x-amz-date"]

        field_security_token = datastore.DataStoreKeyValue()
        field_security_token.key = "X-Amz-Security-Token"
        field_security_token.value = ""

        field_algorithm = datastore.DataStoreKeyValue()
        field_algorithm.key = "X-Amz-Algorithm"
        field_algorithm.value = fields["x-amz-algorithm"]

        field_policy = datastore.DataStoreKeyValue()
        field_policy.key = "policy"
        field_policy.value = fields["policy"]

        field_signature = datastore.DataStoreKeyValue()
        field_signature.key = "X-Amz-Signature"
        field_signature.value = fields["x-amz-signature"]

        res.form = [
            field_key,
            field_credential,
            field_security_token,
            field_algorithm,
            field_date,
            field_policy,
            field_signature
        ]

        return res

    async def complete_post_object(self, client, param: datastore.DataStoreCompletePostParam):
        if param.success:
            datastore_object = self.datastore_db.find_one({"id": param.data_id})
            if datastore_object and (client.pid() == datastore_object["owner"]):
                persistence_id = datastore_object["persistence_id"]
                success, _, _ = self.head_object_by_key(self.calculate_s3_object_key(self.datastore_db, client, persistence_id, param.data_id))
                if success:
                    self.datastore_db.update_one({"id": param.data_id}, {"$set": {"is_validated": True}})

    async def prepare_update_object(self, client, param: datastore.DataStorePrepareUpdateParam):

        obj = self.datastore_db.find_one({"id": param.data_id})
        if not obj:
            raise common.RMCError("DataStore::NotFound")

        if client.pid() != obj["owner"]:
            raise common.RMCError("DataStore::PermissionDenied")

        s3_key = self.calculate_s3_object_key(self.datastore_db, client, obj["persistence_id"], param.data_id)
        response = self.s3_client.generate_presigned_post(Bucket=self.s3_bucket,
                                                          Key=s3_key,
                                                          ExpiresIn=(15 * 60),
                                                          Conditions=[["content-length-range", param.size, param.size], {"x-amz-security-token": ""}])

        fields = response["fields"]

        res = datastore.DataStoreReqUpdateInfo()
        res.url = "https://%s.%s" % (self.s3_bucket, self.s3_endpoint_domain)
        res.form = []
        res.headers = []
        res.root_ca_cert = b""
        res.version = 2

        field_key = datastore.DataStoreKeyValue()
        field_key.key = "key"
        field_key.value = fields["key"]

        field_credential = datastore.DataStoreKeyValue()
        field_credential.key = "X-Amz-Credential"
        field_credential.value = fields["x-amz-credential"]

        field_date = datastore.DataStoreKeyValue()
        field_date.key = "X-Amz-Date"
        field_date.value = fields["x-amz-date"]

        field_security_token = datastore.DataStoreKeyValue()
        field_security_token.key = "X-Amz-Security-Token"
        field_security_token.value = ""

        field_algorithm = datastore.DataStoreKeyValue()
        field_algorithm.key = "X-Amz-Algorithm"
        field_algorithm.value = fields["x-amz-algorithm"]

        field_policy = datastore.DataStoreKeyValue()
        field_policy.key = "policy"
        field_policy.value = fields["policy"]

        field_signature = datastore.DataStoreKeyValue()
        field_signature.key = "X-Amz-Signature"
        field_signature.value = fields["x-amz-signature"]

        res.form = [
            field_key,
            field_credential,
            field_security_token,
            field_algorithm,
            field_date,
            field_policy,
            field_signature
        ]

        self.datastore_db.update_one({"id": param.data_id}, {"$set": {"is_validated": False, "update_size": param.size}})

        return res

    async def complete_update_object(self, client, param: datastore.DataStoreCompleteUpdateParam):
        if param.success:
            datastore_object = self.datastore_db.find_one({"id": param.data_id})
            if datastore_object and (client.pid() == datastore_object["owner"]):
                persistence_id = datastore_object["persistence_id"]
                success, _, _ = self.head_object_by_key(self.calculate_s3_object_key(self.datastore_db, client, persistence_id, param.data_id))
                if success:
                    self.datastore_db.update_one({"id": param.data_id}, {"$set": {"is_validated": True, "size": datastore_object["update_size"]}})

    async def prepare_get_object(self, client, param: datastore.DataStorePrepareGetParam) -> datastore.DataStoreReqGetInfo:
        query = {}
        if param.persistence_target.owner_id:
            query.update({"owner": param.persistence_target.owner_id})

        if param.data_id:
            query.update({"id": param.data_id})

        if param.persistence_target.persistence_id:
            query.update({"persistence_id": param.persistence_target.persistence_id})

        obj = self.datastore_db.find_one(query)
        if not obj:
            raise common.RMCError("DataStore::NotFound")

        success, size, url = self.head_object_by_key(self.calculate_s3_object_key_ex(
            self.datastore_db,
            param.persistence_target.owner_id,
            param.persistence_target.persistence_id,
            obj["id"]))

        if not success:
            raise common.RMCError("DataStore::NotFound")

        res = datastore.DataStoreReqGetInfo()
        res.url = url
        res.size = size
        res.data_id = obj["id"]
        res.headers = []
        res.root_ca_cert = b""

        return res

    async def search_object(self, client, param: datastore.DataStoreSearchParam):

        if param.result_range.size > 100:
            raise common.RMCError("DataStore::InvalidArgument")

        # TODO: Support created/updated before/after queries
        query = {"data_type": param.data_type}
        cursor = self.datastore_db.find(query).skip(param.result_range.offset).limit(param.result_range.size)

        if param.result_order_column == 5:  # Creation date:
            cursor = cursor.sort("create_time", pymongo.DESCENDING)
        elif param.result_order_column == 64:
            cursor = cursor.sort("ratings.0.value", pymongo.DESCENDING)

        objects = list(cursor)

        search_result = datastore.DataStoreSearchResult()
        search_result.total_count = len(objects)
        search_result.total_count_type = len(objects)
        search_result.result = []

        for obj in objects:
            meta = datastore.DataStoreMetaInfo()
            meta.meta_binary = b''
            meta.status = 0
            meta.referred_count = 0
            meta.refer_data_id = 0
            meta.ratings = []

            meta.data_id = obj["id"]
            meta.owner_id = obj["owner"]
            meta.name = obj["name"]
            meta.size = obj["size"]
            meta.data_type = obj["data_type"]
            meta.flag = obj["flag"]
            meta.period = obj["period"]
            meta.tags = obj["tags"]

            if param.result_option & 4:
                meta.meta_binary = obj["meta_binary"]

            meta.permission.permission = obj["access_permission"]["permission"]
            meta.permission.recipients = obj["access_permission"]["recipients"]
            meta.delete_permission.recipients = obj["delete_permission"]["recipients"]
            meta.delete_permission.recipients = obj["delete_permission"]["recipients"]

            meta.create_time = common.DateTime.fromtimestamp(datetime.datetime.timestamp(obj["create_time"]))
            meta.update_time = common.DateTime.fromtimestamp(datetime.datetime.timestamp(obj["update_time"]))
            meta.referred_time = common.DateTime.fromtimestamp(datetime.datetime.timestamp(obj["referred_time"]))
            meta.expire_time = common.DateTime.fromtimestamp(datetime.datetime.timestamp(obj["create_time"]))

            for rating in obj["ratings"]:
                rate = datastore.DataStoreRatingInfoWithSlot()
                rate.slot = rating["slot"]
                rate.info.initial_value = rating["initial_value"]
                rate.info.total_value = rating["value"]
                rate.info.count = rating["count"]
                meta.ratings.append(rate)

            search_result.result.append(meta)

        return search_result

    async def change_meta(self, client, param: datastore.DataStoreChangeMetaParam):
        obj = self.datastore_db.find_one({"id": param.data_id})
        if not obj:
            raise common.RMCError("DataStore::NotFound")

        if client.pid() != obj["owner"]:
            raise common.RMCError("DataStore::PermissionDenied")

        query = {}
        if param.modifies_flag & 0x08:
            query.update({"period": param.period})

        if param.modifies_flag & 0x10:
            query.update({"meta_binary": param.meta_binary})

        if param.modifies_flag & 0x80:
            query.update({"data_type": param.data_type})

        if query != {}:
            self.datastore_db.update_one({"id": obj["id"]}, {"$set": query})

    async def get_metas_multiple_param(self, client, params: list[datastore.DataStoreGetMetaParam]):

        if len(params) > 100:
            raise common.RMCError("DataStore::InvalidArgument")

        results = []
        infos = []
        for param in params:

            """
                We will ignore permissions and result options
            """

            query = {"owner": param.persistence_target.owner_id}
            if param.data_id:
                query.update({"id": param.data_id})

            if param.persistence_target.persistence_id:
                query.update({"persistence_id": param.persistence_target.persistence_id})

            meta = datastore.DataStoreMetaInfo()
            meta.data_id = 0
            meta.owner_id = 0
            meta.size = 0
            meta.name = ""
            meta.data_type = 0
            meta.meta_binary = b''
            meta.permission = datastore.DataStorePermission()
            meta.delete_permission = datastore.DataStorePermission()
            meta.create_time = common.DateTime(0)
            meta.update_time = common.DateTime(0)
            meta.period = 0
            meta.status = 0
            meta.referred_count = 0
            meta.refer_data_id = 0
            meta.flag = 0
            meta.referred_time = common.DateTime(0)
            meta.expire_time = common.DateTime(0)
            meta.tags = []
            meta.ratings = []

            obj = self.datastore_db.find_one(query)
            if not obj:
                results.append(common.Result.error("DataStore::NotFound"))
                infos.append(meta)

            meta.data_id = obj["id"]
            meta.owner_id = obj["owner"]
            meta.name = obj["name"]
            meta.size = obj["size"]
            meta.data_type = obj["data_type"]
            meta.flag = obj["flag"]
            meta.period = obj["period"]
            meta.tags = obj["tags"]

            if param.result_option & 4:
                meta.meta_binary = obj["meta_binary"]

            meta.permission.permission = obj["access_permission"]["permission"]
            meta.permission.recipients = obj["access_permission"]["recipients"]
            meta.delete_permission.recipients = obj["delete_permission"]["recipients"]
            meta.delete_permission.recipients = obj["delete_permission"]["recipients"]

            meta.create_time = common.DateTime.fromtimestamp(datetime.datetime.timestamp(obj["create_time"]))
            meta.update_time = common.DateTime.fromtimestamp(datetime.datetime.timestamp(obj["update_time"]))
            meta.referred_time = common.DateTime.fromtimestamp(datetime.datetime.timestamp(obj["referred_time"]))
            meta.expire_time = common.DateTime.fromtimestamp(datetime.datetime.timestamp(obj["create_time"]))

            for rating in obj["ratings"]:
                rate = datastore.DataStoreRatingInfoWithSlot()
                rate.slot = rating["slot"]
                rate.info.initial_value = rating["initial_value"]
                rate.info.total_value = rating["value"]
                rate.info.count = rating["count"]
                meta.ratings.append(rate)

            results.append(common.Result.success("DataStore::Unknown"))
            infos.append(meta)

        res = rmc.RMCResponse()
        res.results = results
        res.infos = infos

        return res

    async def rate_object(self, client, target: datastore.DataStoreRatingTarget, param: datastore.DataStoreRateObjectParam, fetch_ratings: bool):

        obj = self.datastore_db.find_one({"id": target.data_id})
        if not obj:
            raise common.RMCError("DataStore::NotFound")

        if len(obj["ratings"]) <= target.slot:
            raise common.RMCError("DataStore::InvalidArgument")

        rating_target = "ratings.%d" % target.slot
        self.datastore_db.update_one({"id": target.data_id}, {
            "$inc": {
                rating_target + ".value": param.rating_value,
                rating_target + ".count": 1
            }
        })

        res = datastore.DataStoreRatingInfo()
        res.total_value = obj["ratings"][target.slot]["value"] + param.rating_value
        res.count = obj["ratings"][target.slot]["count"] + 1
        res.initial_value = obj["ratings"][target.slot]["initial_value"]

        return res

    async def get_object_infos(self, client, object_ids: list[int]):
        res = rmc.RMCResponse()
        res.infos = []
        res.results = []

        for object_id in object_ids:

            info = datastore.DataStoreReqGetInfo()
            info.url = ""
            info.headers = []
            info.data_id = object_id
            info.size = 0
            info.root_ca_cert = b""

            obj = self.datastore_db.find_one({"id": object_id})
            if not obj:
                res.infos.append(info)
                res.results.append(common.Result.error("DataStore::NotFound"))
                continue

            success, size, url = self.head_object_by_key(self.calculate_s3_object_key_ex(
                self.datastore_db, obj["owner"], obj["persistence_id"], obj["id"]))

            if not success:
                res.infos.append(info)
                res.results.append(common.Result.error("DataStore::NotFound"))
                continue

            info.url = url
            info.size = size

            res.infos.append(info)
            res.results.append(common.Result.success("DataStore::Unknown"))

        return res
