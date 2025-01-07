import secrets
from datetime import datetime, timezone
from typing import Callable

from nintendo.nex import rmc, kerberos, authentication, common

from nex_protocols_common_py.context import Context, AuthenticationUser


class CommonAuthenticationServer(authentication.AuthenticationServer):
    def __init__(self,
                 context: Context,
                 build_string: str,
                 get_nex_password_func: Callable[[int], str],
                 auth_callback: Callable[[AuthenticationUser], common.Result] = None):

        super().__init__()

        self.context = context
        self.build_string = build_string
        self.get_nex_password_func = get_nex_password_func
        self.auth_callback = auth_callback

    # ============= Utility functions  =============

    @staticmethod
    def derive_key(user: AuthenticationUser):
        deriv = kerberos.KeyDerivationOld(65000, 1024)
        return deriv.derive_key(user.password.encode("ascii"), user.pid)

    def generate_ticket(self, source: AuthenticationUser, target: AuthenticationUser):
        user_key = self.derive_key(source)
        server_key = self.derive_key(target)
        session_key = secrets.token_bytes(self.context.settings["kerberos.key_size"])

        internal = kerberos.ServerTicket()
        internal.timestamp = common.DateTime.now()
        internal.source = source.pid
        internal.session_key = session_key

        ticket = kerberos.ClientTicket()
        ticket.session_key = session_key
        ticket.target = target.pid
        ticket.internal = internal.encrypt(server_key, self.context.settings)

        return ticket.encrypt(user_key, self.context.settings)

    def get_special_user(self, pid: int):
        for u in self.context.special_users:
            if u.pid == pid:
                return u

    def get_user_from_pid(self, pid: int):
        try:
            password = self.get_nex_password_func(pid)
            return AuthenticationUser(pid, str(pid), password)
        except:
            pass

    # ============= Method implementations  =============

    async def login(self, client, username):
        print("User trying to log in:", username)

        user = self.get_user_from_pid(int(username))
        if not user:
            raise common.RMCError("RendezVous::InvalidUsername")

        server = self.get_special_user(2)  # Special user: Quazal Rendez-Vous
        if not server:
            raise common.RMCError("Core::NotImplemented")

        error = common.Result.success()
        if self.auth_callback:
            error = self.auth_callback(user)
            error.raise_if_error()

        url = common.StationURL(
            scheme="prudps",
            address=self.context.server_info.secure_host,
            port=self.context.server_info.secure_port,
            PID=server.pid, CID=1, type=2,
            sid=1, stream=10
        )

        conn_data = authentication.RVConnectionData()
        conn_data.main_station = url
        conn_data.special_protocols = []
        conn_data.special_station = common.StationURL()
        conn_data.server_time = common.DateTime.fromtimestamp(datetime.now(timezone.utc).timestamp())

        response = rmc.RMCResponse()
        response.result = error
        response.pid = user.pid
        response.ticket = self.generate_ticket(user, server) if error.is_success() else b""
        response.connection_data = conn_data
        response.server_name = self.build_string
        return response

    # Wii U servers don't seem to check what's in the extra data.
    async def login_ex(self, client, username, extra_data):
        print("User trying to log in:", username)

        user = self.get_user_from_pid(int(username))
        if not user:
            raise common.RMCError("RendezVous::InvalidUsername")

        server = self.get_special_user(pid=2)  # Special user: Quazal Rendez-Vous
        if not server:
            raise common.RMCError("Core::NotImplemented")

        error = common.Result.success()
        if self.auth_callback:
            error = self.auth_callback(user)

        url = common.StationURL(
            scheme="prudps",
            address=self.context.server_info.secure_host,
            port=self.context.server_info.secure_port,
            PID=server.pid, CID=1, type=2,
            sid=1, stream=10
        )

        conn_data = authentication.RVConnectionData()
        conn_data.main_station = url
        conn_data.special_protocols = []
        conn_data.special_station = common.StationURL()
        conn_data.server_time = common.DateTime.fromtimestamp(datetime.now(timezone.utc).timestamp())

        response = rmc.RMCResponse()
        response.result = error
        response.pid = user.pid
        response.ticket = self.generate_ticket(user, server) if error.is_success() else b""
        response.connection_data = conn_data
        response.server_name = self.build_string
        return response

    async def request_ticket(self, client, source, target):
        print("User trying to request ticket:", source, target)

        user = self.get_user_from_pid(source)
        if not user:
            raise common.RMCError("Core::AccessDenied")

        server = self.get_special_user(target)  # Special user: Quazal Rendez-Vous
        if not server:
            raise common.RMCError("Core::AccessDenied")

        response = rmc.RMCResponse()
        response.result = common.Result.success()
        response.ticket = self.generate_ticket(user, server)
        return response
