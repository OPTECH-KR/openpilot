"""Car select menu for Hyundai / Kia / Genesis (OPTECH 시작 tab, optech_panel.cc).

Same names and order as optech-hkg (its selfdrive/car/hyundai/car_menu.py): inside a brand the cars are sorted by model
family, then model year, and shown with the Korean market name (ELANTRA -> AVANTE, FORTE -> K3, OPTIMA -> K5, AZERA ->
GRANDEUR) plus the vehicle code and years. The value saved in dp_car_assigned stays the CAR string from values.py.
Only normal CAN cars are listed: CAN FD cars need a red panda, which this C2 build does not use for them.
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
  "HYUNDAI AZERA 6TH GEN": ("현대", "그랜저", 2020, "GRANDEUR IG FACELIFT 2020-2022 (AZERA)"),
  "HYUNDAI AZERA HYBRID 6TH GEN": ("현대", "그랜저", 2019, "GRANDEUR HYBRID IG 2019-2020 (AZERA)"),
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
  "KIA OPTIMA 4TH GEN": ("기아", "K5", 2017, "K5 JF 2017 (USA)"),
  "KIA OPTIMA 4TH GEN FACELIFT": ("기아", "K5", 2019, "K5 JF FACELIFT 2019-2020 (USA)"),
  "KIA OPTIMA HYBRID 2017 & SPORTS 2019": ("기아", "K5", 2017, "K5 HYBRID JF 2017-2019 (USA)"),
  "KIA OPTIMA HYBRID 4TH GEN FACELIFT": ("기아", "K5", 2019, "K5 HYBRID JF FACELIFT 2019 (USA)"),
  "KIA K5 2021": ("기아", "K5", 2020, "K5 DL3 2020-2023"),
  "KIA K5 HYBRID 2020": ("기아", "K5", 2020, "K5 HYBRID DL3 2020-2022"),
  "KIA NIRO HYBRID 2019": ("기아", "니로", 2018, "NIRO HYBRID DE 2018-2019"),
  "KIA NIRO HYBRID 2021": ("기아", "니로", 2021, "NIRO HYBRID DE FACELIFT 2021-2022"),
  "KIA NIRO PLUG-IN HYBRID 2022": ("기아", "니로", 2021, "NIRO PLUG-IN DE FACELIFT 2021-2022"),
  "KIA NIRO EV 2020": ("기아", "니로", 2019, "NIRO EV DE 2019-2022"),
  "KIA SELTOS 2021": ("기아", "셀토스", 2021, "SELTOS SP2 2021"),
  "KIA STINGER GT2 2018": ("기아", "스팅어", 2018, "STINGER CK 2018-2020"),
  "KIA STINGER 2022": ("기아", "스팅어", 2021, "STINGER MEISTER CK 2021-2022"),
  "KIA SORENTO GT LINE 2018": ("기아", "쏘렌토", 2018, "SORENTO UM 2018-2019"),
  "KIA CEED INTRO ED 2019": ("기아", "씨드", 2019, "CEED CD 2019 (EUROPE)"),

  # ---------------- 제네시스 ----------------
  "HYUNDAI GENESIS 2015-2016": ("제네시스", "G80", 2015, "GENESIS DH 2015-2016"),
  "GENESIS G70 2018": ("제네시스", "G70", 2018, "G70 IK 2018-2019"),
  "GENESIS G70 2020": ("제네시스", "G70", 2020, "G70 IK 2020"),
  "GENESIS G80 2017": ("제네시스", "G80", 2017, "G80 DH 2017-2019"),
  "GENESIS G90 2017": ("제네시스", "G90", 2017, "G90 HI 2017-2018 (USA)"),
}


def _brand_guess(car):
  return "제네시스" if car.startswith("GENESIS") else "기아" if car.startswith("KIA") else "현대"


def _key(car):
  brand, family, year, name = MENU.get(car, (_brand_guess(car), car, 0, car))
  return (BRANDS.index(brand), family, year, name)


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
