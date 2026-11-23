<p align="center"><img src="selfdrive/assets/img_optech.png" width="160"></p>

<h1 align="center">OPTECH C2 · optech-spst</h1>

<p align="center">콤마2(C2) · 이온(EON)용 openpilot<br>legacypilot(드래곤파일럿 d2 계열)에 OPTECH 화면 · 설정 메뉴 · 써니파일럿 · 스타파일럿 기능을 옮겨 왔습니다.</p>

---

## 어떤 브랜치를 설치하나요?

| 브랜치 | 차량 | 판다 |
|---|---|---|
| **optech-spst** (이 브랜치) | 현대 · 기아 · 제네시스 **일반 CAN** 차량 + GM · 토요타 · 혼다 등 다른 브랜드 | C2 기본 판다 |
| **optech-hkg** | 현대 · 기아 · 제네시스 **일반 CAN** 차량 (apilot 기반) | C2 기본 판다 |
| **optech-hkg-fd** | 현대 · 기아 · 제네시스 **CAN FD** 차량 (아이오닉 5 · 6, EV6 등 최근 차량) | **레드 판다 필요** |

차종은 설치 후 **설정 → OPTECH → 시작 → 차종 선택**에서 브랜드 → 차종 → 연식 순서로 고릅니다. 자동 인식이 잘 되면 '자동 인식'으로 두세요.

## ⚠️ 먼저 읽어 주세요

* 운전 보조 기능입니다. **항상 전방을 보고, 언제든 직접 운전할 준비**를 해 주세요.
* 설정을 함부로 바꾸면 사고 위험이 있으며, **사고 · 고장은 본인 책임**입니다.
* 판다 코드를 수정했으므로 **comma connect에 연결하면 BAN**될 수 있습니다.

## 지원 차량

### 현대 · 기아 · 제네시스 (일반 CAN)
* **현대**: i30 PD, 그랜저 IG · 그랜저 하이브리드 IG (해외명 아제라), 벨로스터 JS, 싼타페 TM (가솔린 · 하이브리드 · 플러그인), 쏘나타 LF · DN8 (하이브리드 포함), 아반떼 AD · CN7 (하이브리드 포함), 아이오닉 (하이브리드 · 플러그인 · 일렉트릭), 커스틴, 코나 OS (가솔린 · 하이브리드 · 일렉트릭), 투싼 TL, 팰리세이드 LX2
* **기아**: K3 BD, K5 JF (하이브리드 포함) · K5 DL3 (하이브리드 포함), 니로 DE (하이브리드 · 플러그인 · EV), 셀토스, 스팅어, 쏘렌토 UM, 씨드
* **제네시스**: 제네시스 DH, G70, G80 DH, G90
* 조향은 openpilot, 가감속은 차의 순정 스마트 크루즈(SCC)가 맡습니다. 가감속까지 openpilot에 맡기려면 **토글 → openpilot 가감속 제어 (알파)**를 켜세요. 이때 차의 자동 긴급 제동(AEB)이 꺼집니다.
* 크루즈(SCC)가 카메라 쪽에 있는 차는 주행 중 스스로 알아내서 저장하고, 다음 시동부터 적용합니다 (**고급 → 현대 / 기아 / 제네시스 전용**에서 확인 · 변경).
* CAN FD 차량(아이오닉 5 · 6, EV6, 투싼 NX4, 쏘렌토 MQ4, 카니발 KA4, GV70 · GV80 등)은 이 브랜치에 없습니다. **optech-hkg-fd**를 쓰세요.
* 그랜저 IG(2017~2019 가솔린), K7, K9, 모하비, 캐스퍼 등 국내 전용 차종은 아직 없습니다 (optech-hkg에는 있음).

### 쉐보레 (GM)
* **볼트 EUV (2022~2023)**: 조향은 openpilot, 가감속은 차의 순정 ACC.
* **볼트 EV, ACC 없음 (2017~2021)**: 기본은 조향만. comma 페달 장치를 달면 가감속도 합니다. 차종을 고르면 시작 탭에 **볼트 EV 설정**이 나옵니다.
* ACC 없는 GM 차량(이름 끝이 NO ACC), 트랙스 2024, 서버번 2016은 자동 인식이 안 되니 직접 고르세요.

### 그 밖의 브랜드
GMC · 캐딜락 · 뷰익, 토요타 · 렉서스, 혼다 · 어큐라, 폭스바겐 · 아우디 · 세아트 · 스코다, 마쓰다, 닛산, 스바루, 포드, 크라이슬러 · 지프 · 램, 테슬라 등 legacypilot이 지원하는 차종을 그대로 씁니다.

