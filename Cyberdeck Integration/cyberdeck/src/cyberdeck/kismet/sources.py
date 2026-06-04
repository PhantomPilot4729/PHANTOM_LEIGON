OMNI_UUID: str = ""
CONE_UUID: str = ""
BLE_UUID: str = ""

def load(uuid_map: dict) -> None:
    global OMNI_UUID, CONE_UUID, BLE_UUID
    OMNI_UUID = uuid_map.get("omni","")
    CONE_UUID = uuid_map.get("cone","")
    BLE_UUID = uuid_map.get("ble","")