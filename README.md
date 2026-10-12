# Chip Evolution: UESTC Merge Game

`index.html` is a self-contained, offline version of the game. It includes its styles, game code, and all eight image assets, so you can copy or share this single file and play without a server or an internet connection.

## How to play

- Move the mouse or drag with a finger to aim, then release to drop an item.
- Use the left and right arrow keys to adjust the drop position, Space to drop, `P` to pause, and `R` to restart.
- Matching items merge into the next level. Consecutive merges increase the score.
- The game ends when an item stays above the warning line for two seconds.
- Holes, diodes, and integrated circuits are horizontal ellipses; Glasgow is a vertical ellipse. Collisions can cause rotation, so drop position and stack direction affect merges.
- Use the buttons at the top to toggle sound, pause, or restart. The high score is saved in the current browser when storage is available.

## Playing on a phone

The page supports portrait and landscape layouts, including screen safe areas. The board keeps its proportions and scales down on shorter screens. On very short screens, the page can scroll. Drag on the board to aim and release to drop; multi-touch and canceled system gestures should not trigger an extra drop.

Send `index.html` to your phone, download it, and open it with a browser or an HTML viewer that can run local HTML and JavaScript. You can also open the file directly in a desktop browser.

Some file-preview apps display the HTML without running its JavaScript. If the game remains on “Starting game,” use an app that supports local scripts. Packaging the game as one file keeps its assets together, but does not guarantee that every phone preview app will run it.

Touch controls require Pointer Events support. The game attempts to save the high score locally; if the app blocks storage, the game remains playable, but the record may not persist after closing it.

## Rebuilding the portable HTML

`game.js` and `lv1.png` through `lv8.png` are the editable web source and shared assets. After changing them, run:

```bash
python3 build_html.py
```

This regenerates `index.html` while preserving its styles and mobile layout. Players only need the resulting HTML file.

## Python version

Install Pygame and run the game from this directory:

```bash
python3 -m pip install pygame
python3 main.py
```

The Python version uses the same eight level images and ellipse shapes. It also includes bouncy collisions, combo scoring, a warning-line timer, sound controls, and a high-score record. It does not require Pymunk. In both versions, ellipse collisions use a rotating 20-sided approximation and can produce spin.

Run the Python tests with:

```bash
python3 -m unittest test_main.py
```

Run the web-game checks with:

```bash
node test_game.cjs
```

The portable-only checks can be run with:

```bash
node test_game.cjs --portable-only
```

They check the self-contained assets, source synchronization, offline startup, and dropping and merging when browser storage is unavailable.

## Glasgow logo source

`lv7.png` is based on the original logo package from the [University of Glasgow Brand Toolkit](https://www.gla.ac.uk/myglasgow/staff/brandtoolkit/logo/downloads/), specifically its [logo asset archive](https://www.gla.ac.uk/media/Media_1228330_smxx.zip). The university shield was cropped from `Unboxed colour logo white text.png`, removing the surrounding whitespace and wordmark while preserving the shield's colors and proportions.
