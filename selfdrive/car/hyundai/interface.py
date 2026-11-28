from cereal import car
from panda import Panda
from openpilot.common.conversions import Conversions as CV
from openpilot.selfdrive.car.hyundai.hyundaicanfd import CanBus
from openpilot.selfdrive.car.hyundai.values import HyundaiFlags, CAR, DBC, CANFD_CAR, CAMERA_SCC_CAR, CANFD_RADAR_SCC_CAR, \
                                         CANFD_UNSUPPORTED_LONGITUDINAL_CAR, EV_CAR, HYBRID_CAR, LEGACY_SAFETY_MODE_CAR, \
                                         UNSUPPORTED_LONGITUDINAL_CAR, Buttons, NON_SCC_CAR, NON_SCC_VARIANT
from openpilot.selfdrive.car.hyundai.values import is_camera_scc, CAMERA_SCC_PARAM, optech_cruise_rule
from openpilot.selfdrive.car.hyundai.radar_interface import RADAR_START_ADDR
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.car import create_button_events, get_safety_config
from openpilot.selfdrive.car.interfaces import CarInterfaceBase
from openpilot.selfdrive.car.disable_ecu import disable_ecu

from openpilot.common.params import Params

Ecu = car.CarParams.Ecu
SafetyModel = car.CarParams.SafetyModel
ButtonType = car.CarState.ButtonEvent.Type
EventName = car.CarEvent.EventName
ENABLE_BUTTONS = (Buttons.RES_ACCEL, Buttons.SET_DECEL, Buttons.CANCEL)
BUTTONS_DICT = {Buttons.RES_ACCEL: ButtonType.accelCruise, Buttons.SET_DECEL: ButtonType.decelCruise,
                Buttons.GAP_DIST: ButtonType.gapAdjustCruise, Buttons.CANCEL: ButtonType.cancel}
CANCEL_ALL_OFF_TIME = 0.4  # optech-hkg: CANCEL held this long turns everything off (shorter: speed control only)
MAIN_STEER_ON_TIME = 1.0   # the cruise standby coming on this soon after the cruise button -> the driver turned it on


def set_safety_config_hyundai(candidate, CAN, can_fd=False):
  platform = SafetyModel.hyundaiCanfd if can_fd else \
             SafetyModel.hyundaiLegacy if candidate in LEGACY_SAFETY_MODE_CAR else \
             SafetyModel.hyundai
  cfgs = [get_safety_config(platform), ]
  if CAN.ECAN >= 4:
    cfgs.insert(0, get_safety_config(SafetyModel.noOutput))

  return cfgs


