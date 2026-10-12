#!/usr/bin/env python3
"""Build a self-contained copy of the game in index.html."""

from __future__ import annotations

import ast
import base64
import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
HTML_PATH = ROOT / "index.html"
GAME_PATH = ROOT / "game.js"
ASSET_NAMES = tuple(f"lv{i}.png" for i in range(1, 9))
DATA_PREFIX = "data:image/png;base64,"


class BuildError(Exception):
    pass


def fail(message: str) -> None:
    raise BuildError(message)


def read_inputs() -> tuple[str, str, dict[str, bytes]]:
    paths = [HTML_PATH, GAME_PATH, *(ROOT / name for name in ASSET_NAMES)]
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        fail("Missing required input(s): " + ", ".join(missing))

    try:
        html = HTML_PATH.read_bytes().decode("utf-8")
        game = GAME_PATH.read_bytes().decode("utf-8")
        assets = {name: (ROOT / name).read_bytes() for name in ASSET_NAMES}
    except (OSError, UnicodeDecodeError) as exc:
        fail(f"Could not read build inputs: {exc}")

    for name, data in assets.items():
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            fail(f"{name} is not a PNG file")
    return html, game, assets


def inline_asset_sources(game: str, assets: dict[str, bytes]) -> str:
    pattern = re.compile(
        r"(?m)^(?P<indent>[ \t]*)const[ \t]+assetSources[ \t]*=[ \t]*"
        r"(?P<array>\[[^\r\n]*\])(?P<semicolon>;?)(?P<trailing>[ \t]*)$"
    )
    matches = list(pattern.finditer(game))
    if len(matches) != 1:
        fail(f"Expected exactly one assetSources declaration; found {len(matches)}")

    match = matches[0]
    try:
        declared = ast.literal_eval(match.group("array"))
    except (SyntaxError, ValueError) as exc:
        fail(f"Could not parse assetSources declaration: {exc}")

    expected = ["", *ASSET_NAMES]
    if declared != expected:
        fail(f"assetSources must be {expected!r}; found {declared!r}")

    data_uris = [DATA_PREFIX + base64.b64encode(assets[name]).decode("ascii") for name in ASSET_NAMES]
    replacement_values = ["", *data_uris]
    replacement_array = json.dumps(replacement_values, ensure_ascii=False, separators=(", ", ": "))
    replacement = (
        f"{match.group('indent')}const assetSources = {replacement_array}"
        f"{match.group('semicolon')}{match.group('trailing')}"
    )
    return game[: match.start()] + replacement + game[match.end() :]


def attr_value(tag: str, name: str) -> str | None:
    attr = re.compile(
        rf"(?<![\w:-]){re.escape(name)}\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))",
        re.IGNORECASE,
    )
    match = attr.search(tag)
    if not match:
        return None
    return next(value for value in match.groups() if value is not None)


def replace_next_image(html: str, image_data_uri: str) -> str:
    img_pattern = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)
    matches = [
        match
        for match in img_pattern.finditer(html)
        if attr_value(match.group(0), "id") == "next-img"
    ]
    if len(matches) != 1:
        fail(f"Expected exactly one img#next-img element; found {len(matches)}")

    match = matches[0]
    tag = match.group(0)
    src_pattern = re.compile(
        r"(?P<prefix>\s+src\s*=\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
        re.IGNORECASE | re.DOTALL,
    )
    src_matches = list(src_pattern.finditer(tag))
    if len(src_matches) > 1:
        fail("img#next-img has more than one src attribute")
    if src_matches:
        src_match = src_matches[0]
        new_tag = (
            tag[: src_match.start()]
            + src_match.group("prefix")
            + src_match.group("quote")
            + image_data_uri
            + src_match.group("quote")
            + tag[src_match.end() :]
        )
    else:
        closing = "/>" if tag.rstrip().endswith("/>") else ">"
        insert_at = len(tag.rstrip()) - len(closing)
        new_tag = tag[:insert_at] + f' src="{image_data_uri}"' + tag[insert_at:]
    return html[: match.start()] + new_tag + html[match.end() :]


