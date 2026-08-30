#!/usr/bin/env python3
"""Render the Gmail-to-Google-Tasks Veritas story as a 72-second motion film."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

import veritas_cinematic_intro as core


WIDTH = 1920
HEIGHT = 1080
FPS = 60
DURATION = 72.0
TRANSITION = 0.70

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
GMAIL_RED = (234, 67, 53)
TASKS_BLUE = (66, 133, 244)
GOOGLE_YELLOW = (251, 188, 5)
GOOGLE_GREEN = (52, 168, 83)
PAPER = (246, 248, 246)
PAPER_2 = (233, 237, 234)
PAPER_TEXT = (31, 39, 36)
PAPER_MUTED = (91, 103, 97)

F_KICKER = core.font(18, mono=True)
F_MICRO = core.font(15, mono=True)
F_SMALL = core.font(20)
F_BODY = core.font(27)
F_CARD = core.font(31, rounded=True)
F_TITLE = core.font(90, rounded=True)
F_TITLE_LARGE = core.font(106, rounded=True)
F_METRIC = core.font(72, rounded=True)


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
    dy: int = 35


SCENES = (
    Scene(0.0, 7.0, "customer-change", "A normal customer moment"),
    Scene(7.0, 14.5, "email-arrives", "The signal arrives in Gmail"),
    Scene(14.5, 21.0, "task-stale", "One company, two different truths"),
    Scene(21.0, 28.0, "manual-hunt", "The work nobody owns"),
    Scene(28.0, 35.0, "meet-veritas", "Autonomous consequence repair"),
    Scene(35.0, 42.0, "authenticate", "01 · Authenticate the signal"),
    Scene(42.0, 49.0, "trace", "02 · Trace exact ownership"),
    Scene(49.0, 58.0, "repair", "03 · Repair the real Google Task"),
    Scene(58.0, 66.0, "prove", "04 · Re-read, verify, prove"),
    Scene(66.0, 72.0, "brand", "Customer signal → owned action"),
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


def pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], label: str, color, *, light: bool = False) -> tuple[int, int, int, int]:
    x, y = xy
    width = max(126, round(draw.textlength(label, font=F_MICRO)) + 36)
    fill = (242, 247, 244) if light else (11, 31, 24)
    ink = color if not light else (32, 88, 63)
    rounded(draw, (x, y, x + width, y + 40), 20, fill, color, 2)
    draw.ellipse((x + 13, y + 15, x + 23, y + 25), fill=color)
    text(draw, (x + 31, y + 20), label.upper(), F_MICRO, ink, anchor="lm")
    return (x, y, x + width, y + 40)


def gmail_icon(draw: ImageDraw.ImageDraw, center: tuple[int, int], size: int = 58) -> None:
    x, y = center
    half = size // 2
    rounded(draw, (x - half, y - half, x + half, y + half), 14, (255, 255, 255), (209, 215, 211), 2)
    left = x - half + 11
    right = x + half - 11
    top = y - half + 15
    bottom = y + half - 14
    draw.line((left, bottom, left, top, x, y + 4, right, top, right, bottom), fill=GMAIL_RED, width=max(4, size // 10), joint="curve")


def tasks_icon(draw: ImageDraw.ImageDraw, center: tuple[int, int], size: int = 58) -> None:
    x, y = center
    radius = size // 2
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=TASKS_BLUE)
    draw.line((x - 14, y + 1, x - 4, y + 12, x + 18, y - 15), fill=(255, 255, 255), width=max(5, size // 10), joint="curve")


def veritas_icon(draw: ImageDraw.ImageDraw, center: tuple[int, int], size: int = 62) -> None:
    x, y = center
    half = size // 2
    rounded(draw, (x - half, y - half, x + half, y + half), 16, SURFACE_2, GREEN, 3)
    text(draw, (x, y), "V", core.font(round(size * 0.46), mono=True), GREEN, anchor="mm")


def brand(draw: ImageDraw.ImageDraw) -> None:
    veritas_icon(draw, (81, 69), 48)
    text(draw, (126, 68), "VERITAS", core.font(20, mono=True), INK, anchor="lm")
    draw.line((244, 53, 244, 83), fill=LINE, width=1)
    text(draw, (265, 68), "AUTONOMOUS CONSEQUENCE REPAIR", F_MICRO, MUTED, anchor="lm")


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
    text(draw, (1862, 68), f"STEP {index + 1:02d} / {len(SCENES):02d}", F_MICRO, SOFT, anchor="rm")
    draw.line((58, 1008, 1862, 1008), fill=(28, 48, 40), width=1)
    text(draw, (58, 1035), "GMAIL AUTHENTICATED  /  MANIFEST-SCOPED  /  GOOGLE TASK RE-READ VERIFIED", F_MICRO, SOFT)
    return image


def window(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, icon: str) -> None:
    x1, y1, x2, y2 = box
    rounded(draw, box, 26, PAPER, (146, 159, 151), 2)
    rounded(draw, (x1, y1, x2, y1 + 70), 26, PAPER_2)
    draw.rectangle((x1, y1 + 40, x2, y1 + 70), fill=PAPER_2)
    draw.ellipse((x1 + 24, y1 + 28, x1 + 36, y1 + 40), fill=(225, 96, 87))
    draw.ellipse((x1 + 45, y1 + 28, x1 + 57, y1 + 40), fill=(232, 180, 82))
    draw.ellipse((x1 + 66, y1 + 28, x1 + 78, y1 + 40), fill=(75, 176, 118))
    if icon == "gmail":
        gmail_icon(draw, (x1 + 120, y1 + 35), 40)
    else:
        tasks_icon(draw, (x1 + 120, y1 + 35), 40)
    text(draw, (x1 + 154, y1 + 35), title, core.font(22, rounded=True), PAPER_TEXT, anchor="lm")


def gmail_message(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, compact: bool = False) -> None:
    x1, y1, x2, y2 = box
    window(draw, box, "Gmail", "gmail")
    content_x = x1 + (52 if compact else 210)
    if not compact:
        draw.line((x1 + 180, y1 + 70, x1 + 180, y2), fill=(216, 222, 218), width=2)
        text(draw, (x1 + 35, y1 + 115), "Inbox", F_SMALL, GMAIL_RED)
        text(draw, (x1 + 35, y1 + 165), "Starred", F_SMALL, PAPER_MUTED)
        text(draw, (x1 + 35, y1 + 215), "Sent", F_SMALL, PAPER_MUTED)
    title_font = core.font(27 if compact else 34, rounded=True)
    title_y = y1 + (96 if compact else 112)
    avatar_y = y1 + (137 if compact else 168)
    text(draw, (content_x, title_y), "Decrease acquisition spend", title_font, PAPER_TEXT)
    draw.ellipse((content_x, avatar_y, content_x + 52, avatar_y + 52), fill=(185, 82, 189))
    text(draw, (content_x + 26, avatar_y + 26), "R", core.font(22, rounded=True), (255, 255, 255), anchor="mm")
    text(draw, (content_x + 72, avatar_y + 8), "Rudra Bhaskar", core.font(22, rounded=True), PAPER_TEXT)
    sender_line = "24uec023@lnmiit.ac.in" if compact else "24uec023@lnmiit.ac.in  →  company inbox"
    text(draw, (content_x + 72, avatar_y + 39), sender_line, F_MICRO, PAPER_MUTED)
    body_y = y1 + (215 if compact else 280)
    if compact:
        text(draw, (content_x, body_y), "Please decrease acquisition\nspend by 10%.", core.font(21), PAPER_TEXT, spacing=7)
        text(draw, (content_x, body_y + 67), "Same owner and due date.", core.font(18), PAPER_MUTED)
    else:
        text(draw, (content_x, body_y), "Hi team,", F_BODY, PAPER_TEXT)
        text(draw, (content_x, body_y + 58), "I changed my mind. Please decrease acquisition spend\nby 10% from what I quoted.", F_BODY, PAPER_TEXT, spacing=11)
        text(draw, (content_x, body_y + 152), "Keep the same owner and due date.", F_BODY, PAPER_TEXT)
    pill(draw, (content_x, y2 - (50 if compact else 78)), "normal email · no route code", GMAIL_RED, light=True)


def task_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title_value: str, note: str, *, stale: bool = False, completed: bool = False) -> None:
    x1, y1, x2, y2 = box
    rounded(draw, box, 18, (255, 255, 255), (195, 204, 198), 2)
    circle_color = GOOGLE_GREEN if completed else RED if stale else TASKS_BLUE
    draw.ellipse((x1 + 24, y1 + 26, x1 + 52, y1 + 54), outline=circle_color, width=3)
    if completed:
        draw.line((x1 + 31, y1 + 40, x1 + 37, y1 + 47, x1 + 48, y1 + 32), fill=GOOGLE_GREEN, width=3)
    text(draw, (x1 + 72, y1 + 25), title_value, core.font(28, rounded=True), PAPER_TEXT)
    text(draw, (x1 + 72, y1 + 69), note, core.font(21), PAPER_MUTED)
    pill(draw, (x1 + 72, y2 - 58), "Due Fri · 3:00 PM", TASKS_BLUE, light=True)
    pill(draw, (x1 + 300, y2 - 58), "Owner unchanged", GOOGLE_GREEN, light=True)
    if stale:
        draw.line((x1 + 70, y1 + 47, min(x2 - 32, x1 + 520), y1 + 47), fill=RED, width=5)


def tasks_window(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title_value: str, note: str, *, stale: bool = False, completed: bool = False) -> None:
    x1, y1, x2, y2 = box
    window(draw, box, "Google Tasks", "tasks")
    text(draw, (x1 + 42, y1 + 115), "Veritas", core.font(30, rounded=True), PAPER_TEXT)
    text(draw, (x2 - 42, y1 + 116), "1 task", F_MICRO, PAPER_MUTED, anchor="ra")
    task_card(draw, (x1 + 40, y1 + 155, x2 - 40, y1 + 365), title_value, note, stale=stale, completed=completed)
    text(draw, (x1 + 42, y2 - 55), "Synced with Google Workspace", F_MICRO, PAPER_MUTED)


def scene_customer_change() -> Image.Image:
    image = base(0)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 225), "A customer\nchanged their mind.", F_TITLE_LARGE, INK, spacing=2)
    text(draw, (64, 505), "That happens every day. The dangerous part comes next.", F_BODY, MUTED)
    rounded(draw, (1090, 270, 1790, 670), 30, SURFACE, (46, 80, 65), 2)
    gmail_icon(draw, (1195, 380), 86)
    pill(draw, (1290, 325), "new customer email", GMAIL_RED)
    text(draw, (1290, 405), "Decrease acquisition spend", F_CARD, INK)
    text(draw, (1290, 468), "Please reduce it by 10%.\nKeep the owner and due date.", F_BODY, MUTED, spacing=10)
    text(draw, (1150, 610), "18:07:02  ·  received by company inbox", F_MICRO, SOFT)
    pill(draw, (64, 660), "one ordinary email", GREEN)
    text(draw, (64, 742), "No portal. No ticket. No secret subject code.", F_CARD, INK)
    return image


def scene_email_arrives() -> Image.Image:
    image = base(1)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 220), "They sent one\nnormal email.", F_TITLE, INK)
    text(draw, (64, 455), "The customer should never need to understand your internal systems.", F_BODY, MUTED)
    gmail_message(draw, (820, 190, 1835, 900))
    pill(draw, (64, 610), "authorized customer", GREEN)
    pill(draw, (64, 670), "company inbox", GREEN)
    pill(draw, (64, 730), "plain-language intent", GREEN)
    return image


def scene_task_stale() -> Image.Image:
    image = base(2)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 220), "The inbox knew.\nThe task didn't.", F_TITLE, INK)
    text(draw, (64, 458), "The customer asked for a decrease. The operating task still demanded an increase.", F_BODY, MUTED)
    gmail_message(draw, (720, 565, 1240, 925), compact=True)
    tasks_window(draw, (1280, 565, 1850, 925), "Increase acquisition spend", "Increase the current acquisition budget.", stale=True)
    draw.line((1248, 742, 1272, 742), fill=RED, width=4)
    draw.polygon(((1272, 742), (1254, 732), (1254, 752)), fill=RED)
    pill(draw, (64, 620), "contradiction detected", RED)
    text(draw, (64, 700), "Both systems are individually correct.\nTogether, the business is wrong.", F_CARD, INK)
    return image


def scene_manual_hunt() -> Image.Image:
    image = base(3)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 215), "Someone now has to hunt\nfor every consequence.", F_TITLE, INK)
    text(draw, (64, 450), "Gmail cannot know which task, memo, deck, or decision this email owns.", F_BODY, MUTED)
    centers = ((340, 715, "Gmail", "M", GMAIL_RED), (760, 650, "Google Task", "T", TASKS_BLUE), (1130, 770, "Board memo", "D", BLUE), (1510, 620, "Investor plan", "S", AMBER))
    for x, y, label, code, color in centers:
        draw.ellipse((x - 55, y - 55, x + 55, y + 55), fill=SURFACE, outline=color, width=4)
        text(draw, (x, y), code, F_CARD, color, anchor="mm")
        text(draw, (x, y + 94), label, F_SMALL, INK, anchor="mm")
    for left, right in zip(centers, centers[1:]):
        draw.line((left[0] + 56, left[1], right[0] - 56, right[1]), fill=(87, 71, 60), width=3)
        text(draw, ((left[0] + right[0]) // 2, (left[1] + right[1]) // 2 - 28), "?", F_CARD, RED, anchor="mm")
    pill(draw, (64, 560), "manual search · silent omissions", RED)
    return image


def scene_meet_veritas() -> Image.Image:
    image = base(4)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 215), "Veritas repairs\nwhat the change owns.", F_TITLE, INK)
    text(draw, (64, 450), "A consequence agent between customer truth and operational action.", F_BODY, MUTED)
    y = 735
    xs = (180, 490, 800, 1110, 1420, 1740)
    gmail_icon(draw, (xs[0], y), 78)
    steps = (("01", "DETECT"), ("02", "TRACE"), ("03", "REPAIR"), ("04", "VERIFY"))
    for x, (number, label) in zip(xs[1:5], steps):
        rounded(draw, (x - 115, y - 72, x + 115, y + 72), 22, SURFACE, GREEN, 3)
        text(draw, (x - 80, y - 34), number, F_MICRO, GREEN)
        text(draw, (x, y + 8), label, F_CARD, INK, anchor="mm")
    tasks_icon(draw, (xs[5], y), 78)
    for left, right in zip(xs, xs[1:]):
        left_edge = left + (52 if left in (xs[0], xs[5]) else 115)
        right_edge = right - (52 if right in (xs[0], xs[5]) else 115)
        draw.line((left_edge, y, right_edge, y), fill=GREEN_DARK, width=4)
    pill(draw, (64, 560), "no prompt after the source change", GREEN)
    text(draw, (960, 900), "Authenticated email → exact ownership → guarded task update → independent re-read", F_SMALL, MUTED, anchor="mm")
    return image


def scene_authenticate() -> Image.Image:
    image = base(5)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 215), "First, Veritas proves\nwho said what.", F_TITLE, INK)
    text(draw, (64, 450), "The email becomes durable evidence before any task can change.", F_BODY, MUTED)
    gmail_message(draw, (60, 545, 930, 920), compact=True)
    rounded(draw, (990, 500, 1850, 930), 28, SURFACE, (46, 84, 66), 2)
    text(draw, (1040, 555), "AUTHENTICATED MESSAGE RECEIPT", F_KICKER, GREEN)
    rows = (
        ("01", "Sender", "24uec023@lnmiit.ac.in", "AUTHORIZED"),
        ("02", "Recipient", "company inbox", "MATCHED"),
        ("03", "Message", "msg:a93f2c7d", "SNAPSHOT"),
        ("04", "Intent", "decrease acquisition by 10%", "EXTRACTED"),
    )
    for index, (number, label, value, status) in enumerate(rows):
        y = 635 + index * 72
        rounded(draw, (1030, y - 26, 1810, y + 30), 12, SURFACE_2, (36, 67, 53))
        text(draw, (1052, y + 1), number, F_MICRO, GREEN, anchor="lm")
        text(draw, (1115, y + 1), label, F_SMALL, MUTED, anchor="lm")
        text(draw, (1260, y + 1), value, F_SMALL, INK, anchor="lm")
        text(draw, (1780, y + 1), status, F_MICRO, GREEN, anchor="rm")
    return image


def scene_trace() -> Image.Image:
    image = base(6)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 215), "Then, it follows\nthe registered route.", F_TITLE, INK)
    text(draw, (64, 450), "No keyword match. No guessed similarity. One manifest-bound path.", F_BODY, MUTED)
    pill(draw, (64, 565), "0 inferred paths", GREEN)
    pill(draw, (64, 625), "1 exact owned target", GREEN)
    rounded(draw, (760, 230, 1850, 910), 30, SURFACE, (43, 79, 62), 2)
    text(draw, (820, 290), "REGISTERED CONSEQUENCE MAP", F_KICKER, GREEN)
    nodes = (
        (930, 535, "EMAIL", "M", GMAIL_RED, "msg:a93f2c7d"),
        (1305, 535, "CLAIM", "C", AMBER, "acquisition spend"),
        (1680, 535, "GOOGLE TASK", "T", TASKS_BLUE, "task:acq-01"),
    )
    for x, y, label, code, color, detail in nodes:
        draw.ellipse((x - 60, y - 60, x + 60, y + 60), fill=SURFACE_2, outline=color, width=4)
        text(draw, (x, y), code, F_CARD, color, anchor="mm")
        text(draw, (x, y + 104), label, F_MICRO, color, anchor="mm")
        text(draw, (x, y + 138), detail, F_SMALL, INK, anchor="mm")
    draw.line((990, 535, 1245, 535), fill=GREEN_DARK, width=5)
    draw.line((1365, 535, 1620, 535), fill=GREEN_DARK, width=5)
    text(draw, (1118, 505), "SENDER + INTENT", F_MICRO, GREEN, anchor="mm")
    text(draw, (1492, 505), "EXACT TASK ID", F_MICRO, GREEN, anchor="mm")
    rounded(draw, (905, 775, 1705, 842), 14, (8, 38, 27), GREEN, 2)
    text(draw, (1305, 809), "ONLY THIS TASK IS AUTHORIZED TO CHANGE", F_KICKER, GREEN, anchor="mm")
    return image


def scene_repair() -> Image.Image:
    image = base(7)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 205), "The Google Task\nchanges in front of you.", F_TITLE, INK)
    text(draw, (64, 440), "Veritas edits the owned task and preserves everything the email did not change.", F_BODY, MUTED)
    rounded(draw, (65, 555, 815, 900), 26, PAPER, (154, 165, 158), 2)
    text(draw, (110, 610), "BEFORE", F_KICKER, RED)
    tasks_icon(draw, (745, 610), 46)
    task_card(draw, (105, 665, 775, 850), "Increase acquisition spend", "Increase the current acquisition budget.", stale=True)
    rounded(draw, (1105, 555, 1855, 900), 26, PAPER, TASKS_BLUE, 3)
    text(draw, (1150, 610), "AFTER · GOOGLE TASKS", F_KICKER, TASKS_BLUE)
    tasks_icon(draw, (1785, 610), 46)
    task_card(draw, (1145, 665, 1815, 850), "Reduce acquisition spend by 10%", "Customer revised the requested acquisition budget.", completed=True)
    draw.line((850, 730, 1070, 730), fill=GREEN, width=6)
    draw.polygon(((1070, 730), (1044, 715), (1044, 745)), fill=GREEN)
    pill(draw, (850, 660), "guarded write", GREEN)
    return image


def scene_prove() -> Image.Image:
    image = base(8)
    draw = ImageDraw.Draw(image)
    text(draw, (58, 210), "Finally, Veritas proves\nit really happened.", F_TITLE, INK)
    text(draw, (64, 445), "A separate read-only verifier reopens Gmail and Google Tasks.", F_BODY, MUTED)
    rounded(draw, (70, 540, 1160, 920), 28, SURFACE, (44, 80, 63), 2)
    text(draw, (125, 595), "LIVE AUDIT TIMELINE", F_KICKER, GREEN)
    events = (
        ("18:07:02", "Email received", "msg:a93f2c7d"),
        ("18:07:04", "Authorized sender matched", "policy:customer-route"),
        ("18:07:07", "Google Task revised", "revision 2 → 3"),
        ("18:07:09", "Task independently re-read", "content matched"),
    )
    draw.line((155, 650, 155, 860), fill=(45, 99, 75), width=4)
    for index, (stamp, label, detail) in enumerate(events):
        y = 665 + index * 64
        draw.ellipse((143, y - 12, 167, y + 12), fill=GREEN)
        text(draw, (200, y), stamp, F_MICRO, GREEN, anchor="lm")
        text(draw, (330, y), label, F_SMALL, INK, anchor="lm")
        text(draw, (1080, y), detail, F_MICRO, MUTED, anchor="rm")
    rounded(draw, (1210, 495, 1845, 930), 28, (8, 39, 28), GREEN, 3)
    pill(draw, (1270, 545), "certificate issued", GREEN)
    text(draw, (1270, 655), "EMAIL → TASK\nINTEGRITY\nCERTIFICATE", core.font(42, rounded=True), INK, spacing=2)
    draw.line((1270, 810, 1785, 810), fill=(57, 111, 85), width=2)
    text(draw, (1270, 850), "CERT-E2T-7A92", F_CARD, GREEN)
    text(draw, (1270, 892), "CONTENT-ADDRESSED · INDEPENDENTLY VERIFIED", F_MICRO, MUTED)
    return image


def scene_brand() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG_DEEP)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 72):
        draw.line((x, 0, x, HEIGHT), fill=(7, 22, 17), width=1)
    for y in range(0, HEIGHT, 72):
        draw.line((0, y, WIDTH, y), fill=(7, 22, 17), width=1)
    text(draw, (960, 175), "ONE NORMAL EMAIL.", F_KICKER, GREEN, anchor="mm")
    text(draw, (960, 305), "One exact task.\nFull proof.", core.font(92, rounded=True), INK, anchor="ma", spacing=0, align="center")
    gmail_icon(draw, (590, 650), 98)
    veritas_icon(draw, (960, 650), 106)
    tasks_icon(draw, (1330, 650), 98)
    draw.line((650, 650, 895, 650), fill=GREEN, width=5)
    draw.line((1015, 650, 1270, 650), fill=GREEN, width=5)
    draw.polygon(((895, 650), (870, 636), (870, 664)), fill=GREEN)
    draw.polygon(((1270, 650), (1245, 636), (1245, 664)), fill=GREEN)
    text(draw, (590, 748), "GMAIL SIGNAL", F_KICKER, GMAIL_RED, anchor="mm")
    text(draw, (960, 748), "VERITAS", F_KICKER, GREEN, anchor="mm")
    text(draw, (1330, 748), "GOOGLE TASK", F_KICKER, TASKS_BLUE, anchor="mm")
    text(draw, (960, 855), "The customer speaks normally. The business stays correct.", F_BODY, MUTED, anchor="mm")
    text(draw, (960, 1008), "ALL THINGS AGENTIC HACKATHON · 2026", F_MICRO, SOFT, anchor="mm")
    return image


BUILDERS = (
    scene_customer_change,
    scene_email_arrives,
    scene_task_stale,
    scene_manual_hunt,
    scene_meet_veritas,
    scene_authenticate,
    scene_trace,
    scene_repair,
    scene_prove,
    scene_brand,
)


PLANS: tuple[tuple[Reveal, ...], ...] = (
    (
        Reveal((38, 185, 1010, 585), 0.02, 0.22, -95, 0),
        Reveal((1040, 230, 1835, 710), 0.18, 0.30, 130, 0),
        Reveal((38, 630, 940, 825), 0.50, 0.22, -55, 30),
    ),
    (
        Reveal((38, 185, 780, 530), 0.02, 0.22, -90, 0),
        Reveal((785, 155, 1875, 935), 0.18, 0.36, 135, 0),
        Reveal((38, 580, 700, 800), 0.42, 0.28, -55, 25),
    ),
    (
        Reveal((38, 185, 1370, 535), 0.02, 0.22, -95, 0),
        Reveal((38, 590, 690, 830), 0.24, 0.22, -55, 20),
        Reveal((680, 530, 1270, 960), 0.30, 0.26, -80, 0),
        Reveal((1250, 530, 1880, 960), 0.50, 0.26, 80, 0),
    ),
    (
        Reveal((38, 180, 1450, 520), 0.02, 0.22, -95, 0),
        Reveal((38, 530, 530, 625), 0.24, 0.16, -55, 0),
        Reveal((250, 630, 435, 900), 0.28, 0.18, 0, 55),
        Reveal((670, 565, 850, 845), 0.40, 0.18, 0, 55),
        Reveal((1040, 680, 1225, 955), 0.52, 0.18, 0, 55),
        Reveal((1415, 525, 1610, 810), 0.64, 0.18, 0, 55),
    ),
    (
        Reveal((38, 180, 1250, 530), 0.02, 0.22, -95, 0),
        Reveal((38, 525, 560, 610), 0.24, 0.16, -55, 0),
        Reveal((120, 630, 1800, 840), 0.28, 0.42, 0, 65),
        Reveal((460, 850, 1460, 945), 0.66, 0.18, 0, 30),
    ),
    (
        Reveal((38, 180, 1120, 530), 0.02, 0.22, -95, 0),
        Reveal((35, 510, 965, 955), 0.25, 0.28, -85, 0),
        Reveal((955, 465, 1880, 960), 0.44, 0.30, 95, 0),
    ),
    (
        Reveal((38, 180, 1060, 540), 0.02, 0.22, -95, 0),
        Reveal((38, 530, 700, 705), 0.24, 0.20, -55, 20),
        Reveal((725, 195, 1885, 950), 0.26, 0.40, 110, 0),
    ),
    (
        Reveal((38, 170, 1500, 530), 0.02, 0.22, -95, 0),
        Reveal((35, 520, 845, 935), 0.27, 0.28, -90, 0),
        Reveal((820, 620, 1100, 810), 0.45, 0.20, 0, 30),
        Reveal((1070, 520, 1885, 935), 0.56, 0.28, 90, 0),
    ),
    (
        Reveal((38, 175, 1260, 525), 0.02, 0.22, -95, 0),
        Reveal((35, 505, 1200, 955), 0.27, 0.34, -85, 0),
        Reveal((1170, 460, 1880, 965), 0.56, 0.28, 90, 0),
    ),
    (
        Reveal((470, 125, 1450, 525), 0.03, 0.24, 0, -65),
        Reveal((500, 560, 1420, 800), 0.28, 0.34, 0, 55),
        Reveal((410, 800, 1510, 930), 0.62, 0.20, 0, 35),
        Reveal((650, 960, 1270, 1045), 0.76, 0.16, 0, 25),
    ),
)


def brand_base() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG_DEEP)
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 72):
        draw.line((x, 0, x, HEIGHT), fill=(7, 22, 17), width=1)
    for y in range(0, HEIGHT, 72):
        draw.line((0, y, WIDTH, y), fill=(7, 22, 17), width=1)
    return image


def scene_at(seconds: float) -> tuple[int, float]:
    for index, scene in enumerate(SCENES):
        if scene.start <= seconds < scene.end:
            return index, (seconds - scene.start) / (scene.end - scene.start)
    return len(SCENES) - 1, 1.0


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
        amount = local(progress, 0.20, 0.48)
        x = round(1790 - 510 * amount)
        draw.ellipse((x - 10, 370, x + 10, 390), fill=GMAIL_RED)
        if amount > 0.72:
            radius = round(16 + 28 * (amount - 0.72) / 0.28)
            draw.ellipse((1195 - radius, 380 - radius, 1195 + radius, 380 + radius), outline=GMAIL_RED, width=3)
    elif index == 1:
        amount = local(progress, 0.28, 0.46)
        if 0 < amount < 1:
            y = round(310 + 500 * amount)
            draw.line((1028, y, 1785, y), fill=(236, 109, 97), width=4)
    elif index == 2:
        amount = local(progress, 0.46, 0.28)
        point = progress_line(draw, (1218, 742), (1305, 742), amount, RED, width=7)
        draw.ellipse((point[0] - 8, point[1] - 8, point[0] + 8, point[1] + 8), fill=RED)
        if amount > 0.76:
            pulse = round(2 + 8 * (amount - 0.76) / 0.24)
            draw.rounded_rectangle((1318 - pulse, 705 - pulse, 1812 + pulse, 824 + pulse), radius=18, outline=RED, width=4)
    elif index == 3:
        nodes = ((340, 715), (760, 650), (1130, 770), (1510, 620))
        travel = local(progress, 0.26, 0.56) * (len(nodes) - 1)
        segment = min(len(nodes) - 2, int(travel))
        part = travel - segment
        point = progress_line(draw, nodes[segment], nodes[segment + 1], part, RED, width=5)
        draw.ellipse((point[0] - 10, point[1] - 10, point[0] + 10, point[1] + 10), fill=RED)
    elif index == 4:
        amount = local(progress, 0.30, 0.52)
        x = round(232 + 1456 * amount)
        draw.ellipse((x - 15, 720, x + 15, 750), fill=GREEN_PALE)
        draw.ellipse((x - 8, 727, x + 8, 743), fill=GREEN)
    elif index == 5:
        amount = local(progress, 0.42, 0.38)
        if 0 < amount < 1:
            y = round(605 + 270 * amount)
            draw.line((1030, y, 1810, y), fill=GREEN, width=4)
    elif index == 6:
        first = local(progress, 0.30, 0.24)
        second = local(progress, 0.52, 0.24)
        point = progress_line(draw, (990, 535), (1245, 535), first, GREEN, width=7)
        if 0 < first < 1:
            draw.ellipse((point[0] - 9, point[1] - 9, point[0] + 9, point[1] + 9), fill=GREEN_PALE)
        point = progress_line(draw, (1365, 535), (1620, 535), second, GREEN, width=7)
        if 0 < second < 1:
            draw.ellipse((point[0] - 9, point[1] - 9, point[0] + 9, point[1] + 9), fill=GREEN_PALE)
    elif index == 7:
        strike = local(progress, 0.28, 0.22)
        progress_line(draw, (175, 712), (610, 712), strike, RED, width=7)
        amount = local(progress, 0.43, 0.34)
        point = progress_line(draw, (850, 730), (1070, 730), amount, GREEN, width=8)
        if 0 < amount < 1:
            draw.ellipse((point[0] - 12, point[1] - 12, point[0] + 12, point[1] + 12), fill=GREEN_PALE)
        if amount > 0.74:
            pulse = round(4 + 10 * (amount - 0.74) / 0.26)
            draw.rounded_rectangle((1105 - pulse, 555 - pulse, 1855 + pulse, 900 + pulse), radius=28, outline=TASKS_BLUE, width=5)
    elif index == 8:
        amount = local(progress, 0.28, 0.48)
        y = round(650 + 210 * amount)
        draw.line((155, 650, 155, y), fill=GREEN_PALE, width=7)
        draw.ellipse((143, y - 12, 167, y + 12), fill=GREEN)
        if amount > 0.80:
            pulse = round(4 + 12 * (amount - 0.80) / 0.20)
            draw.rounded_rectangle((1210 - pulse, 495 - pulse, 1845 + pulse, 930 + pulse), radius=30, outline=GREEN, width=5)
    elif index == 9:
        first = local(progress, 0.30, 0.24)
        second = local(progress, 0.50, 0.24)
        progress_line(draw, (650, 650), (895, 650), first, GREEN_PALE, width=8)
        progress_line(draw, (1015, 650), (1270, 650), second, GREEN_PALE, width=8)
        pulse = local(progress, 0.08, 0.58)
        radius = round(90 + 150 * pulse)
        draw.ellipse((960 - radius, 650 - radius, 960 + radius, 650 + radius), outline=GREEN_DARK, width=3)


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


def compose(finals: list[Image.Image], backgrounds: list[Image.Image], patches, seconds: float) -> Image.Image:
    index, progress = scene_at(seconds)
    frame = animate(index, progress, finals[index], backgrounds[index], patches[index])
    scene = SCENES[index]
    if index == 0:
        frame = Image.blend(Image.new("RGB", frame.size, BG_DEEP), frame, ease(seconds / 1.1))
    elif seconds - scene.start < TRANSITION:
        frame = wipe(finals[index - 1], frame, (seconds - scene.start) / TRANSITION, reverse=index % 2 == 0)
    if DURATION - seconds < 1.2:
        frame = Image.blend(Image.new("RGB", frame.size, BG_DEEP), frame, ease((DURATION - seconds) / 1.2))
    return frame


def render(output: Path, music: Path, preview_frames: Path | None, *, start: float = 0.0, duration: float | None = None, stills_only: bool = False) -> None:
    finals = [builder() for builder in BUILDERS]
    backgrounds = [base(index) for index in range(len(SCENES) - 1)] + [brand_base()]
    patches = prepare_motion(finals, backgrounds)
    if preview_frames is not None:
        preview_frames.mkdir(parents=True, exist_ok=True)
        for index, final in enumerate(finals):
            final.save(preview_frames / f"email-task-{index + 1:02d}-{SCENES[index].name}.png")
    if stills_only:
        return

    clip_duration = duration if duration is not None else DURATION - start
    if start < 0 or clip_duration <= 0 or start + clip_duration > DURATION:
        raise ValueError("render window must remain inside the 72-second film")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s:v", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
        "-ss", str(start), "-i", str(music),
        "-map", "0:v:0", "-map", "1:a:0", "-t", str(clip_duration),
        "-af", "afade=t=in:st=0:d=0.8,afade=t=out:st=69:d=3,volume=0.88",
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
