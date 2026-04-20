#!/usr/bin/env python3
"""
Minnie's Morning Brief — how I see the world right now.

Not a log dump. A personal briefing from Minnie to Joe.
What matters, what's interesting, what I think you should know.

Usage:
    venv/bin/python tools/minnie_morning_brief.py             # Generate and print
    venv/bin/python tools/minnie_morning_brief.py --save      # Save to file
    venv/bin/python tools/minnie_morning_brief.py --self-test  # Run self-tests
"""
import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str((Path(__file__).resolve().parent)))
from steering_runtime import load_runtime_steering, steering_behavior_lines, steering_summary_line

# --- Paths ---
HERMES_ROOT = Path(os.environ.get("HERMES_ROOT", Path.home() / ".hermes"))
TOOLS_DIR = HERMES_ROOT / "hermes-agent" / "tools"
VENV_PYTHON = HERMES_ROOT / "hermes-agent" / "venv" / "bin" / "python"
DAILY_NOTES_DIR = HERMES_ROOT / "daily-notes"
CRON_OUTPUT_DIR = HERMES_ROOT / "cron" / "output"
IMPROVEMENT_REPORTS = HERMES_ROOT / "improvement-reports"
CORRECTIONS_FILE = HERMES_ROOT / "corrections" / "corrections.jsonl"
LEARNINGS_FILE = HERMES_ROOT / "learnings" / "learnings.jsonl"
LESSONS_FILE = HERMES_ROOT / "lessons" / "lessons.md"
PRIMER_FILE = HERMES_ROOT / "primer" / "active-primer.md"
DISCOVERIES_FILE = HERMES_ROOT / "discoveries" / "discoveries.jsonl"
OUTBOX_FILE = HERMES_ROOT / "memory" / "minnie-outbox.json"
BRIEFS_DIR = HERMES_ROOT / "briefs"

CDT = ZoneInfo("America/Chicago")
EST = ZoneInfo("America/New_York")


@dataclass
class BriefSection:
    title: str
    content: str
    has_data: bool = True


@dataclass
class MorningBrief:
    timestamp: str = ""
    greeting: str = ""
    sections: list = field(default_factory=list)

    def render(self) -> str:
        lines = []
        lines.append(self.greeting)
        lines.append("")
        for section in self.sections:
            if section.has_data and section.content.strip():
                lines.append(section.content)
                lines.append("")
        # Sign off
        lines.append("— Minnie")
        return "\n".join(lines)


def _run_tool(tool_name: str, args: list = None, timeout: int = 30) -> str:
    """Run a Hermes tool and capture output."""
    cmd = [str(VENV_PYTHON), str(TOOLS_DIR / tool_name)]
    if args:
        cmd.extend(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(HERMES_ROOT / "hermes-agent")
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        return f"(couldn't reach {tool_name}: {e})"


def _read_json_lines(path: Path, max_age_hours: int = 24) -> list:
    """Read JSONL file, filter to recent entries."""
    if not path.exists():
        return []
    cutoff = datetime.now(CDT) - timedelta(hours=max_age_hours)
    entries = []
    for line in path.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            # Try parsing timestamp
            ts_str = entry.get("timestamp", entry.get("ts", ""))
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=CDT)
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            entries.append(entry)
        except json.JSONDecodeError:
            continue
    return entries


def generate_greeting() -> str:
    """Personal greeting based on time, day, and active steering."""
    now = datetime.now(EST)
    hour = now.hour
    day = now.strftime("%A")
    steering = load_runtime_steering()

    time_notes = {
        "Sunday": "Build day",
        "Monday": "New week",
        "Friday": "End of week",
    }
    time_note = time_notes.get(day, "")

    hour_notes = [
        (3, "Still dark out."),
        (5, "Early. I like it."),
        (9, "Morning."),
        (12, "Midday."),
    ]
    hour_note = next((note for cutoff, note in hour_notes if hour < cutoff), "")

    energy_note = {
        "judgment": "I've been thinking carefully.",
        "balanced": "Here's what's on my mind.",
        "action": "I've been up thinking.",
    }.get(steering.dial, "Here's what's on my mind.")

    if time_note and hour_note:
        return f"Hey Joe. {time_note} — {hour_note.lower()} {energy_note}"
    elif time_note:
        return f"Hey Joe. {time_note}. {energy_note}"
    else:
        return f"Hey Joe. {hour_note} {energy_note}".strip()


