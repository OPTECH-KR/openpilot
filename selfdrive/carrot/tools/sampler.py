"""Light statistical profiler for a busy realtime Python process (C2 controlsd diagnostics).

A daemon thread looks at the main thread's stack every `interval` seconds for `duration` seconds and counts, per
function, how often it was on the stack (inclusive) and how often it was the innermost frame (self). The result goes
to /data/drivelog/diag.txt through drivelog.diag_write. Costs about one stack walk per interval and never raises.
"""
import collections
import os
import random
import sys
import threading
import time


class StackSampler:
  def __init__(self, name, interval=0.004, duration=120., start_delay=20., top=25):
    self.name = name
    self.interval = interval
    self.duration = duration
    self.start_delay = start_delay
    self.top = top
    self.main_id = threading.main_thread().ident
    self.incl = collections.Counter()
    self.self_ = collections.Counter()
    self.samples = 0

  def start(self):
    threading.Thread(target=self._run, name=f"{self.name}-sampler", daemon=True).start()

  @staticmethod
  def _key(code):
    return f"{os.path.basename(code.co_filename)}:{code.co_name}"

  def _run(self):
    try:
      time.sleep(self.start_delay)  # skip startup (car init, model warm-up)
      # a short GIL switch interval while sampling, so a sample is not only taken when the main thread blocks
      old_switch = sys.getswitchinterval()
      sys.setswitchinterval(0.0002)
      end = time.monotonic() + self.duration
      while time.monotonic() < end:
        frame = sys._current_frames().get(self.main_id)
        if frame is not None:
          self.samples += 1
          self.self_[self._key(frame.f_code)] += 1
          seen = set()
          while frame is not None:
            k = self._key(frame.f_code)
            if k not in seen:
              self.incl[k] += 1
              seen.add(k)
            frame = frame.f_back
        time.sleep(self.interval * random.uniform(0.5, 1.5))  # jitter: do not lock onto the 100 Hz loop
      sys.setswitchinterval(old_switch)
      self._write()
    except Exception:  # noqa: BLE001  (diagnostics only)
      pass

  def _write(self):
    from selfdrive.carrot.tools.drivelog import diag_write
    n = max(self.samples, 1)
    diag_write(f"{self.name} sampler: {self.samples} samples over {self.duration:.0f} s")
    diag_write(f"{self.name} self%: " + ", ".join(f"{k} {c * 100. / n:.1f}" for k, c in self.self_.most_common(self.top)))
    diag_write(f"{self.name} incl%: " + ", ".join(f"{k} {c * 100. / n:.1f}" for k, c in self.incl.most_common(self.top)))
