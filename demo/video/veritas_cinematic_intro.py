#!/usr/bin/env python3
"""Render the Veritas cinematic introduction as a deterministic 1080p60 MP4."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


WIDTH = 1920
HEIGHT = 1080
FPS = 60
DURATION = 72.0
TRANSITION = 0.72

BG = (6, 16, 13)
BG_DEEP = (3, 10, 8)
INK = (245, 248, 243)
MUTED = (147, 164, 156)
SOFT = (91, 111, 102)
LINE = (39, 62, 53)
SURFACE = (10, 29, 23)
SURFACE_2 = (13, 36, 28)
GREEN = (82, 211, 147)
GREEN_DARK = (22, 118, 81)
GREEN_PALE = (190, 241, 216)
AMBER = (201, 147, 67)
RED = (212, 100, 89)
BLUE = (95, 160, 194)

FONT_REGULAR_PATH = "/System/Library/Fonts/SFNS.ttf"
FONT_ROUNDED_PATH = "/System/Library/Fonts/SFNSRounded.ttf"
FONT_MONO_PATH = "/System/Library/Fonts/SFNSMono.ttf"


@dataclass(frozen=True)
class Scene:
    start: float
    end: float
    name: str


@dataclass(frozen=True)
class Reveal:
    box: tuple[int, int, int, int]
    start: float
    duration: float = 0.20
    dx: int = 0
    dy: int = 34


SCENES = (
    Scene(0.00, 7.00, "source-change"),
    Scene(7.00, 14.77, "source-sealed"),
    Scene(14.77, 20.00, "memo-stale"),
    Scene(20.00, 26.50, "workspace-stale"),
    Scene(26.50, 32.50, "truth-gap"),
    Scene(32.50, 38.50, "between-tools"),
    Scene(38.50, 44.50, "ownership"),
    Scene(44.50, 51.50, "closed-loop"),
    Scene(51.50, 58.60, "authority"),
    Scene(58.60, 64.50, "proof"),
    Scene(64.50, 69.00, "promise"),
    Scene(69.00, 72.00, "brand"),
)


def font(size: int, *, mono: bool = False, rounded: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_MONO_PATH if mono else FONT_ROUNDED_PATH if rounded else FONT_REGULAR_PATH
    return ImageFont.truetype(path, size)


F_KICKER = font(18, mono=True)
F_MICRO = font(15, mono=True)
F_SMALL = font(19)
F_BODY = font(27)
F_CARD = font(30, rounded=True)
F_TITLE = font(94, rounded=True)
F_TITLE_LARGE = font(112, rounded=True)
F_METRIC = font(82, rounded=True)
F_METRIC_SMALL = font(54, rounded=True)
F_LOGO = font(48, rounded=True)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def ease(value: float) -> float:
    value = clamp(value)
    return value * value * (3.0 - 2.0 * value)


def rgba(color: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return (*color, alpha)


def rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    radius: int = 18,
    fill: tuple[int, ...] | None = None,
    outline: tuple[int, ...] | None = None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    face: ImageFont.FreeTypeFont,
    fill: tuple[int, ...] = INK,
    *,
    spacing: int = 8,
    anchor: str | None = None,
    align: str = "left",
) -> None:
    draw.multiline_text(xy, value, font=face, fill=fill, spacing=spacing, anchor=anchor, align=align)


def brand(draw: ImageDraw.ImageDraw) -> None:
    rounded_rect(draw, (58, 46, 104, 92), radius=12, fill=SURFACE_2, outline=(56, 105, 82), width=2)
    text(draw, (81, 69), "V", font(18, mono=True), GREEN, anchor="mm")
    text(draw, (126, 68), "VERITAS", font(20, mono=True), INK, anchor="lm")
    draw.line((244, 53, 244, 83), fill=LINE, width=1)
    text(draw, (265, 68), "CONTINUOUS EVIDENCE INTEGRITY", F_MICRO, MUTED, anchor="lm")


def chrome(draw: ImageDraw.ImageDraw, scene_index: int, kicker: str) -> None:
    brand(draw)
    text(draw, (58, 156), kicker.upper(), F_KICKER, GREEN)
    text(draw, (1862, 68), f"SCENE {scene_index + 1:02d} / {len(SCENES):02d}", F_MICRO, SOFT, anchor="rm")
    draw.line((58, 1008, 1862, 1008), fill=(28, 48, 40), width=1)
    text(draw, (58, 1035), "EVIDENCE-BOUND  /  MANIFEST-SCOPED  /  INDEPENDENTLY VERIFIED", F_MICRO, SOFT)


def base(scene_index: int, kicker: str) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 72):
        draw.line((x, 0, x, HEIGHT), fill=(8, 25, 19), width=1)
    for y in range(0, HEIGHT, 72):
        draw.line((0, y, WIDTH, y), fill=(8, 25, 19), width=1)
    draw.ellipse((1270, -350, 2200, 580), fill=(6, 28, 20))
    chrome(draw, scene_index, kicker)
    return image


def glow(image: Image.Image, center: tuple[int, int], color: tuple[int, int, int], radius: int = 85) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=rgba(color, 70))
    layer = layer.filter(ImageFilter.GaussianBlur(radius // 2))
    image.paste(layer, (0, 0), layer)


def pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], label: str, color: tuple[int, int, int]) -> None:
    x, y = xy
    width = max(126, int(draw.textlength(label, font=F_MICRO)) + 34)
    rounded_rect(draw, (x, y, x + width, y + 38), radius=19, fill=(11, 31, 24), outline=color)
    draw.ellipse((x + 13, y + 14, x + 23, y + 24), fill=color)
    text(draw, (x + 31, y + 19), label.upper(), F_MICRO, color, anchor="lm")


def node(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    label: str,
    code: str,
    color: tuple[int, int, int],
    status: str,
    *,
    width: int = 250,
) -> tuple[int, int, int, int]:
    x, y = center
    box = (x - width // 2, y - 60, x + width // 2, y + 60)
    rounded_rect(draw, box, radius=18, fill=SURFACE, outline=(42, 71, 59), width=2)
    rounded_rect(draw, (box[0] + 16, box[1] + 19, box[0] + 58, box[1] + 61), radius=11, fill=color)
    text(draw, (box[0] + 37, box[1] + 40), code, F_MICRO, BG, anchor="mm")
    text(draw, (box[0] + 72, box[1] + 27), label, F_SMALL, INK)
    text(draw, (box[0] + 72, box[1] + 61), status.upper(), F_MICRO, color)
    return box


def scene_source_change() -> Image.Image:
    image = base(0, "Workspace signals never stop changing")
    draw = ImageDraw.Draw(image)
    text(draw, (58, 226), "Evidence changes.", F_TITLE_LARGE, INK)
    text(draw, (64, 365), "A metric moves. A policy changes.\nA customer changes their mind.", F_BODY, MUTED, spacing=10)
    text(draw, (64, 500), "REGISTERED SIGNALS", F_MICRO, SOFT)
    pill(draw, (64, 540), "Google Sheets · metrics", GREEN)
    pill(draw, (64, 595), "Google Docs · policy", BLUE)
    pill(draw, (64, 650), "Customer Gmail · intent", RED)
    rounded_rect(draw, (1060, 214, 1810, 760), radius=30, fill=SURFACE, outline=(41, 72, 58), width=2)
    pill(draw, (1120, 268), "registered source", GREEN)
    text(draw, (1120, 355), "Google Sheets", F_SMALL, MUTED)
    text(draw, (1742, 355), "Metrics!B17", F_MICRO, MUTED, anchor="ra")
    draw.line((1120, 395, 1750, 395), fill=LINE, width=2)
    text(draw, (1190, 510), "4%", F_METRIC, MUTED, anchor="mm")
    draw.line((1315, 510, 1485, 510), fill=(61, 85, 75), width=3)
    draw.polygon(((1485, 510), (1462, 497), (1462, 523)), fill=GREEN)
    text(draw, (1610, 510), "9%", F_METRIC, GREEN, anchor="mm")
    text(draw, (1120, 650), "VERSION 12", F_MICRO, SOFT)
    text(draw, (1750, 650), "SNAPSHOT PENDING", F_MICRO, AMBER, anchor="ra")
    draw.line((58, 735, 920, 735), fill=LINE, width=2)
    draw.ellipse((84, 720, 114, 750), fill=GREEN_DARK, outline=GREEN, width=2)
    text(draw, (58, 782), "ONE LIVE SOURCE EVENT", F_MICRO, SOFT)
    text(draw, (825, 782), "CONSEQUENCES UNKNOWN", F_MICRO, RED, anchor="ra")
    return image


def scene_source_sealed() -> Image.Image:
    image = base(1, "Every source becomes durable evidence")
    draw = ImageDraw.Draw(image)
    text(draw, (58, 226), "Every meaningful change\nbecomes evidence.", F_TITLE, INK)
    text(draw, (64, 465), "Authenticated event. Exact source refetched.\nImmutable snapshot sealed.", F_BODY, MUTED)
    glow(image, (1325, 500), GREEN, 120)
    draw = ImageDraw.Draw(image)
    rounded_rect(draw, (965, 240, 1780, 745), radius=28, fill=SURFACE, outline=(45, 83, 66), width=2)
    text(draw, (1030, 303), "CHANGE RECEIPT", F_KICKER, GREEN)
    stages = (
        ("01", "Workspace event", "authenticated", GREEN),
        ("02", "Exact source", "refetched", GREEN),
        ("03", "snapshot · 507df4fd", "sealed", GREEN),
        ("04", "content hash", "bound", GREEN),
    )
    for index, (num, label, status, color) in enumerate(stages):
        y = 380 + index * 79
        rounded_rect(draw, (1025, y - 30, 1718, y + 34), radius=13, fill=SURFACE_2, outline=(34, 67, 52))
        text(draw, (1050, y), num, F_MICRO, color, anchor="lm")
        text(draw, (1120, y), label, F_SMALL, INK, anchor="lm")
        text(draw, (1688, y), status.upper(), F_MICRO, color, anchor="rm")
    pill(draw, (64, 710), "semantic change accepted", GREEN)
    text(draw, (64, 790), "Veritas now knows precisely what changed.", F_CARD, INK)
    return image


def scene_memo_stale() -> Image.Image:
    image = base(2, "The first silent consequence")
    draw = ImageDraw.Draw(image)
    text(draw, (58, 226), "The rest of the business\ndoesn't update itself.", F_TITLE, INK)
    text(draw, (64, 465), "This registered claim still describes the old world.", F_BODY, MUTED)
    # Keep the document clear of the headline at 16:9 and after platform-safe cropping.
    rounded_rect(draw, (1000, 205, 1815, 820), radius=28, fill=(244, 247, 242), outline=(112, 127, 119), width=2)
    text(draw, (1060, 260), "Q3 BOARD MEMO", F_KICKER, (76, 93, 85))
    draw.line((1060, 305, 1750, 305), fill=(203, 210, 205), width=2)
    text(draw, (1060, 374), "Customer health", font(34, rounded=True), fill=(22, 33, 29))
    text(draw, (1060, 443), "Q3 customer churn is 4%.", F_CARD, (28, 39, 35))
    draw.line((1058, 461, 1515, 461), fill=RED, width=5)
    pill(draw, (1060, 500), "stale registered claim", RED)
    text(draw, (1060, 590), "CFO commentary", F_SMALL, (68, 84, 76))
    text(draw, (1060, 635), "Retention remains our highest-leverage\noperating priority this quarter.", font(26, rounded=True), (43, 55, 49), spacing=10)
    rounded_rect(draw, (1060, 727, 1750, 782), radius=10, fill=(228, 238, 231), outline=(143, 172, 156))
    text(draw, (1085, 755), "PROTECTED HUMAN PROSE · HASH UNCHANGED", F_MICRO, GREEN_DARK, anchor="lm")
    text(draw, (58, 760), "The document looked finished.\nIts decision context was already stale.", F_CARD, INK)
    return image


def scene_workspace_stale() -> Image.Image:
    image = base(3, "One change crosses every Workspace surface")
    draw = ImageDraw.Draw(image)
    text(draw, (58, 220), "The memo. The deck.\nThe email. The tasks.", F_TITLE, INK)
    text(draw, (64, 458), "Each surface holds a consequence—and each requires a different repair.", F_BODY, MUTED)
    positions = (
        ((355, 680), "Board memo · Docs", "D", BLUE, "PATCH CLAIM ONLY"),
        ((675, 760), "Exec deck · Slides", "S", AMBER, "UPDATE ANCHOR"),
        ((1020, 670), "Correction · Gmail", "G", RED, "DRAFT · NEVER SEND"),
        ((1345, 755), "Acquisition · Tasks", "T", BLUE, "HUMAN APPROVAL"),
        ((1630, 620), "Retention · Docs", "D", GREEN_DARK, "PRESERVE PROSE"),
    )
    for center, label, code, color, policy in positions:
        node(draw, center, label, code, color, policy, width=280)
    for left, right in zip(positions, positions[1:]):
        a = left[0]
        b = right[0]
        draw.line((a[0] + 137, a[1], b[0] - 137, b[1]), fill=(66, 50, 43), width=2)
    pill(draw, (64, 555), "5 affected artifacts · native semantics", RED)
    return image


def scene_truth_gap() -> Image.Image:
    image = base(4, "The hidden integrity gap")
    draw = ImageDraw.Draw(image)
    text(draw, (58, 226), "The source was true.\nThe business wasn't.", F_TITLE_LARGE, INK)
    text(draw, (64, 510), "Success in one system can become silent failure everywhere else.", F_BODY, MUTED)
    cards = (
        (70, 650, 590, 870, "SOURCE EVIDENCE", "9%", "CURRENT", GREEN),
        (700, 650, 1220, 870, "REGISTERED CLAIMS", "4 / 8", "STALE", RED),
        (1330, 650, 1850, 870, "WORKSPACE TARGETS", "13", "UNVERIFIED", AMBER),
    )
    for x1, y1, x2, y2, label, value, status, color in cards:
        rounded_rect(draw, (x1, y1, x2, y2), radius=24, fill=SURFACE, outline=(42, 72, 59), width=2)
        text(draw, (x1 + 35, y1 + 42), label, F_MICRO, MUTED)
        # Reserve independent vertical bands for the metric and its status badge.
        text(draw, (x1 + 35, y1 + 118), value, F_METRIC_SMALL, INK, anchor="lm")
        pill(draw, (x1 + 35, y1 + 166), status, color)
    return image


def scene_between_tools() -> Image.Image:
    image = base(5, "Distributed tools create a blind spot")
    draw = ImageDraw.Draw(image)
    text(draw, (58, 220), "The failure lives\nbetween tools.", F_TITLE_LARGE, INK)
    text(draw, (64, 500), "Each surface knew its state. None could reconstruct the causal whole.", F_BODY, MUTED)
    centers = {
        "source": (1320, 280),
        "doc": (1010, 520),
        "slides": (1610, 520),
        "mail": (960, 790),
        "task": (1640, 790),
        "human": (1300, 865),
    }
    for a, b in (("source", "doc"), ("source", "slides"), ("doc", "mail"), ("slides", "task"), ("doc", "human"), ("slides", "human")):
        ax, ay = centers[a]
        bx, by = centers[b]
        # Draw one continuous edge behind the nodes. Drawing nodes afterwards masks
        # each center cleanly, so every line terminates exactly at a node boundary.
        draw.line((ax, ay, bx, by), fill=(69, 86, 76), width=3)
    specs = (
        ("source", "Sheet", "S", GREEN, "current"),
        ("doc", "Docs", "D", BLUE, "isolated"),
        ("slides", "Slides", "S", AMBER, "isolated"),
        ("mail", "Gmail", "G", RED, "immutable"),
        ("task", "Tasks", "T", BLUE, "isolated"),
        ("human", "Human prose", "H", GREEN_DARK, "protected"),
    )
    for key, label, code, color, status in specs:
        x, y = centers[key]
        glow(image, (x, y), color, 55)
        draw = ImageDraw.Draw(image)
        draw.ellipse((x - 43, y - 43, x + 43, y + 43), fill=SURFACE, outline=color, width=3)
        text(draw, (x, y - 2), code, F_CARD, color, anchor="mm")
        text(draw, (x, y + 73), label, F_SMALL, INK, anchor="mm")
        text(draw, (x, y + 101), status.upper(), F_MICRO, color, anchor="mm")
    pill(draw, (64, 620), "causal ownership missing", RED)
    return image


def scene_ownership() -> Image.Image:
    image = base(6, "Exact ownership, not a similarity guess")
    draw = ImageDraw.Draw(image)
    text(draw, (58, 220), "Veritas knows exactly\nwhat the change owns.", F_TITLE, INK)
    text(draw, (64, 455), "A versioned Claim Manifest authorizes every path—and excludes guesses.", F_BODY, MUTED)
    rounded_rect(draw, (940, 205, 1815, 850), radius=30, fill=SURFACE, outline=(42, 73, 59), width=2)
    text(draw, (1000, 270), "REGISTERED CONSEQUENCE GRAPH", F_KICKER, GREEN)
    source = (1110, 470)
    claim = (1385, 470)
    artifact = (1660, 470)
    for x, y, label, code, color in (
        (*source, "Metrics!B17", "S", GREEN),
        (*claim, "Churn claim", "C", AMBER),
        (*artifact, "Board memo", "D", BLUE),
    ):
        draw.ellipse((x - 45, y - 45, x + 45, y + 45), fill=SURFACE_2, outline=color, width=3)
        text(draw, (x, y), code, F_CARD, color, anchor="mm")
        text(draw, (x, y + 82), label, F_SMALL, INK, anchor="mm")
    draw.line((1155, 470, 1340, 470), fill=GREEN, width=4)
    draw.line((1430, 470, 1615, 470), fill=GREEN, width=4)
    text(draw, (1248, 440), "SEMANTIC DELTA", F_MICRO, GREEN, anchor="mm")
    text(draw, (1522, 440), "EXACT PATH", F_MICRO, GREEN, anchor="mm")
    draw.line((1110, 640, 1660, 755), fill=(77, 82, 74), width=2)
    draw.line((1390, 698, 1440, 708), fill=RED, width=7)
    text(draw, (1385, 790), "CANDIDATE EDGE · EXCLUDED", F_MICRO, RED, anchor="mm")
    pill(draw, (64, 620), "0 inferred paths", GREEN)
    text(draw, (64, 702), "Gemini may reason.\nThe manifest decides scope.", F_CARD, INK)
    return image


def scene_closed_loop() -> Image.Image:
    image = base(7, "The consequence loop")
    draw = ImageDraw.Draw(image)
    text(draw, (58, 220), "So Veritas closes\nthe consequence loop.", F_TITLE, INK)
    text(draw, (64, 455), "From authenticated evidence to independently verified action.", F_BODY, MUTED)
    y = 700
    xs = (260, 700, 1140, 1580)
    steps = (
        ("01", "DETECT", "Seal the change", GREEN),
        ("02", "TRACE", "Follow exact ownership", AMBER),
        ("03", "REPAIR", "Apply guarded writes", BLUE),
        ("04", "VERIFY", "Re-read every target", GREEN),
    )
    for index, (x, item) in enumerate(zip(xs, steps)):
        number, label, detail, color = item
        glow(image, (x, y), color, 58)
        draw = ImageDraw.Draw(image)
        rounded_rect(draw, (x - 170, y - 105, x + 170, y + 105), radius=24, fill=SURFACE, outline=color, width=2)
        text(draw, (x - 130, y - 62), number, F_MICRO, color)
        text(draw, (x - 130, y - 8), label, F_CARD, INK)
        text(draw, (x - 130, y + 50), detail, F_SMALL, MUTED)
        if index < len(xs) - 1:
            draw.line((x + 170, y, xs[index + 1] - 170, y), fill=GREEN, width=3)
            draw.polygon(((xs[index + 1] - 170, y), (xs[index + 1] - 190, y - 10), (xs[index + 1] - 190, y + 10)), fill=GREEN)
    pill(draw, (64, 545), "no prompt after source change", GREEN)
    return image


def scene_authority() -> Image.Image:
    image = base(8, "Narrow agent authority")
    draw = ImageDraw.Draw(image)
    text(draw, (58, 220), "AI gets context.\nNever unchecked authority.", F_TITLE, INK)
    text(draw, (64, 455), "Gemini reviews the registered change. Deterministic policy owns the keys.", F_BODY, MUTED)
    panels = (
        (70, 600, 900, 900, "GEMINI CAN", GREEN, ("Explain connected evidence", "Flag ambiguous changes", "Recommend proceed or escalate")),
        (1020, 600, 1850, 900, "GEMINI CANNOT", RED, ("Invent a new dependency", "Approve its own decision", "Overwrite a newer revision")),
    )
    for x1, y1, x2, y2, label, color, items in panels:
        rounded_rect(draw, (x1, y1, x2, y2), radius=26, fill=SURFACE, outline=(44, 74, 61), width=2)
        text(draw, (x1 + 38, y1 + 42), label, F_KICKER, color)
        for index, item in enumerate(items):
            y = y1 + 112 + index * 60
            draw.ellipse((x1 + 42, y - 8, x1 + 58, y + 8), fill=color)
            text(draw, (x1 + 80, y), item, F_BODY, INK, anchor="lm")
    pill(draw, (64, 535), "gemini-3.5-flash · structured receipt", GREEN)
    return image


def scene_proof() -> Image.Image:
    image = base(9, "Proof, not a promise")
    draw = ImageDraw.Draw(image)
    text(draw, (58, 220), "Every repair leaves proof.", F_TITLE, INK)
    text(draw, (64, 360), "A separate read-only verifier reopens the real Workspace targets.", F_BODY, MUTED)
    metrics = (
        (70, 520, 480, 820, "13/13", "TARGETS VERIFIED", GREEN),
        (520, 520, 930, 820, "0", "HUMAN EDITS LOST", GREEN),
        (970, 520, 1380, 820, "5/5", "PROTECTED REGIONS", GREEN),
    )
    for x1, y1, x2, y2, value, label, color in metrics:
        rounded_rect(draw, (x1, y1, x2, y2), radius=26, fill=SURFACE, outline=(42, 73, 59), width=2)
        text(draw, ((x1 + x2) // 2, y1 + 112), value, F_METRIC, color, anchor="mm")
        text(draw, ((x1 + x2) // 2, y1 + 220), label, F_MICRO, MUTED, anchor="mm")
    rounded_rect(draw, (1430, 450, 1845, 890), radius=26, fill=(8, 39, 28), outline=GREEN, width=2)
    pill(draw, (1480, 500), "certificate issued", GREEN)
    text(draw, (1480, 610), "EVIDENCE\nINTEGRITY\nCERTIFICATE", font(37, rounded=True), INK, spacing=4)
    draw.line((1480, 755, 1795, 755), fill=(55, 107, 82), width=2)
    text(draw, (1480, 800), "CERT-7A92", F_CARD, GREEN)
    text(draw, (1480, 850), "SCOPED · CONTENT-ADDRESSED", F_MICRO, MUTED)
    return image


def scene_promise() -> Image.Image:
    image = base(10, "The complete Workspace consequence engine")
    draw = ImageDraw.Draw(image)
    text(draw, (58, 220), "Any registered input changes.\nEvery owned consequence\nrepairs safely.", F_TITLE, INK)
    text(draw, (64, 560), "Sheets · Docs · Gmail → Docs · Slides · Gmail drafts · Tasks", F_BODY, MUTED)
    source = (1110, 670)
    draw.ellipse((source[0] - 58, source[1] - 58, source[0] + 58, source[1] + 58), fill=SURFACE, outline=GREEN, width=4)
    text(draw, source, "9%", F_CARD, GREEN, anchor="mm")
    targets = (
        (1430, 430, "D", "DOCS", BLUE),
        (1650, 540, "S", "SLIDES", AMBER),
        (1690, 795, "G", "GMAIL DRAFT", RED),
        (1430, 900, "T", "TASKS", BLUE),
        (1240, 850, "D", "HUMAN PROSE", GREEN_DARK),
    )
    for x, y, code, label, color in targets:
        draw.line((source[0] + 60, source[1], x - 48, y), fill=(45, 123, 84), width=3)
        draw.ellipse((x - 44, y - 44, x + 44, y + 44), fill=SURFACE, outline=GREEN, width=3)
        text(draw, (x, y), code, F_CARD, color, anchor="mm")
        text(draw, (x, y + 68), label, F_MICRO, MUTED, anchor="mm")
        draw.ellipse((x + 50, y - 56, x + 76, y - 30), fill=GREEN)
        text(draw, (x + 63, y - 44), "✓", F_MICRO, BG, anchor="mm")
    pill(draw, (64, 660), "registered targets only", GREEN)
    pill(draw, (64, 720), "native revision checks", GREEN)
    pill(draw, (64, 780), "independent verification", GREEN)
    return image


def scene_brand() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG_DEEP)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 72):
        draw.line((x, 0, x, HEIGHT), fill=(7, 22, 17), width=1)
    for y in range(0, HEIGHT, 72):
        draw.line((0, y, WIDTH, y), fill=(7, 22, 17), width=1)
    glow(image, (960, 480), GREEN, 260)
    draw = ImageDraw.Draw(image)
    rounded_rect(draw, (875, 260, 1045, 430), radius=42, fill=SURFACE_2, outline=GREEN, width=3)
    rounded_rect(draw, (900, 285, 1020, 405), radius=30, fill=(17, 49, 36), outline=(63, 139, 99), width=2)
    text(draw, (960, 345), "V", font(66, mono=True), GREEN, anchor="mm")
    text(draw, (960, 515), "VERITAS", font(82, rounded=True), INK, anchor="mm")
    text(draw, (960, 600), "CONTINUOUS EVIDENCE INTEGRITY", F_KICKER, GREEN, anchor="mm")
    draw.line((690, 660, 1230, 660), fill=(45, 80, 64), width=2)
    text(draw, (960, 720), "When evidence changes, repair every consequence.", F_BODY, MUTED, anchor="mm")
    pill(draw, (705, 800), "gemini 3.5", GREEN)
    pill(draw, (935, 800), "google cloud", GREEN)
    pill(draw, (1190, 800), "workspace native", GREEN)
    text(draw, (960, 1008), "ALL THINGS AGENTIC HACKATHON · 2026", F_MICRO, SOFT, anchor="mm")
    return image


SCENE_BUILDERS = (
    scene_source_change,
    scene_source_sealed,
    scene_memo_stale,
    scene_workspace_stale,
    scene_truth_gap,
    scene_between_tools,
    scene_ownership,
    scene_closed_loop,
    scene_authority,
    scene_proof,
    scene_promise,
    scene_brand,
)


SCENE_KICKERS = (
    "Workspace signals never stop changing",
    "Every source becomes durable evidence",
    "The first silent consequence",
    "One change crosses every Workspace surface",
    "The hidden integrity gap",
    "Distributed tools create a blind spot",
    "Exact ownership, not a similarity guess",
    "The consequence loop",
    "Narrow agent authority",
    "Proof, not a promise",
    "The complete Workspace consequence engine",
)


# Each box is lifted independently from the final layout. The final composition is
# never used as a single static slide until the short closing hold of a scene.
MOTION_PLANS: tuple[tuple[Reveal, ...], ...] = (
    (
        Reveal((38, 185, 910, 430), 0.02, 0.20, -95, 0),
        Reveal((1010, 180, 1850, 800), 0.18, 0.30, 120, 0),
        Reveal((38, 470, 690, 705), 0.32, 0.24, -55, 24),
        Reveal((38, 680, 950, 850), 0.54, 0.20, -55, 24),
    ),
    (
        Reveal((38, 185, 880, 585), 0.02, 0.22, -90, 0),
        Reveal((920, 190, 1835, 800), 0.20, 0.32, 120, 0),
        Reveal((38, 675, 910, 850), 0.52, 0.22, -55, 28),
    ),
    (
        Reveal((38, 185, 940, 545), 0.02, 0.24, -90, 0),
        Reveal((955, 175, 1845, 850), 0.20, 0.32, 125, 0),
        Reveal((38, 700, 900, 850), 0.56, 0.20, -55, 28),
    ),
    (
        Reveal((38, 180, 1250, 520), 0.02, 0.22, -90, 0),
        Reveal((38, 520, 410, 610), 0.24, 0.16, -45, 0),
        Reveal((205, 590, 505, 780), 0.28, 0.18, 0, 55),
        Reveal((525, 670, 825, 860), 0.36, 0.18, 0, 55),
        Reveal((870, 580, 1170, 780), 0.44, 0.18, 0, 55),
        Reveal((1195, 665, 1495, 855), 0.52, 0.18, 0, 55),
        Reveal((1480, 530, 1785, 730), 0.60, 0.18, 0, 55),
    ),
    (
        Reveal((38, 185, 1260, 585), 0.02, 0.23, -95, 0),
        Reveal((45, 615, 620, 900), 0.27, 0.22, 0, 65),
        Reveal((675, 615, 1250, 900), 0.43, 0.22, 0, 65),
        Reveal((1305, 615, 1880, 900), 0.59, 0.22, 0, 65),
    ),
    (
        Reveal((38, 185, 900, 585), 0.02, 0.22, -90, 0),
        Reveal((38, 585, 420, 680), 0.22, 0.16, -45, 0),
        Reveal((1230, 195, 1415, 405), 0.18, 0.18, 0, -55),
        Reveal((915, 430, 1100, 675), 0.31, 0.18, -55, 0),
        Reveal((1515, 430, 1705, 675), 0.39, 0.18, 55, 0),
        Reveal((860, 700, 1055, 970), 0.52, 0.18, -55, 0),
        Reveal((1540, 700, 1740, 970), 0.60, 0.18, 55, 0),
        Reveal((1185, 775, 1420, 1030), 0.68, 0.18, 0, 55),
    ),
    (
        Reveal((38, 185, 920, 565), 0.02, 0.22, -90, 0),
        Reveal((38, 585, 630, 830), 0.25, 0.20, -50, 30),
        Reveal((900, 175, 1855, 880), 0.20, 0.38, 120, 0),
    ),
    (
        Reveal((38, 185, 950, 550), 0.02, 0.22, -90, 0),
        Reveal((38, 515, 540, 590), 0.24, 0.16, -45, 0),
        Reveal((65, 560, 455, 845), 0.28, 0.18, 0, 55),
        Reveal((505, 560, 895, 845), 0.40, 0.18, 0, 55),
        Reveal((945, 560, 1335, 845), 0.52, 0.18, 0, 55),
        Reveal((1385, 560, 1775, 845), 0.64, 0.18, 0, 55),
    ),
    (
        Reveal((38, 185, 1220, 515), 0.02, 0.22, -90, 0),
        Reveal((38, 500, 610, 590), 0.24, 0.16, -45, 0),
        Reveal((45, 565, 925, 930), 0.28, 0.28, -80, 0),
        Reveal((995, 565, 1875, 930), 0.46, 0.28, 80, 0),
    ),
    (
        Reveal((38, 185, 1210, 425), 0.02, 0.22, -90, 0),
        Reveal((45, 485, 505, 850), 0.27, 0.22, 0, 60),
        Reveal((495, 485, 955, 850), 0.39, 0.22, 0, 60),
        Reveal((945, 485, 1405, 850), 0.51, 0.22, 0, 60),
        Reveal((1395, 415, 1880, 925), 0.62, 0.24, 85, 0),
    ),
    (
        Reveal((38, 185, 1050, 640), 0.02, 0.23, -95, 0),
        Reveal((38, 625, 520, 835), 0.25, 0.24, -50, 0),
        Reveal((1020, 350, 1790, 980), 0.25, 0.42, 85, 0),
    ),
    (
        Reveal((830, 215, 1090, 455), 0.04, 0.24, 0, -70),
        Reveal((700, 455, 1220, 625), 0.22, 0.22, 0, 45),
        Reveal((650, 620, 1270, 770), 0.40, 0.22, 0, 40),
        Reveal((650, 770, 1290, 870), 0.58, 0.20, 0, 38),
        Reveal((690, 940, 1230, 1045), 0.72, 0.18, 0, 28),
    ),
)


def brand_background() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG_DEEP)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 72):
        draw.line((x, 0, x, HEIGHT), fill=(7, 22, 17), width=1)
    for y in range(0, HEIGHT, 72):
        draw.line((0, y, WIDTH, y), fill=(7, 22, 17), width=1)
    return image


def local_progress(progress: float, start: float, duration: float) -> float:
    return ease((progress - start) / duration)


def content_layer(final: Image.Image, background: Image.Image) -> Image.Image:
    difference = ImageChops.difference(final, background).convert("L")
    mask = difference.point(lambda value: 255 if value > 3 else 0)
    layer = final.convert("RGBA")
    layer.putalpha(mask)
    return layer


def prepare_motion(
    finals: list[Image.Image], backgrounds: list[Image.Image]
) -> tuple[list[Image.Image], list[list[tuple[Reveal, Image.Image]]]]:
    layers: list[Image.Image] = []
    patches: list[list[tuple[Reveal, Image.Image]]] = []
    for final, background, plan in zip(finals, backgrounds, MOTION_PLANS):
        layer = content_layer(final, background)
        layers.append(layer)
        patches.append([(reveal, layer.crop(reveal.box)) for reveal in plan])
    return layers, patches


def paste_reveal(
    canvas: Image.Image, reveal: Reveal, patch: Image.Image, progress: float
) -> None:
    amount = local_progress(progress, reveal.start, reveal.duration)
    if amount <= 0:
        return
    lifted = patch.copy()
    lifted.putalpha(lifted.getchannel("A").point([round(index * amount) for index in range(256)]))
    x = reveal.box[0] + round(reveal.dx * (1.0 - amount))
    y = reveal.box[1] + round(reveal.dy * (1.0 - amount))
    canvas.alpha_composite(lifted, (x, y))


def draw_progress_line(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    amount: float,
    color: tuple[int, int, int],
    *,
    width: int = 4,
) -> tuple[int, int]:
    amount = clamp(amount)
    point = (
        round(start[0] + (end[0] - start[0]) * amount),
        round(start[1] + (end[1] - start[1]) * amount),
    )
    if amount > 0:
        draw.line((*start, *point), fill=color, width=width)
    return point


def draw_scene_motion(frame: Image.Image, scene_index: int, progress: float) -> None:
    if progress >= 0.90:
        return
    draw = ImageDraw.Draw(frame)
    if scene_index == 0:
        amount = local_progress(progress, 0.34, 0.42)
        point = draw_progress_line(draw, (1315, 510), (1485, 510), amount, GREEN, width=5)
        if 0 < amount < 1:
            draw.ellipse((point[0] - 9, point[1] - 9, point[0] + 9, point[1] + 9), fill=GREEN_PALE)
    elif scene_index == 1:
        amount = local_progress(progress, 0.24, 0.48)
        if 0 < amount < 1:
            y = round(338 + 345 * amount)
            draw.line((1028, y, 1716, y), fill=GREEN, width=3)
    elif scene_index == 2:
        amount = local_progress(progress, 0.38, 0.28)
        draw_progress_line(draw, (1058, 461), (1515, 461), amount, RED, width=7)
    elif scene_index == 3:
        path = ((355, 680), (675, 760), (1020, 670), (1345, 755), (1630, 620))
        travel = local_progress(progress, 0.30, 0.48) * (len(path) - 1)
        segment = min(len(path) - 2, int(travel))
        amount = travel - segment
        point = draw_progress_line(draw, path[segment], path[segment + 1], amount, RED, width=4)
        draw.ellipse((point[0] - 8, point[1] - 8, point[0] + 8, point[1] + 8), fill=RED)
    elif scene_index == 4:
        cards = ((70, 650, 590, 870), (700, 650, 1220, 870), (1330, 650, 1850, 870))
        active = min(2, int(local_progress(progress, 0.28, 0.46) * 3))
        draw.rounded_rectangle(cards[active], radius=24, outline=(83, 177, 126), width=4)
    elif scene_index == 5:
        centers = ((1320, 280), (1010, 520), (1610, 520), (960, 790), (1640, 790), (1300, 865))
        edges = ((0, 1), (0, 2), (1, 3), (2, 4), (1, 5), (2, 5))
        for edge_index, (left, right) in enumerate(edges):
            amount = local_progress(progress, 0.18 + edge_index * 0.065, 0.22)
            draw_progress_line(draw, centers[left], centers[right], amount, GREEN, width=4)
    elif scene_index == 6:
        first = local_progress(progress, 0.30, 0.20)
        second = local_progress(progress, 0.47, 0.20)
        draw_progress_line(draw, (1155, 470), (1340, 470), first, GREEN, width=6)
        draw_progress_line(draw, (1430, 470), (1615, 470), second, GREEN, width=6)
        rejected = local_progress(progress, 0.65, 0.14)
        if rejected > 0:
            x = round(1368 + 74 * rejected)
            draw.line((x - 18, 685, x + 18, 721), fill=RED, width=7)
            draw.line((x - 18, 721, x + 18, 685), fill=RED, width=7)
    elif scene_index == 7:
        amount = local_progress(progress, 0.30, 0.50)
        x = round(430 + 980 * amount)
        draw.ellipse((x - 13, 687, x + 13, 713), fill=GREEN_PALE)
        draw.ellipse((x - 7, 693, x + 7, 707), fill=GREEN)
    elif scene_index == 8:
        for item in range(3):
            amount = local_progress(progress, 0.38 + item * 0.10, 0.12)
            radius = round(5 + 8 * amount)
            for x in (120, 1070):
                y = 712 + item * 60
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=GREEN if x < 500 else RED, width=3)
    elif scene_index == 9:
        amount = local_progress(progress, 0.28, 0.42)
        x = round(70 + 1310 * amount)
        draw.line((70, 842, x, 842), fill=GREEN, width=5)
        if amount > 0.78:
            pulse = round(4 + 7 * (1.0 - abs(0.89 - amount) / 0.11))
            draw.rounded_rectangle((1430 - pulse, 450 - pulse, 1845 + pulse, 890 + pulse), radius=28, outline=GREEN, width=4)
    elif scene_index == 10:
        source = (1110, 670)
        targets = ((1430, 430), (1650, 540), (1690, 795), (1430, 900), (1240, 850))
        for target_index, target in enumerate(targets):
            amount = local_progress(progress, 0.28 + target_index * 0.075, 0.24)
            point = draw_progress_line(draw, source, target, amount, GREEN, width=4)
            if 0 < amount < 1:
                draw.ellipse((point[0] - 7, point[1] - 7, point[0] + 7, point[1] + 7), fill=GREEN_PALE)
    elif scene_index == 11:
        amount = local_progress(progress, 0.04, 0.54)
        radius = round(110 + 210 * amount)
        shade = round(65 * (1.0 - amount))
        draw.ellipse((960 - radius, 345 - radius, 960 + radius, 345 + radius), outline=(22, 118 + shade, 81), width=3)


def animate_scene(
    scene_index: int,
    progress: float,
    final: Image.Image,
    background: Image.Image,
    patches: list[tuple[Reveal, Image.Image]],
) -> Image.Image:
    canvas = background.convert("RGBA")
    for reveal, patch in patches:
        paste_reveal(canvas, reveal, patch, progress)
    frame = canvas.convert("RGB")
    settle = local_progress(progress, 0.82, 0.10)
    if settle > 0:
        frame = Image.blend(frame, final, settle)
    draw_scene_motion(frame, scene_index, progress)
    return frame


def wipe_transition(previous: Image.Image, current: Image.Image, amount: float, *, reverse: bool) -> Image.Image:
    amount = ease(amount)
    feather = 180
    boundary = round(-feather + (WIDTH + feather * 2) * amount)
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(mask)
    solid_end = boundary - feather
    if solid_end > 0:
        draw.rectangle((0, 0, min(WIDTH, solid_end), HEIGHT), fill=255)
    start = max(0, solid_end)
    end = min(WIDTH, boundary)
    for x in range(start, end):
        draw.line((x, 0, x, HEIGHT), fill=round(255 * (x - solid_end) / feather))
    if reverse:
        mask = mask.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return Image.composite(current, previous, mask)


def scene_at(seconds: float) -> tuple[int, float]:
    for index, scene in enumerate(SCENES):
        if scene.start <= seconds < scene.end:
            return index, (seconds - scene.start) / (scene.end - scene.start)
    return len(SCENES) - 1, 1.0


def compose_frame(
    images: list[Image.Image],
    backgrounds: list[Image.Image],
    patches: list[list[tuple[Reveal, Image.Image]]],
    seconds: float,
) -> Image.Image:
    index, progress = scene_at(seconds)
    scene = SCENES[index]
    frame = animate_scene(index, progress, images[index], backgrounds[index], patches[index])
    if index == 0:
        fade = ease(seconds / 1.2)
        frame = Image.blend(Image.new("RGB", frame.size, BG_DEEP), frame, fade)
    elif seconds - scene.start < TRANSITION:
        amount = ease((seconds - scene.start) / TRANSITION)
        frame = wipe_transition(images[index - 1], frame, amount, reverse=index % 2 == 0)

    # Let the final Veritas card reach full strength before the closing fade.
    if DURATION - seconds < 1.2:
        amount = ease((DURATION - seconds) / 1.2)
        frame = Image.blend(Image.new("RGB", frame.size, BG_DEEP), frame, amount)
    return frame


def render(
    output: Path,
    music: Path,
    preview_frames: Path | None,
    *,
    stills_only: bool = False,
    start_at: float = 0.0,
    clip_duration: float | None = None,
) -> None:
    images = [builder() for builder in SCENE_BUILDERS]
    backgrounds = [base(index, kicker) for index, kicker in enumerate(SCENE_KICKERS)]
    backgrounds.append(brand_background())
    _layers, patches = prepare_motion(images, backgrounds)
    if preview_frames is not None:
        preview_frames.mkdir(parents=True, exist_ok=True)
        for index, image in enumerate(images):
            image.save(preview_frames / f"scene-{index + 1:02d}-{SCENES[index].name}.png")

    if stills_only:
        return

    render_duration = clip_duration if clip_duration is not None else DURATION - start_at
    if start_at < 0 or render_duration <= 0 or start_at + render_duration > DURATION:
        raise ValueError("the requested render window must remain inside the 72-second film")

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s:v",
        f"{WIDTH}x{HEIGHT}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-ss",
        str(start_at),
        "-i",
        str(music),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-t",
        str(render_duration),
        "-af",
        "afade=t=in:st=0:d=0.8,afade=t=out:st=69:d=3,volume=0.88",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "16",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "high",
        "-level:v",
        "4.2",
        "-c:a",
        "aac",
        "-b:a",
        "320k",
        "-movflags",
        "+faststart",
        str(output),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert process.stdin is not None
    total_frames = round(render_duration * FPS)
    try:
        for frame_number in range(total_frames):
            seconds = start_at + frame_number / FPS
            frame = compose_frame(images, backgrounds, patches, seconds)
            process.stdin.write(frame.tobytes())
            if frame_number % (FPS * 6) == 0:
                print(
                    f"rendered source {seconds:05.1f}s · clip {frame_number / FPS:04.1f}s / {render_duration:.1f}s",
                    file=sys.stderr,
                    flush=True,
                )
    except BrokenPipeError as error:
        raise RuntimeError("ffmpeg stopped while receiving rendered frames") from error
    finally:
        process.stdin.close()
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg exited with status {return_code}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--music", type=Path, required=True)
    parser.add_argument("--preview-frames", type=Path)
    parser.add_argument("--stills-only", action="store_true")
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float)
    args = parser.parse_args()
    if not args.music.exists():
        raise SystemExit(f"music not found: {args.music}")
    render(
        args.output,
        args.music,
        args.preview_frames,
        stills_only=args.stills_only,
        start_at=args.start,
        clip_duration=args.duration,
    )


if __name__ == "__main__":
    main()
