from minio import Minio
from nintendo.nex.settings import Settings
from pymongo.database import Database
from redis import Redis


class AuthenticationUser:
    def __init__(self,
                 pid: int,
                 name: str,
                 password: str):
        """
        Create a new AuthenticationUser object
        :param pid: User PID
        :param name: Username
        :param password: User password
        """
        self.pid = pid
        self.name = name
        self.password = password


class ServerInfo:
    def __init__(self,
                 auth_host: str,
                 auth_port: int,
                 secure_host: str,
                 secure_port: int):
        """
        Creates a new ServerInfo object (used for storing server host/port information)
        :param auth_host: Authentication server host
        :param auth_port: Authentication server port
        :param secure_host: Secure server host
        :param secure_port: Secure server port
        """
        self.auth_host = auth_host
        self.auth_port = auth_port
        self.secure_host = secure_host
        self.secure_port = secure_port


class Context:
    def __init__(self,
                 settings: Settings,
                 server_info: ServerInfo,
                 database: Database,
                 s3_client: Minio,
                 s3_bucket: str,
                 redis_client: Redis,
                 special_users: list[AuthenticationUser]):
        self.settings = settings
        self.server_info = server_info
        self.database = database
        self.s3_client = s3_client
        self.s3_bucket = s3_bucket
        self.redis_client = redis_client
        self.special_users = special_users
