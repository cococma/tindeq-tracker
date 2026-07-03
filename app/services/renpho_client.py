"""Minimal client for Renpho's private cloud API.

Reverse-engineered — same approach as the Home Assistant Renpho integrations
(antoinebou12/hass_renpho lineage): sign in with the account email and the
password RSA-encrypted against Renpho's well-known public key, then page
measurements with a last_at cursor. May break if Renpho changes their API;
the CSV importer is the fallback path.
"""

import base64

import httpx
import rsa

API_BASE = "https://renpho.qnclouds.com"
APP_ID = "Renpho"

# Renpho's published RSA public key (hardcoded in their apps; widely known).
PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC+25I2upukpfQ7rIaaTZtVE744
u2zV+HaagrUhDOTq8fMVf9yFQvEZh2/HKxFudUxP0dXUa8F6X4XmWumHdQnum3zm
Jr04fz2b2WCcN0ta/rbF2nYAnMVAk2OJVZAMudOiMWhcxV1nNJiKgTNNr13de0EQ
IiOL2CUBzu+HmIfUbQIDAQAB
-----END PUBLIC KEY-----"""

# Renpho measurement field -> our metric code.
FIELD_TO_METRIC = {
    "weight": "weight_kg",
    "bodyfat": "body_fat_pct",
    "water": "water_pct",
    "bmi": "bmi",
    "muscle": "skeletal_muscle_pct",
    "sinew": "muscle_mass_kg",
    "bone": "bone_mass_kg",
    "subfat": "subcutaneous_fat_pct",
    "visfat": "visceral_fat",
    "bmr": "bmr_kcal",
    "protein": "protein_pct",
    "bodyage": "metabolic_age",
}


class RenphoError(Exception):
    pass


def _encrypt_password(password: str) -> str:
    key = rsa.PublicKey.load_pkcs1_openssl_pem(PUBLIC_KEY_PEM)
    return base64.b64encode(rsa.encrypt(password.encode(), key)).decode()


class RenphoClient:
    def __init__(self, email: str, password: str, timeout: float = 20.0):
        self._email = email
        self._password = password
        self._http = httpx.Client(base_url=API_BASE, timeout=timeout)
        self._session_key = None
        self._user_id = None

    def sign_in(self):
        resp = self._http.post(
            "/api/v3/users/sign_in.json",
            params={"app_id": APP_ID},
            json={
                "secure_flag": 1,
                "email": self._email,
                "password": _encrypt_password(self._password),
            },
        )
        if resp.status_code != 200:
            raise RenphoError(f"sign_in HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        self._session_key = data.get("terminal_user_session_key")
        self._user_id = data.get("id")
        if not self._session_key or not self._user_id:
            raise RenphoError(f"sign_in unexpected response: {str(data)[:200]}")

    def measurements(self, last_at: int = 0):
        """Measurements newer than the unix-timestamp cursor."""
        if self._session_key is None:
            self.sign_in()
        resp = self._http.get(
            "/api/v2/measurements/list.json",
            params={
                "app_id": APP_ID,
                "terminal_user_session_key": self._session_key,
                "user_id": self._user_id,
                "last_at": last_at,
                "locale": "en",
            },
        )
        if resp.status_code != 200:
            raise RenphoError(f"measurements HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if not isinstance(data, dict) or "last_ats" not in data and "measurements" not in data:
            raise RenphoError(f"measurements unexpected response: {str(data)[:200]}")
        return data.get("measurements") or []

    def close(self):
        self._http.close()
