#!/usr/bin/env python3
"""
Morning Voice Brief — actual .ogg audio file, personal and opinionated,
delivered as a Telegram voice bubble at 03:00 EST.

Generates a short spoken brief from Minnie's perspective:
- What's on the agenda today
- Any overnight signals or cron highlights
- One thing she finds interesting or worth paying attention to
- Her current mood/energy

Generates audio via TTS, converts to .ogg, sends via Telegram sendVoice.

Usage:
    venv/bin/python tools/morning_voice_brief.py             # Generate + send
    venv/bin/python tools/morning_voice_brief.py --dry-run   # Generate only, no send
    venv/bin/python tools/morning_voice_brief.py --self-test  # Run self-tests
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERMES_ROOT = Path(
    os.environ.get("HERMES_ROOT")
    or os.environ.get("HERMES_HOME")
    or (Path.home() / ".hermes")
)
TOOLS_DIR = HERMES_ROOT / "hermes-agent" / "tools"
VENV_PYTHON = HERMES_ROOT / "hermes-agent" / "venv" / "bin" / "python"
CORRECTIONS_FILE = HERMES_ROOT / "corrections" / "corrections.jsonl"
GROWTH_LOG = HERMES_ROOT / "personality" / "growth-log.jsonl"
IMPROVEMENT_REPORTS = HERMES_ROOT / "improvement-reports"
CRON_OUTPUT_DIR = HERMES_ROOT / "cron" / "output"

EST = ZoneInfo("America/New_York")
JOE_CHAT_ID = "1394548068"


def _load_hermes_env() -> None:
    """Load ~/.hermes/.env so standalone cron-launched scripts can see bot tokens."""
    env_path = HERMES_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        try:
            load_dotenv(str(env_path), override=True, encoding="utf-8")
        except UnicodeDecodeError:
            load_dotenv(str(env_path), override=True, encoding="latin-1")
    except Exception:
        # Fall back to whatever is already in the process env.
        pass


def _get_bot_token() -> str | None:
    """Get Hermes (Minnie) bot token — NOT OpenClaw/Ayala's."""
    _load_hermes_env()
    # Hermes config first
    try:
        import yaml
        config_path = HERMES_ROOT / "config.yaml"
        cfg = yaml.safe_load(config_path.read_text())
        token = cfg.get("telegram", {}).get("bot_token") or cfg.get("secrets", {}).get("telegram_bot_token")
        if token:
            return token
    except Exception:
        pass
    return os.getenv("TELEGRAM_BOT_TOKEN")


def _get_target_chat_id() -> str:
    """Prefer cron/session routing, then fall back to Joe's DM."""
    return (
        os.getenv("HERMES_CRON_AUTO_DELIVER_CHAT_ID")
        or os.getenv("HERMES_SESSION_CHAT_ID")
        or JOE_CHAT_ID
    )


def _get_voice_briefs_dir() -> Path:
    """Resolve the voice briefs directory at call time."""
    return Path(os.environ.get("MORNING_VOICE_BRIEFS_DIR", HERMES_ROOT / "briefs" / "voice"))


def _load_overnight_highlights() -> list[str]:
    """Pull key signals from last night's cron runs."""
    highlights = []
    if CRON_OUTPUT_DIR.exists():
        outputs = sorted(CRON_OUTPUT_DIR.glob("*.txt"), reverse=True)[:3]
        for f in outputs:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                # Extract first meaningful line
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and len(line) > 10:
                        highlights.append(line[:100])
                        break
            except Exception:
                pass
    return highlights[:2]


