이 폴더는 ND Generator 가 쓰는 템플릿 XML 보관 위치입니다.

  nd_template.xml   <- 프로그램이 항상 이 파일 하나만 읽습니다.

[템플릿 교체 방법]
  1. NIS 에서 원하는 조건(형광 필터, 노출, 카메라 설정 등)으로 ND 실험 XML 을 저장합니다.
  2. 그 파일을 이 폴더에 'nd_template.xml' 이름으로 덮어씁니다.
  3. 프로그램의 [템플릿 새로고침] 버튼을 누르면 바로 반영됩니다. (재시작 불필요)

[주의]
  - 파일 이름은 반드시 nd_template.xml 이어야 합니다.
  - 형광 채널 수는 nd_generator_ui.py 의 NUM_FLUOR_CHANNELS 와 같아야 합니다. (현재 9: BF, FITC, Cy3, Cy5, DAPI, Triple x4)
    채널을 추가/삭제한 템플릿을 쓰려면 그 값도 함께 바꾸고, nd_ref 의 nd_4point.xml / 4porint-reference.xml 도 같은 채널 구성으로 맞추세요.
  - 템플릿에는 XY 위치 루프(RLxExpXYPosLoop)와 형광 루프(RLxExpSpectLoop)가 있어야 합니다.
    XY 좌표는 프로그램이 4point 로부터 계산해 덮어쓰므로 템플릿의 좌표값은 무엇이든 상관없습니다.
  - Z-Stack 은 UI 의 [Z-Stack] 탭에서 켜고 끕니다.
    템플릿에 Z-Stack 이 없어도 켜면 자동으로 추가되고, 있어도 끄면 제거됩니다.
    따라서 템플릿은 Z-Stack 유무와 무관하게 하나만 두면 됩니다.
