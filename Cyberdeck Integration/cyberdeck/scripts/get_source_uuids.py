import requests

KISMET_URL = "http://localhost:2501"
AUTH = ("kismet", "your_password_here")

def get_source_uuids():
    resp = requests.get(
        f"{KISMET_URL}/datasource/all_sources.json",
        auth=AUTH
    )
    sources = resp.json()

    uuid_map = {}
    for source in sources:
        name = source.get("kismet.datasource.name","")
        uuid = source.get("kismet.datasource.uuid","")
        uuid_map[name] = uuid
        print(f"Source '{name}' -> UUID: {uuid}")

    return uuid_map