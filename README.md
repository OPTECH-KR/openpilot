APILOT C2 PORT (apilot-c2-port)
------

콤마2(C2) / 이온(EON)용 apilot에 **당근파일럿(carrot) 기능을 옮겨 오고**, 실제 운전에 꼭 필요한 설정만 남겨 쉽게 정리한 브랜치입니다.

## ⚠️ 먼저 읽어 주세요

* 설정값을 함부로 바꾸면 사고 위험이 있으며, **사고·고장이 나면 본인 책임**입니다.
* Panda 코드를 수정했기 때문에 **comma connect에 연결하면 BAN** 될 수 있습니다 (연결되어도 업로드 안 됨).
* 항상 운전자가 전방을 보고, 언제든 직접 운전할 준비를 해 주세요.

## 설치

### 새로 설치 (SSH 접속 후 한 줄로 실행)
```
rm -fr /data/openpilot && cd /data/ && GIT_SSL_NO_VERIFY=true git clone https://github.com/OPTECH-KR/openpilot.git -b apilot-c2-port --depth=1 openpilot && echo '#!/usr/bin/bash' > /data/data/com.termux/files/continue.sh && echo "cd /data/openpilot" >> /data/data/com.termux/files/continue.sh && echo "exec ./launch_openpilot.sh" >> /data/data/com.termux/files/continue.sh && chmod u+x /data/data/com.termux/files/continue.sh && reboot
```

### 업데이트
* **화면에서:** 설정 → 소프트웨어 → 최신 업데이트 → **확인**
  * 새 버전이 있으면 **바뀐 내용 목록**이 나오고, **업데이트**를 누르면 받은 뒤 자동으로 재부팅합니다.
  * 업데이트는 **시동을 끈 상태**에서만 보입니다.
* **SSH로:**
```
cd /data/openpilot && GIT_SSL_NO_VERIFY=true git pull && reboot
```

### 빠른 부팅
* 설치나 업데이트 뒤 **첫 부팅만** 빌드(컴파일) 때문에 몇 분 걸립니다.
* 그 다음 부팅부터는 빌드를 **자동으로 건너뛰어서** 빨리 켜집니다. 따로 설정할 것은 없습니다.
* 화면이 이상하면 설정 → 장치 → **다시 빌드**를 누르면 다음 부팅 때 처음부터 다시 빌드합니다.

### 참고: NEOS
* NEOS(C2 운영체제)는 오래돼서 요즘 인터넷 보안 인증서를 확인하지 못합니다.
* 그래서 git 명령 앞에 `GIT_SSL_NO_VERIFY=true`를 붙여야 합니다 (화면의 업데이트 버튼은 알아서 처리).
* 같은 이유로 NEOS 설치 화면에서 **Continue 버튼이 안 뜰 수 있습니다.** 이때는 SSH로 위 설치 명령을 실행해 주세요.

## 지원 차량

* **현대 · 기아 · 제네시스**: 설정 → 당근파일럿 → 시작 → **차종 선택**
* **쉐보레 볼트 EV / EUV**
* 롱컨(openpilot이 가속·브레이크 직접 제어)은 **SCC 모듈(레이더) 배선 개조**가 필요합니다.
  * SCC 모듈의 CCAN 연결을 끊고 → 판다의 **CAN2(BUS2)** 에 연결
  * 작업을 마쳤으면 설정 → 토글 → **롱컨 (Long Control)** 을 켜고 재부팅

## 운전 방식

* **켜고 끄기는 핸들 버튼으로만** 합니다. 자동 인게이지, 가속·브레이크 페달로 크루즈 켜기/끄기 기능은 실수를 막으려고 뺐습니다.
* **가속페달**: 밟는 동안은 운전자가 가속하고, 떼면 다시 openpilot이 제어합니다 (꺼지지 않음).
  * 설정 속도보다 빨리 달렸다가 떼면 설정 속도가 지금 속도로 올라갑니다 (상한은 '가속페달 속도 맞춤 상한', 0이면 끄기).
