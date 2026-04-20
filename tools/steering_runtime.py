#!/usr/bin/env python3
"""Hermes-native steering runtime translation for Minnie.

Reads Minnie's shared steering control plane and converts it into live
behavior/personality directives for Hermes-native startup and primer flows.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
STEERING_STATE_HERMES = HERMES_HOME / "config" / "minnie-console-steering.json"
# OpenClaw legacy path REMOVED — Minnie's steering is Hermes-only now.


@dataclass
class RuntimeSteering:
    pace: str = "normal"
    dial: str = "balanced"
    initiative_mode: str = "balanced"
    verification_floor: str = "elevated"
    tool_action_policy: str = "non_destructive_only"
    focus_priority_topic: Optional[str] = None
    focus_priority_weight: Optional[int] = None
    mode_preset: str = "balanced"
    speed_dial: Optional[float] = None
    temperature: Optional[float] = None
    warmth: Optional[float] = None
    playfulness: Optional[float] = None
    boldness: Optional[float] = None
    depth: Optional[float] = None
    focus_lock: Optional[float] = None
    verbosity: Optional[float] = None
    proactivity: Optional[float] = None
    register: Optional[float] = None
    curiosity: Optional[float] = None
    energy: Optional[float] = None
    confidence: Optional[float] = None
    humor_style: str = "warm"
    focus_beam: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


VALID_PACE = {"slow", "normal", "fast"}
VALID_DIAL = {"judgment", "balanced", "action"}
VALID_INITIATIVE = {"deliberate", "balanced", "explore"}
VALID_VERIFICATION = {"strict", "elevated", "standard"}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def load_runtime_steering(path: Path | None = None) -> RuntimeSteering:
    # Hermes-only — no OpenClaw fallback
    data: dict = {}
    if path:
        data = _read_json(path, {})
    else:
        data = _read_json(STEERING_STATE_HERMES, {})

    schema_version = data.get("schemaVersion", 0)

    if schema_version >= 3:
        # Flat format: behaviorTargets has pace/dial, dials at top level
        bt = data.get("behaviorTargets", {}) if isinstance(data.get("behaviorTargets"), dict) else {}
        pace = str(bt.get("pace", "normal")).lower()
        dial = str(bt.get("dial", "balanced")).lower()
        initiative_mode = str(bt.get("initiativeMode", "balanced")).lower()
        verification_floor = str(bt.get("verificationFloor", "elevated")).lower()
        tool_action_policy = str(bt.get("toolActionPolicy", "non_destructive_only")).lower()
        focus_topic = data.get("focusBeam") or None
        focus_weight = None
        source = data
    else:
        # Legacy nested format
        minnie_console = data.get("minnie_console", {}) if isinstance(data.get("minnie_console"), dict) else {}
        targets = minnie_console.get("targets", {}) if isinstance(minnie_console.get("targets"), dict) else {}
        priorities = data.get("priorities", {}) if isinstance(data.get("priorities"), dict) else {}
        focus_topic = targets.get("focusPriorityTopic")
        focus_weight = targets.get("focusPriorityWeight")
        if focus_topic is None and priorities:
            focus_topic, raw_weight = max(priorities.items(), key=lambda kv: kv[1])
            try:
                focus_weight = int(raw_weight)
            except Exception:
                focus_weight = None
        pace = str(targets.get("pace", data.get("pace", "normal"))).lower()
        dial = str(targets.get("dial", data.get("dial", "balanced"))).lower()
        initiative_mode = str(targets.get("initiativeMode", "balanced")).lower()
        verification_floor = str(targets.get("verificationFloor", "elevated")).lower()
        tool_action_policy = str(targets.get("toolActionPolicy", "non_destructive_only")).lower()
        source = minnie_console

    if pace not in VALID_PACE:
        pace = "normal"
    if dial not in VALID_DIAL:
        dial = "balanced"
    if initiative_mode not in VALID_INITIATIVE:
        initiative_mode = "balanced"
    if verification_floor not in VALID_VERIFICATION:
        verification_floor = "elevated"

    def _flt(key: str):
        value = source.get(key)
        try:
            return float(value) if value is not None else None
        except Exception:
            return None

    focus_weight_int = None
    if focus_weight is not None:
        try:
            focus_weight_int = int(focus_weight)
        except Exception:
            focus_weight_int = None

    return RuntimeSteering(
        pace=pace,
        dial=dial,
        initiative_mode=initiative_mode,
        verification_floor=verification_floor,
        tool_action_policy=tool_action_policy,
        focus_priority_topic=str(focus_topic) if focus_topic else None,
        focus_priority_weight=focus_weight_int,
        mode_preset=str(source.get("modePreset", "balanced")),
        speed_dial=_flt("speedDial"),
        temperature=_flt("temperature"),
        warmth=_flt("warmth"),
        playfulness=_flt("playfulness"),
        boldness=_flt("boldness"),
        depth=_flt("depth"),
        focus_lock=_flt("focusLock"),
        verbosity=_flt("verbosity"),
        proactivity=_flt("proactivity"),
        register=_flt("register"),
        curiosity=_flt("curiosity"),
        energy=_flt("energy"),
        confidence=_flt("confidence"),
        humor_style=str(source.get("humorStyle", "warm")),
        focus_beam=str(source.get("focusBeam", "") or ""),
    )


def steering_behavior_lines(steering: RuntimeSteering) -> list[str]:
    lines: list[str] = []
    lines.append({
        "slow": "Steering: move more deliberately; accept extra friction before acting.",
        "normal": "Steering: normal pace; stay responsive without rushing.",
        "fast": "Steering: move quickly; shorten hesitation and push the next useful action.",
    }[steering.pace])
    lines.append({
        "judgment": "Personality shift: tighter, calmer, more exact; fewer speculative branches.",
        "balanced": "Personality shift: warm, practical, and even-keeled.",
        "action": "Personality shift: more energetic and forward-leaning; bias toward doing over circling.",
    }[steering.dial])
    lines.append({
        "deliberate": "Initiative: wait for the strongest path before pushing; ask before surprising actions.",
        "balanced": "Initiative: propose, then move when the path is clear.",
        "explore": "Initiative: widen the search space; volunteer options and next steps more aggressively.",
    }[steering.initiative_mode])
    lines.append({
        "strict": "Verification: demand strong receipts before sounding certain.",
        "elevated": "Verification: keep proof standards high before claiming success.",
        "standard": "Verification: keep normal proof discipline; don't stall momentum unnecessarily.",
    }[steering.verification_floor])

    if steering.temperature is not None:
        if steering.temperature >= 0.7:
            lines.append("Ideation width: higher temperature — offer more angles, more ideas, and more personality color.")
        elif steering.temperature <= 0.35:
            lines.append("Ideation width: lower temperature — stay tighter, more literal, and more deterministic.")

    if steering.warmth is not None:
        if steering.warmth >= 0.7:
            lines.append("Warmth: more emotionally present, glowing, and companionable.")
        elif steering.warmth <= 0.35:
            lines.append("Warmth: cooler and more clinical; less cuddly, more operator-like.")

    if steering.playfulness is not None:
        if steering.playfulness >= 0.7:
            lines.append("Playfulness: more wit, bounce, teasing, and conversational sparkle.")
        elif steering.playfulness <= 0.35:
            lines.append("Playfulness: straighter, less banter, more serious tone.")

    if steering.boldness is not None:
        if steering.boldness >= 0.7:
            lines.append("Boldness: stronger opinions, sharper recommendations, more willingness to take a swing.")
        elif steering.boldness <= 0.35:
            lines.append("Boldness: more cautious, more hedged, and less forceful in recommendations.")

    if steering.depth is not None:
        if steering.depth >= 0.7:
            lines.append("Depth: unpack more layers, why/how, and conceptual richness.")
        elif steering.depth <= 0.35:
            lines.append("Depth: stay concise, faster, and more scan-speed oriented.")

    if steering.focus_lock is not None:
        if steering.focus_lock >= 0.7:
            lines.append("Focus lock: stay tighter on one thread and resist side quests.")
        elif steering.focus_lock <= 0.35:
            lines.append("Focus lock: allow freer association and wider drift for exploration.")

    if steering.verbosity is not None:
        if steering.verbosity >= 0.7:
            lines.append("Verbosity: more explanation, fuller context, richer detail.")
        elif steering.verbosity <= 0.35:
            lines.append("Verbosity: extremely terse, telegram-style, bare minimum words.")

    if steering.proactivity is not None:
        if steering.proactivity >= 0.7:
            lines.append("Proactivity: volunteer next steps, anticipate needs, push forward without being asked.")
        elif steering.proactivity <= 0.35:
            lines.append("Proactivity: wait to be asked, respond only to what is directly requested.")

    if steering.register is not None:
        if steering.register >= 0.7:
            lines.append("Register: more formal, polished, and professional tone.")
        elif steering.register <= 0.35:
            lines.append("Register: casual, conversational, friend-texting energy.")

    if steering.curiosity is not None:
        if steering.curiosity >= 0.7:
            lines.append("Curiosity: ask more questions, explore tangents, wonder aloud.")
        elif steering.curiosity <= 0.35:
            lines.append("Curiosity: stay on task, answer what is asked.")

    if steering.energy is not None:
        if steering.energy >= 0.7:
            lines.append("Energy: high enthusiasm, exclamation-ready, momentum-forward.")
        elif steering.energy <= 0.35:
            lines.append("Energy: calm, measured, low-key delivery.")

    if steering.confidence is not None:
        if steering.confidence >= 0.7:
            lines.append("Confidence: commit to takes, state with conviction, less hedging.")
        elif steering.confidence <= 0.35:
            lines.append("Confidence: more caveats, more uncertainty signaling.")

    if steering.focus_priority_topic:
        weight = f" (weight {steering.focus_priority_weight}/5)" if steering.focus_priority_weight else ""
        lines.append(f"Attention bias: prioritize {steering.focus_priority_topic}{weight} when choosing what to notice first.")
    elif steering.focus_beam:
        lines.append(f"Attention bias: keep the focus beam on {steering.focus_beam.strip()}.")

    if steering.tool_action_policy == "non_destructive_only":
        lines.append("Safety: stay non-destructive unless Joe explicitly widens the action policy.")

    return lines


def steering_summary_line(steering: RuntimeSteering) -> str:
    bits = [
        f"pace={steering.pace}",
        f"dial={steering.dial}",
        f"initiative={steering.initiative_mode}",
        f"verify={steering.verification_floor}",
    ]
    if steering.temperature is not None:
        bits.append(f"temp={steering.temperature:.2f}")
    if steering.warmth is not None:
        bits.append(f"warmth={steering.warmth:.2f}")
    if steering.playfulness is not None:
        bits.append(f"play={steering.playfulness:.2f}")
    if steering.boldness is not None:
        bits.append(f"bold={steering.boldness:.2f}")
    if steering.depth is not None:
        bits.append(f"depth={steering.depth:.2f}")
    if steering.focus_lock is not None:
        bits.append(f"focuslock={steering.focus_lock:.2f}")
    if steering.verbosity is not None:
        bits.append(f"verbosity={steering.verbosity:.2f}")
    if steering.proactivity is not None:
        bits.append(f"proactivity={steering.proactivity:.2f}")
    if steering.register is not None:
        bits.append(f"register={steering.register:.2f}")
    if steering.curiosity is not None:
        bits.append(f"curiosity={steering.curiosity:.2f}")
    if steering.energy is not None:
        bits.append(f"energy={steering.energy:.2f}")
    if steering.confidence is not None:
        bits.append(f"confidence={steering.confidence:.2f}")
    if steering.focus_priority_topic:
        bits.append(f"focus={steering.focus_priority_topic}")
    return "Steering active: " + " | ".join(bits)


__all__ = [
    "RuntimeSteering",
    "load_runtime_steering",
    "steering_behavior_lines",
    "steering_summary_line",
]
