# Local_HangJeongDong
## 대한민국 17개 광역시/도별 행정동 JEOJSON 파일입니다.

___

본 repository는 [대한민국 행정동 경계 파일](https://github.com/vuski/admdongkor)의 2021년 4월자 업데이트 데이터로 구성한 것입니다.

`plotly.express`를 이용한 간단 사용법 (서울 구별 인구 시각화)
해당 코드는 `seoul_pop.ipynb`에 있습니다.

```python
import os, json
import pandas as pd
import plotly.express as px
!git clone https://github.com/raqoon886/Local_HangJeongDong.git
os.chdir('./Local_HangJeongDong')

with open('./hangjeongdong_서울특별시.geojson', 'r') as f:
    seoul_geo = json.load(f)
    
seoul_info = pd.read_csv('./sample.txt', delimiter='\t')
seoul_info = seoul_info.iloc[3:,:]
seoul_info = seoul_info[seoul_info['동']!='소계']
seoul_info['full_name'] = '서울특별시'+' '+seoul_info['자치구']+' '+seoul_info['동']
seoul_info['full_name'] = seoul_info['full_name'].apply(lambda x: x.replace('.','·'))
seoul_info['인구'] = seoul_info['인구'].apply(lambda x: int(''.join(x.split(','))))

fig = px.choropleth_mapbox(seoul_info,
                           geojson=seoul_geo,
                           locations='full_name',
                           color='인구',
                           color_continuous_scale='viridis', featureidkey = 'properties.adm_nm',
                           mapbox_style='carto-positron',
                           zoom=9.5,
                           center = {"lat": 37.563383, "lon": 126.996039},
                           opacity=0.5,
                          )

fig
```
![](https://github.com/raqoon886/Local_HangJeongDong/blob/master/seoul.png?raw=true)

---

## 360 equirectangular -> cubemap + XMP rig 자동화

이 스크립트는 **이미 추출된 equirectangular 이미지/마스크 폴더**를 입력받아,
각 이미지를 6개 큐브맵 face로 분할하고 face들을 같은 리그 위치로 묶는 XMP를 생성합니다.

### 스크립트
- `tools/equirect_to_cubemap_xmp.py`

### 핵심 기능
- 단일 파일 또는 폴더 일괄 처리
- 이미지 1장 -> `front/right/back/left/up/down` 6장 생성
- 각 face에 XMP sidecar 생성 (`PosePrior/CalibrationPrior locked`)
- 옵션으로 마스크도 동일 투영으로 분할 생성
- RealityCapture/RealityScan 호환 마스크 네이밍 지원
  - 기본: `image.ext.mask.png` (`--output-mask-mode dot-mask`)
  - 대안: `image_stem_mask.png` (`--output-mask-mode suffix`)

### 입력 마스크 자동 탐색 규칙 (`--with-masks`)
원본 이미지가 `frame_0001.png`이면 아래 순서로 마스크를 찾습니다.
1. `frame_0001_mask.<ext>` (`--input-mask-suffix` 기본값 `_mask`)
2. `frame_0001.png.mask.<ext>`

### 실행 예시
```bash
# 단일 이미지 + 마스크
python3 tools/equirect_to_cubemap_xmp.py ./input/frame_0001.png ./output --with-masks

# 폴더 일괄 + RC 스타일 mask 이름 유지
python3 tools/equirect_to_cubemap_xmp.py ./input_frames ./output --with-masks --output-mask-mode dot-mask
```

### 출력물 예시
- `frame_0001_front.png` ... `frame_0001_down.png`
- `frame_0001_front.png.xmp` ...
- (마스크 사용 시) `frame_0001_front.png.mask.png` ...
- `cubemap_rig_manifest.json`

### 참고
- 품질 손실 최소화를 위해 `--image-format png` 권장
- 마스크는 nearest-neighbor로 투영해 경계 번짐을 최소화
