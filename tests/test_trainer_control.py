"""The bytes are checked against the two specifications field by field.

A wrong scale here does not fail: the trainer simply holds the wrong number, and
a rider grinding up a phantom eight percent has no way to tell it is the app's
arithmetic rather than their legs."""

from __future__ import annotations

import struct

import pytest

from app.core.control import Command, CommandKind, ControlMode, TrainerDirector
from app.sensors.control import (
    AntTrainerControl,
    BleTrainerControl,
    NoTrainerControl,
)
from app.sensors.control_protocol import (
    DEFAULT_CRR,
    FEC_PAGE_TARGET_POWER,
    FEC_PAGE_TRACK_RESISTANCE,
    FTMS_REQUEST_CONTROL,
    FTMS_SET_SIMULATION,
    FTMS_SET_TARGET_POWER,
    FTMS_START_OR_RESUME,
    PAYLOAD_BYTES,
    ControlError,
    fec_target_power,
    fec_track_resistance,
    ftms_request_control,
    ftms_simulation,
    ftms_start,
    ftms_target_power,
)

# Bluetooth.


def test_asking_for_control_and_starting_are_single_bytes() -> None:
    assert ftms_request_control() == bytes([FTMS_REQUEST_CONTROL])
    assert ftms_start() == bytes([FTMS_START_OR_RESUME])


def test_a_power_target_is_whole_watts_signed() -> None:
    opcode, watts = struct.unpack("<Bh", ftms_target_power(250))

    assert opcode == FTMS_SET_TARGET_POWER
    assert watts == 250


def test_a_simulated_slope_is_hundredths_of_a_percent() -> None:
    opcode, wind, grade, crr, area = struct.unpack("<BhhBB", ftms_simulation(3.5))

    assert opcode == FTMS_SET_SIMULATION
    assert grade == 350
    assert wind == 0
    assert crr == round(DEFAULT_CRR * 10000)
    assert area == 51


def test_a_descent_is_sent_as_a_negative_slope() -> None:
    """The field is signed, so a descent is simply below zero."""
    _, _, grade, _, _ = struct.unpack("<BhhBB", ftms_simulation(-6.25))

    assert grade == -625


# ANT+.


def test_the_fec_power_page_is_eight_bytes_of_quarter_watts() -> None:
    payload = fec_target_power(250)

    assert len(payload) == PAYLOAD_BYTES
    assert payload[0] == FEC_PAGE_TARGET_POWER
    assert struct.unpack("<H", payload[6:8])[0] == 1000


def test_the_fec_resistance_page_shifts_the_grade_to_stay_positive() -> None:
    """FE-C sends grade unsigned with two hundred added, so a descent is not a wrap."""
    level = fec_track_resistance(0.0)
    climb = fec_track_resistance(3.5)
    descent = fec_track_resistance(-6.25)

    assert level[0] == FEC_PAGE_TRACK_RESISTANCE
    assert struct.unpack("<H", level[5:7])[0] == 20000
    assert struct.unpack("<H", climb[5:7])[0] == 20350
    assert struct.unpack("<H", descent[5:7])[0] == 19375
    assert all(len(page) == PAYLOAD_BYTES for page in (level, climb, descent))


def test_the_fec_pages_leave_their_reserved_bytes_alone() -> None:
    assert fec_target_power(100)[1:6] == b"\xff" * 5
    assert fec_track_resistance(1.0)[1:5] == b"\xff" * 4


@pytest.mark.parametrize("watts", [-1, 2500])
def test_an_impossible_target_is_refused_rather_than_wrapped(watts: int) -> None:
    """Wrapping is the failure that would silently ask for the opposite."""
    with pytest.raises(ControlError, match="not a target"):
        ftms_target_power(watts)
    with pytest.raises(ControlError, match="not a target"):
        fec_target_power(watts)


@pytest.mark.parametrize("grade", [-60.0, 90.0])
def test_an_impossible_slope_is_refused(grade: float) -> None:
    with pytest.raises(ControlError, match="not a gradient"):
        ftms_simulation(grade)
    with pytest.raises(ControlError, match="not a gradient"):
        fec_track_resistance(grade)


# Sending them.


class Recorder:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    async def __call__(self, payload: bytes) -> None:
        self.written.append(payload)


async def test_bluetooth_asks_for_control_and_starts_the_machine() -> None:
    """Leaving either out looks exactly like a trainer that ignores ERG."""
    writer = Recorder()

    await BleTrainerControl(writer).take_control()

    assert writer.written == [ftms_request_control(), ftms_start()]


