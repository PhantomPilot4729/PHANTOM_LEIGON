import requests
import time
from .fields import FIELDS

class KismetClient:
    def __init__(self, url: str, auth: tuple):
        self.url = url.rstrip("/")
        self.auth = auth

    def get_recent_devices(self, since_seconds: int = 15) -> list:
        cutoff = int(time.time()) - since_seconds
        payload = {
            "fields": FIELDS,
            "last_time": cutoff
        }

        resp = requests.post(
            f"{self.url}/devices/views/all/devices.json",
            auth=self.auth,
            json=payload,
            timeout=5
        )
        resp.raise_for_status()
        return resp.json()
    
    def get_source_uuids(self) -> dict:

        resp = requests.get(
            f"{self.url}/datasource/all_sources.json",
            auth=self.auth,
            timeout=5,
        )
        resp.raise_for_status()
        sources = resp.json()

        uuid_map = {}
        for source in sources:
            name = source.get("kismet.datasource.name","")
            uuid = source.get("kismet.datasource.uuid","")
            if name and uuid:
                uuid_map[name] = uuid
        return uuid_map