* **브레이크**: 조향은 유지하고 가감속만 잠시 운전자가 맡습니다. 브레이크를 떼면 아래 조건에서 다시 openpilot이 가감속합니다 ('브레이크 뗀 뒤 자동 재개').
  * 정차 중: 앞차가 10m 안에 있을 때
  * 주행 중: 앞차가 20m보다 멀리 있거나, 앞차 없이 40km/h 이상일 때
  * 다시 가감속할 때 설정 속도: '브레이크 재개 속도' 1 = **브레이크 밟기 전 속도로 복귀**, 0 = 브레이크 뗀 순간의 속도
* **주행 모드는 '일반'으로 고정**입니다 (차간 버튼을 길게 눌러도 바뀌지 않음).
* **차간 거리**: 핸들의 차간 버튼으로 1~4단계 (1.1 / 1.2 / 1.4 / 1.6초).
* **신호 정지 기능은 꺼져 있습니다.** 빨간불에는 운전자가 브레이크로 멈춰 주세요. 앞차가 서면 따라서 서는 기능은 그대로 동작합니다.

## 이 브랜치에서 추가·변경한 것

* **당근(C3X) 스타일 화면**: 주행 화면 왼쪽 아래 정보 박스 (설정 → 당근파일럿 → 화면 → 화면 모드 **6**)
  * 주행 모드, 차간 단계, 기어, 제한속도·카메라, APM 연결, 신호등, 기기 상태(CPU·메모리·저장공간)
* **설정 메뉴 전체 한국어화** + 항목마다 쉬운 설명
* **당근파일럿 메뉴를 탭 4개로 정리** (시작 / 주행 / 화면 / 고급, 아래 표 참고)
* **내장 과속카메라 DB**: 내비 앱 없이 GPS만으로 고정식 단속카메라 앞에서 감속
  * 공공데이터포털 '전국무인교통단속카메라표준데이터' 중 과속·신호과속·구간단속 약 3만 1천 대
  * 이동식 카메라와 새로 생긴 카메라는 없습니다.
* **NNFF 조향 보정** (twilsonco NNFF, 당근 c3-wip에서 이식): 현대·기아·제네시스 31개 차종 모델 내장
* **NNFF 라이트**: 모델이 없는 차(K7, 그랜저, 볼트 등)용. 앞쪽 커브 변화를 미리 보고 마찰 보정을 넣어 줌
* **화면 항상 켜기**: 시동이 꺼져 있어도 30초 뒤 화면이 꺼지지 않음 (기본 켜짐)
* **소프트웨어 화면**: 버전, 마지막 업데이트, 브랜치, 커밋, 운영체제 버전 표시 + 업데이트 버튼
* 삭제한 기능: 자동 인게이지, 가속페달·브레이크로 크루즈 켜기/끄기, 인게이지 유지, 가속페달 조작 시 해제, 주행 모드 전환(연비/안전/고속/자동), 신호 정지, 크루즈 연비 제어
  * 메뉴에서 뺀 세부 설정들은 기기를 켤 때마다 **기본값으로 자동 고정**되어 계속 동작합니다.

## 설정 메뉴 (설정 → 당근파일럿)

### 시작
| 항목 | 설명 |
|---|---|
| 차종 선택 | 내 차 선택 (현대·기아·제네시스) |
| 부팅 시 핫스팟 켜기 | 기기가 켜질 때 핫스팟 자동 켜기 |
| 업데이트 확인 후 적용 | 새 버전 확인 → 바뀐 내용 보고 업데이트 |

