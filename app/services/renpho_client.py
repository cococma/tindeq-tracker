"""Minimal client for Renpho's private cloud API (Renpho Health app).

Reverse-engineered — credit to danvaneijck/renpho-api for mapping the
Renpho Health backend (cloud.renpho.com): request/response payloads are
AES-128-ECB encrypted with a key hardcoded in the app, login returns a
token, and measurements are paged per scale "table". May break if Renpho
changes their API; the CSV importer is the fallback path.

(The old client here targeted renpho.qnclouds.com, the classic Renpho app —
accounts created in the Renpho Health app don't exist on that backend.)
"""

import base64
import json

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

API_BASE = "https://cloud.renpho.com"
ENCRYPTION_KEY = b"ed*wijdi$h6fe3ew"  # 16-byte AES-128 key from the app
APP_VERSION = "6.6.0"
PLATFORM = "android"

# Body-weight scale device types (hex codes) sent with the login request.
BODY_WEIGHT_SCALES = [
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "0A",
    "0B", "0C", "0D", "0E", "0F", "10", "11", "12", "13", "14",
]

SUCCESS_CODES = {0, "0", 101, "101", 200, "200", 20000, "20000"}

# Renpho measurement field -> our metric code (same codes the CSV importer
# produces, so cloud sync and CSV import land in the same series).
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
    "fatFreeWeight": "fat_free_mass_kg",
    "heartRate": "heart_rate_bpm",
}


class RenphoError(Exception):
    pass


# ── AES-128-ECB payload encryption ────────────────────────────────────────────

def _encrypt(obj) -> dict:
    cipher = AES.new(ENCRYPTION_KEY, AES.MODE_ECB)
    padded = pad(json.dumps(obj, separators=(",", ":")).encode(), AES.block_size)
    return {"encryptData": base64.b64encode(cipher.encrypt(padded)).decode()}


def _encrypt_empty_bytes() -> dict:
    cipher = AES.new(ENCRYPTION_KEY, AES.MODE_ECB)
    padded = pad(b"", AES.block_size)
    return {"encryptData": base64.b64encode(cipher.encrypt(padded)).decode()}


def _decrypt(encrypted_b64: str):
    cipher = AES.new(ENCRYPTION_KEY, AES.MODE_ECB)
    decrypted = unpad(cipher.decrypt(base64.b64decode(encrypted_b64)), AES.block_size)
    return json.loads(decrypted)


class RenphoClient:
    def __init__(self, email: str, password: str, timeout: float = 30.0):
        self._email = email
        self._password = password
        self._http = httpx.Client(base_url=API_BASE, timeout=timeout)
        self._token = None
        self._user_id = None

    def close(self):
        self._http.close()

    def _post(self, endpoint: str, body: dict, auth: bool = True) -> dict:
        headers = {}
        if auth and self._token:
            headers = {
                "token": self._token,
                "userId": str(self._user_id),
                "appVersion": APP_VERSION,
                "platform": PLATFORM,
            }
        resp = self._http.post("/" + endpoint, json=body, headers=headers)
        if resp.status_code != 200:
            raise RenphoError(f"{endpoint} HTTP {resp.status_code}: {resp.text[:200]}")
        result = resp.json()
        code, msg = result.get("code"), result.get("msg", "")
        if msg.lower() != "success" and code not in SUCCESS_CODES:
            raise RenphoError(f"{endpoint} failed: code={code} msg={msg}")
        return result

    # ── API calls ─────────────────────────────────────────────────────────────

    def sign_in(self):
        payload = {
            "questionnaire": {},
            "login": {
                "password": self._password,
                "areaCode": "US",
                "appRevision": APP_VERSION,
                "cellphoneType": "TrainingJournal",
                "systemType": "11",
                "email": self._email,
                "platform": PLATFORM,
            },
            "bindingList": {"deviceTypes": BODY_WEIGHT_SCALES},
        }
        result = self._post("renpho-aggregation/user/login", _encrypt(payload), auth=False)
        login = _decrypt(result["data"]).get("login", {})
        self._token = login.get("token")
        self._user_id = login.get("id")
        if not self._token:
            raise RenphoError("login response had no token")

    def _device_info(self) -> dict:
        # Some server versions want an encrypted empty byte array, others an
        # encrypted empty object — try both (as the reference client does).
        for i, body in enumerate((_encrypt_empty_bytes(), _encrypt({}))):
            try:
                result = self._post("renpho-aggregation/device/count", body)
                return _decrypt(result["data"])
            except RenphoError:
                if i == 1:
                    raise
        return {}

    def _page(self, endpoint: str, table_name: str, user_id, page_size: int = 50):
        """Yield measurement records from a paginated table endpoint."""
        page = 1
        while True:
            body = _encrypt({
                "pageNum": page,
                "pageSize": page_size,
                "userIds": [str(user_id)],
                "tableName": table_name,
            })
            result = self._post(endpoint, body)
            if not result.get("data"):
                return
            records = self._extract_records(_decrypt(result["data"]))
            if not records:
                return
            for r in records:
                yield r
            if len(records) < page_size:
                return
            page += 1

    @staticmethod
    def _extract_records(page_data):
        if isinstance(page_data, list):
            return page_data
        if isinstance(page_data, dict):
            for key in ("list", "data", "records", "measurements"):
                if isinstance(page_data.get(key), list):
                    return page_data[key]
            if "weight" in page_data:
                return [page_data]
        return []

    def measurements(self):
        """All measurements across the account's scales (newest first).

        The Renpho Health API has no last_at cursor — it pages whole tables.
        Personal-scale data volumes are tiny, so we fetch everything and rely
        on the DB's unique constraint for idempotency.
        """
        if self._token is None:
            self.sign_in()

        info = self._device_info()
        all_records = []
        for scale in info.get("scale", []):
            table = scale.get("tableName")
            if not table:
                continue
            user_ids = scale.get("userIds") or []
            uid = self._user_id if (not user_ids or self._user_id in user_ids) else user_ids[0]

            # Impedance scales store data under the body-composition endpoint;
            # weight-only scales under the basic one. Try in that order.
            records = list(self._page(
                "RenphoHealth/scale/queryBodyCompositionMeasureData", table, uid))
            if not records:
                records = list(self._page(
                    "RenphoHealth/scale/queryAllMeasureDataList", table, uid))
            all_records.extend(records)

        all_records.sort(key=lambda m: m.get("timeStamp") or 0, reverse=True)
        return all_records


def measurement_timestamp(m: dict):
    """Unix seconds for a measurement, or None (API mixes s and ms)."""
    ts = m.get("timeStamp") or m.get("time_stamp")
    if not ts:
        return None
    ts = int(ts)
    return ts // 1000 if ts > 1e12 else ts