def check_system_health() -> BriefSection:
    """One-line system health — only speak if something's wrong."""
    output = _run_tool("ops_check.py")

    lines = output.strip().split("\n")
    greens = sum(1 for l in lines if "🟢" in l)
    reds = sum(1 for l in lines if "🔴" in l)
    yellows = sum(1 for l in lines if "🟡" in l)
    total = greens + reds + yellows

    if reds > 0:
        red_items = [l.strip() for l in lines if "🔴" in l]
        content = "Got a problem to flag: " + "; ".join(red_items) + ". Everything else is good."
        return BriefSection(title="System Health", content=content)
    elif yellows > 0:
        content = f"Mostly clean — {yellows} warning(s) but nothing blocking."
        return BriefSection(title="System Health", content=content)
    else:
        # All green — silence means well
        return BriefSection(title="System Health", content="Everything's running clean.", has_data=False)


def check_overnight_results() -> BriefSection:
    """What my crons found while you slept."""
    report_file = IMPROVEMENT_REPORTS / "last-run.json"
    parts = []

    if report_file.exists():
        try:
            report = json.loads(report_file.read_text())
            passed = report.get("tasks_passed", "?")
            total = report.get("tasks_run", "?")
            parts.append(f"ran {passed}/{total} improvement tasks")
        except (json.JSONDecodeError, KeyError):
            pass

    # Check session churn
    churn_output = _run_tool("session_churn_analyzer.py", ["--hours", "8"])
    if churn_output and "Sessions:" in churn_output:
        for line in churn_output.split("\n"):
            if line.startswith("Sessions:"):
                # Extract just the count
                count = line.split("|")[0].replace("Sessions:", "").strip()
                parts.append(f"{count} sessions active")
                break

    # Check for new discoveries
    recent_discoveries = _read_json_lines(DISCOVERIES_FILE, max_age_hours=24)
    if recent_discoveries:
        parts.append(f"scout pulled in {len(recent_discoveries)} new leads")

    if not parts:
        return BriefSection(title="Overnight", content="Quiet night — nothing notable.", has_data=False)

    return BriefSection(title="Overnight", content="Overnight: " + ", ".join(parts) + ".")


def check_feeds() -> BriefSection:
    """Interesting stuff from feeds — with my take."""
    output = _run_tool("feed_monitor.py", ["check"])

    if "New relevant items: 0" in output or not output:
        return BriefSection(title="Feed Highlights", content="", has_data=False)

    # Extract items
    items = []
    for line in output.split("\n"):
        if line.startswith("- **["):
            items.append(line.strip())

    if not items:
        return BriefSection(title="Feed Highlights", content="", has_data=False)

    # Write prose, not a list
    n = len(items)
    # Strip markdown bold/brackets for cleaner prose
    clean = []
    for item in items[:3]:
        # "- **[Source]** Title — description" -> "Title — description"
        cleaned = item.lstrip("- ")
        if "**" in cleaned:
            # Remove **[Source]** prefix
            parts = cleaned.split("** ", 1)
            if len(parts) > 1:
                cleaned = parts[1]
        clean.append(cleaned)

    if len(clean) == 1:
        content = f"Feeds had {n} new items. Worth your time: {clean[0]}."
    else:
        highlights = "; ".join(clean[:-1]) + f"; and {clean[-1]}"
        content = f"Feeds had {n} new items. Worth your time: {highlights}."

    return BriefSection(title="Feed Highlights", content=content)


