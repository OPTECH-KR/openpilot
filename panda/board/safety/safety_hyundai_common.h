#ifndef SAFETY_HYUNDAI_COMMON_H
#define SAFETY_HYUNDAI_COMMON_H

const int HYUNDAI_PARAM_EV_GAS = 1;
const int HYUNDAI_PARAM_HYBRID_GAS = 2;
const int HYUNDAI_PARAM_LONGITUDINAL = 4;
const int HYUNDAI_PARAM_CAMERA_SCC = 8;
const int HYUNDAI_PARAM_CANFD_HDA2 = 16;
const int HYUNDAI_PARAM_ALT_LIMITS = 64; // TODO: shift this down with the rest of the common flags
// optech (optech-hkg / StarPilot): cars without SCC, only the regular cruise control (Kia Ray EV, Porter II EV and the
// trims without smart cruise). 32 / 128 are taken by the CAN FD modes.
const int HYUNDAI_PARAM_NON_SCC = 256;
// ... with a comma pedal: openpilot does the speed through GAS_COMMAND (0x200), engaged with SET / RES like op long
const int HYUNDAI_PARAM_NON_SCC_PEDAL = 512;
// ... Ray EV with carrot's strong pedal scaling (PR 570): command 0.70 is raw 795 / 1572 instead of 530 / 1035
const int HYUNDAI_PARAM_NON_SCC_PEDAL_STRONG = 1024;
// ... and no TCS13 (Porter II EV): the brake comes from E_EMS11
const int HYUNDAI_PARAM_NON_SCC_NO_TCS = 2048;

const uint8_t HYUNDAI_PREV_BUTTON_SAMPLES = 8;  // roughly 160 ms
const uint32_t HYUNDAI_STANDSTILL_THRSLD = 12;  // 0.375 kph

enum {
  HYUNDAI_BTN_NONE = 0,
  HYUNDAI_BTN_RESUME = 1,
  HYUNDAI_BTN_SET = 2,
  HYUNDAI_BTN_CANCEL = 4,
};

// common state
bool hyundai_ev_gas_signal = false;
bool hyundai_hybrid_gas_signal = false;
bool hyundai_longitudinal = false;
bool hyundai_camera_scc = false;
bool hyundai_canfd_hda2 = false;
bool hyundai_alt_limits = false;
bool hyundai_non_scc = false;
bool hyundai_non_scc_pedal = false;
bool hyundai_non_scc_pedal_strong = false;
bool hyundai_non_scc_no_tcs = false;
uint8_t hyundai_last_button_interaction;  // button messages since the user pressed an enable button

uint16_t hyundai_canfd_crc_lut[256];

void hyundai_common_init(uint16_t param) {
  hyundai_ev_gas_signal = GET_FLAG(param, HYUNDAI_PARAM_EV_GAS);
  hyundai_hybrid_gas_signal = !hyundai_ev_gas_signal && GET_FLAG(param, HYUNDAI_PARAM_HYBRID_GAS);
  hyundai_camera_scc = GET_FLAG(param, HYUNDAI_PARAM_CAMERA_SCC);
  hyundai_canfd_hda2 = GET_FLAG(param, HYUNDAI_PARAM_CANFD_HDA2);
  hyundai_alt_limits = GET_FLAG(param, HYUNDAI_PARAM_ALT_LIMITS);
  hyundai_non_scc = GET_FLAG(param, HYUNDAI_PARAM_NON_SCC);
  hyundai_non_scc_pedal = hyundai_non_scc && GET_FLAG(param, HYUNDAI_PARAM_NON_SCC_PEDAL);
  hyundai_non_scc_pedal_strong = hyundai_non_scc_pedal && GET_FLAG(param, HYUNDAI_PARAM_NON_SCC_PEDAL_STRONG);
  hyundai_non_scc_no_tcs = hyundai_non_scc && GET_FLAG(param, HYUNDAI_PARAM_NON_SCC_NO_TCS);

  hyundai_last_button_interaction = HYUNDAI_PREV_BUTTON_SAMPLES;

#ifdef ALLOW_DEBUG
  hyundai_longitudinal = GET_FLAG(param, HYUNDAI_PARAM_LONGITUDINAL);
#else
  hyundai_longitudinal = false;
#endif
}

void hyundai_common_cruise_state_check(const int cruise_engaged) {
  // some newer HKG models can re-enable after spamming cancel button,
  // so keep track of user button presses to deny engagement if no interaction

  // enter controls on rising edge of ACC and recent user button press, exit controls when ACC off
  if (!hyundai_longitudinal) {
    if (cruise_engaged && !cruise_engaged_prev && (hyundai_last_button_interaction < HYUNDAI_PREV_BUTTON_SAMPLES)) {
      controls_allowed = true;
    }

    if (!cruise_engaged) {
      controls_allowed = false;
    }
    cruise_engaged_prev = cruise_engaged;
  }
}

void hyundai_common_cruise_buttons_check(const int cruise_button, const int main_button) {
  if ((cruise_button == HYUNDAI_BTN_RESUME) || (cruise_button == HYUNDAI_BTN_SET) || (cruise_button == HYUNDAI_BTN_CANCEL) ||
      (main_button != 0)) {
    hyundai_last_button_interaction = 0U;
  } else {
    hyundai_last_button_interaction = MIN(hyundai_last_button_interaction + 1U, HYUNDAI_PREV_BUTTON_SAMPLES);
  }

  if (hyundai_longitudinal) {
    // enter controls on falling edge of resume or set
    bool set = (cruise_button != HYUNDAI_BTN_SET) && (cruise_button_prev == HYUNDAI_BTN_SET);
    bool res = (cruise_button != HYUNDAI_BTN_RESUME) && (cruise_button_prev == HYUNDAI_BTN_RESUME);
    if (set || res) {
      controls_allowed = true;
    }

    // exit controls on cancel press
    if (cruise_button == HYUNDAI_BTN_CANCEL) {
      controls_allowed = false;
    }

    cruise_button_prev = cruise_button;
  }
}

uint32_t hyundai_common_canfd_compute_checksum(const CANPacket_t *to_push) {
  int len = GET_LEN(to_push);
  uint32_t address = GET_ADDR(to_push);

  uint16_t crc = 0;

  for (int i = 2; i < len; i++) {
    crc = (crc << 8U) ^ hyundai_canfd_crc_lut[(crc >> 8U) ^ GET_BYTE(to_push, i)];
  }

  // Add address to crc
  crc = (crc << 8U) ^ hyundai_canfd_crc_lut[(crc >> 8U) ^ ((address >> 0U) & 0xFFU)];
  crc = (crc << 8U) ^ hyundai_canfd_crc_lut[(crc >> 8U) ^ ((address >> 8U) & 0xFFU)];

  if (len == 24) {
    crc ^= 0x819dU;
  } else if (len == 32) {
    crc ^= 0x9f5bU;
  } else {

  }

  return crc;
}

#endif