class CarInterface(CarInterfaceBase):
  def __init__(self, CP, CarController, CarState):
    super().__init__(CP, CarController, CarState)
    self.cruise_rule = optech_cruise_rule(CP)  # optech-hkg cruise button rule (values.optech_cruise_rule)
    self.cancel_frames = 0        # frames the CANCEL button has been held
    self.main_frames_since = 1000  # frames since the cruise (main) button was last seen pressed
    self.main_pressed_prev = False

  @staticmethod
  def _get_params(ret, candidate, fingerprint, car_fw, experimental_long, docs):
    # optech (optech-hkg): a model with SCC that shows no SCC11 (1056) on either bus at the start is its trim without SCC
    if candidate in NON_SCC_VARIANT and len(fingerprint[0]) and 1056 not in fingerprint[0] and 1056 not in fingerprint[2]:
      candidate = NON_SCC_VARIANT[candidate]
      ret.carFingerprint = candidate
    ret.carName = "hyundai"
    ret.radarUnavailable = RADAR_START_ADDR not in fingerprint[1] or DBC[ret.carFingerprint]["radar"] is None
    params = Params()

    # These cars have been put into dashcam only due to both a lack of users and test coverage.
    # These cars likely still work fine. Once a user confirms each car works and a test route is
    # added to selfdrive/car/tests/routes.py, we can remove it from this list.
    # FIXME: the Optima Hybrid 2017 uses a different SCC12 checksum
    ret.dashcamOnly = candidate in {CAR.KIA_OPTIMA_H, }
    ret.dashcamOnly = False if ret.dashcamOnly and params.get_bool("dp_car_dashcam_mode_removal") else ret.dashcamOnly

    hda2 = Ecu.adas in [fw.ecu for fw in car_fw]
    CAN = CanBus(None, hda2, fingerprint)

    if candidate in CANFD_CAR:
      # detect HDA2 with ADAS Driving ECU
      if hda2:
        if 0x110 in fingerprint[CAN.CAM]:
          ret.flags |= HyundaiFlags.CANFD_HDA2_ALT_STEERING.value
      else:
        # non-HDA2
        if 0x1cf not in fingerprint[CAN.ECAN]:
          ret.flags |= HyundaiFlags.CANFD_ALT_BUTTONS.value
        # ICE cars do not have 0x130; GEARS message on 0x40 or 0x70 instead
        if 0x130 not in fingerprint[CAN.ECAN]:
          if 0x40 not in fingerprint[CAN.ECAN]:
            ret.flags |= HyundaiFlags.CANFD_ALT_GEARS_2.value
          else:
            ret.flags |= HyundaiFlags.CANFD_ALT_GEARS.value
        if candidate not in CANFD_RADAR_SCC_CAR:
          ret.flags |= HyundaiFlags.CANFD_CAMERA_SCC.value
    else:
      # Send LFA message on cars with HDA
      if 0x485 in fingerprint[2]:
        ret.flags |= HyundaiFlags.SEND_LFA.value
      # optech: no SCC (optech-hkg / StarPilot): only the car's regular cruise control
      if candidate in NON_SCC_CAR:
        ret.flags |= HyundaiFlags.NON_SCC.value
        if 916 not in fingerprint[0] and len(fingerprint[0]) and candidate in (EV_CAR | HYBRID_CAR):  # no TCS13 (Porter II EV)
          ret.flags |= HyundaiFlags.NON_SCC_NO_TCS.value
        # the Ray EV's LFAHDA_MFC (0x485) is 8 bytes; ours is the 4-byte one, so do not send it there
        if fingerprint[2].get(0x485) != 4:
          ret.flags &= ~HyundaiFlags.SEND_LFA.value

      # These cars use the FCA11 message for the AEB and FCW signals, all others use SCC12
      if 0x38d in fingerprint[0] or 0x38d in fingerprint[2]:
        ret.flags |= HyundaiFlags.USE_FCA.value

    ret.steerActuatorDelay = 0.1  # Default delay
    ret.steerLimitTimer = 0.4
    CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    if candidate in (CAR.AZERA_6TH_GEN, CAR.AZERA_HEV_6TH_GEN):
      ret.mass = 1600. if candidate == CAR.AZERA_6TH_GEN else 1675.  # ICE is ~average of 2.5L and 3.5L
      ret.wheelbase = 2.885
      ret.steerRatio = 14.5
    elif candidate in (CAR.SANTA_FE, CAR.SANTA_FE_2022, CAR.SANTA_FE_HEV_2022, CAR.SANTA_FE_PHEV_2022):
      ret.mass = 3982. * CV.LB_TO_KG
      ret.wheelbase = 2.766
      # Values from optimizer
      ret.steerRatio = 16.55  # 13.8 is spec end-to-end
      ret.tireStiffnessFactor = 0.82
    elif candidate in (CAR.SONATA, CAR.SONATA_HYBRID):
      ret.mass = 1513.
      ret.wheelbase = 2.84
      ret.steerRatio = 13.27 * 1.15   # 15% higher at the center seems reasonable
      ret.tireStiffnessFactor = 0.65
    elif candidate == CAR.SONATA_LF:
      ret.mass = 1536.
      ret.wheelbase = 2.804
      ret.steerRatio = 13.27 * 1.15   # 15% higher at the center seems reasonable
    elif candidate == CAR.PALISADE:
      ret.mass = 1999.
      ret.wheelbase = 2.90
      ret.steerRatio = 15.6 * 1.15
      ret.tireStiffnessFactor = 0.63
    elif candidate in (CAR.ELANTRA, CAR.ELANTRA_GT_I30):
      ret.mass = 1275.
      ret.wheelbase = 2.7
      ret.steerRatio = 15.4            # 14 is Stock | Settled Params Learner values are steerRatio: 15.401566348670535
      ret.tireStiffnessFactor = 0.385    # stiffnessFactor settled on 1.0081302973865127
      ret.minSteerSpeed = 32 * CV.MPH_TO_MS
    elif candidate in (CAR.ELANTRA_2021, CAR.ELANTRA_2022_NON_SCC):
      ret.mass = 2800. * CV.LB_TO_KG
      ret.wheelbase = 2.72
      ret.steerRatio = 12.9
      ret.tireStiffnessFactor = 0.65
    elif candidate in (CAR.ELANTRA_HEV_2021, CAR.ELANTRA_HEV_2022_NON_SCC):
      ret.mass = 3017. * CV.LB_TO_KG
      ret.wheelbase = 2.72
      ret.steerRatio = 12.9
      ret.tireStiffnessFactor = 0.65
    elif candidate == CAR.HYUNDAI_GENESIS:
      ret.mass = 2060.
      ret.wheelbase = 3.01
      ret.steerRatio = 16.5
      ret.minSteerSpeed = 60 * CV.KPH_TO_MS
    elif candidate in (CAR.KONA, CAR.KONA_EV, CAR.KONA_HEV, CAR.KONA_EV_2022, CAR.KONA_EV_2ND_GEN, CAR.KONA_NON_SCC,
                       CAR.KONA_EV_NON_SCC):
      ret.mass = {CAR.KONA_EV: 1685., CAR.KONA_HEV: 1425., CAR.KONA_EV_2022: 1743., CAR.KONA_EV_2ND_GEN: 1740.,
                  CAR.KONA_EV_NON_SCC: 1685.}.get(candidate, 1275.)
      ret.wheelbase = {CAR.KONA_EV_2ND_GEN: 2.66, }.get(candidate, 2.6)
      ret.steerRatio = {CAR.KONA_EV_2ND_GEN: 13.6, }.get(candidate, 13.42)  # Spec
      ret.tireStiffnessFactor = 0.385
    elif candidate in (CAR.IONIQ, CAR.IONIQ_EV_LTD, CAR.IONIQ_PHEV_2019, CAR.IONIQ_HEV_2022, CAR.IONIQ_EV_2020, CAR.IONIQ_PHEV):
      ret.mass = 1490.  # weight per hyundai site https://www.hyundaiusa.com/ioniq-electric/specifications.aspx
      ret.wheelbase = 2.7
      ret.steerRatio = 13.73  # Spec
      ret.tireStiffnessFactor = 0.385
      if candidate in (CAR.IONIQ, CAR.IONIQ_EV_LTD, CAR.IONIQ_PHEV_2019):
        ret.minSteerSpeed = 32 * CV.MPH_TO_MS
    elif candidate in (CAR.IONIQ_5, CAR.IONIQ_6):
      ret.mass = 1948
      ret.wheelbase = 2.97
      ret.steerRatio = 14.26
      ret.tireStiffnessFactor = 0.65
    elif candidate == CAR.VELOSTER:
      ret.mass = 2917. * CV.LB_TO_KG
      ret.wheelbase = 2.80
      ret.steerRatio = 13.75 * 1.15
      ret.tireStiffnessFactor = 0.5
    elif candidate == CAR.TUCSON:
      ret.mass = 3520. * CV.LB_TO_KG
      ret.wheelbase = 2.67
      ret.steerRatio = 14.00 * 1.15
      ret.tireStiffnessFactor = 0.385
    elif candidate in (CAR.TUCSON_4TH_GEN, CAR.TUCSON_HYBRID_4TH_GEN):
      ret.mass = 1630.  # average
      ret.wheelbase = 2.756
      ret.steerRatio = 16.
      ret.tireStiffnessFactor = 0.385
    elif candidate == CAR.SANTA_CRUZ_1ST_GEN:
      ret.mass = 1870.  # weight from Limited trim - the only supported trim
      ret.wheelbase = 3.000
      # steering ratio according to Hyundai News https://www.hyundainews.com/assets/documents/original/48035-2022SantaCruzProductGuideSpecsv2081521.pdf
      ret.steerRatio = 14.2
    elif candidate == CAR.CUSTIN_1ST_GEN:
      ret.mass = 1690.  # from https://www.hyundai-motor.com.tw/clicktobuy/custin#spec_0
      ret.wheelbase = 3.055
      ret.steerRatio = 17.0  # from learner
    elif candidate == CAR.STARIA_4TH_GEN:
      ret.mass = 2205.
      ret.wheelbase = 3.273
      ret.steerRatio = 11.94  # https://www.hyundai.com/content/dam/hyundai/au/en/models/staria-load/premium-pip-update-2023/spec-sheet/STARIA_Load_Spec-Table_March_2023_v3.1.pdf

    # Kia
    elif candidate == CAR.KIA_SORENTO:
      ret.mass = 1985.
      ret.wheelbase = 2.78
      ret.steerRatio = 14.4 * 1.1   # 10% higher at the center seems reasonable
    elif candidate in (CAR.KIA_NIRO_EV, CAR.KIA_NIRO_EV_2ND_GEN, CAR.KIA_NIRO_PHEV, CAR.KIA_NIRO_HEV_2021, CAR.KIA_NIRO_HEV_2ND_GEN, CAR.KIA_NIRO_PHEV_2022):
      ret.mass = 3543. * CV.LB_TO_KG  # average of all the cars
      ret.wheelbase = 2.7
      ret.steerRatio = 13.6  # average of all the cars
      ret.tireStiffnessFactor = 0.385
      if candidate == CAR.KIA_NIRO_PHEV:
        ret.minSteerSpeed = 32 * CV.MPH_TO_MS
    elif candidate in (CAR.KIA_SELTOS, CAR.KIA_SELTOS_2023_NON_SCC):
      ret.mass = 1337.
      ret.wheelbase = 2.63
      ret.steerRatio = 14.56
    elif candidate == CAR.KIA_SPORTAGE_5TH_GEN:
      ret.mass = 1700.  # weight from SX and above trims, average of FWD and AWD versions
      ret.wheelbase = 2.756
      ret.steerRatio = 13.6  # steering ratio according to Kia News https://www.kiamedia.com/us/en/models/sportage/2023/specifications
    elif candidate in (CAR.KIA_OPTIMA_G4, CAR.KIA_OPTIMA_G4_FL, CAR.KIA_OPTIMA_H, CAR.KIA_OPTIMA_H_G4_FL):
      ret.mass = 3558. * CV.LB_TO_KG
      ret.wheelbase = 2.80
      ret.steerRatio = 13.75
      ret.tireStiffnessFactor = 0.5
      if candidate == CAR.KIA_OPTIMA_G4:
        ret.minSteerSpeed = 32 * CV.MPH_TO_MS
    elif candidate in (CAR.KIA_STINGER, CAR.KIA_STINGER_2022):
      ret.mass = 1825.
      ret.wheelbase = 2.78
      ret.steerRatio = 14.4 * 1.15   # 15% higher at the center seems reasonable
    elif candidate in (CAR.KIA_FORTE, CAR.KIA_FORTE_2019_NON_SCC, CAR.KIA_FORTE_2021_NON_SCC):
      ret.mass = 2878. * CV.LB_TO_KG
      ret.wheelbase = 2.80
      ret.steerRatio = 13.75
      ret.tireStiffnessFactor = 0.5
    elif candidate == CAR.KIA_CEED:
      ret.mass = 1450.
      ret.wheelbase = 2.65
      ret.steerRatio = 13.75
      ret.tireStiffnessFactor = 0.5
    elif candidate in (CAR.KIA_K5_2021, CAR.KIA_K5_HEV_2020):
      ret.mass = 3381. * CV.LB_TO_KG
      ret.wheelbase = 2.85
      ret.steerRatio = 13.27  # 2021 Kia K5 Steering Ratio (all trims)
      ret.tireStiffnessFactor = 0.5
    elif candidate == CAR.KIA_EV6:
      ret.mass = 2055
      ret.wheelbase = 2.9
      ret.steerRatio = 16.
      ret.tireStiffnessFactor = 0.65
    elif candidate == CAR.KIA_SPORTAGE_HYBRID_5TH_GEN:
      ret.mass = 1767.  # SX Prestige trim support only
      ret.wheelbase = 2.756
      ret.steerRatio = 13.6
    elif candidate in (CAR.KIA_SORENTO_4TH_GEN, CAR.KIA_SORENTO_HEV_4TH_GEN, CAR.KIA_SORENTO_PHEV_4TH_GEN):
      ret.wheelbase = 2.81
      ret.steerRatio = 13.5  # average of the platforms
      if candidate == CAR.KIA_SORENTO_4TH_GEN:
        ret.mass = 3957 * CV.LB_TO_KG
      elif candidate == CAR.KIA_SORENTO_HEV_4TH_GEN:
        ret.mass = 4255 * CV.LB_TO_KG
      else:
        ret.mass = 4537 * CV.LB_TO_KG
    elif candidate == CAR.KIA_CARNIVAL_4TH_GEN:
      ret.mass = 2087.
      ret.wheelbase = 3.09
      ret.steerRatio = 14.23
    elif candidate == CAR.KIA_K8_HEV_1ST_GEN:
      ret.mass = 1630.  # https://carprices.ae/brands/kia/2023/k8/1.6-turbo-hybrid
      ret.wheelbase = 2.895
      ret.steerRatio = 13.27  # guesstimate from K5 platform

    # Genesis
    elif candidate == CAR.GENESIS_GV60_EV_1ST_GEN:
      ret.mass = 2205
      ret.wheelbase = 2.9
      # https://www.motor1.com/reviews/586376/2023-genesis-gv60-first-drive/#:~:text=Relative%20to%20the%20related%20Ioniq,5%2FEV6%27s%2014.3%3A1.
      ret.steerRatio = 12.6
    elif candidate == CAR.GENESIS_G70:
      ret.steerActuatorDelay = 0.1
      ret.mass = 1640.0
      ret.wheelbase = 2.84
      ret.steerRatio = 13.56
    elif candidate in (CAR.GENESIS_G70_2020, CAR.GENESIS_G70_2021_NON_SCC):
      ret.mass = 3673.0 * CV.LB_TO_KG
      ret.wheelbase = 2.83
      ret.steerRatio = 12.9
    elif candidate == CAR.GENESIS_GV70_1ST_GEN:
      ret.mass = 1950.
      ret.wheelbase = 2.87
      ret.steerRatio = 14.6
    elif candidate == CAR.GENESIS_G80:
      ret.mass = 2060.
      ret.wheelbase = 3.01
      ret.steerRatio = 16.5
    elif candidate == CAR.GENESIS_G90:
      ret.mass = 2200.
      ret.wheelbase = 3.15
      ret.steerRatio = 12.069
    elif candidate == CAR.GENESIS_GV80:
      ret.mass = 2258.
      ret.wheelbase = 2.95
      ret.steerRatio = 14.14

    # optech: Korean market cars, specs from optech-hkg (apilot / carrot; mass here without the cargo it adds)
    elif candidate in (CAR.GRANDEUR_IG, CAR.GRANDEUR_IG_HEV):
      ret.mass = 1570.
      ret.wheelbase = 2.845
      ret.steerRatio = 16.
      ret.tireStiffnessFactor = 0.8
    elif candidate in (CAR.GRANDEUR_IG_FL, CAR.GRANDEUR_IG_FL_HEV):
      ret.mass = 1675.
      ret.wheelbase = 2.885
      ret.steerRatio = 16.5
      ret.tireStiffnessFactor = 0.8
      ret.steerActuatorDelay = 0.2
    elif candidate == CAR.NEXO:
      ret.mass = 1885.
      ret.wheelbase = 2.79
      ret.steerRatio = 15.3
      ret.tireStiffnessFactor = 0.385
    elif candidate == CAR.CASPER:
      ret.mass = 1060.
      ret.wheelbase = 2.4
      ret.steerRatio = 14.3
    elif candidate == CAR.CASPER_EV:
      ret.mass = 1355.
      ret.wheelbase = 2.58
      ret.steerRatio = 14.3
    elif candidate == CAR.VENUE_2021_NON_SCC:  # sunnypilot (wheelbase, steer ratio); curb weight about 1.2 t
      ret.mass = 1200.
      ret.wheelbase = 2.52
      ret.steerRatio = 14.4
      ret.tireStiffnessFactor = 0.65
    elif candidate == CAR.KIA_RAY_EV:  # StarPilot
      ret.mass = 1295.
      ret.wheelbase = 2.52
      ret.steerRatio = 14.5
      ret.tireStiffnessFactor = 0.65
    elif candidate == CAR.PORTER_II_EV:  # carrot
      ret.mass = 1970.
      ret.wheelbase = 2.64
      ret.steerRatio = 14.5
      ret.tireStiffnessFactor = 0.65
    elif candidate == CAR.KONA_2022:
      ret.mass = 1491.
      ret.wheelbase = 2.6
      ret.steerRatio = 13.42
      ret.tireStiffnessFactor = 0.385
    elif candidate in (CAR.K7, CAR.K7_HEV, CAR.K7_PE, CAR.K7_HEV_PE):
      ret.mass = 1850.
      ret.wheelbase = 2.855
      ret.steerRatio = 15.5
      ret.tireStiffnessFactor = 0.7
    elif candidate == CAR.KIA_MOHAVE:
      ret.mass = 2285.
      ret.wheelbase = 2.895
      ret.steerRatio = 16.
      ret.tireStiffnessFactor = 0.7
    elif candidate in (CAR.KIA_K5_JF, CAR.KIA_K5_HEV_JF, CAR.KIA_K5_HEV_2022):
      ret.mass = 1705. if candidate == CAR.KIA_K5_HEV_JF else 1515.
      ret.wheelbase = 2.85 if candidate == CAR.KIA_K5_HEV_2022 else 2.80
      ret.steerRatio = 15.5
      ret.tireStiffnessFactor = 0.7
    elif candidate == CAR.KIA_K9:
      ret.mass = 2075.
      ret.wheelbase = 3.15
      ret.steerRatio = 14.5
      ret.tireStiffnessFactor = 0.7
    elif candidate == CAR.GENESIS_EQ900:
      ret.mass = 2200.
      ret.wheelbase = 3.15
      ret.steerRatio = 16.0
      ret.steerActuatorDelay = 0.075
    elif candidate == CAR.GENESIS_EQ900_L:
      ret.mass = 2290.
      ret.wheelbase = 3.45
      ret.steerRatio = 16.0
    elif candidate == CAR.GENESIS_G90_2019:
      ret.mass = 2150.
      ret.wheelbase = 3.16
      ret.steerRatio = 16.0

    # *** longitudinal control ***
    if candidate in CANFD_CAR:
      ret.longitudinalTuning.kpV = [0.1]
      ret.longitudinalTuning.kiV = [0.0]
      ret.experimentalLongitudinalAvailable = candidate not in (CANFD_UNSUPPORTED_LONGITUDINAL_CAR | CANFD_RADAR_SCC_CAR)
    else:
      ret.longitudinalTuning.kpV = [0.5]
      ret.longitudinalTuning.kiV = [0.0]
      # optech: SCC on the camera side (remembered from an earlier drive)
      if candidate not in CAMERA_SCC_CAR and Params().get_bool(CAMERA_SCC_PARAM):
        ret.flags |= HyundaiFlags.CAMERA_SCC.value
      ret.experimentalLongitudinalAvailable = candidate not in UNSUPPORTED_LONGITUDINAL_CAR and not is_camera_scc(ret)
    if ret.flags & HyundaiFlags.NON_SCC:  # no SCC to command: steering with the car's regular cruise control
      ret.experimentalLongitudinalAvailable = False
    ret.openpilotLongitudinalControl = experimental_long and ret.experimentalLongitudinalAvailable
    ret.pcmCruise = not ret.openpilotLongitudinalControl

    # optech: Ray EV / Porter II EV with a comma pedal (the car's menu switch on and the pedal box seen at the start):
    # openpilot does the speed through the accelerator (pedal.py), SET / RES engage, no brake (regen only)
    from openpilot.selfdrive.car.hyundai import pedal as hkg_pedal
    if ret.flags & HyundaiFlags.NON_SCC and hkg_pedal.pedal_wanted(candidate, fingerprint):
      ret.flags |= HyundaiFlags.NON_SCC_PEDAL.value
      if hkg_pedal.strong_wanted(candidate):
        ret.flags |= HyundaiFlags.NON_SCC_PEDAL_STRONG.value
      ret.enableGasInterceptor = True
      ret.experimentalLongitudinalAvailable = True
      ret.openpilotLongitudinalControl = True
      ret.pcmCruise = False
      ret.radarUnavailable = True  # no radar: the camera finds the lead
      ret.minEnableSpeed = -1.
      ret.autoResumeSng = False    # no brake to hold the car
      hkg_pedal.set_long_tune(ret, candidate)

    ret.stoppingControl = True
    ret.startingState = True
    ret.vEgoStarting = 0.1
    ret.startAccel = 1.0
    ret.longitudinalActuatorDelayLowerBound = 0.5
    ret.longitudinalActuatorDelayUpperBound = 0.5

    # *** feature detection ***
    if candidate in CANFD_CAR:
      ret.enableBsm = 0x1e5 in fingerprint[CAN.ECAN]
    else:
      ret.enableBsm = 0x58b in fingerprint[0]

    # *** panda safety config ***
    ret.safetyConfigs = set_safety_config_hyundai(candidate, CAN, can_fd=(candidate in CANFD_CAR))

    if hda2:
      ret.flags |= HyundaiFlags.CANFD_HDA2.value
      ret.safetyConfigs[-1].safetyParam |= Panda.FLAG_HYUNDAI_CANFD_HDA2

    if candidate in CANFD_CAR:
      if hda2 and ret.flags & HyundaiFlags.CANFD_HDA2_ALT_STEERING:
        ret.safetyConfigs[-1].safetyParam |= Panda.FLAG_HYUNDAI_CANFD_HDA2_ALT_STEERING
      if ret.flags & HyundaiFlags.CANFD_ALT_BUTTONS:
        ret.safetyConfigs[-1].safetyParam |= Panda.FLAG_HYUNDAI_CANFD_ALT_BUTTONS

    if ret.flags & HyundaiFlags.CANFD_CAMERA_SCC or is_camera_scc(ret):
      ret.safetyConfigs[-1].safetyParam |= Panda.FLAG_HYUNDAI_CAMERA_SCC
    if ret.flags & HyundaiFlags.NON_SCC:
      ret.safetyConfigs[-1].safetyParam |= Panda.FLAG_HYUNDAI_NON_SCC
      if ret.flags & HyundaiFlags.NON_SCC_NO_TCS:
        ret.safetyConfigs[-1].safetyParam |= Panda.FLAG_HYUNDAI_NON_SCC_NO_TCS
      if ret.flags & HyundaiFlags.NON_SCC_PEDAL:
        ret.safetyConfigs[-1].safetyParam |= Panda.FLAG_HYUNDAI_NON_SCC_PEDAL
        if ret.flags & HyundaiFlags.NON_SCC_PEDAL_STRONG:
          ret.safetyConfigs[-1].safetyParam |= Panda.FLAG_HYUNDAI_NON_SCC_PEDAL_STRONG
    if ret.openpilotLongitudinalControl:
      ret.safetyConfigs[-1].safetyParam |= Panda.FLAG_HYUNDAI_LONG
    if candidate in HYBRID_CAR:
      ret.safetyConfigs[-1].safetyParam |= Panda.FLAG_HYUNDAI_HYBRID_GAS
    elif candidate in EV_CAR:
      ret.safetyConfigs[-1].safetyParam |= Panda.FLAG_HYUNDAI_EV_GAS

    if candidate in (CAR.KONA, CAR.KONA_EV, CAR.KONA_HEV, CAR.KONA_EV_2022, CAR.KONA_NON_SCC, CAR.KONA_EV_NON_SCC):
      ret.flags |= HyundaiFlags.ALT_LIMITS.value
      ret.safetyConfigs[-1].safetyParam |= Panda.FLAG_HYUNDAI_ALT_LIMITS

    ret.centerToFront = ret.wheelbase * 0.4

    # mdps, smart mdps
    if 0x2AA in fingerprint[0] or params.get_bool('dp_hkg_min_steer_speed_bypass'):
      ret.minSteerSpeed = 0.

    return ret

  @staticmethod
  def init(CP, logcan, sendcan):
    # optech: no SCC radar to switch off on the cars without SCC (the pedal ones run openpilot long without one)
    if CP.openpilotLongitudinalControl and not (CP.flags & HyundaiFlags.CANFD_CAMERA_SCC.value) and \
       not (CP.flags & HyundaiFlags.NON_SCC.value):
      addr, bus = 0x7d0, 0
      if CP.flags & HyundaiFlags.CANFD_HDA2.value:
        addr, bus = 0x730, CanBus(CP).ECAN
      disable_ecu(logcan, sendcan, bus=bus, addr=addr, com_cont_req=b'\x28\x83\x01')

    # for blinkers
    if CP.flags & HyundaiFlags.ENABLE_BLINKERS:
      disable_ecu(logcan, sendcan, bus=CanBus(CP).ECAN, addr=0x7B1, com_cont_req=b'\x28\x83\x01')

  def _update(self, c):
    self.CS.cp_pedal = self.cp_body  # optech: comma pedal GAS_SENSOR (None unless NON_SCC_PEDAL)
    ret = self.CS.update(self.cp, self.cp_cam)

    if self.CS.CP.openpilotLongitudinalControl:
      ret.buttonEvents = create_button_events(self.CS.cruise_buttons[-1], self.CS.prev_cruise_buttons, BUTTONS_DICT)

    # On some newer model years, the CANCEL button acts as a pause/resume button based on the PCM state
    # To avoid re-engaging when openpilot cancels, check user engagement intention via buttons
    # Main button also can trigger an engagement on these cars
    allow_enable = any(btn in ENABLE_BUTTONS for btn in self.CS.cruise_buttons) or any(self.CS.main_buttons)
    events = self.create_common_events(ret, pcm_enable=self.CS.CP.pcmCruise and not self.cruise_rule,
                                       allow_enable=allow_enable, cancel_disables=not self.cruise_rule)
    if self.cruise_rule:
      self.cruise_rule_events(ret, c, events, allow_enable)
    if self.CS.scc_bus_changed:  # optech: SCC found on the other bus; saved, applies from the next start
      events.add(EventName.dataNeededDEPRECATED)

    # low speed steer alert hysteresis logic (only for cars with steer cut off above 10 m/s)
    if ret.vEgo < (self.CP.minSteerSpeed + 2.) and self.CP.minSteerSpeed > 10.:
      self.low_speed_alert = True
    if ret.vEgo > (self.CP.minSteerSpeed + 4.):
      self.low_speed_alert = False
    if self.low_speed_alert:
      events.add(car.CarEvent.EventName.belowSteerSpeed)

    ret.events = events.to_msg()

    return ret

  def cruise_rule_events(self, ret, c, events, allow_enable):
    """optech-hkg's cruise button rule (values.optech_cruise_rule): the on / off events from the buttons. Speed control
    pausing on a short CANCEL or the brake (openpilot long) is in controlsd; on stock SCC the car's SCC does that itself
    and openpilot keeps steering (no pcmDisable when it goes off)."""
    # CANCEL held 0.4 s -> all off (every frame while it stays held, so it also keeps openpilot from coming on)
    self.cancel_frames = self.cancel_frames + 1 if self.CS.cruise_buttons[-1] == Buttons.CANCEL else 0
    if self.cancel_frames >= int(CANCEL_ALL_OFF_TIME / DT_CTRL):
      events.add(EventName.buttonCancel)

    # the cruise (main) button pressed while openpilot is on -> all off (stock SCC: the standby goes off as well)
    main_pressed = any(self.CS.main_buttons)
    self.main_frames_since = 0 if main_pressed else self.main_frames_since + 1
    if main_pressed and not self.main_pressed_prev and c.enabled:
      events.add(EventName.buttonCancel)
    self.main_pressed_prev = main_pressed

    if self.CP.pcmCruise:
      if ret.cruiseState.enabled and not self.CS.out.cruiseState.enabled and allow_enable:
        # the driver's SET / RES turned the car's SCC on -> openpilot on as well (steering + the car's speed control)
        events.add(EventName.pcmEnable)
      elif ret.cruiseState.available and not self.CS.out.cruiseState.available and \
           self.main_frames_since < int(MAIN_STEER_ON_TIME / DT_CTRL):
        # the driver turned the cruise standby on with the cruise button -> steering only (SET / RES for the speed).
        # A standby that comes on by itself at the start stays off. CAN FD: the standby is not seen (always on), so
        # there openpilot comes on with SET / RES only, as in optech-hkg-fd
        events.add(EventName.pcmEnable)

  def apply(self, c, now_nanos):
    return self.CC.update(c, self.CS, now_nanos)
