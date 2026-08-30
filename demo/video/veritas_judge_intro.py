#!/usr/bin/env python3
"""Render the 48-second judge-facing Veritas opening film."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

import veritas_cinematic_intro as core
import veritas_email_tasks_intro as route


WIDTH = 1920
HEIGHT = 1080
FPS = 60
DURATION = 48.0
TRANSITION = 0.62

BG = core.BG
BG_DEEP = core.BG_DEEP
INK = core.INK
MUTED = core.MUTED
SOFT = core.SOFT
LINE = core.LINE
SURFACE = core.SURFACE
SURFACE_2 = core.SURFACE_2
GREEN = core.GREEN
GREEN_DARK = core.GREEN_DARK
GREEN_PALE = core.GREEN_PALE
AMBER = core.AMBER
RED = core.RED
BLUE = core.BLUE
GMAIL_RED = route.GMAIL_RED
TASKS_BLUE = route.TASKS_BLUE
PAPER = route.PAPER
PAPER_TEXT = route.PAPER_TEXT
PAPER_MUTED = route.PAPER_MUTED

F_KICKER = core.font(18, mono=True)
F_MICRO = core.font(15, mono=True)
F_SMALL = core.font(20)
F_BODY = core.font(27)
F_CARD = core.font(30, rounded=True)
F_TITLE = core.font(88, rounded=True)
F_TITLE_LARGE = core.font(102, rounded=True)
F_METRIC = core.font(68, rounded=True)


@dataclass(frozen=True)
class Scene:
    start: float
    end: float
    name: str
    kicker: str


@dataclass(frozen=True)
class Reveal:
    box: tuple[int, int, int, int]
    start: float
    duration: float = 0.20
    dx: int = 0
    dy: int = 34


SCENES = (
    Scene(0.0, 6.0, "email-hook", "One ordinary customer moment"),
    Scene(6.0, 12.0, "contradiction", "One company, two different truths"),
    Scene(12.0, 18.0, "zoom-out", "This is only one consequence"),
    Scene(18.0, 25.0, "platform", "Continuous evidence integrity"),
    Scene(25.0, 32.0, "ownership", "Exact blast radius, never a guess"),
    Scene(32.0, 39.0, "native-repair", "Every surface keeps its own rules"),
    Scene(39.0, 45.0, "proof", "Independent proof, not a success response"),
    Scene(45.0, 48.0, "brand", "When reality changes"),
)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def ease(value: float) -> float:
    value = clamp(value)
    return value * value * (3.0 - 2.0 * value)


def local(progress: float, start: float, duration: float) -> float:
    return ease((progress - start) / duration)


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill, outline=None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, face: ImageFont.FreeTypeFont, fill=INK, *, anchor=None, spacing: int = 8, align: str = "left") -> None:
    draw.multiline_text(xy, value, font=face, fill=fill, anchor=anchor, spacing=spacing, align=align)


def brand(draw: ImageDraw.ImageDraw) -> None:
    rounded(draw, (58, 46, 104, 92), 12, SURFACE_2, GREEN, 2)
    text(draw, (81, 69), "V", core.font(18, mono=True), GREEN, anchor="mm")
    text(draw, (126, 68), "VERITAS", core.font(20, mono=True), INK, anchor="lm")
    draw.line((244, 53, 244, 83), fill=LINE, width=1)
    text(draw, (265, 68), "CONTINUOUS EVIDENCE INTEGRITY", F_MICRO, MUTED, anchor="lm")


def base(index: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 72):
        draw.line((x, 0, x, HEIGHT), fill=(8, 25, 19), width=1)
    for y in range(0, HEIGHT, 72):
        draw.line((0, y, WIDTH, y), fill=(8, 25, 19), width=1)
    draw.ellipse((1290, -360, 2190, 540), fill=(6, 28, 20))
    brand(draw)
    text(draw, (58, 156), SCENES[index].kicker.upper(), F_KICKER, GREEN)
    text(draw, (1862, 68), f"BEAT {index + 1:02d} / {len(SCENES):02d}", F_MICRO, SOFT, anchor="rm")
    draw.line((58, 1008, 1862, 1008), fill=(28, 48, 40), width=1)
    text(draw, (58, 1035), "EVIDENCE-BOUND  /  MANIFEST-SCOPED  /  INDEPENDENTLY VERIFIED", F_MICRO, SOFT)
    return image


def pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], label: str, color) -> tuple[int, int, int, int]:
    x, y = xy
    width = max(126, round(draw.textlength(label, font=F_MICRO)) + 36)
    rounded(draw, (x, y, x + width, y + 40), 20, (11, 31, 24), color, 2)
    draw.ellipse((x + 13, y + 15, x + 23, y + 25), fill=color)
    text(draw, (x + 31, y + 20), label.upper(), F_MICRO, color, anchor="lm")
    return (x, y, x + width, y + 40)


def source_node(draw: ImageDraw.ImageDraw, center: tuple[int, int], code: str, label: str, detail: str, color) -> None:
    x, y = center
    draw.ellipse((x - 49, y - 49, x + 49, y + 49), fill=SURFACE_2, outline=color, width=3)
    text(draw, (x, y), code, F_CARD, color, anchor="mm")
    text(draw, (x, y + 82), label, F_SMALL, INK, anchor="mm")
    text(draw, (x, y + 114), detail, F_MICRO, color, anchor="mm")


def scene_email_hook() -> Image.Image:
    image = base(0)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 220), "A customer\nchanged their mind.", F_TITLE, INK, spacing=2)
    text(draw, (64, 462), "They sent one completely normal email.", F_BODY, MUTED)
    pill(draw, (64, 565), "authorized customer", GREEN)
    pill(draw, (64, 625), "plain-language intent", GREEN)
    pill(draw, (64, 685), "no portal · no route code", GREEN)
    route.gmail_message(draw, (790, 185, 1835, 905))
    return image


def scene_contradiction() -> Image.Image:
    image = base(1)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 215), "The inbox changed.\nThe task didn't.", F_TITLE, INK)
    text(draw, (64, 455), "The customer requested a decrease. Operations still demanded an increase.", F_BODY, MUTED)
    pill(draw, (64, 570), "silent business contradiction", RED)
    text(draw, (64, 650), "Both tools are individually correct.\nTogether, the company is wrong.", F_CARD, INK)
    route.gmail_message(draw, (700, 535, 1210, 965), compact=True)
    route.tasks_window(draw, (1260, 535, 1850, 965), "Increase acquisition spend", "Increase the current acquisition budget.", stale=True)
    draw.line((1218, 752, 1248, 752), fill=RED, width=5)
    draw.polygon(((1248, 752), (1228, 741), (1228, 763)), fill=RED)
    return image


def scene_zoom_out() -> Image.Image:
    image = base(2)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 205), "That was only\none consequence.", F_TITLE, INK)
    text(draw, (64, 445), "Reality changes in metrics, policies, and customer conversations.\nConsequences live everywhere else.", F_BODY, MUTED, spacing=10)
    input_nodes = (
        ((270, 720), "S", "Google Sheets", "METRICS", GREEN),
        ((620, 720), "D", "Google Docs", "POLICY", BLUE),
        ((970, 720), "G", "Customer Gmail", "INTENT", RED),
    )
    for center, code, label, detail, color in input_nodes:
        source_node(draw, center, code, label, detail, color)
    rounded(draw, (1190, 620, 1390, 820), 35, SURFACE_2, GREEN, 3)
    text(draw, (1290, 720), "V", core.font(62, mono=True), GREEN, anchor="mm")
    outputs = ((1580, 610, "D", "DOCS"), (1760, 700, "S", "SLIDES"), (1580, 830, "T", "TASKS"))
    for x, y, code, label in outputs:
        draw.ellipse((x - 38, y - 38, x + 38, y + 38), fill=SURFACE, outline=GREEN_DARK, width=3)
        text(draw, (x, y), code, F_SMALL, GREEN, anchor="mm")
        text(draw, (x, y + 61), label, F_MICRO, MUTED, anchor="mm")
    for center, *_ in input_nodes:
        draw.line((center[0] + 50, center[1], 1190, 720), fill=(43, 93, 69), width=3)
    for x, y, *_ in outputs:
        draw.line((1390, 720, x - 39, y), fill=(43, 93, 69), width=3)
    return image


def scene_platform() -> Image.Image:
    image = base(3)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 205), "Veritas is the integrity layer\nfor AI-created knowledge work.", core.font(78, rounded=True), INK)
    text(draw, (64, 425), "It repairs consequences—not reminders.", F_BODY, MUTED)
    y = 720
    xs = (255, 705, 1155, 1605)
    stages = (
        ("01", "DETECT", "Seal the change", GREEN),
        ("02", "TRACE", "Follow exact ownership", AMBER),
        ("03", "REPAIR", "Apply guarded native writes", BLUE),
        ("04", "VERIFY", "Independently re-read", GREEN),
    )
    for index, (x, (number, label, detail, color)) in enumerate(zip(xs, stages)):
        rounded(draw, (x - 175, y - 105, x + 175, y + 105), 24, SURFACE, color, 2)
        text(draw, (x - 130, y - 62), number, F_MICRO, color)
        text(draw, (x - 130, y - 8), label, F_CARD, INK)
        text(draw, (x - 130, y + 50), detail, F_SMALL, MUTED)
        if index < 3:
            draw.line((x + 175, y, xs[index + 1] - 175, y), fill=GREEN, width=4)
            draw.polygon(((xs[index + 1] - 175, y), (xs[index + 1] - 194, y - 10), (xs[index + 1] - 194, y + 10)), fill=GREEN)
    pill(draw, (64, 510), "Gemini reasons · deterministic policy owns the keys", GREEN)
    return image


def scene_ownership() -> Image.Image:
    image = base(4)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 210), "It traces the exact\nblast radius.", F_TITLE, INK)
    text(draw, (64, 448), "No similarity guess can authorize a repair.", F_BODY, MUTED)
    metrics = ((64, 555, "4", "AFFECTED CLAIMS"), (64, 650, "5", "AFFECTED ARTIFACTS"), (64, 745, "9", "REGISTERED PATHS"), (64, 840, "0", "INFERRED PATHS"))
    for x, y, value, label in metrics:
        text(draw, (x, y), value, core.font(40, rounded=True), GREEN)
        text(draw, (x + 78, y + 20), label, F_MICRO, MUTED, anchor="lm")
    # Leave a deliberate gutter after the headline.  The old panel began at
    # x=710 while the final "t" in "exact" ended at x=714, which caused the
    # panel to cover the letter during the reveal.
    rounded(draw, (750, 225, 1870, 925), 30, SURFACE, (44, 80, 63), 2)
    text(draw, (790, 285), "VERSIONED CLAIM MANIFEST", F_KICKER, GREEN)
    source = (870, 560)
    claims = ((1230, 340), (1230, 480), (1230, 620), (1230, 760))
    artifacts = ((1690, 340), (1690, 480), (1690, 620), (1690, 760))
    source_node(draw, source, "S", "Metrics!B17", "SNAPSHOT 507DF4", GREEN)
    for index, center in enumerate(claims, start=1):
        x, y = center
        draw.ellipse((x - 49, y - 49, x + 49, y + 49), fill=SURFACE_2, outline=AMBER, width=3)
        text(draw, (x, y), "C", F_CARD, AMBER, anchor="mm")
        text(draw, (x, y + 68), f"Claim {index}", core.font(17), INK, anchor="mm")
    labels = ("DOCS", "SLIDES", "GMAIL", "TASKS")
    colors = (BLUE, AMBER, RED, TASKS_BLUE)
    for center, label, color in zip(artifacts, labels, colors):
        x, y = center
        draw.ellipse((x - 49, y - 49, x + 49, y + 49), fill=SURFACE_2, outline=color, width=3)
        text(draw, (x, y), label[0], F_CARD, color, anchor="mm")
        text(draw, (x, y + 68), label, core.font(17), INK, anchor="mm")
    for claim in claims:
        draw.line((source[0] + 50, source[1], claim[0] - 50, claim[1]), fill=GREEN_DARK, width=3)
    mappings = ((0, 0), (1, 0), (1, 1), (2, 2), (3, 3))
    for claim_index, artifact_index in mappings:
        claim = claims[claim_index]
        artifact = artifacts[artifact_index]
        draw.line((claim[0] + 50, claim[1], artifact[0] - 50, artifact[1]), fill=(50, 101, 76), width=3)
    return image


def repair_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], code: str, app: str, action: str, protection: str, color) -> None:
    x1, y1, x2, y2 = box
    rounded(draw, box, 24, SURFACE, (44, 79, 62), 2)
    rounded(draw, (x1 + 28, y1 + 28, x1 + 80, y1 + 80), 13, color)
    text(draw, (x1 + 54, y1 + 54), code, F_MICRO, BG, anchor="mm")
    text(draw, (x1 + 100, y1 + 40), app, F_CARD, INK)
    text(draw, (x1 + 30, y1 + 125), action, F_BODY, INK)
    draw.line((x1 + 30, y1 + 180, x2 - 30, y1 + 180), fill=LINE, width=2)
    text(draw, (x1 + 30, y1 + 220), protection.upper(), F_MICRO, MUTED)
    pill(draw, (x1 + 30, y2 - 60), "verified native repair", GREEN)


def scene_native_repair() -> Image.Image:
    image = base(5)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 205), "Then every surface is repaired\nby its own rules.", core.font(78, rounded=True), INK)
    text(draw, (64, 420), "Minimal changes. Human authorship preserved. Irreversible actions constrained.", F_BODY, MUTED)
    repair_card(draw, (55, 545, 475, 915), "D", "Google Docs", "Patch only the claim", "CFO paragraph preserved", BLUE)
    repair_card(draw, (505, 545, 925, 915), "S", "Google Slides", "Update exact anchor", "Revision precondition", AMBER)
    repair_card(draw, (955, 545, 1375, 915), "G", "Gmail", "Create correction draft", "Sent original immutable", RED)
    repair_card(draw, (1405, 545, 1825, 915), "T", "Google Tasks", "Update existing task", "Human approval required", TASKS_BLUE)
    return image


def scene_proof() -> Image.Image:
    image = base(6)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 205), "Then a separate verifier\nproves it really happened.", F_TITLE, INK)
    text(draw, (64, 440), "A successful write response is never accepted as truth.", F_BODY, MUTED)
    cards = ((65, 555, 465, 845, "13/13", "TARGETS VERIFIED"), (500, 555, 900, 845, "5/5", "PROTECTED REGIONS"), (935, 555, 1335, 845, "0", "HUMAN EDITS LOST"))
    for x1, y1, x2, y2, value, label in cards:
        rounded(draw, (x1, y1, x2, y2), 25, SURFACE, (43, 77, 61), 2)
        text(draw, ((x1 + x2) // 2, y1 + 105), value, F_METRIC, GREEN, anchor="mm")
        text(draw, ((x1 + x2) // 2, y1 + 205), label, F_MICRO, MUTED, anchor="mm")
    rounded(draw, (1380, 480, 1845, 900), 26, (8, 39, 28), GREEN, 3)
    pill(draw, (1430, 525), "certificate issued", GREEN)
    text(draw, (1430, 635), "EVIDENCE\nINTEGRITY\nCERTIFICATE", core.font(37, rounded=True), INK, spacing=3)
    draw.line((1430, 780, 1795, 780), fill=(55, 107, 82), width=2)
    text(draw, (1430, 830), "CERT-7A92", F_CARD, GREEN)
    text(draw, (1430, 875), "CONTENT-ADDRESSED · SCOPED", F_MICRO, MUTED)
    return image


def brand_base() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG_DEEP)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 72):
        draw.line((x, 0, x, HEIGHT), fill=(7, 22, 17), width=1)
    for y in range(0, HEIGHT, 72):
        draw.line((0, y, WIDTH, y), fill=(7, 22, 17), width=1)
    return image


def scene_brand() -> Image.Image:
    image = brand_base()
    draw = ImageDraw.Draw(image)
    text(draw, (960, 175), "VERITAS", F_KICKER, GREEN, anchor="mm")
    text(draw, (960, 310), "When evidence changes,\nrepair every consequence.", core.font(82, rounded=True), INK, anchor="ma", spacing=0, align="center")
    source_node(draw, (500, 700), "S", "REGISTERED EVIDENCE", "SHEETS · DOCS · GMAIL", GREEN)
    rounded(draw, (875, 620, 1045, 790), 42, SURFACE_2, GREEN, 3)
    text(draw, (960, 705), "V", core.font(64, mono=True), GREEN, anchor="mm")
    source_node(draw, (1420, 700), "✓", "VERIFIED WORKSPACE", "DOCS · SLIDES · TASKS", GREEN)
    draw.line((550, 700, 875, 700), fill=GREEN, width=5)
    draw.line((1045, 700, 1370, 700), fill=GREEN, width=5)
    draw.polygon(((875, 700), (850, 686), (850, 714)), fill=GREEN)
    draw.polygon(((1370, 700), (1345, 686), (1345, 714)), fill=GREEN)
    text(draw, (960, 925), "AI CREATED THE WORK. VERITAS KEEPS IT CONSISTENT.", F_MICRO, MUTED, anchor="mm")
    return image


BUILDERS = (
    scene_email_hook,
    scene_contradiction,
    scene_zoom_out,
    scene_platform,
    scene_ownership,
    scene_native_repair,
    scene_proof,
    scene_brand,
)


PLANS: tuple[tuple[Reveal, ...], ...] = (
    (
        Reveal((38, 180, 760, 520), 0.02, 0.22, 0, 34),
        Reveal((755, 150, 1875, 940), 0.18, 0.36, 125, 0),
        Reveal((38, 530, 620, 760), 0.45, 0.26, -50, 25),
    ),
    (
        Reveal((38, 180, 1270, 520), 0.02, 0.22, 0, 34),
        Reveal((38, 535, 650, 830), 0.25, 0.22, -50, 25),
        Reveal((665, 535, 1230, 965), 0.32, 0.28, -80, 0),
        Reveal((1235, 535, 1880, 965), 0.52, 0.28, 80, 0),
    ),
    (
        Reveal((38, 175, 1180, 540), 0.02, 0.23, 0, 34),
        Reveal((175, 600, 1080, 900), 0.28, 0.30, 0, 60),
        Reveal((1140, 570, 1435, 865), 0.47, 0.22, 0, 50),
        Reveal((1480, 525, 1840, 930), 0.60, 0.22, 70, 0),
    ),
    (
        Reveal((38, 170, 1700, 510), 0.02, 0.24, 0, 34),
        Reveal((38, 480, 820, 570), 0.24, 0.17, -50, 0),
        Reveal((50, 575, 460, 865), 0.28, 0.20, 0, 55),
        Reveal((500, 575, 910, 865), 0.40, 0.20, 0, 55),
        Reveal((950, 575, 1360, 865), 0.52, 0.20, 0, 55),
        Reveal((1400, 575, 1815, 865), 0.64, 0.20, 0, 55),
    ),
    (
        Reveal((38, 175, 735, 510), 0.02, 0.22, 0, 34),
        Reveal((38, 520, 500, 940), 0.24, 0.30, -55, 20),
        Reveal((740, 190, 1885, 965), 0.20, 0.28, 0, 42),
    ),
    (
        Reveal((38, 175, 1660, 510), 0.02, 0.22, 0, 34),
        Reveal((35, 515, 495, 950), 0.24, 0.22, 0, 60),
        Reveal((485, 515, 945, 950), 0.36, 0.22, 0, 60),
        Reveal((935, 515, 1395, 950), 0.48, 0.22, 0, 60),
        Reveal((1385, 515, 1850, 950), 0.60, 0.22, 0, 60),
    ),
    (
        Reveal((38, 175, 1260, 510), 0.02, 0.22, 0, 34),
        Reveal((35, 520, 490, 880), 0.26, 0.22, 0, 60),
        Reveal((470, 520, 925, 880), 0.40, 0.22, 0, 60),
        Reveal((905, 520, 1360, 880), 0.54, 0.22, 0, 60),
        Reveal((1345, 445, 1880, 935), 0.63, 0.24, 80, 0),
    ),
    (
        Reveal((430, 125, 1490, 560), 0.02, 0.26, 0, -65),
        Reveal((400, 585, 1520, 875), 0.30, 0.38, 0, 55),
        Reveal((600, 880, 1320, 960), 0.68, 0.18, 0, 28),
    ),
)


def make_content_layer(final: Image.Image, background: Image.Image) -> Image.Image:
    difference = ImageChops.difference(final, background).convert("L")
    mask = difference.point(lambda value: 255 if value > 3 else 0)
    layer = final.convert("RGBA")
    layer.putalpha(mask)
    return layer


def prepare_motion(finals: list[Image.Image], backgrounds: list[Image.Image]) -> list[list[tuple[Reveal, Image.Image]]]:
    prepared: list[list[tuple[Reveal, Image.Image]]] = []
    for final, background, plan in zip(finals, backgrounds, PLANS):
        layer = make_content_layer(final, background)
        prepared.append([(reveal, layer.crop(reveal.box)) for reveal in plan])
    return prepared


def paste_reveal(canvas: Image.Image, reveal: Reveal, patch: Image.Image, progress: float) -> None:
    amount = local(progress, reveal.start, reveal.duration)
    if amount <= 0:
        return
    lifted = patch.copy()
    lifted.putalpha(lifted.getchannel("A").point([round(index * amount) for index in range(256)]))
    x = reveal.box[0] + round(reveal.dx * (1.0 - amount))
    y = reveal.box[1] + round(reveal.dy * (1.0 - amount))
    canvas.alpha_composite(lifted, (x, y))


def progress_line(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], amount: float, color, *, width: int = 5) -> tuple[int, int]:
    amount = clamp(amount)
    point = (round(start[0] + (end[0] - start[0]) * amount), round(start[1] + (end[1] - start[1]) * amount))
    if amount > 0:
        draw.line((*start, *point), fill=color, width=width)
    return point


def scene_motion(frame: Image.Image, index: int, progress: float) -> None:
    if progress >= 0.91:
        return
    draw = ImageDraw.Draw(frame)
    if index == 0:
        amount = local(progress, 0.28, 0.45)
        if 0 < amount < 1:
            y = round(300 + 510 * amount)
            draw.line((1000, y, 1780, y), fill=(236, 109, 97), width=4)
    elif index == 1:
        amount = local(progress, 0.45, 0.30)
        point = progress_line(draw, (1218, 752), (1295, 752), amount, RED, width=7)
        draw.ellipse((point[0] - 8, point[1] - 8, point[0] + 8, point[1] + 8), fill=RED)
    elif index == 2:
        amount = local(progress, 0.30, 0.50)
        for start in ((320, 720), (670, 720), (1020, 720)):
            progress_line(draw, start, (1190, 720), amount, GREEN, width=5)
        if amount > 0.58:
            out = local(progress, 0.58, 0.22)
            for end in ((1541, 610), (1721, 700), (1541, 830)):
                progress_line(draw, (1390, 720), end, out, GREEN, width=5)
    elif index == 3:
        amount = local(progress, 0.28, 0.52)
        x = round(430 + 1000 * amount)
        draw.ellipse((x - 14, 706, x + 14, 734), fill=GREEN_PALE)
        draw.ellipse((x - 7, 713, x + 7, 727), fill=GREEN)
    elif index == 4:
        # The manifest panel finishes its entrance before the live trace begins.
        # Otherwise these fixed-coordinate highlights briefly diverge from the
        # translated graph underneath them and look like duplicate branches.
        first = local(progress, 0.50, 0.16)
        second = local(progress, 0.66, 0.16)
        for claim in ((1180, 340), (1180, 480), (1180, 620), (1180, 760)):
            if 0 < first < 1:
                x = round(920 + (claim[0] - 920) * first)
                y = round(560 + (claim[1] - 560) * first)
                draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=GREEN_PALE)
                draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=GREEN)
        for start, end in (((1280, 340), (1640, 340)), ((1280, 480), (1640, 340)), ((1280, 480), (1640, 480)), ((1280, 620), (1640, 620)), ((1280, 760), (1640, 760))):
            if 0 < second < 1:
                x = round(start[0] + (end[0] - start[0]) * second)
                y = round(start[1] + (end[1] - start[1]) * second)
                draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=GREEN_PALE)
                draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=GREEN_DARK)
    elif index == 5:
        amount = local(progress, 0.25, 0.52)
        x = round(90 + 1695 * amount)
        draw.line((90, 893, x, 893), fill=GREEN, width=6)
        draw.ellipse((x - 10, 883, x + 10, 903), fill=GREEN_PALE)
    elif index == 6:
        amount = local(progress, 0.28, 0.44)
        x = round(65 + 1270 * amount)
        draw.line((65, 872, x, 872), fill=GREEN, width=6)
        if amount > 0.78:
            pulse = round(4 + 10 * (amount - 0.78) / 0.22)
            draw.rounded_rectangle((1380 - pulse, 480 - pulse, 1845 + pulse, 900 + pulse), radius=29, outline=GREEN, width=5)
    elif index == 7:
        first = local(progress, 0.24, 0.22)
        second = local(progress, 0.48, 0.22)
        progress_line(draw, (550, 700), (875, 700), first, GREEN_PALE, width=8)
        progress_line(draw, (1045, 700), (1370, 700), second, GREEN_PALE, width=8)
        pulse = local(progress, 0.08, 0.62)
        radius = round(95 + 160 * pulse)
        draw.ellipse((960 - radius, 705 - radius, 960 + radius, 705 + radius), outline=GREEN_DARK, width=3)


def animate(index: int, progress: float, final: Image.Image, background: Image.Image, patches: list[tuple[Reveal, Image.Image]]) -> Image.Image:
    canvas = background.convert("RGBA")
    for reveal, patch in patches:
        paste_reveal(canvas, reveal, patch, progress)
    frame = canvas.convert("RGB")
    settle = local(progress, 0.83, 0.09)
    if settle > 0:
        frame = Image.blend(frame, final, settle)
    scene_motion(frame, index, progress)
    return frame


def wipe(previous: Image.Image, current: Image.Image, amount: float, *, reverse: bool) -> Image.Image:
    """Move between beats without ever superimposing their typography.

    The earlier feathered wipe mixed two complete scenes for several frames.
    Large headlines then appeared to run underneath incoming panels.  A short
    dip through the deep background keeps the cut cinematic while ensuring
    that every individual frame contains content from only one beat.
    """
    del reverse  # Kept in the signature so existing call sites stay simple.
    amount = clamp(amount)
    if amount < 0.5:
        return Image.blend(previous, Image.new("RGB", previous.size, BG_DEEP), ease(amount * 2.0))
    return Image.blend(Image.new("RGB", current.size, BG_DEEP), current, ease((amount - 0.5) * 2.0))


def scene_at(seconds: float) -> tuple[int, float]:
    for index, scene in enumerate(SCENES):
        if scene.start <= seconds < scene.end:
            return index, (seconds - scene.start) / (scene.end - scene.start)
    return len(SCENES) - 1, 1.0


def compose(finals: list[Image.Image], backgrounds: list[Image.Image], patches, seconds: float) -> Image.Image:
    index, progress = scene_at(seconds)
    frame = animate(index, progress, finals[index], backgrounds[index], patches[index])
    scene = SCENES[index]
    if index == 0:
        frame = Image.blend(Image.new("RGB", frame.size, BG_DEEP), frame, ease(seconds / 0.9))
    elif seconds - scene.start < TRANSITION:
        frame = wipe(finals[index - 1], frame, (seconds - scene.start) / TRANSITION, reverse=index % 2 == 0)
    if DURATION - seconds < 1.0:
        frame = Image.blend(Image.new("RGB", frame.size, BG_DEEP), frame, ease((DURATION - seconds) / 1.0))
    return frame


def render(output: Path, music: Path, preview_frames: Path | None, *, start: float = 0.0, duration: float | None = None, stills_only: bool = False) -> None:
    finals = [builder() for builder in BUILDERS]
    backgrounds = [base(index) for index in range(len(SCENES) - 1)] + [brand_base()]
    patches = prepare_motion(finals, backgrounds)
    if preview_frames is not None:
        preview_frames.mkdir(parents=True, exist_ok=True)
        for index, final in enumerate(finals):
            final.save(preview_frames / f"judge-{index + 1:02d}-{SCENES[index].name}.png")
    if stills_only:
        return

    clip_duration = duration if duration is not None else DURATION - start
    if start < 0 or clip_duration <= 0 or start + clip_duration > DURATION:
        raise ValueError("render window must remain inside the 48-second film")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s:v", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
        "-ss", str(start), "-i", str(music),
        "-map", "0:v:0", "-map", "1:a:0", "-t", str(clip_duration),
        "-af", "afade=t=in:st=0:d=0.7,afade=t=out:st=45:d=3,volume=0.88",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-profile:v", "high", "-level:v", "4.2",
        "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", str(output),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert process.stdin is not None
    total_frames = round(clip_duration * FPS)
    try:
        for frame_number in range(total_frames):
            seconds = start + frame_number / FPS
            process.stdin.write(compose(finals, backgrounds, patches, seconds).tobytes())
            if frame_number % (FPS * 6) == 0:
                print(f"rendered source {seconds:05.1f}s · clip {frame_number / FPS:04.1f}s / {clip_duration:.1f}s", file=sys.stderr, flush=True)
    except BrokenPipeError as error:
        raise RuntimeError("ffmpeg stopped while receiving animated frames") from error
    finally:
        process.stdin.close()
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg exited with status {code}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--music", type=Path, required=True)
    parser.add_argument("--preview-frames", type=Path)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--stills-only", action="store_true")
    args = parser.parse_args()
    if not args.music.exists():
        raise SystemExit(f"music not found: {args.music}")
    render(args.output, args.music, args.preview_frames, start=args.start, duration=args.duration, stills_only=args.stills_only)


if __name__ == "__main__":
    main()