### 주행 (평소엔 여기만 보시면 됩니다)
| 묶음 | 항목 | 설명 |
|---|---|---|
| 브레이크 | 브레이크 뗀 뒤 자동 재개 | 브레이크를 떼면 다시 openpilot이 가감속 |
| | 브레이크 재개 속도 | 1: 원래 설정 속도로 복귀 / 0: 뗀 순간의 속도 |
| | 소프트홀드 | 정차 후 브레이크를 떼도 차를 잡아 줌 (0 끔 / 1 켬 / 2 SCC와 함께) |
| 크루즈 | 크루즈 알림음 | 크루즈 켜고 끌 때 소리 (0 끔 / 1 작게 / 2 크게) |
| | 버튼 한 번에 바뀌는 속도 | 크루즈 속도 버튼 한 번에 몇 km/h |
| | 가속페달 속도 맞춤 상한 | 가속페달로 올린 속도를 설정 속도로 (0이면 끔) |
| | 제한속도까지 자동 올림 | 앞차를 따라갈 때 설정 속도를 도로 제한속도까지 올림 (0이면 끔) |
| 감속 | 커브 자동 감속 | 커브 앞에서 미리 감속 |
| | 카메라 감속 | 과속카메라 앞 감속 (0 끔 / 1 APM / 2 APM+순정 내비 / 3 NDA) |
| | 내장 카메라 DB | 내비 앱 없이 내장 DB로 카메라 감속 (재부팅 필요) |
| | 카메라 알림 | 0 끔 / 1 핸들 진동 / 2 계기판 / 3 HUD |
| | 방지턱 통과 속도 | 과속방지턱을 넘을 때 속도 |
| 조향 | 경로 좌우 보정 (쏠릴 때) | 차가 한쪽으로 치우치면 보정 (- 왼쪽 / + 오른쪽) |
| | NNFF 조향 보정 | 모델이 있는 31개 차종용 (재부팅 필요) |
| | NNFF 라이트 | 모델이 없는 차용 (재부팅 필요) |
| | 차선변경 최소 속도 | 방향지시등 자동 차선 변경이 되는 최소 속도 |

### 화면
화면 모드 · 화면 항상 켜기 · 타이어 공기압 · 시간 표시 · 기기 상태 · 후측방(BSD) 경고 · APM 연결 표시 · 운전자 모니터링

* **운전자 모니터링**: 1 = 얼굴 인식 켬 / 0 = 아이콘만 숨김 / **-1 = 얼굴 인식 끄기** (재부팅 필요, 대신 핸들·페달·버튼 조작이 몇 분 동안 없으면 경고)

### 고급 (차가 이상할 때만)
| 묶음 | 언제 보나 | 항목 |
|---|---|---|
| 조향 세부 | 커브에서 덜 꺾이거나 너무 꺾일 때 | 조향비 고정, 실시간 조향비 적용, 조향 반응 지연 보정, 토크 사용자 설정·가속 계수·마찰 계수 |
| 출발·정지 | 출발이 굼뜨거나 정지가 거칠 때 | 출발 저크, 출발 가속, 정지 유지 힘, 앞차 뒤 정지 거리 |
| 속도별 가속 세기 | 가속이 너무 세거나 약할 때 | 0 / 40 / 60 / 80 / 110 / 140 km/h |
| 커브 | 커브 감속이 과하거나 부족할 때 | 커브 감속 비율 |
| 실험 모드 | | openpilot 가감속 제어(알파), 실험 모드 |
| 개발용 | | 디버그 정보, 디버그 그래프, 오류 로그 |

## 토글 (설정 → 토글)
* **롱컨 (Long Control)**: 롱컨 작업(SCC 배선 개조)을 마치셨으면 켜 주세요. 재부팅 후 적용.
* **레이더 트랙 사용**: SCC 데이터 대신 레이더 트랙 사용 (산타페 2022 HEV 등)

## APM (내비 앱 연동, 선택)
* 폰에 **APilotMan(APM)** 앱을 설치하면 내비 앱(Waze, Tmap 등)의 카메라·안내 정보를 C2로 보내 줍니다.
* 폰과 C2가 **같은 와이파이(또는 C2 핫스팟)** 에 있어야 합니다.
* APM은 내비 앱 로그를 읽어야 해서, PC에 폰을 연결하고 한 번 실행해 주세요:
```
adb shell pm grant com.ajouatom.apilotman android.permission.READ_LOGS
```
* 연결되면 화면에 APM 연결 표시가 나옵니다. 맵피(Mappy)는 서비스가 끝나서 쓸 수 없습니다.
* 내비 앱 없이 카메라 감속만 쓰려면 **내장 카메라 DB**를 켜면 됩니다.

## 만든 사람과 출처
* apilot: ajouatom
* 당근파일럿(carrot), c3-wip: ajouatom
* NNFF: twilsonco
* 과속카메라 데이터: 공공데이터포털 (전국무인교통단속카메라표준데이터)
* C2 포팅·정리: OPTECH-KR

