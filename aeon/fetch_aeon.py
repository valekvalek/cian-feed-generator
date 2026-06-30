import requests
import math
import time
import xml.etree.ElementTree as ET
from xml.dom import minidom

BASE_URL = "https://river-park.ru"
API_URL = f"{BASE_URL}/ajax/flats/"
JK_NAME = "Ривер Парк Бизнес"
DEVELOPER = "Aeon"

PARAMS_BASE = {
    "cnt": 30,
    "filter[project]": "Riverpark",
    "filter[special]": "",
    "filter[type]": "",
    "filter[bld]": "",
    "filter[offers]": "",
    "filter[finishing]": 0,
    "sort[sec]": 0,
    "sort[name]": 0,
    "sort[sq]": 0,
    "sort[price]": 1,
    "sort[rooms]": 0,
    "sort[floor]": 0,
    "art_code": "flat"
}
HEADERS = {"User-Agent": "Mozilla/5.0"}

READY_MAP = {
    "25101": "I квартал 2025",
    "25552": "II квартал 2025",
}

ROOMS_MAP = {
    "S": "Студия",
    "M": "2-комнатная",
    "L": "3-комнатная",
}

def fetch_all_lots():
    p = dict(PARAMS_BASE, page=1)
    r = requests.get(API_URL, params=p, headers=HEADERS, timeout=30)
    data = r.json()
    count = data.get("count", 0)
    pages = math.ceil(count / 30)
    print(f"Всего лотов: {count}, страниц: {pages}")
    all_lots = data.get("data", [])
    for page in range(2, pages + 1):
        p = dict(PARAMS_BASE, page=page)
        r = requests.get(API_URL, params=p, headers=HEADERS, timeout=30)
        lots = r.json().get("data", [])
        all_lots.extend(lots)
        print(f"  стр {page}: +{len(lots)}, итого {len(all_lots)}")
        time.sleep(0.3)
    return all_lots

def sub(parent, tag, text=None):
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el

def build_xml(lots):
    root = ET.Element("feed")
    root.set("version", "1")
    exported = 0
    for lot in lots:
        if not lot.get("real_price") or lot.get("reserved") == "Y":
            continue
        offer = sub(root, "object")
        sub(offer, "id", lot["id"])
        sub(offer, "externalId", lot["lotcode"])
        sub(offer, "type", "продажа")
        sub(offer, "objectType", "апартаменты")
        sub(offer, "newbuilding", "да")
        sub(offer, "jkName", JK_NAME)
        sub(offer, "developer", DEVELOPER)
        addr = sub(offer, "address")
        sub(addr, "country", "Россия")
        sub(addr, "region", "Москва")
        sub(addr, "city", "Москва")
        sub(addr, "street", "Коломенская набережная")
        sub(addr, "complex", JK_NAME)
        sub(offer, "building", lot.get("building", ""))
        sub(offer, "section", lot.get("section", ""))
        sub(offer, "floor", lot.get("floor", ""))
        sub(offer, "flatNumber", lot.get("num", ""))
        sub(offer, "lotCode", lot.get("lotcode", ""))
        sub(offer, "totalArea", lot.get("sq", ""))
        rooms_raw = lot.get("rooms", "S")
        sub(offer, "rooms", ROOMS_MAP.get(rooms_raw, rooms_raw))
        sub(offer, "roomType", lot.get("articlesubtype", ""))
        ready_raw = lot.get("ready", "")
        sub(offer, "deliveryDate", READY_MAP.get(ready_raw, ready_raw))
        price_el = sub(offer, "price")
        sub(price_el, "value", lot.get("real_price", ""))
        sub(price_el, "currency", "RUB")
        sub(price_el, "pricePerMeter", lot.get("real_meterprice", ""))
        advantages = [a["name"] for a in lot.get("advantages", []) if a.get("name")]
        if advantages:
            sub(offer, "description", " | ".join(advantages))
        sub(offer, "url", f"{BASE_URL}/lots/flat/?id={lot['id']}")
        if lot.get("layout"):
            sub(offer, "layoutImage", BASE_URL + lot["layout"])
        if lot.get("plan"):
            sub(offer, "planPdf", BASE_URL + lot["plan"])
        exported += 1
    print(f"Выгружено: {exported} из {len(lots)}")
    return root

def save_xml(root, filename):
    xml_str = minidom.parseString(
        ET.tostring(root, encoding="unicode")
    ).toprettyxml(indent="  ", encoding=None)
    lines = xml_str.split("\n")
    if lines[0].startswith("<?xml"):
        lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Сохранён: {filename}")

if __name__ == "__main__":
    lots = fetch_all_lots()
    root = build_xml(lots)
    save_xml(root, "aeon/aeon_riverpark_feed.xml")
