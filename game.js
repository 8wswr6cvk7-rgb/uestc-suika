(() => {
  'use strict';

  const W = 460, H = 630, LEFT = 20, RIGHT = 440, FLOOR = 608, DANGER = 135;
  const STEP = 1 / 120, GRAVITY = 1450, DROP_DELAY = 0.42;
  const names = ['', '电子', '空穴', 'PN 结', '二极管', 'MOS 管', '集成电路', '格拉斯哥', '电子科大'];
  const radii = [0, 19, 27, 37, 49, 63, 79, 98, 119];
  const xScale = [0, 1, 1.30, 1, 1.35, 1, 1.25, 0.88, 1];
  const POLYGON_SIDES = 20;
  const polygonCache = new WeakMap();
  const colors = ['', '#76dcf6', '#ffcb81', '#f78caa', '#a9baff', '#9be9ba', '#7dcbee', '#f5c26d', '#ff9e72'];
  const assetSources = ['', 'lv1.png', 'lv2.png', 'lv3.png', 'lv4.png', 'lv5.png', 'lv6.png', 'lv7.png', 'lv8.png'];
  const images = names.map((_, i) => {
    if (!i) return null;
    const image = new Image();
    image.src = assetSources[i];
    return image;
  });

  const $ = (id) => document.getElementById(id);
  const canvas = $('game'), arena = $('arena'), ctx = canvas.getContext('2d');
  const ui = {
    score: $('score'), best: $('best'), nextImg: $('next-img'), nextName: $('next-name'),
    progress: $('progress-list'), status: $('status'), statusText: $('status-text'), combo: $('combo'),
    overlay: $('overlay'), overlayIcon: $('overlay-icon'), overlayTitle: $('overlay-title'),
    overlayText: $('overlay-text'), overlayBtn: $('overlay-btn'), pause: $('pause-btn'),
    sound: $('sound-btn'), restart: $('restart-btn'), hint: $('hint')
  };

  function readBest() {
    try {
      return Math.max(0, Number(localStorage.getItem('uestc_merge_best')) || 0,
        Number(localStorage.getItem('uestc_highscore')) || 0);
    }
    catch { return 0; }
  }
  function saveBest(value) {
    try { localStorage.setItem('uestc_merge_best', String(value)); } catch { /* private browsing */ }
  }
  function randLevel() {
    const n = Math.random();
    return n < 0.48 ? 1 : n < 0.81 ? 2 : 3;
  }
  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }
  function axesFor(level) {
    const r = radii[level], sx = xScale[level];
    return { rx: r * sx, ry: r / sx };
  }
  function extents(body) {
    const c = Math.cos(body.angle), s = Math.sin(body.angle);
    return {
      x: Math.sqrt(body.rx * body.rx * c * c + body.ry * body.ry * s * s),
      y: Math.sqrt(body.rx * body.rx * s * s + body.ry * body.ry * c * c)
    };
  }
  function isCircle(body) { return Math.abs(body.rx - body.ry) < 1e-8; }
  function polygonGeometry(body) {
    const cached = polygonCache.get(body);
    if (cached && cached.x === body.x && cached.y === body.y && cached.angle === body.angle) return cached;
    const points = [], normals = [], c = Math.cos(body.angle), s = Math.sin(body.angle);
    for (let i = 0; i < POLYGON_SIDES; i++) {
      const theta = Math.PI * 2 * i / POLYGON_SIDES;
      const lx = body.rx * Math.cos(theta), ly = body.ry * Math.sin(theta);
      points.push({ x: body.x + lx * c - ly * s, y: body.y + lx * s + ly * c });
    }
    // Opposite polygon edges have parallel axes, so cache one axis per pair.
    for (let i = 0; i < points.length / 2; i++) {
      const p = points[i], q = points[(i + 1) % points.length];
      const ax = q.y - p.y, ay = p.x - q.x, length = Math.hypot(ax, ay);
      if (length > 1e-9) normals.push({ x: ax / length, y: ay / length });
    }
    const geometry = { x: body.x, y: body.y, angle: body.angle, points, normals };
    polygonCache.set(body, geometry);
    return geometry;
  }
  function supportPoint(body, dx, dy) {
    if (isCircle(body)) {
      const length = Math.hypot(dx, dy) || 1;
      return { x: body.x + dx / length * body.rx, y: body.y + dy / length * body.rx };
    }
    const c = Math.cos(body.angle), s = Math.sin(body.angle);
    const ux = dx * c + dy * s, uy = -dx * s + dy * c;
    const denominator = Math.hypot(body.rx * ux, body.ry * uy) || 1;
    const lx = body.rx * body.rx * ux / denominator;
    const ly = body.ry * body.ry * uy / denominator;
    return { x: body.x + lx * c - ly * s, y: body.y + lx * s + ly * c };
  }
  function project(body, axis, geometry = null) {
    if (isCircle(body)) {
      const center = body.x * axis.x + body.y * axis.y;
      return { min: center - body.rx, max: center + body.rx };
    }
    let min = Infinity, max = -Infinity;
    for (const point of geometry.points) {
      const value = point.x * axis.x + point.y * axis.y;
      min = Math.min(min, value); max = Math.max(max, value);
    }
    return { min, max };
  }
  function collision(a, b) {
    const dx = b.x - a.x, dy = b.y - a.y;
    const bound = Math.max(a.rx, a.ry) + Math.max(b.rx, b.ry);
    if (dx * dx + dy * dy >= bound * bound) return null;
    if (isCircle(a) && isCircle(b)) {
      const distance = Math.hypot(dx, dy), limit = a.rx + b.rx;
      if (distance >= limit) return null;
      const nx = distance > 1e-9 ? dx / distance : 0, ny = distance > 1e-9 ? dy / distance : 1;
      const pointA = supportPoint(a, nx, ny), pointB = supportPoint(b, -nx, -ny);
      return { nx, ny, penetration: limit - distance,
        x: (pointA.x + pointB.x) / 2, y: (pointA.y + pointB.y) / 2 };
    }

    const geometryA = isCircle(a) ? null : polygonGeometry(a);
    const geometryB = isCircle(b) ? null : polygonGeometry(b);
    const axes = [];
    if (geometryA) axes.push(...geometryA.normals);
    if (geometryB) axes.push(...geometryB.normals);
    if (isCircle(a) !== isCircle(b)) {
      const circle = isCircle(a) ? a : b;
      const ovalPoints = isCircle(a) ? geometryB.points : geometryA.points;
      let nearest = ovalPoints[0], nearestSq = Infinity;
      for (const point of ovalPoints) {
        const vx = point.x - circle.x, vy = point.y - circle.y, distanceSq = vx * vx + vy * vy;
        if (distanceSq < nearestSq) { nearest = point; nearestSq = distanceSq; }
      }
      const ax = nearest.x - circle.x, ay = nearest.y - circle.y, length = Math.hypot(ax, ay);
      if (length > 1e-9) axes.push({ x: ax / length, y: ay / length });
    }

    let minimum = Infinity, bestAxis = null;
    for (let axis of axes) {
      const pa = project(a, axis, geometryA), pb = project(b, axis, geometryB);
      if (pa.max <= pb.min || pb.max <= pa.min) return null;
      // Translation distance, including the case where one projection contains the other.
      const overlap = Math.min(pa.max - pb.min, pb.max - pa.min);
      if (overlap < minimum) { minimum = overlap; bestAxis = axis; }
    }
    if (!bestAxis) return null;
    if (dx * bestAxis.x + dy * bestAxis.y < 0) bestAxis = { x: -bestAxis.x, y: -bestAxis.y };
    else bestAxis = { x: bestAxis.x, y: bestAxis.y };
    const pointA = supportPoint(a, bestAxis.x, bestAxis.y);
    const pointB = supportPoint(b, -bestAxis.x, -bestAxis.y);
    let pointX, pointY;
    if (isCircle(a)) { pointX = pointA.x; pointY = pointA.y; }
    else if (isCircle(b)) { pointX = pointB.x; pointY = pointB.y; }
    else { pointX = (pointA.x + pointB.x) / 2; pointY = (pointA.y + pointB.y) / 2; }
    return { nx: bestAxis.x, ny: bestAxis.y, penetration: minimum,
      x: pointX, y: pointY };
  }
  function pointVelocity(body, x, y) {
    const rx = x - body.x, ry = y - body.y;
    return { x: body.vx - body.spin * ry, y: body.vy + body.spin * rx };
  }
  function applyImpulse(body, impulseX, impulseY, x, y) {
    body.vx += impulseX / body.mass; body.vy += impulseY / body.mass;
    body.spin += ((x - body.x) * impulseY - (y - body.y) * impulseX) / body.inertia;
  }
  function resizeCanvas() {
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(W * pixelRatio);
    canvas.height = Math.round(H * pixelRatio);
    ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  }
  window.addEventListener('resize', resizeCanvas);
  resizeCanvas();

  let balls, particles, rings, labels, score, best = readBest(), current, next;
  let maxReached, aimX, cooldown, warning, combo, comboClock, elapsed, uiClock;
  let paused = false, ended = false, activePointerId = null, soundOn = false, audio = null;
  let lastFrame = performance.now(), accumulator = 0;
  ui.best.textContent = best.toLocaleString('zh-CN');

  function clampBodyX(x, body) {
    const { x: halfWidth } = extents(body);
    return clamp(x, LEFT + halfWidth, RIGHT - halfWidth);
  }
  function cancelPointerGesture() { activePointerId = null; }
  function makeBall(level, x, y, vx = 0, vy = 0, spin = (Math.random() - 0.5) * 1.1) {
    const r = radii[level], { rx, ry } = axesFor(level);
    const body = { level, r, rx, ry, mass: rx * ry, inertia: rx * ry * (rx * rx + ry * ry) / 4,
      x, y, vx, vy, age: 0, angle: 0, spin,
      squash: 0, pop: 0, lastImpact: -10 };
    body.x = clampBodyX(x, body);
    return body;
  }
  function renderProgress() {
    ui.progress.innerHTML = names.slice(1).map((name, index) => {
      const lv = index + 1, unlocked = lv <= maxReached;
      return `<div class="tier ${unlocked ? 'reached' : 'locked'} ${lv === maxReached ? 'current' : ''}">
        <img class="tier-icon" src="${assetSources[lv]}" alt=""><div><div class="tier-num">LEVEL ${String(lv).padStart(2, '0')}</div><div class="tier-name">${name}</div></div></div>`;
    }).join('');
  }
  function updateUI() {
    ui.score.textContent = score.toLocaleString('zh-CN');
    ui.best.textContent = best.toLocaleString('zh-CN');
    ui.nextImg.src = assetSources[next];
    ui.nextName.textContent = names[next];
    ui.combo.textContent = combo > 1 && comboClock > 0 ? `连锁 ×${combo}` : '';
    ui.status.classList.toggle('danger', warning > 0);
    ui.statusText.textContent = warning > 0 ? `越线警报 ${Math.max(0, (2 - warning)).toFixed(1)}s` : '实验进行中';
  }
  function showOverlay(kind) {
    ui.overlay.classList.add('show');
    if (kind === 'over') {
      ui.overlayIcon.textContent = '✦';
      ui.overlayTitle.textContent = '本轮实验结束';
      ui.overlayText.textContent = `获得 ${score.toLocaleString('zh-CN')} 分 · 最高合成 ${names[maxReached]}`;
      ui.overlayBtn.textContent = '再试一次';
      ui.hint.textContent = '按 R 重新开始';
    } else {
      ui.overlayIcon.textContent = 'Ⅱ';
      ui.overlayTitle.textContent = '实验暂停';
      ui.overlayText.textContent = '球已经停住，随时可以继续。';
      ui.overlayBtn.textContent = '继续实验';
    }
  }
  function hideOverlay() { ui.overlay.classList.remove('show'); }
  function reset() {
    balls = []; particles = []; rings = []; labels = [];
    score = 0; current = randLevel(); next = randLevel(); maxReached = 1;
    aimX = W / 2; cooldown = 0; warning = 0; combo = 0; comboClock = 0; elapsed = 0; uiClock = 0;
    paused = false; ended = false; cancelPointerGesture(); accumulator = 0;
    ui.pause.textContent = 'Ⅱ'; ui.pause.setAttribute('aria-label', '暂停游戏');
    ui.overlayBtn.disabled = false;
    ui.hint.textContent = '同级相碰，合成进化';
    hideOverlay(); renderProgress(); updateUI();
  }

  function ensureAudio() {
    if (!soundOn) return;
    try {
      audio ||= new (window.AudioContext || window.webkitAudioContext)();
      if (audio.state === 'suspended') audio.resume();
    } catch { soundOn = false; }
  }
  function tone(frequency, duration, kind = 'sine', volume = 0.035) {
    if (!soundOn || !audio) return;
    const now = audio.currentTime;
    const oscillator = audio.createOscillator(), gain = audio.createGain();
    oscillator.type = kind;
    oscillator.frequency.setValueAtTime(frequency, now);
    oscillator.frequency.exponentialRampToValueAtTime(frequency * 0.72, now + duration);
    gain.gain.setValueAtTime(volume, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + duration);
    oscillator.connect(gain); gain.connect(audio.destination);
    oscillator.start(now); oscillator.stop(now + duration);
  }
  function drop() {
    if (paused || ended || cooldown > 0) return;
    balls.push(makeBall(current, aimX, 61));
    tone(260, 0.09, 'sine', 0.027);
    current = next; next = randLevel(); cooldown = DROP_DELAY;
    updateUI();
  }
  function pointerX(event) {
    const rect = canvas.getBoundingClientRect();
    const angle = 0, { rx, ry } = axesFor(current);
    const halfWidth = Math.sqrt(rx * rx * Math.cos(angle) ** 2 + ry * ry * Math.sin(angle) ** 2);
    return clamp((event.clientX - rect.left) * W / rect.width, LEFT + halfWidth, RIGHT - halfWidth);
  }
  arena.addEventListener('pointerdown', (event) => {
    if (event.target !== canvas || paused || ended || activePointerId !== null) return;
    if (event.button !== 0 || event.isPrimary === false) return;
    activePointerId = event.pointerId;
    aimX = pointerX(event);
    arena.setPointerCapture(event.pointerId);
    ensureAudio();
  });
  arena.addEventListener('pointermove', (event) => {
    if (activePointerId !== null) {
      if (event.pointerId === activePointerId) aimX = pointerX(event);
    } else if (event.pointerType === 'mouse') {
      aimX = pointerX(event);
    }
  });
  arena.addEventListener('pointerup', (event) => {
    if (event.pointerId !== activePointerId) return;
    aimX = pointerX(event);
    cancelPointerGesture();
    drop();
  });
  arena.addEventListener('pointercancel', (event) => {
    if (event.pointerId === activePointerId) cancelPointerGesture();
  });
  arena.addEventListener('lostpointercapture', (event) => {
    if (event.pointerId === activePointerId) cancelPointerGesture();
  });
  window.addEventListener('keydown', (event) => {
    if (event.code === 'KeyR') { reset(); return; }
    if (event.code === 'KeyP' || event.code === 'Escape') { togglePause(); return; }
    if (event.code === 'ArrowLeft' || event.code === 'ArrowRight' || event.code === 'Space') event.preventDefault();
    if (event.code === 'ArrowLeft') aimX = clampBodyX(aimX - 24, { ...axesFor(current), angle: 0 });
    if (event.code === 'ArrowRight') aimX = clampBodyX(aimX + 24, { ...axesFor(current), angle: 0 });
    if (event.code === 'Space' && !event.repeat) { ensureAudio(); drop(); }
  });
  function togglePause() {
    if (ended) return;
    paused = !paused;
    if (paused) cancelPointerGesture();
    ui.pause.textContent = paused ? '▶' : 'Ⅱ';
    ui.pause.setAttribute('aria-label', paused ? '继续游戏' : '暂停游戏');
    if (paused) showOverlay('pause'); else hideOverlay();
  }
  ui.pause.addEventListener('click', togglePause);
  ui.restart.addEventListener('click', reset);
  ui.overlayBtn.addEventListener('click', () => { if (ended) reset(); else togglePause(); });
  ui.sound.addEventListener('click', () => {
    soundOn = !soundOn; ensureAudio();
    ui.sound.textContent = soundOn ? '♫' : '♪';
    ui.sound.setAttribute('aria-label', soundOn ? '关闭音效' : '开启音效');
    if (soundOn) tone(560, 0.12);
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden && !paused && !ended) togglePause(); });

  function burst(x, y, level) {
    const color = colors[level];
    const count = level >= 7 ? 23 : 11 + level;
    for (let i = 0; i < count; i++) {
      const a = Math.PI * 2 * i / count + Math.random() * 0.35;
      const v = 70 + Math.random() * (level >= 7 ? 220 : 150);
      particles.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v,
        life: 0.4 + Math.random() * 0.3, ttl: 0.7, color, size: 2 + Math.random() * 3 });
    }
    rings.push({ x, y, r: 15, life: 0.42, ttl: 0.42, color });
  }
  function impact(ball, strength, nx, ny) {
    if (strength < 210 || elapsed - ball.lastImpact < 0.13) return;
    ball.lastImpact = elapsed;
    ball.squash = Math.min(0.24, strength / 1900);
    if (strength > 380) {
      for (let i = 0; i < 3; i++) particles.push({ x: ball.x - nx * ball.r * 0.75, y: ball.y - ny * ball.r * 0.75,
        vx: (Math.random() - 0.5) * 90, vy: -30 - Math.random() * 55,
        life: 0.25, ttl: 0.25, color: colors[ball.level], size: 2 });
    }
  }
  function merge(a, b) {
    const level = a.level + 1;
    const { rx, ry } = axesFor(level);
    const x = clamp((a.x + b.x) / 2, LEFT + rx, RIGHT - rx);
    const y = Math.min((a.y + b.y) / 2, FLOOR - ry);
    const born = makeBall(level, x, y, (a.vx + b.vx) * 0.25, Math.min(-120, (a.vy + b.vy) * 0.15 - 120), 0);
    // Keep orbital and spin angular momentum when two bodies become one.
    const ax = a.x - born.x, ay = a.y - born.y, bx = b.x - born.x, by = b.y - born.y;
    const angularMomentum = a.inertia * a.spin + b.inertia * b.spin
      + a.mass * (ax * a.vy - ay * a.vx) + b.mass * (bx * b.vy - by * b.vx);
    born.spin = clamp(angularMomentum / born.inertia, -8, 8);
    born.pop = 0.22;
    balls.push(born);
    if (comboClock > 0) combo += 1; else combo = 1;
    comboClock = 1.65;
    const gained = Math.round(10 * 2 ** (level - 1) * (1 + Math.min(combo - 1, 5) * 0.25));
    score += gained;
    if (score > best) { best = score; saveBest(best); }
    if (level > maxReached) { maxReached = level; renderProgress(); }
    burst(x, y, level);
    labels.push({ x, y: y - 10, text: `+${gained}`, life: 0.9, ttl: 0.9, color: colors[level] });
    if (level >= 7) ui.hint.textContent = level === 8 ? '电子科大合成成功！' : '再进一步，就能合成电子科大！';
    tone(260 + level * 76, 0.18, 'triangle', 0.045);
    updateUI();
  }
  function collideWall(b, nx, ny, penetration, highSpeedElasticity) {
    if (penetration > 0) { b.x += nx * penetration; b.y += ny * penetration; }
    const point = supportPoint(b, -nx, -ny);
    let velocity = pointVelocity(b, point.x, point.y);
    const normalSpeed = velocity.x * nx + velocity.y * ny;
    if (normalSpeed >= 0) return;
    impact(b, -normalSpeed, -nx, -ny);
    const rx = point.x - b.x, ry = point.y - b.y;
    const rn = rx * ny - ry * nx;
    const elasticity = -normalSpeed > 70 ? highSpeedElasticity : 0;
    const normalImpulse = -(1 + elasticity) * normalSpeed
      / (1 / b.mass + rn * rn / b.inertia);
    applyImpulse(b, normalImpulse * nx, normalImpulse * ny, point.x, point.y);

    const tx = -ny, ty = nx;
    velocity = pointVelocity(b, point.x, point.y);
    const tangentSpeed = velocity.x * tx + velocity.y * ty;
    const rt = rx * ty - ry * tx;
    const tangentDenominator = 1 / b.mass + rt * rt / b.inertia;
    const friction = clamp(-tangentSpeed / tangentDenominator,
      -normalImpulse * 0.32, normalImpulse * 0.32);
    applyImpulse(b, friction * tx, friction * ty, point.x, point.y);
  }
  function collideWalls(b) {
    const half = extents(b);
    if (b.x - half.x < LEFT) collideWall(b, 1, 0, LEFT - (b.x - half.x), 0.5);
    if (b.x + half.x > RIGHT) collideWall(b, -1, 0, b.x + half.x - RIGHT, 0.5);
    if (b.y + half.y > FLOOR) collideWall(b, 0, -1, b.y + half.y - FLOOR, 0.47);
  }
  function resolvePairs() {
    const taken = new Set(), matches = [];
    for (let i = 0; i < balls.length; i++) {
      const a = balls[i]; if (taken.has(a)) continue;
      for (let j = i + 1; j < balls.length; j++) {
        const b = balls[j]; if (taken.has(b)) continue;
        const contact = collision(a, b);
        if (!contact) continue;
        if (a.level === b.level && a.level < 8) {
          taken.add(a); taken.add(b); matches.push([a, b]); break;
        }
        const { nx, ny } = contact;
        const invA = 1 / a.mass, invB = 1 / b.mass, invTotal = invA + invB;
        const push = Math.max(0, contact.penetration - 0.1) * 0.68 / invTotal;
        a.x -= nx * push * invA; a.y -= ny * push * invA;
        b.x += nx * push * invB; b.y += ny * push * invB;
        const raX = contact.x - a.x, raY = contact.y - a.y;
        const rbX = contact.x - b.x, rbY = contact.y - b.y;
        let va = pointVelocity(a, contact.x, contact.y), vb = pointVelocity(b, contact.x, contact.y);
        let rvx = vb.x - va.x, rvy = vb.y - va.y;
        const normalSpeed = rvx * nx + rvy * ny;
        if (normalSpeed >= 0) continue;
        const elasticity = normalSpeed < -85 ? 0.59 : 0.08;
        const raN = raX * ny - raY * nx, rbN = rbX * ny - rbY * nx;
        const normalDenominator = invTotal + raN * raN / a.inertia + rbN * rbN / b.inertia;
        const impulse = -(1 + elasticity) * normalSpeed / normalDenominator;
        applyImpulse(a, -impulse * nx, -impulse * ny, contact.x, contact.y);
        applyImpulse(b, impulse * nx, impulse * ny, contact.x, contact.y);
        const tx = -ny, ty = nx;
        va = pointVelocity(a, contact.x, contact.y); vb = pointVelocity(b, contact.x, contact.y);
        rvx = vb.x - va.x; rvy = vb.y - va.y;
        const tangentSpeed = rvx * tx + rvy * ty;
        const raT = raX * ty - raY * tx, rbT = rbX * ty - rbY * tx;
        const tangentDenominator = invTotal + raT * raT / a.inertia + rbT * rbT / b.inertia;
        const friction = clamp(-tangentSpeed / tangentDenominator, -impulse * 0.34, impulse * 0.34);
        applyImpulse(a, -friction * tx, -friction * ty, contact.x, contact.y);
        applyImpulse(b, friction * tx, friction * ty, contact.x, contact.y);
        impact(a, -normalSpeed, nx, ny); impact(b, -normalSpeed, -nx, -ny);
      }
    }
    if (matches.length) {
      balls = balls.filter(ball => !taken.has(ball));
      for (const [a, b] of matches) merge(a, b);
    }
  }
  function advanceEffects(dt) {
    for (const p of particles) { p.x += p.vx * dt; p.y += p.vy * dt; p.vy += 180 * dt; p.life -= dt; }
    for (const ring of rings) { ring.r += 260 * dt; ring.life -= dt; }
    for (const label of labels) { label.y -= 48 * dt; label.life -= dt; }
    particles = particles.filter(p => p.life > 0);
    rings = rings.filter(r => r.life > 0);
    labels = labels.filter(l => l.life > 0);
  }
  function simulate(dt) {
    elapsed += dt;
    cooldown = Math.max(0, cooldown - dt);
    comboClock = Math.max(0, comboClock - dt);
    for (const b of balls) {
      b.age += dt;
      b.vy += GRAVITY * dt;
      b.vx *= 0.998; b.vy *= 0.999;
      b.x += b.vx * dt; b.y += b.vy * dt;
      b.angle += b.spin * dt; b.spin *= 0.991;
      b.squash *= 0.88;
      b.pop = Math.max(0, b.pop - dt);
      collideWalls(b);
    }
    for (let iteration = 0; iteration < 4; iteration++) {
      resolvePairs();
      for (const b of balls) collideWalls(b);
    }
    advanceEffects(dt);
    const overflowing = balls.some(b => b.age > 0.85 && b.y - extents(b).y < DANGER);
    warning = overflowing ? warning + dt : Math.max(0, warning - dt * 2);
    if (warning >= 2) {
      ended = true; warning = 2; cancelPointerGesture(); showOverlay('over'); tone(175, 0.55, 'sawtooth', 0.04);
    }
    uiClock += dt;
    if (uiClock >= 0.1) { uiClock = 0; updateUI(); }
  }

  function drawBackground() {
    const bg = ctx.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, '#173657'); bg.addColorStop(0.28, '#112847'); bg.addColorStop(1, '#0d1b32');
    ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
    ctx.strokeStyle = '#89d7f411'; ctx.lineWidth = 1;
    for (let x = 25; x < W; x += 35) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
    for (let y = 24; y < H; y += 35) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
    const glow = ctx.createRadialGradient(W / 2, 40, 15, W / 2, 40, 290);
    glow.addColorStop(0, '#61bfff1c'); glow.addColorStop(1, '#61bfff00');
    ctx.fillStyle = glow; ctx.fillRect(0, 0, W, 360);
    ctx.fillStyle = '#7feaff13'; ctx.fillRect(0, FLOOR, W, H - FLOOR);
    ctx.strokeStyle = '#71cee492'; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(LEFT, FLOOR); ctx.lineTo(RIGHT, FLOOR); ctx.stroke();
    ctx.strokeStyle = '#5dbad05c'; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(LEFT, 0); ctx.lineTo(LEFT, FLOOR); ctx.moveTo(RIGHT, 0); ctx.lineTo(RIGHT, FLOOR); ctx.stroke();
    ctx.strokeStyle = warning > 0 ? '#ff7b8f' : '#e6a271a1';
    ctx.lineWidth = warning > 0 ? 3 : 1.5; ctx.setLineDash([8, 7]);
    ctx.beginPath(); ctx.moveTo(LEFT + 2, DANGER); ctx.lineTo(RIGHT - 2, DANGER); ctx.stroke(); ctx.setLineDash([]);
    ctx.font = 'bold 10px system-ui'; ctx.fillStyle = warning > 0 ? '#ffabb8' : '#b8a5a2';
    ctx.fillText('警戒线', LEFT + 9, DANGER - 9);
    ctx.textAlign = 'right'; ctx.fillStyle = '#89b4c7'; ctx.fillText('DROP ZONE', RIGHT - 9, 20); ctx.textAlign = 'left';
  }
  function drawOrb(x, y, level, angle = 0, squash = 0, scale = 1, alpha = 1) {
    const { rx, ry } = axesFor(level), color = colors[level];
    ctx.save(); ctx.globalAlpha = alpha; ctx.translate(x, y); ctx.rotate(angle);
    ctx.scale(scale * (1 + squash * 0.5), scale * (1 - squash * 0.65));
    ctx.shadowColor = color; ctx.shadowBlur = level >= 7 ? 20 : 11;
    const fill = ctx.createRadialGradient(-rx * 0.35, -ry * 0.5, Math.min(rx, ry) * 0.07, 0, 0, Math.max(rx, ry));
    fill.addColorStop(0, '#456d93'); fill.addColorStop(0.5, '#213d61'); fill.addColorStop(1, '#11263f');
    ctx.fillStyle = fill; ctx.beginPath(); ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2); ctx.fill();
    ctx.shadowBlur = 0; ctx.strokeStyle = color; ctx.lineWidth = Math.max(2, Math.min(rx, ry) * 0.052); ctx.stroke();
    ctx.strokeStyle = '#ffffff73'; ctx.lineWidth = Math.max(1, Math.min(rx, ry) * 0.035);
    ctx.beginPath(); ctx.ellipse(0, 0, rx * 0.82, ry * 0.82, 0, Math.PI * 1.12, Math.PI * 1.65); ctx.stroke();
    const image = images[level];
    if (image?.complete && image.naturalWidth) {
      const factor = level === 8 ? 1.65 : 1.49;
      const boxWidth = rx * factor, boxHeight = ry * factor;
      const imageScale = Math.min(boxWidth / image.naturalWidth, boxHeight / image.naturalHeight);
      const imageWidth = image.naturalWidth * imageScale, imageHeight = image.naturalHeight * imageScale;
      ctx.save(); ctx.beginPath(); ctx.ellipse(0, 0, rx * 0.8, ry * 0.8, 0, 0, Math.PI * 2); ctx.clip();
      ctx.drawImage(image, -imageWidth / 2, -imageHeight / 2, imageWidth, imageHeight); ctx.restore();
    } else {
      ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.font = `bold ${Math.max(15, Math.min(rx, ry) * 0.7)}px system-ui`;
      ctx.fillText(String(level), 0, 1);
    }
    ctx.restore();
  }
  function drawAim() {
    if (ended || paused) return;
    const { rx, ry } = axesFor(current), halfWidth = rx, halfHeight = ry;
    const x = clamp(aimX, LEFT + halfWidth, RIGHT - halfWidth);
    ctx.save(); ctx.strokeStyle = '#a9edff68'; ctx.lineWidth = 1.5; ctx.setLineDash([5, 9]);
    ctx.beginPath(); ctx.moveTo(x, 64 + halfHeight); ctx.lineTo(x, FLOOR); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = '#8fe7f340'; ctx.beginPath(); ctx.ellipse(x, FLOOR - 3, rx * 1.3, 5, 0, 0, Math.PI * 2); ctx.fill();
    drawOrb(x, 61, current, 0, 0, 1 + Math.sin(elapsed * 4) * 0.025, cooldown > 0 ? 0.48 : 0.96);
    ctx.restore();
  }
  function drawEffects() {
    for (const ring of rings) {
      ctx.globalAlpha = ring.life / ring.ttl;
      ctx.strokeStyle = ring.color; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(ring.x, ring.y, ring.r, 0, Math.PI * 2); ctx.stroke();
    }
    for (const p of particles) {
      ctx.globalAlpha = clamp(p.life / p.ttl, 0, 1);
      ctx.fillStyle = p.color; ctx.beginPath(); ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2); ctx.fill();
    }
    ctx.textAlign = 'center'; ctx.font = '900 21px system-ui';
    for (const label of labels) {
      ctx.globalAlpha = label.life / label.ttl;
      ctx.fillStyle = label.color; ctx.fillText(label.text, label.x, label.y);
    }
    ctx.globalAlpha = 1; ctx.textAlign = 'left';
  }
  function render() {
    ctx.clearRect(0, 0, W, H);
    drawBackground();
    drawAim();
    for (const b of balls) {
      const scale = b.pop > 0 ? 1 + Math.sin((1 - b.pop / 0.22) * Math.PI) * 0.18 : 1;
      drawOrb(b.x, b.y, b.level, b.angle, b.squash, scale);
    }
    drawEffects();
  }
  function frame(now) {
    const delta = Math.min(0.05, (now - lastFrame) / 1000);
    lastFrame = now;
    if (!paused && !ended) {
      accumulator = Math.min(0.1, accumulator + delta);
      while (accumulator >= STEP && !ended) { simulate(STEP); accumulator -= STEP; }
    }
    render(); requestAnimationFrame(frame);
  }
  reset(); requestAnimationFrame(frame);
})();
