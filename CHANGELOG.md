# Changelog

## [0.2.0](https://github.com/dchernykh1984/RideWithUBT/compare/v0.1.0...v0.2.0) (2026-09-09)


### Features

* **core:** ride with other people on the same road ([c435d50](https://github.com/dchernykh1984/RideWithUBT/commit/c435d50631466a5320ef55f3e6697883bbb3b648))
* **render:** draw the track on a surface, with a line at each edge ([7d908b0](https://github.com/dchernykh1984/RideWithUBT/commit/7d908b00b659be9bd1eca9343abdfc40f1e06e97))
* **settings:** choose your wheel, tyre and trainer ([423bc1d](https://github.com/dchernykh1984/RideWithUBT/commit/423bc1de0950e22946b4d68648c2f1e3f03aacd7))
* **workout:** read the training plan's calendar from Garmin ([a4094c5](https://github.com/dchernykh1984/RideWithUBT/commit/a4094c5d1f7cb5c9c54f694388ce55b5b18f1b2d))


### Documentation

* say how to open an unsigned build on each platform ([a78a51a](https://github.com/dchernykh1984/RideWithUBT/commit/a78a51aedc8e939da6433df41a55e9a67c8dbf8e))

## 0.1.0 (2026-09-09)


### Features

* **core:** ride on power, weight and gradient instead of a fixed speed ([1b702be](https://github.com/dchernykh1984/RideWithUBT/commit/1b702be44f06b516798d35f0822d4196afb8786a))
* **render:** draw the track and ride it with the junction arrow ([c79fd05](https://github.com/dchernykh1984/RideWithUBT/commit/c79fd0533df793694ad6fec69226325e9c018bef))
* **sensors:** add the ANT+ transport ([a6a496f](https://github.com/dchernykh1984/RideWithUBT/commit/a6a496fa213b46a3174c0bd85c811b1756960461))
* **sensors:** add the Bluetooth Low Energy transport ([9151be8](https://github.com/dchernykh1984/RideWithUBT/commit/9151be8b0b3a07d840c3fa8e1e6879f5195af028))
* **sensors:** add the transport-independent sensor layer ([a8771ac](https://github.com/dchernykh1984/RideWithUBT/commit/a8771ac345723c3c32d2c68690257221f13836d7))
* **sensors:** command smart trainers for ERG and course gradient ([ad247d0](https://github.com/dchernykh1984/RideWithUBT/commit/ad247d0c78f54ad869853fc2ea0b72d2a32c2e6b))
* **sensors:** pair devices and ride with them ([395adec](https://github.com/dchernykh1984/RideWithUBT/commit/395adec3259bf886b5a576be70a3962033b201cd))
* **services:** import workouts from Garmin Connect ([9eb420f](https://github.com/dchernykh1984/RideWithUBT/commit/9eb420fdc3d048211f2bb419688b15ca07340195))
* **services:** upload rides to Garmin and Strava ([f82dfab](https://github.com/dchernykh1984/RideWithUBT/commit/f82dfab061affb22acc04092e1a12d2410594296))
* **storage:** record rides as FIT files in the activity store ([dd32bcc](https://github.com/dchernykh1984/RideWithUBT/commit/dd32bcc644a2abbdcb648fd473215bcc013b0a41))
* **storage:** record the ride where it happened ([e35cf2f](https://github.com/dchernykh1984/RideWithUBT/commit/e35cf2fc6c3ab968c04dfdc5fbc512314fc5fa88))
* **trainer:** add wheel and trainer catalogues with power estimation ([5bdb0bf](https://github.com/dchernykh1984/RideWithUBT/commit/5bdb0bf490e640060fee94bcd85e69f60de99281))
* **trainer:** measure a trainer's curve while riding it ([f1505a2](https://github.com/dchernykh1984/RideWithUBT/commit/f1505a20fc6e4efa8e6405a0ab3473771daf5336))
* **workout:** ride structured workouts from generated plans ([95da54c](https://github.com/dchernykh1984/RideWithUBT/commit/95da54cf19a078ce7f86a4ce2bbfe5f14552e6af))
* **world:** add the track network, junctions and navigation ([e4616bb](https://github.com/dchernykh1984/RideWithUBT/commit/e4616bbaae0c451d022a871c8f0981fc35a72037))
* **world:** build a pit lane alongside the circuit ([7e10bee](https://github.com/dchernykh1984/RideWithUBT/commit/7e10bee08b274610d50025fec1acc10b3a65f42f))
* **world:** build the Sokol circuit from OpenStreetMap ([2469e88](https://github.com/dchernykh1984/RideWithUBT/commit/2469e88bba7a86fb0f8201483c20c1ed2c9a546b))
* **world:** give the circuit the ground it really has ([95e5c6c](https://github.com/dchernykh1984/RideWithUBT/commit/95e5c6cd13d70b70492f2dd78b8ea06684980783))


### Bug Fixes

* **build:** make the macOS build work and the self-check honest ([cbd1d23](https://github.com/dchernykh1984/RideWithUBT/commit/cbd1d23b548f6fd0069506919b780040d539cc39))
* **cli:** answer a mistyped name with a sentence, not a stack trace ([e0accfc](https://github.com/dchernykh1984/RideWithUBT/commit/e0accfcee7537e4e6c6483a419ec9af5b0a46ed5))
* **render:** show the whole circuit instead of clipping it at the horizon ([ca70e3a](https://github.com/dchernykh1984/RideWithUBT/commit/ca70e3ad5d1b658d470b3992f50364eb402daa34))
* **sensors:** close a device that fails to open ([0aef3de](https://github.com/dchernykh1984/RideWithUBT/commit/0aef3de4f89dc6aad636107106a244c5edfe7b29))
* **sensors:** read ANT+ revolution counters at their real width ([d836997](https://github.com/dchernykh1984/RideWithUBT/commit/d83699768cf7efd6c8705e1b7f6e77a0e4b8ca57))
* **world:** put the Sokol pit lane on the left of the track ([0cb7a6b](https://github.com/dchernykh1984/RideWithUBT/commit/0cb7a6bfade3e160814ead796f9dd83cd4c7df45))


### Documentation

* describe how the ANT+ radio is driven ([cb12c5a](https://github.com/dchernykh1984/RideWithUBT/commit/cb12c5ac4f843723c4b36178fa69998635ee1d15))
* describe the renderer and the new commands ([fb6b2cf](https://github.com/dchernykh1984/RideWithUBT/commit/fb6b2cf96ca0bf354e9bb219e5293b2eabbd9871))
* explain that the pit lane is built, not traced ([3794f30](https://github.com/dchernykh1984/RideWithUBT/commit/3794f30228b02bb372a46099c269df68107e8c22))
* explain why recordings carry no coordinates ([85b9faa](https://github.com/dchernykh1984/RideWithUBT/commit/85b9faa09d98554a25b0b56cefb9993446d7bf13))
* note that the BLE characteristics are parsed in-tree ([8c4bc2a](https://github.com/dchernykh1984/RideWithUBT/commit/8c4bc2a75ca46efade07efa706566988e7eb3b8f))
* record how a smart trainer is commanded and how often ([634af24](https://github.com/dchernykh1984/RideWithUBT/commit/634af24933a6df421429996fd34f96321e1a701d))
* record how worlds are generated and what Sokol measures ([49ed77a](https://github.com/dchernykh1984/RideWithUBT/commit/49ed77acb00e4604488134352144cf8f2bba2413))
* record the power model and the numbers it has to match ([16ffd74](https://github.com/dchernykh1984/RideWithUBT/commit/16ffd74db0788b214c9724c10e58c09ec97d5d21))
* record the Sokol track layout, junctions and the data split ([8fd698f](https://github.com/dchernykh1984/RideWithUBT/commit/8fd698f0ab1af93335420fca209b80ab7771014c))
* record the workout model and the plan format trap ([48985ee](https://github.com/dchernykh1984/RideWithUBT/commit/48985ee8e95320fd717157df14285f565b4c300f))
