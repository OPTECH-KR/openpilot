from cereal import log
from common.conversions import Conversions as CV

# C2 cereal nests these enums under LateralPlan (newer cereal has them at top level).
LaneChangeState = log.LateralPlan.LaneChangeState
LaneChangeDirection = log.LateralPlan.LaneChangeDirection
Desire = log.LateralPlan.Desire
TurnDirection = Desire

LANE_CHANGE_SPEED_MIN = 30 * CV.KPH_TO_MS
LANE_CHANGE_TIME_MAX = 10.0

BLINKER_NONE = 0
BLINKER_LEFT = 1
BLINKER_RIGHT = 2
BLINKER_BOTH = 3

DESIRES = {
  LaneChangeDirection.none: {
    LaneChangeState.off: Desire.none,
    LaneChangeState.preLaneChange: Desire.none,
    LaneChangeState.laneChangeStarting: Desire.none,
    LaneChangeState.laneChangeFinishing: Desire.none,
  },
  LaneChangeDirection.left: {
    LaneChangeState.off: Desire.none,
    LaneChangeState.preLaneChange: Desire.none,
    LaneChangeState.laneChangeStarting: Desire.laneChangeLeft,
    LaneChangeState.laneChangeFinishing: Desire.laneChangeLeft,
  },
  LaneChangeDirection.right: {
    LaneChangeState.off: Desire.none,
    LaneChangeState.preLaneChange: Desire.none,
    LaneChangeState.laneChangeStarting: Desire.laneChangeRight,
    LaneChangeState.laneChangeFinishing: Desire.laneChangeRight,
  },
}

TURN_DESIRES = {
  TurnDirection.none: Desire.none,
  TurnDirection.turnLeft: Desire.turnLeft,
  TurnDirection.turnRight: Desire.turnRight,
}
