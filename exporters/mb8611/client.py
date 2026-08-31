"""HTTP client for the MB8611.

Safety constraints from spec §10.1 are enforced here, not by the caller:
aggressive polling wedges the modem's web server and takes the internet
down. Single-flight, hard timeouts, and fail-soft are mandatory.
"""

import threading
import time

import requests
import urllib3

from . import hnap

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REQUEST_TIMEOUT_SECONDS = 10
MINIMUM_INTERVAL_SECONDS = 60


class MB8611Client:
    def __init__(self, host: str, username: str, password: str) -> None:
        self._url = f"https://{host}/HNAP1/"
        self._username = username
        self._password = password
        self._lock = threading.Lock()
        self._last_fetch = 0.0
        self._cached: dict | None = None

    def _login(self, session: requests.Session) -> str:
        action = '"http://purenetworks.com/HNAP1/Login"'
        response = session.post(
            self._url,
            json={"Login": {"Action": "request", "Username": self._username,
                            "LoginPassword": "", "Captcha": "",
                            "PrivateLogin": "LoginPassword"}},
            headers={"SOAPAction": action},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()["LoginResponse"]

        private_key = hnap.compute_private_key(
            payload["PublicKey"], self._password, payload["Challenge"])
        session.cookies.set("uid", payload["Cookie"])
        session.cookies.set("PrivateKey", private_key)

        session.post(
            self._url,
            json={"Login": {"Action": "login", "Username": self._username,
                            "LoginPassword": hnap.compute_login_password(
                                private_key, payload["Challenge"]),
                            "Captcha": "", "PrivateLogin": "LoginPassword"}},
            headers={
                "SOAPAction": action,
                "HNAP_AUTH": hnap.compute_auth_header(
                    private_key, "Login", int(time.time() * 1000)),
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        ).raise_for_status()
        return private_key

    def fetch_status(self) -> dict | None:
        """Fetch channel status, or None on any failure.

        Single-flight: concurrent callers get the cached result rather than
        issuing a second request. Rate-limited to MINIMUM_INTERVAL_SECONDS.
        """
        if not self._lock.acquire(blocking=False):
            return self._cached

        try:
            if time.time() - self._last_fetch < MINIMUM_INTERVAL_SECONDS:
                return self._cached

            session = requests.Session()
            session.verify = False
            try:
                private_key = self._login(session)
                response = session.post(
                    self._url,
                    json={"GetMultipleHNAPs": {
                        "GetMotoStatusDownstreamChannelInfo": "",
                        "GetMotoStatusUpstreamChannelInfo": "",
                        "GetMotoStatusConnectionInfo": ""}},
                    headers={
                        "SOAPAction":
                            '"http://purenetworks.com/HNAP1/GetMultipleHNAPs"',
                        "HNAP_AUTH": hnap.compute_auth_header(
                            private_key, "GetMultipleHNAPs",
                            int(time.time() * 1000)),
                    },
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                self._cached = response.json()["GetMultipleHNAPsResponse"]
            except Exception:
                self._cached = None
            finally:
                session.close()
                self._last_fetch = time.time()

            return self._cached
        finally:
            self._lock.release()
