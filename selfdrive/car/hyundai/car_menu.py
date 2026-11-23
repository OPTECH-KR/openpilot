"""Car select menu for Hyundai / Kia / Genesis (OPTECH 시작 tab, optech_panel.cc).

Same names and order as optech-hkg (its selfdrive/car/hyundai/car_menu.py): inside a brand the cars are sorted by model
family, then model year, and shown with the Korean market name (ELANTRA -> AVANTE, FORTE -> K3, OPTIMA -> K5, AZERA ->
GRANDEUR) plus the vehicle code and years. The value saved in dp_car_assigned stays the CAR string from values.py.
Only normal CAN cars are listed: CAN FD cars need a red panda, which this C2 build does not use for them.
The Korean market cars (values.KOREA_CAR: Grandeur IG, K7, K9, Mohave, Casper, Nexo, EQ900, ...) come from optech-hkg.
So do the cars without SCC (values.NON_SCC_CAR, 'NO SCC', Ray EV, Porter II EV).
The manager puts menu_entries() into dp_car_list ("hkg_menu"); the UI keeps that order.
"""

BRANDS = ("현대", "기아", "제네시스")
BRAND_EN = {"현대": "HYUNDAI", "기아": "KIA", "제네시스": "GENESIS"}

# CAR string: (brand, model family, first model year, menu name without the brand). Family + year give the order.
MENU = {
  # ---------------- 현대 ----------------
  "HYUNDAI CUSTIN 1ST GEN": ("현대", "커스틴", 2023, "CUSTIN 2023 (CHINA)"),
  "HYUNDAI KONA 2020": ("현대", "코나", 2020, "KONA OS 2020"),
  "HYUNDAI KONA HYBRID 2020": ("현대", "코나", 2020, "KONA HYBRID OS 2020"),
  "HYUNDAI KONA ELECTRIC 2019": ("현대", "코나", 2018, "KONA ELECTRIC OS 2018-2021"),
  "HYUNDAI KONA ELECTRIC 2022": ("현대", "코나", 2022, "KONA ELECTRIC OS FACELIFT 2022"),
  "HYUNDAI KONA 2022": ("현대", "코나", 2022, "KONA OS FACELIFT 2022"),
  "HYUNDAI KONA 2019 NON-SCC": ("현대", "코나", 2018, "KONA OS 2018-2021 NO SCC"),
  "HYUNDAI KONA ELECTRIC 2019 NON-SCC": ("현대", "코나", 2018, "KONA ELECTRIC OS 2018-2021 NO SCC"),
  "HYUNDAI VENUE 2021 NON-SCC": ("현대", "베뉴", 2020, "VENUE QX 2020~ NO SCC"),
  "HYUNDAI PORTER II EV 2024": ("현대", "포터", 2024, "PORTER II ELECTRIC 2024"),
  "HYUNDAI GRANDEUR IG 2017": ("현대", "그랜저", 2017, "GRANDEUR IG 2017-2019"),
  "HYUNDAI GRANDEUR IG HEV 2019": ("현대", "그랜저", 2017, "GRANDEUR HYBRID IG 2017-2019"),
  "HYUNDAI GRANDEUR IG FL 2020": ("현대", "그랜저", 2020, "GRANDEUR IG FACELIFT 2020-2022"),
  "HYUNDAI GRANDEUR IG FL HEV 2020": ("현대", "그랜저", 2020, "GRANDEUR HYBRID IG FACELIFT 2020-2022"),
  # comma's names for the Grandeur sold abroad (Azera): kept for auto detect, listed after the Korean ones
  "HYUNDAI AZERA 6TH GEN": ("현대", "그랜저", 2099, "AZERA 2022 (GRANDEUR IG FACELIFT, OVERSEAS)"),
  "HYUNDAI AZERA HYBRID 6TH GEN": ("현대", "그랜저", 2099, "AZERA HYBRID 2019-2020 (GRANDEUR IG, OVERSEAS)"),
  "HYUNDAI NEXO": ("현대", "넥쏘", 2018, "NEXO FE 2018~"),
  "HYUNDAI CASPER AX1": ("현대", "캐스퍼", 2022, "CASPER AX1 2022~"),
  "HYUNDAI CASPER EV 2024": ("현대", "캐스퍼", 2024, "CASPER ELECTRIC AX1 2024~"),
  "HYUNDAI VELOSTER 2019": ("현대", "벨로스터", 2019, "VELOSTER JS 2019-2020"),
  "HYUNDAI SANTA FE 2019": ("현대", "싼타페", 2019, "SANTA FE TM 2019-2020"),
  "HYUNDAI SANTA FE 2022": ("현대", "싼타페", 2021, "SANTA FE TM FACELIFT 2021-2022"),
  "HYUNDAI SANTA FE HYBRID 2022": ("현대", "싼타페", 2022, "SANTA FE HYBRID TM 2022"),
  "HYUNDAI SANTA FE PlUG-IN HYBRID 2022": ("현대", "싼타페", 2022, "SANTA FE PLUG-IN TM 2022"),
  "HYUNDAI SONATA 2019": ("현대", "쏘나타", 2018, "SONATA LF 2018-2019"),
  "HYUNDAI SONATA 2020": ("현대", "쏘나타", 2020, "SONATA DN8 2020-2022"),
  "HYUNDAI SONATA HYBRID 2021": ("현대", "쏘나타", 2020, "SONATA HYBRID DN8 2020-2022"),
  "HYUNDAI ELANTRA 2017": ("현대", "아반떼", 2017, "AVANTE AD 2017-2019"),
  "HYUNDAI ELANTRA 2021": ("현대", "아반떼", 2021, "AVANTE CN7 2021-2022"),
  "HYUNDAI ELANTRA HYBRID 2021": ("현대", "아반떼", 2021, "AVANTE HYBRID CN7 2021-2023"),
  "HYUNDAI ELANTRA 2022 NON-SCC": ("현대", "아반떼", 2021, "AVANTE CN7 2021~ NO SCC"),
  "HYUNDAI ELANTRA HYBRID 2022 NON-SCC": ("현대", "아반떼", 2021, "AVANTE HYBRID CN7 2021~ NO SCC"),
  "HYUNDAI IONIQ HYBRID 2017-2019": ("현대", "아이오닉", 2017, "IONIQ HYBRID AE 2017-2019"),
  "HYUNDAI IONIQ HYBRID 2020-2022": ("현대", "아이오닉", 2020, "IONIQ HYBRID AE 2020-2022"),
  "HYUNDAI IONIQ PLUG-IN HYBRID 2019": ("현대", "아이오닉", 2019, "IONIQ PLUG-IN AE 2019"),
  "HYUNDAI IONIQ PHEV 2020": ("현대", "아이오닉", 2020, "IONIQ PLUG-IN AE 2020-2021"),
  "HYUNDAI IONIQ ELECTRIC LIMITED 2019": ("현대", "아이오닉", 2019, "IONIQ ELECTRIC AE 2019"),
  "HYUNDAI IONIQ ELECTRIC 2020": ("현대", "아이오닉", 2020, "IONIQ ELECTRIC AE 2020"),
  "HYUNDAI I30 N LINE 2019 & GT 2018 DCT": ("현대", "i30", 2017, "I30 PD 2017-2019"),
  "HYUNDAI TUCSON 2019": ("현대", "투싼", 2019, "TUCSON TL 2019-2021"),
  "HYUNDAI PALISADE 2020": ("현대", "팰리세이드", 2019, "PALISADE LX2 2019-2022"),

  # ---------------- 기아 ----------------
  "KIA FORTE E 2018 & GT 2021": ("기아", "K3", 2019, "K3 BD 2019-2021"),
  "KIA FORTE 2019 NON-SCC": ("기아", "K3", 2019, "K3 BD 2019-2020 NO SCC"),
  "KIA FORTE 2021 NON-SCC": ("기아", "K3", 2021, "K3 BD FACELIFT 2021~ NO SCC"),
  "KIA RAY EV 2024": ("기아", "레이", 2024, "RAY EV TAM 2024~"),
  "KIA K5 2016-2019": ("기아", "K5", 2016, "K5 JF 2016-2019"),
  "KIA K5 HEV 2017": ("기아", "K5", 2017, "K5 HYBRID JF 2017"),
  "KIA OPTIMA 4TH GEN": ("기아", "K5", 2017, "K5 JF 2017 (USA)"),
  "KIA OPTIMA 4TH GEN FACELIFT": ("기아", "K5", 2019, "K5 JF FACELIFT 2019-2020 (USA)"),
  "KIA OPTIMA HYBRID 2017 & SPORTS 2019": ("기아", "K5", 2017, "K5 HYBRID JF 2017-2019 (USA)"),
  "KIA OPTIMA HYBRID 4TH GEN FACELIFT": ("기아", "K5", 2019, "K5 HYBRID JF FACELIFT 2019 (USA)"),
  "KIA K5 2021": ("기아", "K5", 2020, "K5 DL3 2020-2023"),
  "KIA K5 HYBRID 2020": ("기아", "K5", 2020, "K5 HYBRID DL3 2020-2022"),
  "KIA K5 HEV 2022 LEGACY": ("기아", "K5", 2022, "K5 HYBRID DL3 2022 (LEGACY)"),
  "KIA K7 2016-2019": ("기아", "K7", 2016, "K7 YG 2016-2019"),
  "KIA K7 HEV 2016-2019": ("기아", "K7", 2016, "K7 HYBRID YG 2016-2019"),
  "KIA K7 2020": ("기아", "K7", 2020, "K7 PREMIER YG 2020-2021"),
  "KIA K7 HEV 2020": ("기아", "K7", 2020, "K7 PREMIER HYBRID YG 2020-2021"),
  "KIA K9 2016-2019": ("기아", "K9", 2016, "K9 RJ 2016-2019"),
  "KIA MOHAVE 2019": ("기아", "모하비", 2019, "MOHAVE HM 2019~"),
  "KIA NIRO HYBRID 2019": ("기아", "니로", 2018, "NIRO HYBRID DE 2018-2019"),
  "KIA NIRO HYBRID 2021": ("기아", "니로", 2021, "NIRO HYBRID DE FACELIFT 2021-2022"),
  "KIA NIRO PLUG-IN HYBRID 2022": ("기아", "니로", 2021, "NIRO PLUG-IN DE FACELIFT 2021-2022"),
  "KIA NIRO EV 2020": ("기아", "니로", 2019, "NIRO EV DE 2019-2022"),
  "KIA SELTOS 2021": ("기아", "셀토스", 2021, "SELTOS SP2 2021"),
  "KIA SELTOS 2023 NON-SCC": ("기아", "셀토스", 2023, "SELTOS SP2 2023-2024 NO SCC"),
  "KIA STINGER GT2 2018": ("기아", "스팅어", 2018, "STINGER CK 2018-2020"),
  "KIA STINGER 2022": ("기아", "스팅어", 2021, "STINGER MEISTER CK 2021-2022"),
  "KIA SORENTO GT LINE 2018": ("기아", "쏘렌토", 2018, "SORENTO UM 2018-2019"),
  "KIA CEED INTRO ED 2019": ("기아", "씨드", 2019, "CEED CD 2019 (EUROPE)"),

  # ---------------- 제네시스 ----------------
  "HYUNDAI GENESIS 2015-2016": ("제네시스", "G80", 2015, "GENESIS DH 2015-2016"),
  "GENESIS G70 2018": ("제네시스", "G70", 2018, "G70 IK 2018-2019"),
  "GENESIS G70 2020": ("제네시스", "G70", 2020, "G70 IK 2020"),
  "GENESIS G70 2021 NON-SCC": ("제네시스", "G70", 2021, "G70 IK 2021 NO SCC"),
  "GENESIS G80 2017": ("제네시스", "G80", 2017, "G80 DH 2017-2019"),
  "GENESIS EQ900 2017": ("제네시스", "G90", 2016, "EQ900 HI 2016-2018"),
  "GENESIS EQ900 LIMOUSINE": ("제네시스", "G90", 2016, "EQ900 LIMOUSINE HI 2016-2018"),
  "GENESIS G90 2017": ("제네시스", "G90", 2017, "G90 HI 2017-2018 (USA)"),
  "GENESIS G90 2019": ("제네시스", "G90", 2019, "G90 HI FACELIFT 2019-2021"),
}


