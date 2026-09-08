"""Panda3D frontend.

Everything in this package may import Panda3D and may touch the window; nothing
outside it may. That line is what keeps the simulation, the sensors and the
workout engine testable without a display, and what would let a different
frontend be built later without touching them.
"""