![](https://i.imgur.com/b0ZyIx5.jpg)

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
* A supported device to run this software: a [comma three](https://comma.ai/shop/products/three).
* This software. The setup procedure of the comma three allows the user to enter a URL for custom software.
The URL, openpilot.comma.ai will install the release version of openpilot. To install openpilot master, you can use installer.comma.ai/commaai/master, and replacing commaai with another GitHub username can install a fork.
* One of [the 150+ supported cars](docs/CARS.md). We support Honda, Toyota, Hyundai, Nissan, Kia, Chrysler, Lexus, Acura, Audi, VW, and more. If your car is not supported but has adaptive cruise control and lane-keeping assist, it's likely able to run openpilot.
* A [car harness](https://comma.ai/shop/products/car-harness) to connect to your car.

We have detailed instructions for [how to mount the device in a car](https://comma.ai/setup).

Running on PC
------

All of openpilot's services can run as normal on a PC, even without special hardware or a car. To develop or experiment with openpilot you can run openpilot on recorded or simulated data.

With openpilot's tools, you can plot logs, replay drives, and watch the full-res camera streams. See [the tools README](tools/README.md) for more information.

You can also run openpilot in simulation [with the CARLA simulator](tools/sim/README.md). This allows openpilot to drive around a virtual car on your Ubuntu machine. The whole setup should only take a few minutes but does require a decent GPU.

A PC running openpilot can also control your vehicle if it is connected to a [webcam](https://github.com/commaai/openpilot/tree/master/tools/webcam), a [black panda](https://comma.ai/shop/products/panda), and a [harness](https://comma.ai/shop/products/car-harness).

Community and Contributing
------

openpilot is developed by [comma](https://comma.ai/) and by users like you. We welcome both pull requests and issues on [GitHub](http://github.com/commaai/openpilot). Bug fixes and new car ports are encouraged. Check out [the contributing docs](docs/CONTRIBUTING.md).

Documentation related to openpilot development can be found on [docs.comma.ai](https://docs.comma.ai). Information about running openpilot (e.g. FAQ, fingerprinting, troubleshooting, custom forks, community hardware) should go on the [wiki](https://github.com/commaai/openpilot/wiki).

You can add support for your car by following guides we have written for [Brand](https://blog.comma.ai/how-to-write-a-car-port-for-openpilot/) and [Model](https://blog.comma.ai/openpilot-port-guide-for-toyota-models/) ports. Generally, a car with adaptive cruise control and lane keep assist is a good candidate. [Join our Discord](https://discord.comma.ai) to discuss car ports: most car makes have a dedicated channel.

Want to get paid to work on openpilot? [comma is hiring](https://comma.ai/jobs/).

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
    ├── pyextra             # Extra python packages
    └── system              # Generic services
        ├── camerad         # Driver to capture images from the camera sensors
        ├── clocksd         # Broadcasts current time
        ├── hardware        # Hardware abstraction classes
        ├── logcatd         # systemd journal as a service
        └── proclogd        # Logs information from /proc
    └── selfdrive           # Code needed to drive the car
        ├── assets          # Fonts, images, and sounds for UI
        ├── athena          # Allows communication with the app
        ├── boardd          # Daemon to talk to the board
        ├── car             # Car specific code to read states and control actuators
        ├── controls        # Planning and controls
        ├── debug           # Tools to help you debug and do car ports
        ├── locationd       # Precise localization and vehicle parameter estimation
        ├── loggerd         # Logger and uploader of car data
        ├── manager         # Deamon that starts/stops all other daemons as needed
        ├── modeld          # Driving and monitoring model runners
        ├── monitoring      # Daemon to determine driver attention
        ├── navd            # Turn-by-turn navigation
        ├── sensord         # IMU interface code
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
[![Total alerts](https://img.shields.io/lgtm/alerts/g/commaai/openpilot.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/commaai/openpilot/alerts/)
[![Language grade: Python](https://img.shields.io/lgtm/grade/python/g/commaai/openpilot.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/commaai/openpilot/context:python)
[![Language grade: C/C++](https://img.shields.io/lgtm/grade/cpp/g/commaai/openpilot.svg?logo=lgtm&logoWidth=18)](https://lgtm.com/projects/g/commaai/openpilot/context:cpp)
[![codecov](https://codecov.io/gh/commaai/openpilot/branch/master/graph/badge.svg)](https://codecov.io/gh/commaai/openpilot)