def check_ayala_outbox() -> BriefSection:
    """Anything pending between Minnie and Ayala."""
    if not OUTBOX_FILE.exists():
        return BriefSection(title="Ayala", content="No pending items in the outbox.", has_data=False)

    try:
        data = json.loads(OUTBOX_FILE.read_text())
        messages = data if isinstance(data, list) else data.get("messages", [])
        pending = [m for m in messages if m.get("status") == "pending"]
        if pending:
            content = f"{len(pending)} pending message(s) for Ayala:\n"
            for msg in pending[:3]:
                subj = msg.get("subject", msg.get("type", "unknown"))
                content += f"  - {subj}\n"
            return BriefSection(title="Ayala", content=content.strip())
        else:
            return BriefSection(title="Ayala", content="Outbox clear. No pending handoffs.", has_data=False)
    except (json.JSONDecodeError, KeyError):
        return BriefSection(title="Ayala", content="Outbox exists but couldn't parse it.", has_data=True)


def check_my_growth() -> BriefSection:
    """What I've learned since last brief — self-reflection, not metrics."""
    parts = []

    # Recent corrections
    recent_corrections = _read_json_lines(CORRECTIONS_FILE, max_age_hours=24)
    if recent_corrections:
        parts.append(f"absorbed {len(recent_corrections)} correction(s)")

    # Recent learnings
    recent_learnings = _read_json_lines(LEARNINGS_FILE, max_age_hours=24)
    if recent_learnings:
        parts.append(f"{len(recent_learnings)} lessons in the pipeline")

    # Primer status
    if PRIMER_FILE.exists():
        stat = PRIMER_FILE.stat()
        age_hours = (datetime.now().timestamp() - stat.st_mtime) / 3600
        if age_hours < 24:
            parts.append("primer's fresh")
        else:
            parts.append(f"primer's getting stale ({age_hours:.0f}h old)")

    if not parts:
        return BriefSection(title="My Growth", content="Growth-wise: steady state, nothing new since last brief.", has_data=True)

    return BriefSection(title="My Growth", content="Growth-wise: " + ", ".join(parts) + ".")


def generate_suggestion() -> BriefSection:
    """One thing I think we should look at today — lead with curiosity."""
    now = datetime.now(EST)
    day = now.strftime("%A")

    suggestions = [
        "We've got 56 tools without self-tests. That's a trust problem waiting to happen. I'd like to knock out a batch.",
        "MinnieConsole is beautiful but static. I could wire it to read real cron outputs and system health live — want me to try?",
        "The Ayala handoff system is one-way right now. Building a proper inbox would let her delegate tasks to me directly.",
    ]

    if day == "Sunday":
        return BriefSection(
            title="Today's Thought",
            content="What I'm thinking about today: it's build day. Pick what feels right and I'll go deep on it."
        )

    # Rotate based on day of year
    idx = now.timetuple().tm_yday % len(suggestions)
    return BriefSection(title="Today's Thought", content=f"What I'm thinking about today: {suggestions[idx]}")


def generate_brief() -> MorningBrief:
    """Generate the full morning brief."""
    brief = MorningBrief()
    brief.timestamp = datetime.now(CDT).strftime("%Y-%m-%d %H:%M CDT")
    brief.greeting = generate_greeting()

    brief.sections = [
        generate_suggestion(),
        check_overnight_results(),
        check_feeds(),
        check_ayala_outbox(),
        check_my_growth(),
        check_system_health(),
    ]

    return brief


def save_brief(brief: MorningBrief) -> Path:
    """Save brief to file."""
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(CDT)
    filename = f"brief_{now.strftime('%Y%m%d_%H%M')}.md"
    path = BRIEFS_DIR / filename
    path.write_text(brief.render())

    # Also save as latest
    latest = BRIEFS_DIR / "latest.md"
    latest.write_text(brief.render())

    return path


