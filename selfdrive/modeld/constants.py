IDX_N = 33

def index_function(idx, max_val=192, max_idx=32):
  return (max_val) * ((idx/max_idx)**2)


T_IDXS = [index_function(idx, max_val=10.0) for idx in range(IDX_N)]


class ModelConstants:
  """Namespace view of the C2 constants for code ported from newer openpilot/carrot."""
  IDX_N = IDX_N
  T_IDXS = T_IDXS