def _brand_guess(car):
  return "제네시스" if car.startswith("GENESIS") else "기아" if car.startswith("KIA") else "현대"


def _key(car):
  brand, family, year, name = MENU.get(car, (_brand_guess(car), car, 0, car))
  electrified = any(w in name.split() for w in ("HYBRID", "PLUG-IN", "ELECTRIC", "EV"))
  return (BRANDS.index(brand), family, year, electrified, name)  # same year: the gasoline car first


def menu_entries(cars, canfd_cars=()):
  """[{"car", "brand", "name"}] for these CAR strings in menu order; CAN FD cars are left out.
  A car missing from MENU is still listed (by its CAR string) so a new car never disappears from the menu."""
  entries = []
  for car in sorted((c for c in cars if c not in canfd_cars), key=_key):
    brand, _, _, name = MENU.get(car, (_brand_guess(car), car, 0, car.split(" ", 1)[-1]))
    entries.append({"car": car, "brand": BRAND_EN[brand], "name": name})
  return entries


def _name(c):
  return str(c.value if hasattr(c, "value") else c)


def hkg_menu():
  from openpilot.selfdrive.car.hyundai.values import CAR, CANFD_CAR
  return menu_entries([_name(c) for c in CAR], {_name(c) for c in CANFD_CAR})
