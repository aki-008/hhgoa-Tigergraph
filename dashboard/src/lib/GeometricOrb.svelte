<script>
  // GeometricOrb ported to Svelte + plain Three.js (react-three/fiber is React-only).
  // Same motion math as the reference: pole-to-pole latitude lines, squiggle
  // displacement, per-vertex depth fade. Transparent background to sit in UI.
  import * as THREE from "three";
  import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
  import { Line2 } from "three/examples/jsm/lines/Line2.js";
  import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
  import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";

  let {
    numLines = 16,
    radius = 1.5,
    speed = 20,
    lineWidth = 2.5,
    color = "#8ab4ff",
    squiggleAmount = 0.04,
    squiggleFrequency = 4,
    squiggleSpeed = 2,
    pointsPerLine = 72,
    enableZoom = false,
    minDistance = 2,
    maxDistance = 20,
    active = false, // true while the agent is consulting a source
  } = $props();

  let host = $state(null);
  let cleanup = null;
  let failed = $state(false);

  $effect(() => {
    if (!host) return;
    try {
      cleanup = init();
    } catch (_) {
      failed = true;
    }
    return () => cleanup?.();
  });

  function init() {
    const W = () => host.clientWidth || 200;
    const H = () => host.clientHeight || 200;
    const energy = () => (active ? 1.7 : 0.7);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(W(), H());
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, W() / H(), 0.1, 100);
    camera.position.set(0, 0, 8);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enablePan = false;
    controls.enableZoom = enableZoom;
    controls.minDistance = minDistance;
    controls.maxDistance = maxDistance;

    const baseColor = new THREE.Color(color);
    const lines = [];
    for (let i = 0; i < numLines; i++) {
      const geometry = new LineGeometry();
      const material = new LineMaterial({
        color: baseColor.getHex(),
        linewidth: lineWidth,
        transparent: true,
        opacity: 1,
        vertexColors: true,
        dashed: false,
      });
      material.resolution.set(W(), H());
      const line = new Line2(geometry, material);
      line.computeLineDistances();
      const group = new THREE.Group();
      group.add(line);
      group.rotation.y = (i / numLines) * Math.PI;
      scene.add(group);
      lines.push({
        idx: i,
        group, geometry, material,
        timeOffset: (i / numLines) * speed,
        longitudeRotation: (i / numLines) * Math.PI,
        cosR: Math.cos((i / numLines) * Math.PI),
        sinR: Math.sin((i / numLines) * Math.PI),
        positions: new Float32Array((pointsPerLine + 1) * 3),
        colors: new Float32Array((pointsPerLine + 1) * 3),
      });
    }

    const camDir = new THREE.Vector3();
    let raf = 0;
    let elapsed = 0;
    let last = performance.now();
    const clock = () => {
      const now = performance.now();
      elapsed += ((now - last) / 1000) * energy();
      last = now;
      return elapsed;
    };
    const tmpV = new THREE.Vector3();

    function frame() {
      raf = requestAnimationFrame(frame);
      const time = clock();
      camDir.copy(camera.position).normalize();
      for (const L of lines) {
        const progress = ((time + L.timeOffset) % speed) / speed;
        const latitude = progress * Math.PI;
        const circleRadius = Math.sin(latitude) * radius;
        const yPosition = Math.cos(latitude) * radius;
        for (let i = 0; i < pointsPerLine; i++) {
          const angle = (i / pointsPerLine) * Math.PI * 2;
          const squiggle =
            Math.sin(angle * squiggleFrequency + time * squiggleSpeed + L.idx * 0.5) *
            squiggleAmount;
          const radiusSquiggle =
            Math.cos(angle * squiggleFrequency * 1.3 + time * squiggleSpeed * 0.8) *
            squiggleAmount * 0.5;
          const displacedRadius = circleRadius + (squiggle + radiusSquiggle) * circleRadius;
          const ySquiggle =
            Math.sin(angle * squiggleFrequency * 0.7 + time * squiggleSpeed * 1.2) *
            squiggleAmount * 0.4;
          const x = Math.cos(angle) * displacedRadius;
          const y = yPosition + ySquiggle * circleRadius;
          const z = Math.sin(angle) * displacedRadius;
          const o = i * 3;
          L.positions[o] = x;
          L.positions[o + 1] = y;
          L.positions[o + 2] = z;
          const worldX = x * L.cosR + z * L.sinR;
          const worldZ = -x * L.sinR + z * L.cosR;
          const dot = worldX * camDir.x + y * camDir.y + worldZ * camDir.z;
          const opacity = ((dot / radius + 1) / 2) * 0.85 + 0.15;
          L.colors[o] = baseColor.r * opacity;
          L.colors[o + 1] = baseColor.g * opacity;
          L.colors[o + 2] = baseColor.b * opacity;
        }
        const last3 = pointsPerLine * 3;
        L.positions[last3] = L.positions[0];
        L.positions[last3 + 1] = L.positions[1];
        L.positions[last3 + 2] = L.positions[2];
        L.colors[last3] = L.colors[0];
        L.colors[last3 + 1] = L.colors[1];
        L.colors[last3 + 2] = L.colors[2];
        L.geometry.setPositions(L.positions);
        L.geometry.setColors(L.colors);
        L.group.rotation.y = L.longitudeRotation;
      }
      controls.update();
      renderer.render(scene, camera);
    }
    frame();

    const ro = new ResizeObserver(() => {
      const w = W(), h = H();
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      for (const L of lines) L.material.resolution.set(w, h);
    });
    ro.observe(host);

    cleanup = () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      for (const L of lines) {
        L.geometry.dispose();
        L.material.dispose();
      }
      renderer.dispose();
      if (renderer.domElement.parentNode === host) host.removeChild(renderer.domElement);
    };
    return cleanup;
  }
</script>

{#if failed}
  <div class="orbfallback" aria-hidden="true"></div>
{:else}
  <div class="orbhost" bind:this={host} aria-hidden="true"></div>
{/if}

<style>
  .orbhost { width: 100%; height: 100%; }
  .orbhost :global(canvas) { width: 100% !important; height: 100% !important; display: block; }
  .orbfallback { width: 100%; height: 100%; border-radius: 50%;
    background: radial-gradient(circle at 38% 32%, #cfe0ff 0%, #5b7cff 38%, #22306e 72%, #0b0d12 100%); }
</style>
