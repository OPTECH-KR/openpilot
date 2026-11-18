<p align="center"><img src="https://raw.githubusercontent.com/OPTECH-KR/openpilot/optech/selfdrive/assets/img_optech.png" width="160"></p>

<h1 align="center">OPTECH C2</h1>

<p align="center">콤마2(C2) · 이온(EON)용 openpilot<br>apilot에 당근파일럿 · 써니파일럿 · 스타파일럿 기능을 옮겨 오고, 꼭 필요한 설정만 남겨 쉽게 정리했습니다.</p>

<p align="center"><b><a href="SETTINGS_KO.md">📖 설정 가이드 (모든 메뉴 설명 · 추천값 · 상황별 해결)</a></b></p>

---

## 어떤 브랜치를 설치하나요?

| 브랜치 | 차량 | 판다 |
|---|---|---|
| **optech** | 일반 CAN 차량 (대부분의 현대 · 기아 · 제네시스, 쉐보레 볼트) | C2 기본 판다 |
| **optech-fd** (이 브랜치) | CAN FD 차량 (아이오닉 5 · 6, EV6 등 최근 차량) | **레드 판다 필요** |

내 차가 어느 쪽인지 모르겠으면, 설치 후 **당근파일럿 → 시작 → 차종 선택** 목록에 내 차가 있는지 보세요. 없으면 다른 브랜치입니다.

## ⚠️ 먼저 읽어 주세요

* 운전 보조 기능입니다. **항상 전방을 보고, 언제든 직접 운전할 준비**를 해 주세요.
* 설정을 함부로 바꾸면 사고 위험이 있으며, **사고 · 고장은 본인 책임**입니다.
* 판다 코드를 수정했으므로 **comma connect에 연결하면 BAN**될 수 있습니다.

## 1. 설치

SSH로 기기에 접속해서 아래 한 줄을 붙여 넣으세요. (일반 CAN 차량은 `-b optech-fd`를 `-b optech`로 바꾸세요.)

```
rm -fr /data/openpilot && cd /data/ && GIT_SSL_NO_VERIFY=true git clone https://github.com/OPTECH-KR/openpilot.git -b optech-fd --depth=1 openpilot && echo '#!/usr/bin/bash' > /data/data/com.termux/files/continue.sh && echo "cd /data/openpilot" >> /data/data/com.termux/files/continue.sh && echo "exec ./launch_openpilot.sh" >> /data/data/com.termux/files/continue.sh && chmod u+x /data/data/com.termux/files/continue.sh && reboot
```

* 첫 부팅은 빌드 때문에 몇 분 걸립니다. 그다음부터는 빨리 켜집니다.
* NEOS가 오래돼서 git 명령에는 `GIT_SSL_NO_VERIFY=true`가 필요하고, 설치 화면에서 Continue 버튼이 안 뜰 수 있습니다. 그래서 SSH로 설치합니다.

## 2. 업데이트

* **화면에서:** 당근파일럿 → 시작 → **업데이트 확인 후 적용**. 바뀐 내용을 보여 주고, 받은 뒤 자동으로 재부팅합니다.
* **SSH로:**

```
cd /data/openpilot && GIT_SSL_NO_VERIFY=true git pull && reboot
```

> 예전 브랜치 이름(`apilot-c2-port`, `apilot-c2-canfd`)으로 설치했다면 업데이트가 안 됩니다. 위 **설치** 명령으로 다시 설치해 주세요.

## 3. 처음 설정 (이것만 하면 됩니다)

1. 당근파일럿 → 시작 → **차종 선택** (브랜드 → 차종 → 연식 순으로 정리되어 있습니다)
2. 토글 → **롱컨** (SCC 배선 개조를 했으면 켜기 → 재부팅)
3. 당근파일럿 → 주행 → **내장 카메라 DB 1** (내비 앱을 안 쓰면)
4. 당근파일럿 → 조향 → **NNFF** 또는 **NNFF 라이트** 켜기

나머지는 기본값 그대로 두세요. 불편한 점이 있으면 [설정 가이드의 상황별 해결](SETTINGS_KO.md#상황별-해결)을 보세요.

## 4. 지원 차량

### 현대 · 기아 · 제네시스 CAN FD 차량
* 전체 목록은 기기의 **차종 선택**에서 볼 수 있습니다.
* **레드 판다**가 필요합니다. 기기를 재부팅한 뒤 판다가 안 잡히면 레드 판다를 한 번 다시 꽂아 보세요.
* HDA1 / HDA2 방식은 자동으로 알아냅니다. 필요하면 **기타 차종** 화면에서 직접 고를 수 있습니다.

### 기타 차종 (시험 중)
* 핸들을 각도로 움직이는 신형 차(아이오닉 5 PE, EV6 PE 등)는 당근파일럿 → 시작 → **기타 차종**에서 고릅니다.
* 아직 실제 차로 충분히 시험하지 않았습니다. 처음에는 안전한 곳에서 조심해서 확인해 주세요.

> 레이 EV · 포터 II EV · 쉐보레 볼트는 일반 CAN 차량이라 **optech** 브랜치에 있습니다.

## 5. 운전 방식

* **켜고 끄기는 핸들 버튼으로만** 합니다.
* **가속페달**: 밟는 동안만 운전자가 가속하고, 떼면 다시 openpilot이 제어합니다.
* **브레이크**: 조향은 그대로 두고 가감속만 잠시 운전자가 맡습니다. 떼면 **원래 설정 속도로 돌아갑니다**.
* **차간 거리**: 핸들의 차간 버튼으로 1~4단계.
* **주행 화면**: 당근 C3X 스타일 정보 박스로 고정되어 있습니다.
* **신호 정지는 꺼져 있습니다.** 빨간불에는 브레이크로 멈춰 주세요. 앞차를 따라 서는 것은 됩니다.

## 6. 더 알아보기

* 메뉴 전체 설명, 추천값, 폰 내비 연동(APM): [설정 가이드](SETTINGS_KO.md)
* 바뀐 내용: [배포 기록](https://github.com/OPTECH-KR/openpilot/commits/optech-fd) (자세한 작업 기록은 [optech-fd-dev](https://github.com/OPTECH-KR/openpilot/commits/optech-fd-dev))

## 만든 사람과 출처

* apilot · 당근파일럿: ajouatom
* 써니파일럿 · 스타파일럿 (기능 참고)
* NNFF: twilsonco
* 과속카메라 데이터: 공공데이터포털
* C2 포팅 · 정리: **OPTECH-KR**

원본 [openpilot](https://github.com/commaai/openpilot)은 comma.ai가 만들었고 [MIT 라이선스](LICENSE)를 따릅니다.

**이 소프트웨어는 연구용 알파 버전이며 제품이 아닙니다. 사용에 따른 책임과 법규 준수는 사용자에게 있으며, 어떠한 보증도 하지 않습니다.**
