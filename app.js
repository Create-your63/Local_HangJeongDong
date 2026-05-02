import * as THREE from 'https://unpkg.com/three@0.161.0/build/three.module.js';
import { OrbitControls } from 'https://unpkg.com/three@0.161.0/examples/jsm/controls/OrbitControls.js';
import { PLYLoader } from 'https://unpkg.com/three@0.161.0/examples/jsm/loaders/PLYLoader.js';
import { PCDLoader } from 'https://unpkg.com/three@0.161.0/examples/jsm/loaders/PCDLoader.js';
import * as GaussianSplats3D from 'https://cdn.jsdelivr.net/npm/@mkkellogg/gaussian-splats-3d@0.4.7/build/gaussian-splats-3d.module.js';

const canvas = document.getElementById('viewerCanvas');
const modeSelect = document.getElementById('modeSelect');
const urlInput = document.getElementById('urlInput');
const loadBtn = document.getElementById('loadBtn');

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(canvas.clientWidth || window.innerWidth, canvas.clientHeight || window.innerHeight);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0c1019);

const camera = new THREE.PerspectiveCamera(60, 1, 0.01, 1000);
camera.position.set(1.5, 1.5, 1.5);

const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 0.3, 0);
controls.update();

const light = new THREE.DirectionalLight(0xffffff, 1.4);
light.position.set(2, 3, 4);
scene.add(light, new THREE.AmbientLight(0xffffff, 0.45), new THREE.GridHelper(8, 16));

let activeObject = null;
let splatViewer = null;

function setStatus(message) {
  loadBtn.textContent = message;
}

function clearCurrent() {
  if (activeObject) {
    scene.remove(activeObject);
    activeObject = null;
  }
  if (splatViewer) {
    splatViewer.stop();
    splatViewer = null;
  }
}

async function loadPointCloud(url) {
  const lower = url.toLowerCase();
  if (lower.endsWith('.ply')) {
    const loader = new PLYLoader();
    const geometry = await loader.loadAsync(url);
    geometry.computeVertexNormals();
    const material = new THREE.PointsMaterial({ size: 0.01, vertexColors: !!geometry.attributes.color });
    activeObject = new THREE.Points(geometry, material);
  } else if (lower.endsWith('.pcd')) {
    const loader = new PCDLoader();
    activeObject = await loader.loadAsync(url);
  } else {
    throw new Error('Point Cloud 모드에서는 .ply 또는 .pcd 파일을 사용하세요.');
  }

  scene.add(activeObject);
  const box = new THREE.Box3().setFromObject(activeObject);
  const center = box.getCenter(new THREE.Vector3());
  controls.target.copy(center);
  camera.position.copy(center.clone().addScalar(1.5));
  controls.update();
}

async function loadSplat(url) {
  splatViewer = new GaussianSplats3D.Viewer({
    rootElement: document.getElementById('viewerSection'),
    cameraUp: [0, 1, 0],
    cameraPosition: [1.5, 1.5, 1.5],
    cameraLookAt: [0, 0, 0],
    sharedMemoryForWorkers: false,
  });

  await splatViewer.addSplatScene(url, { progressiveLoad: true });
  splatViewer.start();
}

loadBtn.addEventListener('click', async () => {
  const mode = modeSelect.value;
  const url = urlInput.value.trim();
  if (!url) {
    alert('먼저 파일 URL을 입력해주세요.');
    return;
  }

  clearCurrent();
  setStatus('로딩 중...');

  try {
    if (mode === 'point') {
      await loadPointCloud(url);
    } else {
      await loadSplat(url);
    }
    setStatus('불러오기');
  } catch (error) {
    console.error(error);
    setStatus('불러오기');
    alert(error.message || '파일을 불러오지 못했습니다. URL과 CORS 설정을 확인해주세요.');
  }
});

function animate() {
  requestAnimationFrame(animate);
  renderer.setSize(canvas.clientWidth || window.innerWidth, canvas.clientHeight || window.innerHeight, false);
  camera.aspect = (canvas.clientWidth || window.innerWidth) / (canvas.clientHeight || window.innerHeight);
  camera.updateProjectionMatrix();
  renderer.render(scene, camera);
}
animate();
