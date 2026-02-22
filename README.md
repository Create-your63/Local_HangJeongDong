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

## 360 equirectangular 폴더 -> cubemap + XMP rig (+mask) 자동화

이미 추출된 equirectangular 이미지 폴더를 입력으로 받아,
각 이미지를 6개 큐브맵(face)으로 분할하고 face별 XMP sidecar를 생성합니다.

또한 마스크 폴더를 함께 주면, 동일한 분할을 마스크에도 적용해
RealityCapture/RealityScan에서 이미지-마스크 매칭이 가능하도록 파일명을 맞춰 출력합니다.

### 스크립트
- `tools/equirect_to_cubemap_xmp.py`

### 예시 실행
```bash
python3 tools/equirect_to_cubemap_xmp.py \
  ./eq_frames \
  ./cubemap_out \
  --mask-dir ./eq_masks \
  --mask-suffix _mask \
  --face-size 1536 \
  --image-format png \
  --image-name-template "{stem}_{face}.{ext}" \
  --mask-name-template "{stem}_{face}_mask.png"
```

### 핵심 포인트
- 입력은 **폴더 단위 배치 처리**입니다.
- 각 원본 프레임마다 6개 face 이미지 + 6개 XMP를 생성합니다.
- `--mask-dir`를 주면 마스크도 동일 투영으로 6개 생성됩니다(최근접 샘플링).
- 마스크 파일명은 `--mask-name-template`로 커스터마이즈할 수 있어,
  사용하는 RealityScan/RealityCapture 매칭 규칙에 맞출 수 있습니다.
- 기본 XMP는 Capturing Reality `xcr` 네임스페이스를 사용합니다.

### 출력
- 분할 이미지들
- 이미지별 `.xmp` sidecar
- (옵션) 분할 마스크 이미지들
- `cubemap_rig_manifest.json`
