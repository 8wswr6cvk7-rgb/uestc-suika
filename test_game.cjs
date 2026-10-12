const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(require('node:path').join(__dirname, 'game.js'), 'utf8');
const anchor = '  reset(); requestAnimationFrame(frame);\n})();';
assert.ok(source.includes(anchor), 'test hook anchor should exist in game.js');
const testHook = `
  globalThis.__gameTest = {
    makeBall, collision, extents, resolvePairs, collideWalls, simulate, frame, reset, togglePause,
    getState: () => ({ balls, score, best, combo, comboClock, warning, elapsed, paused, ended }),
    getInputState: () => ({ activePointerId, aimX, ballCount: balls.length, paused, ended }),
    setState: (state) => {
      if ('balls' in state) balls = state.balls;
      if ('score' in state) score = state.score;
      if ('best' in state) best = state.best;
      if ('combo' in state) combo = state.combo;
      if ('comboClock' in state) comboClock = state.comboClock;
      if ('warning' in state) warning = state.warning;
      if ('elapsed' in state) elapsed = state.elapsed;
      if ('paused' in state) paused = state.paused;
      if ('ended' in state) ended = state.ended;
    }
  };
  reset();
})();`;

function loadGame(runtimeSource = source, { denyStorage = false } = {}) {
  assert.ok(runtimeSource.includes(anchor), 'runtime should include the test hook anchor');
  const instrumented = runtimeSource.replace(anchor, testHook);
  const makeElement = () => ({
    textContent: '', innerHTML: '', listeners: new Map(), captures: [],
    rect: { left: 0, top: 0, width: 460, height: 630 },
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener(type, listener) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(listener);
    },
    dispatch(type, event = {}) {
      for (const listener of this.listeners.get(type) || []) listener(event);
    },
    setAttribute() {},
    setPointerCapture(pointerId) { this.captures.push(pointerId); },
    getBoundingClientRect() { return this.rect; }
  });
  const gradient = { addColorStop() {} };
  const context = new Proxy({
    createLinearGradient: () => gradient,
    createRadialGradient: () => gradient
  }, {
    get(target, key) {
      if (key in target) return target[key];
      return () => {};
    }
  });
  const elements = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, makeElement());
      const element = elements.get(id);
      if (id === 'game') element.getContext = () => context;
      return element;
    },
    addEventListener() {}, hidden: false
  };
  const requestedImages = [];
  class FakeImage {
    constructor() { this.complete = false; this.naturalWidth = 0; this.naturalHeight = 0; }
    set src(value) { this._src = value; requestedImages.push(value); }
    get src() { return this._src; }
  }
  const sandbox = {
    document,
    window: { devicePixelRatio: 1, addEventListener() {} },
    Image: FakeImage,
    localStorage: {
      getItem() { if (denyStorage) throw new Error('file viewer blocks storage'); return null; },
      setItem() { if (denyStorage) throw new Error('file viewer blocks storage'); }
    },
    performance: { now: () => 0 },
    requestAnimationFrame() {},
    Math
  };
  vm.runInNewContext(instrumented, sandbox, { filename: 'game.js' });
  const game = sandbox.__gameTest;
  game.elements = elements;
  game.requestedImages = requestedImages;
  return game;
}