> 현대 · 기아 · 제네시스와 볼트 EV(페달)는 이 브랜치에서 아직 실제 차로 충분히 시험하지 않았습니다. 처음에는 **토글 → openpilot 사용**을 끄고(읽기 전용) 짧게 달려 본 뒤, 안전한 곳에서 조심해서 확인해 주세요.

---

원본 legacypilot 안내 (영어)

# Legacypilot

This software includes contributions from [dragonpilot](https://github.com/dragonpilot-community/dragonpilot/tree/beta2) and [openpilot](https://github.com/commaai/openpilot).

NOTICE: legacypilot is not affiliated with comma.ai and is not an official comma.ai product. legacypilot is released under the terms of the MIT License. See the LICENSE file for more details.


## About

legacypilot is a side project that enables comma.ai EON and Comma Two devices to use the dragonpilot. This project was started after comma.ai deprecated support for the EON in version 0.7.9 and for Comma Two in version 0.8.13.1, in order to provide continued access to these devices.

legacypilot combines the Nuclear Grade Model with the latest openpilot (almost) codebase to create a hybrid solution. With the legacypilot project, we have stripped out nearly 99% of the dragonpilot code.

In summary, legacypilot is based on Openpilot 0.8.16 with the latest vehicle model support from the Openpilot master branch.

Please note that this build is and will always be in the experimental phase and may not be suitable for use as a daily driver.

I recommend using the openpilot [commatwo_master](https://github.com/commaai/openpilot/tree/commatwo_master) branch for your daily driving needs.


## Why use legacypilot

I have decided to make this side project open source for users who wish to:

* Port unsupported vehicles using cheaper devices.
* Evaluate end-to-end lateral and longitudinal control on previously unsupported vehicles.
* Understand the limitations of legacy devices.
* Experience pure openpilot (without the modifications of dragonpilot)
* Make their own EON/C2 fork without spending hundreds of hours reverting and testing code.

By making this project open source, I hope to alleviate some of the frustration and complaints about not being able to access the dragonpilot source code.

I encourage users to consider purchasing a [comma 3x](https://shop.comma.ai) for the best and up-to-date openpilot experience.


## Limitations

* On-road tests are conducted exclusively in a 2021 Toyota C-HR; other models may not perform properly.
* ~~CAN-FD and BODY features are not supported due to outdated libraries in EON/C2 firmware.~~
* The driving AI model remains in version 0.8.16, as porting TinyGrad/PyOpenCL requires significant effort.
* The driver monitoring AI model remains in version 0.8.13.
* Navigation On Openpilot (NOO) is not supported, as it requires a newer driving model that is not currently available in legacypilot.
* Services are not optimized for resource usage, and using all services may result in overheating issues.
* Language files can only be generated in a PC due to missing Qt5 tools.
* webjoystick is disabled as it requires additional python modules. (aiohttp and others)
* Starting from August 7th, 2023, comma has removed ESP/GPS support from Panda. You can find more details about this change in this [link](https://github.com/commaai/panda/commit/c66b98b2a67441faa4cfcd36c3c9d9f90474cd08).
  * Going forward, I will focus solely on maintaining the safety aspects of the code, ensuring that vehicle support and safety declarations remain up to date.
* For safety concern, End-to-End / vision only longitudinal control only available in 0.8.16 driving model.


## Configuration

* For research purposes, the INDI and LQR lateral controllers have been restored. Please use the `dp_lat_controller` parameter to override the default controller (0 = DEFAULT, 1 = INDI, 2 = LQR).
* If you are not a Comma Two device, you can use the `dp_no_fan_ctrl` parameter to disable fan-related detection and control.
* The BODY has been tested and is working; however, I personally haven't tried it, so I'm not sure what steps are needed to get it to work.


## Red Panda (a.k.a. CAN-FD support)
The EON + Red Panda configuration has been tested and worked on [my Toyota](https://youtu.be/KgrI2Ley_Nk) (CAN), so technically it should work on CAN-FD vehicles. However, there are a couple of considerations:
* C2 will not function without hardware modification. You cannot connect the Red Panda directly to the C2 USB port.
* If any changes are made to the Red Panda firmware, the firmware needs to be pre-compiled on a PC and then uploaded to `/data/openpilot/panda/board/obj/`.
* Please be aware that you may encounter **CANBUS disconnection errors**. If this occurs, simply **power cycle BOTH your device and Red Panda**.


=======================

![openpilot on the comma 3X](https://github.com/commaai/openpilot/assets/4038174/f1081737-8718-4241-a22a-3ceba526361a)

Table of Contents
=======================

* [What is openpilot?](#what-is-openpilot)
* [Running in a car](#running-on-a-dedicated-device-in-a-car)
* [Running on PC](#running-on-pc)
* [Community and Contributing](#community-and-contributing)
* [User Data and comma Account](#user-data-and-comma-account)
* [Safety and Testing](#safety-and-testing)
* [Directory Structure](#directory-structure)
* [Licensing](#licensing)

---

What is openpilot?
------

[openpilot](http://github.com/commaai/openpilot) is an open source driver assistance system. Currently, openpilot performs the functions of Adaptive Cruise Control (ACC), Automated Lane Centering (ALC), Forward Collision Warning (FCW), and Lane Departure Warning (LDW) for a growing variety of [supported car makes, models, and model years](docs/CARS.md). In addition, while openpilot is engaged, a camera-based Driver Monitoring (DM) feature alerts distracted and asleep drivers. See more about [the vehicle integration](docs/INTEGRATION.md) and [limitations](docs/LIMITATIONS.md).

<table>
  <tr>
    <td><a href="https://youtu.be/NmBfgOanCyk" title="Video By Greer Viau"><img src="https://i.imgur.com/1w8c6d2.jpg"></a></td>
    <td><a href="https://youtu.be/VHKyqZ7t8Gw" title="Video By Logan LeGrand"><img src="https://i.imgur.com/LnBucik.jpg"></a></td>
    <td><a href="https://youtu.be/VxiR4iyBruo" title="Video By Charlie Kim"><img src="https://i.imgur.com/4Qoy48c.jpg"></a></td>
    <td><a href="https://youtu.be/-IkImTe1NYE" title="Video By Aragon"><img src="https://i.imgur.com/04VNzPf.jpg"></a></td>
  </tr>
  <tr>
    <td><a href="https://youtu.be/iIUICQkdwFQ" title="Video By Logan LeGrand"><img src="https://i.imgur.com/b1LHQTy.jpg"></a></td>
    <td><a href="https://youtu.be/XOsa0FsVIsg" title="Video By PinoyDrives"><img src="https://i.imgur.com/6FG0Bd8.jpg"></a></td>
    <td><a href="https://youtu.be/bCwcJ98R_Xw" title="Video By JS"><img src="https://i.imgur.com/zO18CbW.jpg"></a></td>
    <td><a href="https://youtu.be/BQ0tF3MTyyc" title="Video By Tsai-Fi"><img src="https://i.imgur.com/eZzelq3.jpg"></a></td>
  </tr>
</table>


Running on a dedicated device in a car
------

To use openpilot in a car, you need four things
* A supported device to run this software: a [comma 3X](https://comma.ai/shop/comma-3x) or comma three.
* This software. The setup procedure of the comma 3/3X allows the user to enter a URL for custom software.
The URL, openpilot.comma.ai will install the release version of openpilot. To install openpilot master, you can use installer.comma.ai/commaai/master, and replacing commaai with another GitHub username can install a fork.
* One of [the 250+ supported cars](docs/CARS.md). We support Honda, Toyota, Hyundai, Nissan, Kia, Chrysler, Lexus, Acura, Audi, VW, Ford and more. If your car is not supported but has adaptive cruise control and lane-keeping assist, it's likely able to run openpilot.
* A [car harness](https://comma.ai/shop/products/car-harness) to connect to your car.

We have detailed instructions for [how to mount the device in a car](https://comma.ai/setup).

Running on PC
------

All openpilot services can run as usual on a PC without requiring special hardware or a car. You can also run openpilot on recorded or simulated data to develop or experiment with openpilot.

With openpilot's tools, you can plot logs, replay drives, and watch the full-res camera streams. See [the tools README](tools/README.md) for more information.

You can also run openpilot in simulation [with the CARLA simulator](tools/sim/README.md). This allows openpilot to drive around a virtual car on your Ubuntu machine. The whole setup should only take a few minutes but does require a decent GPU.

A PC running openpilot can also control your vehicle if it is connected to a [webcam](https://github.com/commaai/openpilot/tree/master/tools/webcam), a [black panda](https://comma.ai/shop/products/panda), and a [harness](https://comma.ai/shop/products/car-harness).

Community and Contributing
------

openpilot is developed by [comma](https://comma.ai/) and by users like you. We welcome both pull requests and issues on [GitHub](http://github.com/commaai/openpilot). Bug fixes and new car ports are encouraged. Check out [the contributing docs](docs/CONTRIBUTING.md).

Documentation related to openpilot development can be found on [docs.comma.ai](https://docs.comma.ai). Information about running openpilot (e.g. FAQ, fingerprinting, troubleshooting, custom forks, community hardware) should go on the [wiki](https://github.com/commaai/openpilot/wiki).

You can add support for your car by following guides we have written for [Brand](https://blog.comma.ai/how-to-write-a-car-port-for-openpilot/) and [Model](https://blog.comma.ai/openpilot-port-guide-for-toyota-models/) ports. Generally, a car with adaptive cruise control and lane keep assist is a good candidate. [Join our Discord](https://discord.comma.ai) to discuss car ports: most car makes have a dedicated channel.

Want to get paid to work on openpilot? [comma is hiring](https://comma.ai/jobs#open-positions).

And [follow us on Twitter](https://twitter.com/comma_ai).

User Data and comma Account
------

By default, openpilot uploads the driving data to our servers. You can also access your data through [comma connect](https://connect.comma.ai/). We use your data to train better models and improve openpilot for everyone.

openpilot is open source software: the user is free to disable data collection if they wish to do so.

openpilot logs the road-facing cameras, CAN, GPS, IMU, magnetometer, thermal sensors, crashes, and operating system logs.
The driver-facing camera is only logged if you explicitly opt-in in settings. The microphone is not recorded.

By using openpilot, you agree to [our Privacy Policy](https://comma.ai/privacy). You understand that use of this software or its related services will generate certain types of user data, which may be logged and stored at the sole discretion of comma. By accepting this agreement, you grant an irrevocable, perpetual, worldwide right to comma for the use of this data.

Safety and Testing
----

* openpilot observes ISO26262 guidelines, see [SAFETY.md](docs/SAFETY.md) for more details.
* openpilot has software-in-the-loop [tests](.github/workflows/selfdrive_tests.yaml) that run on every commit.
* The code enforcing the safety model lives in panda and is written in C, see [code rigor](https://github.com/commaai/panda#code-rigor) for more details.
* panda has software-in-the-loop [safety tests](https://github.com/commaai/panda/tree/master/tests/safety).
* Internally, we have a hardware-in-the-loop Jenkins test suite that builds and unit tests the various processes.
* panda has additional hardware-in-the-loop [tests](https://github.com/commaai/panda/blob/master/Jenkinsfile).
* We run the latest openpilot in a testing closet containing 10 comma devices continuously replaying routes.

Directory Structure
------
    .
    ├── cereal              # The messaging spec and libs used for all logs
    ├── common              # Library like functionality we've developed here
    ├── docs                # Documentation
    ├── opendbc             # Files showing how to interpret data from cars
    ├── panda               # Code used to communicate on CAN
    ├── third_party         # External libraries
    └── system              # Generic services
        ├── camerad         # Driver to capture images from the camera sensors
        ├── clocksd         # Broadcasts current time
        ├── hardware        # Hardware abstraction classes
        ├── logcatd         # systemd journal as a service
        ├── loggerd         # Logger and uploader of car data
        ├── proclogd        # Logs information from /proc
        ├── sensord         # IMU interface code
        └── ubloxd          # u-blox GNSS module interface code
    └── selfdrive           # Code needed to drive the car
        ├── assets          # Fonts, images, and sounds for UI
        ├── athena          # Allows communication with the app
        ├── boardd          # Daemon to talk to the board
        ├── car             # Car specific code to read states and control actuators
        ├── controls        # Planning and controls
        ├── debug           # Tools to help you debug and do car ports
        ├── locationd       # Precise localization and vehicle parameter estimation
        ├── manager         # Daemon that starts/stops all other daemons as needed
        ├── modeld          # Driving and monitoring model runners
        ├── monitoring      # Daemon to determine driver attention
        ├── navd            # Turn-by-turn navigation
        ├── test            # Unit tests, system tests, and a car simulator
        └── ui              # The UI

Licensing
------

openpilot is released under the MIT license. Some parts of the software are released under other licenses as specified.

Any user of this software shall indemnify and hold harmless Comma.ai, Inc. and its directors, officers, employees, agents, stockholders, affiliates, subcontractors and customers from and against all allegations, claims, actions, suits, demands, damages, liabilities, obligations, losses, settlements, judgments, costs and expenses (including without limitation attorneys’ fees and costs) which arise out of, relate to or result from any use of this software by user.

**THIS IS ALPHA QUALITY SOFTWARE FOR RESEARCH PURPOSES ONLY. THIS IS NOT A PRODUCT.
YOU ARE RESPONSIBLE FOR COMPLYING WITH LOCAL LAWS AND REGULATIONS.
NO WARRANTY EXPRESSED OR IMPLIED.**

---

<img src="https://d1qb2nb5cznatu.cloudfront.net/startups/i/1061157-bc7e9bf3b246ece7322e6ffe653f6af8-medium_jpg.jpg?buster=1458363130" width="75"></img> <img src="https://cdn-images-1.medium.com/max/1600/1*C87EjxGeMPrkTuVRVWVg4w.png" width="225"></img>

[![openpilot tests](https://github.com/commaai/openpilot/workflows/openpilot%20tests/badge.svg?event=push)](https://github.com/commaai/openpilot/actions)
[![codecov](https://codecov.io/gh/commaai/openpilot/branch/master/graph/badge.svg)](https://codecov.io/gh/commaai/openpilot)
