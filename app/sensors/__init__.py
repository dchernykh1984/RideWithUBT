"""Sensors, and the live picture they add up to.

A sensor is a source of typed readings. Nothing above this package learns whether
a reading arrived over Bluetooth Low Energy or ANT+, which is what lets the two
transports be added, replaced or run side by side without the ride, the workout
engine or the recorder noticing.

This module is the transport-independent half: what a reading is, how raw
revolution counters become speed and cadence, and how several devices add up to
one view of the rider. The transports themselves live in `ble.py` and `ant.py`.
"""