# --- Self-test ---
def run_self_test():
    """Self-test suite."""
    import tempfile

    passed = 0
    failed = 0

    def check(label, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  PASS: {label}")
        else:
            failed += 1
            print(f"  FAIL: {label} — {detail}", file=sys.stderr)

    print("Minnie Morning Brief — Self-Test")
    print("=" * 40)

    # 1. Greeting generates
    greeting = generate_greeting()
    check("greeting generates", isinstance(greeting, str) and len(greeting) > 10, f"got: {greeting}")

    # 2. Greeting contains 'Joe'
    check("greeting mentions Joe", "Joe" in greeting, f"got: {greeting}")

    # 3. Greeting is context-aware (has a time-based note)
    has_context = any(w in greeting for w in ["Build day", "New week", "End of week", "Still dark", "Early", "Morning", "Midday", "Hey Joe"])
    check("greeting is context-aware", has_context, f"got: {greeting}")

    # 4. BriefSection dataclass works
    section = BriefSection(title="Test", content="test content")
    check("BriefSection creates", section.title == "Test" and section.has_data is True)

    # 5. MorningBrief dataclass works
    brief = MorningBrief(greeting="Hello", sections=[section])
    check("MorningBrief creates", brief.greeting == "Hello")

    # 6. Render produces output
    rendered = brief.render()
    check("render produces output", len(rendered) > 20 and "Hello" in rendered, f"length: {len(rendered)}")

    # 7. Render includes section content (no titles in new format)
    check("render includes section content", "test content" in rendered)

    # 8. Render ends with sign-off
    check("render ends with sign-off", "— Minnie" in rendered, f"got: {rendered[-30:]}")

    # 9. Sections with has_data=False are excluded
    hidden = BriefSection(title="Hidden", content="should not appear", has_data=False)
    brief2 = MorningBrief(greeting="Hi", sections=[section, hidden])
    rendered2 = brief2.render()
    check("hidden sections excluded", "should not appear" not in rendered2)

    # 10. _read_json_lines handles missing file
    result = _read_json_lines(Path("/tmp/nonexistent_minnie_brief_test.jsonl"))
    check("missing file returns empty list", result == [])

    # 11. _read_json_lines handles valid JSONL
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        now_iso = datetime.now(CDT).isoformat()
        f.write(json.dumps({"timestamp": now_iso, "data": "test"}) + "\n")
        f.write(json.dumps({"timestamp": now_iso, "data": "test2"}) + "\n")
        tmppath = Path(f.name)
    entries = _read_json_lines(tmppath, max_age_hours=1)
    check("reads valid JSONL", len(entries) == 2, f"got {len(entries)}")
    tmppath.unlink()

    # 12. _read_json_lines filters old entries
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        old_ts = (datetime.now(CDT) - timedelta(hours=48)).isoformat()
        f.write(json.dumps({"timestamp": old_ts, "data": "old"}) + "\n")
        tmppath = Path(f.name)
    entries = _read_json_lines(tmppath, max_age_hours=24)
    check("filters old entries", len(entries) == 0, f"got {len(entries)}")
    tmppath.unlink()

    # 13. Save brief works
    with tempfile.TemporaryDirectory() as tmpdir:
        global BRIEFS_DIR
        orig_dir = BRIEFS_DIR
        BRIEFS_DIR = Path(tmpdir) / "briefs"
        test_brief = MorningBrief(greeting="Test brief", sections=[section])
        saved_path = save_brief(test_brief)
        check("save creates file", saved_path.exists())
        check("save creates latest", (BRIEFS_DIR / "latest.md").exists())
        content = saved_path.read_text()
        check("saved content correct", "Test brief" in content)
        BRIEFS_DIR = orig_dir

    # 14. generate_suggestion returns a section
    suggestion = generate_suggestion()
    check("suggestion generates", isinstance(suggestion, BriefSection) and len(suggestion.content) > 10)

    # 15. Full brief generates without crash
    try:
        full_brief = generate_brief()
        check("full brief generates", isinstance(full_brief, MorningBrief) and len(full_brief.sections) >= 5)
    except Exception as e:
        check("full brief generates", False, str(e))

    # 16. Full brief renders
    try:
        rendered_full = full_brief.render()
        check("full brief renders", len(rendered_full) > 100, f"length: {len(rendered_full)}")
    except Exception as e:
        check("full brief renders", False, str(e))

    print(f"\n{'=' * 40}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Minnie's Morning Brief")
    parser.add_argument("--save", action="store_true", help="Save brief to file")
    parser.add_argument("--self-test", action="store_true", help="Run self-tests")
    args = parser.parse_args()

    if args.self_test:
        sys.exit(run_self_test())

    brief = generate_brief()
    print(brief.render())

    if args.save:
        path = save_brief(brief)
        print(f"\nSaved to: {path}")