// The forwarded file carries its complete runtime and image data, including with storage blocked.
if (!process.argv.includes('--input-only')) {
  const path = require('node:path'), os = require('node:os');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'suika-portable-'));
  try {
    const copiedFile = path.join(directory, 'forwarded-game.html');
    fs.copyFileSync(path.join(__dirname, 'index.html'), copiedFile);
    assert.equal(fs.readdirSync(directory).length, 1, 'only the HTML is copied');
    const html = fs.readFileSync(copiedFile, 'utf8');
    assert.ok(!/<script\b[^>]*\bsrc\s*=/i.test(html), 'the copied file has no external script');
    const match = html.match(/<script id="game-runtime">([\s\S]*?)<\/script>/);
    assert.ok(match, 'the HTML includes the standalone game runtime');
    const runtime = match[1].trim();
    const assetLine = runtime.match(/^  const assetSources = (\[[^\n]+\]);$/m);
    assert.ok(assetLine, 'the runtime includes the embedded asset array');
    const assets = JSON.parse(assetLine[1]);
    assert.equal(assets.length, 9);
    for (let level = 1; level <= 8; level++) {
      assert.ok(assets[level].startsWith('data:image/png;base64,'), `level ${level} has inline PNG data`);
      const bytes = Buffer.from(assets[level].split(',')[1], 'base64');
      assert.deepEqual(bytes, fs.readFileSync(path.join(__dirname, `lv${level}.png`)));
    }
    const bundledSource = source.replace(/^  const assetSources = .*;$/m, assetLine[0])
      .replace(/<\/script/gi, '<\\/script').trim();
    assert.equal(runtime, bundledSource, 'the HTML contains the current game source');
    for (const denyStorage of [false, true]) {
      const portable = loadGame(runtime, { denyStorage });
      assert.equal(portable.requestedImages.length, 8);
      assert.ok(portable.requestedImages.every(url => url.startsWith('data:image/png;base64,')));
      assert.ok(portable.elements.get('next-img').src.startsWith('data:image/png;base64,'));
      assert.ok(!portable.elements.get('progress-list').innerHTML.includes('src="lv'));
      assert.equal(portable.elements.get('overlay-btn').disabled, false, 'startup enables the game controls');
      const arena = portable.elements.get('arena'), target = portable.elements.get('game');
      const event = { target, pointerId: 1, pointerType: 'touch', isPrimary: true, button: 0, clientX: 230 };
      arena.dispatch('pointerdown', event);
      arena.dispatch('pointerup', event);
      assert.equal(portable.getState().balls.length, 1);
      portable.frame(50);
      assert.ok(portable.getState().balls[0].y > 61, 'the copied game advances after a touch drop');
      portable.setState({ balls: [portable.makeBall(1, 180, 400), portable.makeBall(1, 210, 400)] });
      portable.resolvePairs();
      assert.equal(portable.getState().score, 20, 'scoring still works when local storage is unavailable');
    }
    process.stdout.write('single-file HTML offline startup and asset checks passed\n');
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

if (process.argv.includes('--portable-only')) process.exit(0);

const game = loadGame();
const { makeBall, collision, extents, setState, getState } = game;

function pointer(type, { target = 'game', pointerId = 1, pointerType = 'touch',
  isPrimary = true, button = 0, clientX = 100, clientY = 100 } = {}) {
  game.elements.get('arena').dispatch(type, {
    target: game.elements.get(target), pointerId, pointerType, isPrimary, button, clientX, clientY
  });
}

// Pointer input stays with one primary contact, cancels safely, and drops only on its release.
{
  const input = () => game.getInputState();
  const arena = game.elements.get('arena');
  const canvas = game.elements.get('game');
  canvas.rect = { left: 10, top: 0, width: 230, height: 315 };

  game.reset();
  pointer('pointerdown', { pointerId: 11, clientX: 40 });
  pointer('pointerdown', { pointerId: 12, isPrimary: false, clientX: 200 });
  pointer('pointerup', { pointerId: 12, isPrimary: false, clientX: 200 });
  assert.equal(input().activePointerId, 11, 'a secondary finger cannot take or release the active drag');
  assert.equal(input().ballCount, 0, 'a secondary finger release does not drop');
  pointer('pointermove', { pointerId: 12, isPrimary: false, clientX: 220 });
  assert.equal(input().aimX, 60, 'secondary pointer movement does not steer the active drag');
  pointer('pointermove', { pointerId: 11, clientX: 100 });
  pointer('pointerup', { pointerId: 11, clientX: 120 });
  pointer('pointerup', { pointerId: 11, clientX: 160 });
  assert.equal(input().ballCount, 1, 'one active pointer release creates exactly one ball');
  assert.equal(input().activePointerId, null, 'the drag ends after release');
  assert.equal(input().aimX, 220, 'CSS display width maps pointer coordinates to game coordinates');
  assert.equal(arena.captures.at(-1), 11, 'the active pointer is captured by the arena');

  game.reset();
  pointer('pointerdown', { pointerId: 21 });
  pointer('pointercancel', { pointerId: 21 });
  pointer('pointerup', { pointerId: 21 });
  assert.equal(input().ballCount, 0, 'pointercancel cancels without dropping');
  assert.equal(input().activePointerId, null);

  pointer('pointerdown', { pointerId: 22 });
  pointer('lostpointercapture', { pointerId: 22 });
  pointer('pointerup', { pointerId: 22 });
  assert.equal(input().ballCount, 0, 'lost pointer capture cancels without dropping');
  assert.equal(input().activePointerId, null);

  pointer('pointerdown', { pointerId: 23, pointerType: 'mouse', button: 2 });
  pointer('pointerup', { pointerId: 23, pointerType: 'mouse', button: 2 });
  assert.equal(input().ballCount, 0, 'right-click does not start a drop gesture');

  game.togglePause();
  pointer('pointerdown', { pointerId: 24 });
  pointer('pointerup', { pointerId: 24 });
  assert.equal(input().activePointerId, null, 'paused games do not start pointer drags');
  assert.equal(input().ballCount, 0);
  pointer('pointerdown', { target: 'overlay-btn', pointerId: 25 });
  pointer('pointerup', { target: 'overlay-btn', pointerId: 25 });
  assert.equal(input().ballCount, 0, 'overlay pointer input does not drop');
  game.elements.get('overlay-btn').dispatch('click');
  assert.equal(input().paused, false, 'the overlay button resumes the game');
  game.elements.get('pause-btn').dispatch('click');
  assert.equal(input().paused, true);
  assert.equal(input().ballCount, 0, 'pause button clicks do not drop');
  game.elements.get('restart-btn').dispatch('click');
  assert.equal(input().paused, false);
  assert.equal(input().ballCount, 0, 'restart button clicks do not drop');

  setState({ paused: false, ended: true });
  pointer('pointerdown', { pointerId: 26 });
  pointer('pointerup', { pointerId: 26 });
  assert.equal(input().activePointerId, null, 'ended games do not start pointer drags');
  assert.equal(input().ballCount, 0);
}

if (process.argv.includes('--input-only')) {
  process.stdout.write('pointer input regression tests passed\n');
  process.exit(0);
}

// The same center separation misses a horizontal ellipse and hits it after rotation.
{
  const small = makeBall(1, 200, 250, 0, 0, 0);
  const oval = makeBall(2, 200, 294, 0, 0, 0);
  assert.equal(collision(small, oval), null);
  oval.angle = Math.PI / 2;
  assert.ok(collision(small, oval), 'rotating the ellipse changes the contact result');
}

// Rotated half-width controls wall placement.
{
  const oval = makeBall(2, 30, 240, 0, 0, 0);
  game.collideWalls(oval);
  const unrotatedX = oval.x;
  oval.x = 30; oval.angle = Math.PI / 2;
  game.collideWalls(oval);
  assert.ok(oval.x < unrotatedX, 'the narrow rotated half-width leaves the center closer to the wall');
  assert.ok(oval.x - extents(oval).x >= 20 - 1e-8);
}

// Equal ellipses whose bounding circles overlap remain separate when their shapes do not touch.
{
  game.reset();
  const a = makeBall(2, 200, 220, 0, 0, 0);
  const b = makeBall(2, 200, 270, 0, 0, 0);
  assert.equal(collision(a, b), null);
  setState({ balls: [a, b] });
  game.resolvePairs();
  assert.equal(getState().balls.length, 2);
  assert.equal(getState().score, 0);
}

// A glancing mixed-shape impact transfers angular velocity through the contact impulse.
{
  game.reset();
  const oval = makeBall(2, 200, 250, 100, 0, 0);
  const circle = makeBall(3, 239, 278, -100, 0, 0);
  setState({ balls: [oval, circle] });
  game.resolvePairs();
  assert.ok(Math.abs(oval.spin) > 1e-4 || Math.abs(circle.spin) > 1e-4,
    'an off-center collision must impart spin');
}

// Mixed-contact torque uses the circle's radial contact point in either argument order.
{
  const circle = makeBall(1, 125.77723815539623, 302.3617816414195, 0, 0, 0);
  const oval = makeBall(7, 230, 300, 0, 0, 0);
  oval.angle = 0;
  for (const [a, b, circleIsA] of [[circle, oval, true], [oval, circle, false]]) {
    const contact = collision(a, b);
    assert.ok(contact, 'the configured circle/ellipse pair overlaps');
    const circleNormalX = circleIsA ? contact.nx : -contact.nx;
    const circleNormalY = circleIsA ? contact.ny : -contact.ny;
    const armX = contact.x - circle.x, armY = contact.y - circle.y;
    assert.ok(Math.abs(armX * circleNormalY - armY * circleNormalX) < 1e-6,
      'the contact arm on the circle is radial to the SAT normal');
  }
}

// Existing merge, pause, and danger-line rules remain active.
{
  game.reset();
  setState({ balls: [makeBall(1, 180, 300, 0, 0, 0), makeBall(1, 210, 300, 0, 0, 0)] });
  game.resolvePairs();
  assert.equal(getState().balls.length, 1);
  assert.equal(getState().balls[0].level, 2);
  assert.equal(getState().score, 20);

  game.togglePause();
  const before = getState().elapsed;
  game.frame(100);
  assert.equal(getState().paused, true);
  assert.equal(getState().elapsed, before, 'paused frames do not advance simulation time');
  game.togglePause();

  const dangerous = makeBall(1, 220, 145, 0, 0, 0);
  dangerous.age = 1;
  setState({ balls: [dangerous], warning: 1.999, elapsed: 0, ended: false });
  // A single fixed step crosses the two-second warning threshold.
  game.simulate(1 / 120);
  assert.equal(getState().ended, true, 'persistent danger-line overlap ends the round');

  game.reset();
  const rotatedWarning = makeBall(2, 230, 165, 0, 0, 0);
  rotatedWarning.age = 1;
  setState({ balls: [rotatedWarning], warning: 0, elapsed: 0, ended: false });
  game.simulate(1 / 120);
  assert.equal(getState().warning, 0, 'the unrotated ellipse stays below the warning line');
  rotatedWarning.angle = Math.PI / 2;
  setState({ warning: 1.999, elapsed: 0, ended: false });
  game.simulate(1 / 120);
  assert.equal(getState().ended, true, 'rotation increases the ellipse half-height at the warning line');
}

// A dense mixed-level stack should settle without large residual circle/ellipse overlap.
{
  game.reset();
  const stack = [];
  for (let level = 1; level <= 8; level++) {
    const body = makeBall(level, 100 + (level % 3) * 90,
      200 + Math.floor(level / 3) * 60, 0, 0, 0);
    body.angle = 0.17 * level;
    stack.push(body);
  }
  setState({ balls: stack, warning: 0, ended: false, elapsed: 0 });
  let worstPenetration = 0, activePairChecks = 0;
  const step = 1 / 120;
  for (let frame = 0; frame < 2400; frame++) {
    game.simulate(step);
    if (frame < 1800) continue;
    const bodies = getState().balls;
    for (let i = 0; i < bodies.length; i++) {
      for (let j = i + 1; j < bodies.length; j++) {
        activePairChecks++;
        const contact = collision(bodies[i], bodies[j]);
        if (contact) worstPenetration = Math.max(worstPenetration, contact.penetration);
      }
    }
  }
  for (const body of getState().balls) {
    for (const key of ['x', 'y', 'vx', 'vy', 'angle', 'spin']) {
      assert.ok(Number.isFinite(body[key]), `stack body ${key} remains finite`);
    }
  }
  assert.ok(worstPenetration < 1, `active-pair penetration should settle below 1 px; got ${worstPenetration}`);
  process.stdout.write(`mixed-level 2400-step check: worst active-pair penetration over last 600 steps ${worstPenetration.toFixed(3)} px (${activePairChecks} pair checks)\n`);
}

// Exercise broad-phase filtering and repeated SAT contacts with a dispersed 40-body scene.
{
  game.reset();
  const bodies = [];
  for (let row = 0; row < 8; row++) {
    for (let col = 0; col < 5; col++) {
      const level = (row + col) % 2 ? 1 : 2;
      const vx = ((row + 2 * col) % 3 - 1) * 2;
      const vy = ((3 * row + col) % 5 - 2) * 2;
      bodies.push(makeBall(level, 60 + col * 82, 120 + row * 62, vx, vy, 0));
    }
  }
  setState({ balls: bodies, warning: 0, ended: false, elapsed: 0 });
  const started = process.hrtime.bigint();
  for (let i = 0; i < 60; i++) game.simulate(1 / 120);
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
  const finalBodies = getState().balls;
  assert.equal(finalBodies.length, 40, 'the separated scene should remain a 40-body scene');
  for (const body of finalBodies) {
    for (const key of ['x', 'y', 'vx', 'vy', 'angle', 'spin', 'mass', 'inertia']) {
      assert.ok(Number.isFinite(body[key]), `body ${key} remains finite`);
    }
  }
  process.stdout.write(`40-body 60-step check passed (${elapsedMs.toFixed(2)} ms)\n`);
}

process.stdout.write('game geometry and rule tests passed\n');