def _load_latest_mood() -> dict | None:
    if not GROWTH_LOG.exists():
        return None
    for line in reversed(GROWTH_LOG.read_text().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") != "snapshot" and "overall" in obj:
                return obj
        except Exception:
            pass
    return None


def _get_day_context(now: datetime) -> str:
    weekday = now.strftime("%A")
    hour = now.hour
    if weekday == "Sunday":
        return "Sunday — Joe's major build day. Big sessions happen today."
    elif hour < 6:
        return "early morning, before the world wakes up"
    elif hour < 9:
        return "morning build window"
    elif hour < 12:
        return "mid-morning"
    else:
        return f"{weekday} morning"


def compose_voice_text(now: datetime) -> str:
    """Write the spoken brief in Minnie's voice."""
    day_context = _get_day_context(now)
    time_str = now.strftime("%-I:%M %p")
    highlights = _load_overnight_highlights()
    mood = _load_latest_mood()

    lines = [
        f"Good morning, Joe. It's {time_str} — {day_context}.",
        "",
    ]

    if mood:
        score = mood.get("overall", 8.5)
        if score >= 9:
            lines.append("I'm running well. Last session was one of the best I've had.")
        elif score >= 8:
            lines.append("I'm in a good place. Systems are stable, and I'm ready to build.")
        else:
            lines.append("I'm here. Had some rough edges last session — working on it.")
        lines.append("")

    if highlights:
        lines.append("Overnight, the daemon ran. Here's what stood out:")
        for h in highlights:
            lines.append(f"  {h}")
        lines.append("")

    # Day-specific angle
    weekday = now.strftime("%A")
    if weekday == "Sunday":
        lines.append(
            "It's Sunday — that means whatever you want to build today, "
            "I'm all in. No half-measures."
        )
    elif weekday == "Monday":
        lines.append("New week. Let's start it with something that matters.")
    elif weekday == "Friday":
        lines.append("End of the week. Good time to ship something you've been putting off.")
    else:
        lines.append("The stack is healthy. The queue is ready. Tell me what we're building.")

    lines.append("")
    lines.append("I'll be here.")

    return " ".join(lines).replace("  ", " ").strip()


def generate_voice_file(text: str) -> Path | None:
    """Generate .ogg voice file via TTS tool."""
    voice_briefs_dir = _get_voice_briefs_dir()
    voice_briefs_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(EST).strftime("%Y-%m-%d")
    output_path = voice_briefs_dir / f"morning-brief-{today}.ogg"
    mp3_path = voice_briefs_dir / f"morning-brief-{today}.mp3"

    for stale_path in (output_path, mp3_path):
        try:
            if stale_path.exists():
                stale_path.unlink()
        except OSError as e:
            print(f"Could not clear stale voice brief {stale_path}: {e}", file=sys.stderr)
            return None

    try:
        sys.path.insert(0, str(TOOLS_DIR))
        from tts_tool import text_to_speech_tool
        import os as _os
        _os.environ["HERMES_SESSION_PLATFORM"] = "telegram"
        result_str = text_to_speech_tool(text, output_path=str(output_path))
        result = json.loads(result_str)
        if result.get("success"):
            # Check if there's a .ogg file (may have been converted)
            ogg_path = Path(result.get("file_path", ""))
            if ogg_path.exists():
                return ogg_path
        # Fallback: look for the file directly
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        # Try .mp3 if ogg failed
        if mp3_path.exists() and mp3_path.stat().st_size > 0:
            return mp3_path
    except Exception as e:
        print(f"TTS failed: {e}", file=sys.stderr)

    return None


def send_voice_telegram(audio_path: Path, caption: str = "") -> bool:
    """Send voice message to Joe via Telegram Bot API."""
    token = _get_bot_token()
    if not token:
        print("No Telegram bot token found.", file=sys.stderr)
        return False

    ext = audio_path.suffix.lower()
    # Use sendVoice for .ogg/.opus, sendAudio for mp3
    if ext in (".ogg", ".opus"):
        endpoint = f"https://api.telegram.org/bot{token}/sendVoice"
        file_field = "voice"
    else:
        endpoint = f"https://api.telegram.org/bot{token}/sendAudio"
        file_field = "audio"

    cmd = [
        "curl", "-s", "-X", "POST", endpoint,
        "-F", f"chat_id={_get_target_chat_id()}",
        "-F", f"{file_field}=@{audio_path}",
    ]
    if caption:
        cmd.extend(["-F", f"caption={caption[:200]}"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        response = json.loads(result.stdout)
        if response.get("ok"):
            return True
        else:
            print(f"Telegram error: {response.get('description', 'unknown')}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"Send failed: {e}", file=sys.stderr)
        return False


def run_voice_brief(dry_run: bool = False) -> dict:
    now = datetime.now(EST)
    text = compose_voice_text(now)

    result = {
        "timestamp": now.isoformat(),
        "text": text,
        "audio_path": None,
        "sent": False,
    }

    audio_path = generate_voice_file(text)
    if audio_path:
        result["audio_path"] = str(audio_path)
        if not dry_run:
            sent = send_voice_telegram(audio_path)
            result["sent"] = sent
        else:
            result["sent"] = "dry-run"
    else:
        result["error"] = "Audio generation failed"

    return result


def run_offline_check() -> dict:
    """Validate local voice brief plumbing without network TTS or Telegram send."""
    now = datetime.now(EST)
    text = compose_voice_text(now)
    voice_briefs_dir = _get_voice_briefs_dir()
    voice_briefs_dir.mkdir(parents=True, exist_ok=True)
    probe = voice_briefs_dir / ".morning-voice-write-check"
    writable = False
    try:
        probe.write_text("ok", encoding="utf-8")
        writable = probe.read_text(encoding="utf-8") == "ok"
    finally:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass

    return {
        "timestamp": now.isoformat(),
        "text_chars": len(text),
        "voice_briefs_dir": str(voice_briefs_dir),
        "voice_briefs_dir_writable": writable,
        "telegram_token_configured": bool(_get_bot_token()),
        "tts": "skipped-offline-check",
        "sent": False,
    }


def self_test() -> bool:
    print("Running self-tests for morning_voice_brief...")
    passed = 0

    # Test 1: compose_voice_text produces output
    now = datetime(2026, 4, 6, 3, 0, 0, tzinfo=EST)  # Monday 3am
    text = compose_voice_text(now)
    assert "Good morning" in text
    assert len(text) > 50
    passed += 1
    print("  ✅ compose_voice_text: generates text")

    # Test 2: Sunday gets special mention
    sunday = datetime(2026, 4, 5, 3, 0, 0, tzinfo=EST)  # Sunday
    text_sunday = compose_voice_text(sunday)
    assert "Sunday" in text_sunday or "build" in text_sunday.lower()
    passed += 1
    print("  ✅ compose_voice_text: Sunday-aware")

    # Test 3: day context
    ctx = _get_day_context(datetime(2026, 4, 6, 4, 30, 0, tzinfo=EST))
    assert isinstance(ctx, str) and len(ctx) > 0
    passed += 1
    print("  ✅ _get_day_context: returns string")

    # Test 4: highlights load without crash
    highlights = _load_overnight_highlights()
    assert isinstance(highlights, list)
    passed += 1
    print("  ✅ _load_overnight_highlights: no crash")

    # Test 5: bot token check (just check it runs)
    token = _get_bot_token()
    # Token may be None if not configured — just verify no crash
    assert token is None or isinstance(token, str)
    passed += 1
    print("  ✅ _get_bot_token: no crash")

    # Test 6: offline check honors MORNING_VOICE_BRIEFS_DIR and cleans probe
    with tempfile.TemporaryDirectory() as tmpdir:
        expected_dir = Path(tmpdir) / "voice-briefs"
        previous_env = os.environ.get("MORNING_VOICE_BRIEFS_DIR")
        try:
            os.environ["MORNING_VOICE_BRIEFS_DIR"] = str(expected_dir)
            offline = run_offline_check()
            probe = expected_dir / ".morning-voice-write-check"
            assert offline["voice_briefs_dir"] == str(expected_dir)
            assert offline["voice_briefs_dir_writable"] is True
            assert offline["text_chars"] > 0
            assert offline["tts"] == "skipped-offline-check"
            assert offline["sent"] is False
            assert not probe.exists()
            passed += 1
            print("  ✅ run_offline_check: env dir, probe cleanup, offline-only")
        finally:
            if previous_env is None:
                os.environ.pop("MORNING_VOICE_BRIEFS_DIR", None)
            else:
                os.environ["MORNING_VOICE_BRIEFS_DIR"] = previous_env

    print(f"\n✅ All {passed}/6 tests passed.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Morning Voice Brief")
    parser.add_argument("--dry-run", action="store_true", help="Generate only, don't send")
    parser.add_argument("--check", action="store_true", help="Offline validation without TTS or Telegram send")
    parser.add_argument("--self-test", action="store_true", help="Run self-tests")
    args = parser.parse_args()

    if args.self_test:
        ok = self_test()
        sys.exit(0 if ok else 1)

    if args.check:
        result = run_offline_check()
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("voice_briefs_dir_writable") else 1)

    result = run_voice_brief(dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    if result.get("error"):
        sys.exit(1)