def inline_runtime(html: str, game: str) -> str:
    script_pattern = re.compile(r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
    candidates = []
    for match in script_pattern.finditer(html):
        attrs = match.group("attrs")
        script_id = attr_value("<script" + attrs + ">", "id")
        src = attr_value("<script" + attrs + ">", "src")
        if script_id == "game-runtime" or src in {"game.js", "./game.js"}:
            candidates.append(match)
    if not candidates:
        fail("Could not find an existing game.js script or #game-runtime script to replace")

    # Replace the source script wherever it currently appears, then append one
    # canonical runtime block immediately before </body>.
    for match in reversed(candidates):
        html = html[: match.start()] + html[match.end() :]

    body_closes = list(re.finditer(r"</body\s*>", html, re.IGNORECASE))
    if len(body_closes) != 1:
        fail(f"Expected exactly one closing body tag; found {len(body_closes)}")
    body_close = body_closes[0]
    prefix = html[: body_close.start()].rstrip(" \t\r\n")
    suffix = html[body_close.start() :]
    safe_game = re.sub(r"</script", r"<\/script", game, flags=re.IGNORECASE)
    runtime = f'\n  <script id="game-runtime">\n{safe_game}\n</script>\n'
    return prefix + runtime + suffix


def validate_output(html: str, expected_game: str, assets: dict[str, bytes]) -> None:
    style_before = re.search(r"<style\b[^>]*>.*?</style\s*>", HTML_PATH.read_bytes().decode("utf-8"), re.I | re.S)
    style_after = re.search(r"<style\b[^>]*>.*?</style\s*>", html, re.I | re.S)
    if not style_before or not style_after or style_before.group(0) != style_after.group(0):
        fail("The existing stylesheet was changed or is missing")

    scripts = list(re.finditer(r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>", html, re.I | re.S))
    if len(scripts) != 1:
        fail(f"Expected one inline script; found {len(scripts)}")
    runtime = scripts[0]
    runtime_tag = "<script" + runtime.group("attrs") + ">"
    if attr_value(runtime_tag, "id") != "game-runtime" or attr_value(runtime_tag, "src") is not None:
        fail("The inline game-runtime script must have no src attribute")
    body = runtime.group("body")
    if not (body.startswith("\n") and body.endswith("\n")):
        fail("Unexpected game-runtime script wrapper")
    if body[1:-1] != expected_game:
        fail("The inline runtime does not equal the transformed game.js")
    closing_body = re.search(r"</body\s*>", html, re.I)
    if not closing_body or html[runtime.end() : closing_body.start()].strip():
        fail("game-runtime is not the last body element")

    # Inspect real markup outside the inline JavaScript, so template strings in
    # the game source cannot be mistaken for HTML elements.
    markup = html[: runtime.start()] + html[runtime.end() :]
    tag_pattern = re.compile(r"<(?!/|!|\?)(?P<name>[A-Za-z][\w:-]*)\b(?P<attrs>[^<>]*)>", re.S)
    attribute_pattern = re.compile(
        r"(?P<name>[^\s=/>]+)(?:\s*=\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)'|(?P<bare>[^\s>]+)))?"
    )
    for tag_match in tag_pattern.finditer(markup):
        tag_name = tag_match.group("name").lower()
        attrs = {}
        for attr_match in attribute_pattern.finditer(tag_match.group("attrs")):
            value = next((v for v in (attr_match.group("double"), attr_match.group("single"), attr_match.group("bare")) if v is not None), "")
            attrs[attr_match.group("name").lower()] = value
        if "src" in attrs and not attrs["src"].startswith(DATA_PREFIX):
            fail(f"External src resource found on <{tag_name}>")
        if tag_name == "link" and attrs.get("href"):
            fail("External link resource found")

    data_uris = re.findall(r"data:image/png;base64,([A-Za-z0-9+/=]+)", html)
    expected_payloads = Counter([assets[ASSET_NAMES[0]], *[assets[name] for name in ASSET_NAMES]])
    decoded_payloads = []
    try:
        decoded_payloads = [base64.b64decode(value, validate=True) for value in data_uris]
    except (ValueError, base64.binascii.Error) as exc:
        fail(f"Invalid embedded PNG base64: {exc}")
    if len(data_uris) != 9 or Counter(decoded_payloads) != expected_payloads:
        fail("Embedded PNG data does not decode byte-for-byte to lv1.png through lv8.png")

    next_imgs = [
        match.group(0)
        for match in re.finditer(r"<img\b[^>]*>", markup, re.I | re.S)
        if attr_value(match.group(0), "id") == "next-img"
    ]
    if len(next_imgs) != 1 or attr_value(next_imgs[0], "src") != DATA_PREFIX + base64.b64encode(assets["lv1.png"]).decode("ascii"):
        fail("Initial next-img src is not the embedded lv1.png")

    # CSS resources can also fetch over the network; this page has no need for
    # url() or @import because every visual asset is embedded.
    style_blocks = re.findall(r"<style\b[^>]*>(.*?)</style\s*>", markup, re.I | re.S)
    for css in style_blocks:
        if re.search(r"@import\b", css, re.I):
            fail("External CSS import found")
        for url in re.findall(r"url\(\s*(['\"]?)(.*?)\1\s*\)", css, re.I | re.S):
            if not url[1].strip().lower().startswith("data:"):
                fail("External CSS url() resource found")


def build() -> int:
    html, game, assets = read_inputs()
    original_styles = re.findall(r"<style\b[^>]*>.*?</style\s*>", html, re.I | re.S)
    if len(original_styles) != 1:
        fail(f"Expected one existing stylesheet; found {len(original_styles)}")

    transformed_game = inline_asset_sources(game, assets)
    lv1_data_uri = DATA_PREFIX + base64.b64encode(assets["lv1.png"]).decode("ascii")
    output = replace_next_image(html, lv1_data_uri)
    output = inline_runtime(output, transformed_game)

    expected_game = re.sub(r"</script", r"<\/script", transformed_game, flags=re.IGNORECASE)
    validate_output(output, expected_game, assets)

    output_bytes = output.encode("utf-8")
    try:
        HTML_PATH.write_bytes(output_bytes)
    except OSError as exc:
        fail(f"Could not write index.html: {exc}")
    return len(output_bytes)


if __name__ == "__main__":
    try:
        size = build()
        print(f"Built {HTML_PATH.name}: {size} bytes; embedded 8 PNGs (9 data URIs including the initial preview).")
    except BuildError as exc:
        print(f"build_html.py: {exc}", file=sys.stderr)
        sys.exit(1)