async def test_bluetooth_sends_the_right_command_for_each_mode() -> None:
    writer = Recorder()
    control = BleTrainerControl(writer)

    await control.apply(Command(CommandKind.TARGET_POWER, 240))
    await control.apply(Command(CommandKind.SIMULATION, 2.5))

    assert writer.written == [ftms_target_power(240), ftms_simulation(2.5)]


async def test_ant_needs_no_permission() -> None:
    """On FE-C a page sent is a command given; there is nothing to request."""
    writer = Recorder()

    await AntTrainerControl(writer).take_control()

    assert writer.written == []


async def test_ant_sends_the_right_page_for_each_mode() -> None:
    writer = Recorder()
    control = AntTrainerControl(writer)

    await control.apply(Command(CommandKind.TARGET_POWER, 240))
    await control.apply(Command(CommandKind.SIMULATION, 2.5))

    assert writer.written == [fec_target_power(240), fec_track_resistance(2.5)]


async def test_a_trainer_that_cannot_be_commanded_swallows_everything() -> None:
    """So a ride never has to ask whether control exists."""
    control = NoTrainerControl()

    await control.take_control()
    await control.apply(Command(CommandKind.TARGET_POWER, 240))


# Deciding what to send.


def test_with_control_off_nothing_is_sent() -> None:
    director = TrainerDirector(ControlMode.OFF)

    assert director.update(now=1.0, gradient=0.05, target_w=250) is None


def test_erg_asks_for_the_workout_target() -> None:
    director = TrainerDirector(ControlMode.ERG)

    command = director.update(now=1.0, gradient=0.05, target_w=250)

    assert command == Command(CommandKind.TARGET_POWER, 250)


def test_erg_with_no_target_leaves_the_trainer_alone() -> None:
    """A free warm-up inside an ERG workout has nothing to hold."""
    director = TrainerDirector(ControlMode.ERG)

    assert director.update(now=1.0, target_w=None) is None


def test_simulation_turns_the_gradient_into_a_percentage() -> None:
    director = TrainerDirector(ControlMode.SIMULATION)

    command = director.update(now=1.0, gradient=0.035)

    assert command is not None
    assert command.grade_percent == pytest.approx(3.5)


def test_the_same_value_is_not_sent_again_and_again() -> None:
    """A command shares the radio with the readings; flooding it costs both."""
    director = TrainerDirector(ControlMode.ERG)
    director.update(now=1.0, target_w=250)

    repeats = [director.update(now=1.0 + step, target_w=250) for step in range(1, 8)]

    assert all(command is None for command in repeats)


def test_a_change_too_small_to_feel_is_not_sent() -> None:
    director = TrainerDirector(ControlMode.ERG)
    director.update(now=1.0, target_w=250)

    assert director.update(now=3.0, target_w=252) is None
    assert director.update(now=4.0, target_w=258) is not None


def test_a_change_worth_feeling_goes_out() -> None:
    director = TrainerDirector(ControlMode.SIMULATION)
    director.update(now=1.0, gradient=0.0)

    assert director.update(now=2.0, gradient=0.0005) is None, "a twentieth of a percent"
    assert director.update(now=3.0, gradient=0.02) is not None


def test_commands_are_not_sent_faster_than_the_floor() -> None:
    director = TrainerDirector(ControlMode.ERG, min_interval_s=0.5)
    director.update(now=1.0, target_w=200)

    assert director.update(now=1.2, target_w=400) is None
    assert director.update(now=1.6, target_w=400) is not None


def test_a_standing_value_is_repeated_now_and_then() -> None:
    """In case the trainer missed it, or was reset while the rider was riding."""
    director = TrainerDirector(ControlMode.ERG, refresh_after_s=10.0)
    director.update(now=0.0, target_w=250)

    assert director.update(now=5.0, target_w=250) is None
    assert director.update(now=11.0, target_w=250) is not None


def test_switching_mode_sends_at_once() -> None:
    director = TrainerDirector(ControlMode.ERG)
    director.update(now=1.0, target_w=250)

    director.mode = ControlMode.SIMULATION
    command = director.update(now=2.0, gradient=0.03)

    assert command is not None
    assert command.kind is CommandKind.SIMULATION


def test_resetting_makes_the_next_command_go_out() -> None:
    director = TrainerDirector(ControlMode.ERG)
    director.update(now=1.0, target_w=250)

    director.reset()

    assert director.last_command is None
    assert director.update(now=1.1, target_w=250) is not None
