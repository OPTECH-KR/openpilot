"""Car select menu order: Hyundai / Kia / Genesis cars grouped by brand, then model, then model year.

The menu shows the CAR string itself (English, in this order); the value saved in the SelectedCar param stays the CAR string from values.py, so a car
chosen before keeps working. values.py main() prints the list the manager stores in /data/params/d/SupportedCars, one
car per line as "CAR string|brand|display text" (the UI also accepts an old plain "CAR string" line).
The same file is used on apilot-c2-port (CAN cars) and apilot-c2-canfd (CAN FD cars); each branch lists its own cars.
"""

BRANDS = ("현대", "기아", "제네시스", "쉐보레")

# CAR string: (brand, model family, display text, first model year). Family + year give the order inside a brand.
MENU = {
  # ---------------- 현대 ----------------
  "HYUNDAI CASPER AX1": ("현대", "캐스퍼", "캐스퍼 (2022~)", 2022),
  "HYUNDAI CASPER EV 2024": ("현대", "캐스퍼", "캐스퍼 일렉트릭 (2024~)", 2024),
  "HYUNDAI CUSTIN 1ST GEN": ("현대", "커스틴", "커스틴 (2023, 중국)", 2023),
  "HYUNDAI KONA 2020": ("현대", "코나", "코나 OS (2020)", 2020),
  "HYUNDAI KONA 2022": ("현대", "코나", "코나 OS 페이스리프트 (2022)", 2022),
  "HYUNDAI KONA HYBRID 2020": ("현대", "코나", "코나 하이브리드 OS (2020)", 2020),
  "HYUNDAI KONA ELECTRIC 2019": ("현대", "코나", "코나 일렉트릭 OS (2018~2021)", 2018),
  "HYUNDAI KONA ELECTRIC 2022": ("현대", "코나", "코나 일렉트릭 OS 페이스리프트 (2022)", 2022),
  "HYUNDAI KONA EV 2ND GEN": ("현대", "코나", "디 올 뉴 코나 일렉트릭 SX2 (2023~)", 2023),
  "HYUNDAI KONA HEV 2ND GEN": ("현대", "코나", "디 올 뉴 코나 하이브리드 SX2 (2024~)", 2024),
  "HYUNDAI GRANDEUR IG 2017": ("현대", "그랜저", "그랜저 IG (2017~2019)", 2017),
  "HYUNDAI GRANDEUR IG HEV 2019": ("현대", "그랜저", "그랜저 하이브리드 IG (2017~2019)", 2017),
  "HYUNDAI GRANDEUR IG FL 2020": ("현대", "그랜저", "더 뉴 그랜저 IG (2020~2022)", 2020),
  "HYUNDAI GRANDEUR IG FL HEV 2020": ("현대", "그랜저", "더 뉴 그랜저 하이브리드 IG (2020~2022)", 2020),
  "HYUNDAI GRANDEUR GN7 2023": ("현대", "그랜저", "디 올 뉴 그랜저 GN7 (2023~)", 2023),
  "HYUNDAI NEXO": ("현대", "넥쏘", "넥쏘 (2018~)", 2018),
  "HYUNDAI VELOSTER 2019": ("현대", "벨로스터", "벨로스터 JS (2019~2020)", 2019),
  "HYUNDAI SANTA FE 2019": ("현대", "싼타페", "싼타페 TM (2019~2020)", 2019),
  "HYUNDAI SANTA FE 2022": ("현대", "싼타페", "더 뉴 싼타페 TM (2021~2022)", 2021),
  "HYUNDAI SANTA FE HYBRID 2022": ("현대", "싼타페", "더 뉴 싼타페 하이브리드 TM (2022)", 2022),
  "HYUNDAI SANTA FE PlUG-IN HYBRID 2022": ("현대", "싼타페", "더 뉴 싼타페 플러그인 TM (2022)", 2022),
  "HYUNDAI SANTA FE MX5 2024": ("현대", "싼타페", "디 올 뉴 싼타페 MX5 (2024~)", 2024),
  "HYUNDAI SANTA FE MX5 HEV 2024": ("현대", "싼타페", "디 올 뉴 싼타페 하이브리드 MX5 (2024~)", 2024),
  "HYUNDAI SANTA CRUZ 1ST GEN": ("현대", "싼타크루즈", "싼타크루즈 (2021~2022, 북미)", 2021),
  "HYUNDAI SONATA 2019": ("현대", "쏘나타", "쏘나타 LF (2018~2019)", 2018),
  "HYUNDAI SONATA 2020": ("현대", "쏘나타", "쏘나타 DN8 (2020~2022)", 2020),
  "HYUNDAI SONATA HYBRID 2021": ("현대", "쏘나타", "쏘나타 하이브리드 DN8 (2020~2022)", 2020),
  "HYUNDAI SONATA 2024": ("현대", "쏘나타", "쏘나타 디 엣지 DN8 (2024~)", 2024),
  "HYUNDAI ELANTRA 2017": ("현대", "아반떼", "아반떼 AD (2017~2019)", 2017),
  "HYUNDAI ELANTRA 2021": ("현대", "아반떼", "아반떼 CN7 (2021~2022)", 2021),
  "HYUNDAI ELANTRA HYBRID 2021": ("현대", "아반떼", "아반떼 하이브리드 CN7 (2021~2023)", 2021),
  "HYUNDAI IONIQ HYBRID 2017-2019": ("현대", "아이오닉", "아이오닉 하이브리드 (2017~2019)", 2017),
  "HYUNDAI IONIQ HYBRID 2020-2022": ("현대", "아이오닉", "아이오닉 하이브리드 (2020~2022)", 2020),
  "HYUNDAI IONIQ PLUG-IN HYBRID 2019": ("현대", "아이오닉", "아이오닉 플러그인 (2019)", 2019),
  "HYUNDAI IONIQ PHEV 2020": ("현대", "아이오닉", "아이오닉 플러그인 (2020~2021)", 2020),
  "HYUNDAI IONIQ ELECTRIC LIMITED 2019": ("현대", "아이오닉", "아이오닉 일렉트릭 (2019)", 2019),
  "HYUNDAI IONIQ ELECTRIC 2020": ("현대", "아이오닉", "아이오닉 일렉트릭 (2020)", 2020),
  "HYUNDAI IONIQ 5 2022": ("현대", "아이오닉 5", "아이오닉 5 (2022~2024)", 2022),
  "HYUNDAI IONIQ 5 N 2024": ("현대", "아이오닉 5", "아이오닉 5 N (2024~)", 2024),
  "HYUNDAI IONIQ 5 PE 2025": ("현대", "아이오닉 5", "아이오닉 5 PE (2025~)", 2025),
  "HYUNDAI IONIQ 6 2023": ("현대", "아이오닉 6", "아이오닉 6 (2023~2024)", 2023),
  "HYUNDAI IONIQ 6 PE 2025": ("현대", "아이오닉 6", "아이오닉 6 PE (2025~)", 2025),
  "HYUNDAI IONIQ 9 2025": ("현대", "아이오닉 9", "아이오닉 9 (2025~)", 2025),
  "HYUNDAI I30 N LINE 2019 & GT 2018 DCT": ("현대", "i30", "i30 PD · 엘란트라 GT (2017~2019)", 2017),
  "HYUNDAI STARIA 4TH GEN": ("현대", "스타리아", "스타리아 (2022~)", 2022),
  "HYUNDAI TUCSON TL SCC 2017": ("현대", "투싼", "투싼 TL SCC (2017)", 2017),
  "HYUNDAI TUCSON 2019": ("현대", "투싼", "투싼 TL (2019~2021)", 2019),
  "HYUNDAI TUCSON 4TH GEN": ("현대", "투싼", "투싼 NX4 (2021~)", 2021),
  "HYUNDAI TUCSON HYBRID 4TH GEN": ("현대", "투싼", "투싼 하이브리드 NX4 (2022~)", 2022),
  "HYUNDAI PALISADE 2020": ("현대", "팰리세이드", "팰리세이드 LX2 (2019~2022)", 2019),
  "HYUNDAI PORTER II EV 2024": ("현대", "포터", "포터 II 일렉트릭 (2024)", 2024),

  # ---------------- 기아 ----------------
  "KIA FORTE E 2018 & GT 2021": ("기아", "K3", "K3 BD (포르테, 2019~2021)", 2019),
  "KIA K5 2016-2019": ("기아", "K5", "K5 JF (2016~2019)", 2016),
  "KIA OPTIMA 4TH GEN": ("기아", "K5", "K5 JF (옵티마, 2017)", 2017),
  "KIA OPTIMA 4TH GEN FACELIFT": ("기아", "K5", "더 뉴 K5 JF (옵티마, 2019~2020)", 2019),
  "KIA K5 HEV 2017": ("기아", "K5", "K5 하이브리드 JF (2017)", 2017),
  "KIA OPTIMA HYBRID 2017 & SPORTS 2019": ("기아", "K5", "K5 하이브리드 JF (옵티마, 2017·2019)", 2017),
  "KIA OPTIMA HYBRID 4TH GEN FACELIFT": ("기아", "K5", "더 뉴 K5 하이브리드 JF (옵티마, 2019)", 2019),
  "KIA K5 2021": ("기아", "K5", "K5 DL3 (2020~2023)", 2020),
  "KIA K5 HYBRID 2020": ("기아", "K5", "K5 하이브리드 DL3 (2020~2022)", 2020),
  "KIA K5 HEV 2022 LEGACY": ("기아", "K5", "K5 하이브리드 DL3 (2022, 구형 방식)", 2022),
  "KIA K5 2024": ("기아", "K5", "더 뉴 K5 DL3 (2024~)", 2024),
  "KIA K5 HEV 2024": ("기아", "K5", "더 뉴 K5 하이브리드 DL3 (2024~)", 2024),
  "KIA K7 2016-2019": ("기아", "K7", "K7 YG (2016~2019)", 2016),
  "KIA K7 HEV 2016-2019": ("기아", "K7", "K7 하이브리드 YG (2016~2019)", 2016),
  "KIA K7 2020": ("기아", "K7", "K7 프리미어 YG (2020~2021)", 2020),
  "KIA K7 HEV 2020": ("기아", "K7", "K7 프리미어 하이브리드 YG (2020~2021)", 2020),
  "KIA K8 HEV 1ST GEN": ("기아", "K8", "K8 하이브리드 GL3 (2022~)", 2022),
  "KIA K9 2016-2019": ("기아", "K9", "K9 (2016~2019)", 2016),
  "KIA NIRO HYBRID 2019": ("기아", "니로", "니로 하이브리드·플러그인 DE (2018~2019)", 2018),
  "KIA NIRO HYBRID 2021": ("기아", "니로", "더 뉴 니로 하이브리드 DE (2021~2022)", 2021),
  "KIA NIRO PLUG-IN HYBRID 2022": ("기아", "니로", "더 뉴 니로 플러그인 DE (2021~2022)", 2021),
  "KIA NIRO EV 2020": ("기아", "니로", "니로 EV DE (2019~2022)", 2019),
  "KIA NIRO EV 2ND GEN": ("기아", "니로", "디 올 뉴 니로 EV SG2 (2023~)", 2023),
  "KIA NIRO HEV 2ND GEN": ("기아", "니로", "디 올 뉴 니로 하이브리드 SG2 (2023~)", 2023),
  "KIA RAY EV 2024": ("기아", "레이", "레이 EV (2024~)", 2024),
  "KIA MOHAVE 2019": ("기아", "모하비", "모하비 더 마스터 (2019~)", 2019),
  "KIA SELTOS 2021": ("기아", "셀토스", "셀토스 (2021)", 2021),
  "KIA SPORTAGE 5TH GEN": ("기아", "스포티지", "스포티지 NQ5 (2022~)", 2022),
  "KIA SPORTAGE HYBRID 5TH GEN": ("기아", "스포티지", "스포티지 하이브리드 NQ5 (2022~)", 2022),
  "KIA STINGER GT2 2018": ("기아", "스팅어", "스팅어 (2018~2020)", 2018),
  "KIA STINGER 2022": ("기아", "스팅어", "스팅어 마이스터 (2021~2022)", 2021),
  "KIA SORENTO GT LINE 2018": ("기아", "쏘렌토", "쏘렌토 UM (2018~2019)", 2018),
  "KIA SORENTO 4TH GEN": ("기아", "쏘렌토", "쏘렌토 MQ4 (2021~2023)", 2021),
  "KIA SORENTO HEV 4TH GEN": ("기아", "쏘렌토", "쏘렌토 하이브리드·플러그인 MQ4 (2021~2023)", 2021),
  "KIA SOUL EV (SK3)": ("기아", "쏘울", "쏘울 EV SK3 (2019)", 2019),
  "KIA CEED INTRO ED 2019": ("기아", "씨드", "씨드 (2019, 유럽)", 2019),
  "KIA CARNIVAL 4TH GEN": ("기아", "카니발", "카니발 KA4 (2021~2024)", 2021),
  "KIA EV3 2025": ("기아", "EV3", "EV3 (2024~)", 2024),
  "KIA EV4 2025": ("기아", "EV4", "EV4 (2025~)", 2025),
  "KIA EV6 2022": ("기아", "EV6", "EV6 (2021~2024)", 2021),
  "KIA EV6 PE 2025": ("기아", "EV6", "더 뉴 EV6 PE (2024~)", 2024),
  "KIA EV9 2024": ("기아", "EV9", "EV9 (2023~)", 2023),
  "KIA PV5 2025": ("기아", "PV5", "PV5 (2025~)", 2025),

  # ---------------- 제네시스 ----------------
  "HYUNDAI GENESIS 2015-2016": ("제네시스", "G80", "제네시스 DH (현대, 2015~2016)", 2015),
  "GENESIS G70 2018": ("제네시스", "G70", "G70 (2018~2019)", 2018),
  "GENESIS G70 2020": ("제네시스", "G70", "G70 (2020)", 2020),
  "GENESIS G80 2017": ("제네시스", "G80", "G80 DH (2017~2019)", 2017),
  "GENESIS G80 2ND GEN FACELIFT": ("제네시스", "G80", "G80 RG3 페이스리프트 (2024~)", 2024),
  "GENESIS EQ900 2017": ("제네시스", "G90", "EQ900 (2016~2018)", 2016),
  "GENESIS EQ900 LIMOUSINE": ("제네시스", "G90", "EQ900 리무진 (2016~2018)", 2016),
  "GENESIS G90 2017": ("제네시스", "G90", "G90 HI (2017~2018, 북미)", 2017),
  "GENESIS G90 2019": ("제네시스", "G90", "G90 HI 페이스리프트 (2019~2021)", 2019),
  "GENESIS GV60 EV 1ST GEN": ("제네시스", "GV60", "GV60 (2021~)", 2021),
  "GENESIS GV70 1ST GEN": ("제네시스", "GV70", "GV70 JK1 (2021~2023)", 2021),
  "GENESIS GV70 EV 1ST GEN": ("제네시스", "GV70", "GV70 전동화 (2022~2023, 레이더 SCC)", 2022),
  "GENESIS GV70 ELECTRIFIED 1ST GEN": ("제네시스", "GV70", "GV70 전동화 (2023~2024, HDA2)", 2023),
  "GENESIS GV80 2023": ("제네시스", "GV80", "GV80 JX1 (2020~2023)", 2020),

  # ---------------- 쉐보레 (GM, selfdrive/car/gm) ----------------
  "CHEVROLET BOLT EV NO ACC": ("쉐보레", "볼트", "볼트 EV ACC 없음 (2017~2021)", 2017),
  "CHEVROLET BOLT EUV 2022": ("쉐보레", "볼트", "볼트 EUV (2022~2023)", 2022),
}


def _key(car):
  brand, family, display, year = MENU.get(car, (_brand_guess(car), car, car, 0))
  b = BRANDS.index(brand) if brand in BRANDS else len(BRANDS)
  return (b, family, year, display)


def _brand_guess(car):
  return "쉐보레" if car.startswith("CHEVROLET") else "제네시스" if car.startswith("GENESIS") else "기아" if car.startswith("KIA") else "현대" if car.startswith("HYUNDAI") else "기타"


BRAND_EN = {"현대": "HYUNDAI", "기아": "KIA", "제네시스": "GENESIS", "쉐보레": "CHEVROLET"}


def menu_lines(cars):
  """menu file lines for these CAR strings, sorted by brand, model family and year. The menu shows the CAR string
  itself (the user wants the original English names); the Korean texts above only set the order."""
  lines = []
  for car in sorted(cars, key=_key):
    brand = MENU.get(car, (_brand_guess(car),))[0]
    lines.append(f"{car}|{BRAND_EN.get(brand, brand)}|{car}")
  return lines
