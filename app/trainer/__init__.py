"""Turning what the rider owns into watts.

Two directions, both explicit:

* forward - a plain trainer plus a speed sensor, where the wheel's rollout and
  the trainer's resistance curve give an estimate of power;
* reverse - a real power meter on the same bike, where measured speed and
  measured power are fitted into a curve that can be contributed back.

Nothing here imports Panda3D or talks to a device; it is arithmetic over data.
"""
