"""
AutoEval - CC Agentic Coding Labels Automation Script
Single-page flow: extract conversation → Claude evaluates → fill ratings → submit.
"""

import os
import re
import sys
import time
import random
import subprocess
import threading
import argparse
from pathlib import Path

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

sys.path.insert(0, str(Path(__file__).parent))
from config import (
    PAGE_LOAD_WAIT,
    NEXT_BUTTON_WAIT,
    NEXT_CHECK_INTERVAL,
    FORM_INTERACTION_DELAY,
    SCROLL_DELAY,
    CHROME_KILL_WAIT,
    CLAUDE_EVAL_TIMEOUT,
    SUBMIT_WAIT_MIN,
    SUBMIT_WAIT_MAX,
    EVAL_FILE_MAX_WAIT,
)
from claude_pty import create_subprocess_pty

# --- Configuration ---
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
EVAL_SCRIPT_DIR = PROJECT_ROOT / "autoeval"
load_dotenv(EVAL_SCRIPT_DIR / ".env")

EVAL_DIR = PROJECT_ROOT / "evaluation"
INPUT_DIR = EVAL_DIR / "input"
OUTPUT_DIR = EVAL_DIR / "output"

FEEDBACK_URL = os.getenv("FEEDBACK_URL", "https://feedback.anthropic.com/surveyor/cc_agentic_coding_labels")
CHROME_USER_DATA_PATH = os.getenv("CHROME_USER_DATA_PATH", "")


# ============== Chrome ==============

def setup_chrome_driver(profile_path=None):
    print("\nSelenium requires Chrome to be completely closed to use your profile.")
    kill_choice = input("Close all existing Chrome windows now? (y/n): ")
    if kill_choice.lower() == 'y':
        print("Force closing Chrome...")
        os.system("taskkill /F /IM chrome.exe")
        time.sleep(CHROME_KILL_WAIT)
    else:
        print("Skipping... (Script may crash if Chrome is still running)")

    chrome_options = Options()
    if profile_path:
        chrome_options.add_argument(f"user-data-dir={profile_path}")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--remote-allow-origins=*")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    print("Launching Chrome...")
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_window_size(1920, 1080)
    return driver


# ============== Extraction ==============

def wait_for_page_ready(driver):
    print(f"Waiting {PAGE_LOAD_WAIT} seconds for page to fully load...")
    time.sleep(PAGE_LOAD_WAIT)
    print("Page wait complete.")


def extract_conversation_parts(driver):
    """
    Extract the conversation from the single-page review.
    Uses data-testid selectors for reliable Agent A/B extraction.
    Splits at 'Latest Comparison' marker for initial conversation history.
    """
    print("Extracting conversation parts from page...")

    result = driver.execute_script("""
        // ===== AGENT A & B: Use innerText for FULL content (including tool calls) =====
        function extractAgent(testId) {
            var container = document.querySelector('[data-testid="' + testId + '"]');
            if (!container) return '';

            // First, expand all collapsed <details> elements so innerText captures everything
            var detailsEls = container.querySelectorAll('details');
            for (var d = 0; d < detailsEls.length; d++) {
                detailsEls[d].setAttribute('open', '');
            }

            // Use innerText on the ENTIRE container — this captures:
            // - <span class="whitespace-pre-wrap"> thinking/response text
            // - Tool invocation blocks (Read, Edit, Bash, etc.) with their params
            // - Tool output/results
            // - Any other visible content
            return (container.innerText || '').trim();
        }

        var agentA = extractAgent('assistant-response-0');
        var agentB = extractAgent('assistant-response-1');

        // ===== INITIAL CONVERSATION: everything before "Latest Comparison" =====
        var initialParts = [];

        // Strategy 1: Find all conversation items (li elements) before the marker
        var allLis = document.querySelectorAll('li');
        var foundMarker = false;

        for (var i = 0; i < allLis.length; i++) {
            var liText = (allLis[i].innerText || '').trim();

            // Stop when we hit the "Latest Comparison" section
            if (liText.indexOf('Latest Comparison') !== -1) {
                foundMarker = true;
                break;
            }

            // Only include items that look like conversation turns
            if (liText.length > 20) {
                initialParts.push(liText);
            }
        }

        // Strategy 2: If li-based approach found nothing, try full-page text split
        if (initialParts.length === 0) {
            var body = document.querySelector('main') ||
                       document.querySelector('[role="main"]') ||
                       document.body;
            var fullText = (body.innerText || '');
            var markerIdx = fullText.indexOf('Latest Comparison');

            if (markerIdx !== -1) {
                var beforeText = fullText.substring(0, markerIdx).trim();
                initialParts = [beforeText];
                foundMarker = true;
            } else {
                initialParts = [fullText];
            }
        }

        // ===== FALLBACK 1: CSS class-based extraction for agents =====
        if (!agentA || !agentB) {
            var respDivs = document.querySelectorAll('.assistant-response-editable-text-field');

            // Expand all <details> in fallback containers too
            for (var rd = 0; rd < respDivs.length; rd++) {
                var dets = respDivs[rd].querySelectorAll('details');
                for (var dd = 0; dd < dets.length; dd++) {
                    dets[dd].setAttribute('open', '');
                }
            }

            if (respDivs.length >= 1 && !agentA) {
                agentA = (respDivs[0].innerText || '').trim();
            }
            if (respDivs.length >= 2 && !agentB) {
                agentB = (respDivs[1].innerText || '').trim();
            }
        }

        // ===== FALLBACK 2: Look for bold A/B labels =====
        if (!agentA || !agentB) {
            var boldSpans = document.querySelectorAll('span.font-bold, span[class*="font-bold"]');
            for (var bs = 0; bs < boldSpans.length; bs++) {
                var label = (boldSpans[bs].textContent || '').trim();
                if ((label === 'A' || label === 'B')) {
                    var parent = boldSpans[bs].closest('[class*="flex"]');
                    if (!parent) parent = boldSpans[bs].parentElement;
                    if (!parent) continue;

                    var respDiv = parent.querySelector('.border-gray-200, [class*="border-2"]');
                    if (!respDiv) respDiv = parent;

                    // Expand <details> here too
                    var rdets = respDiv.querySelectorAll('details');
                    for (var rdd = 0; rdd < rdets.length; rdd++) {
                        rdets[rdd].setAttribute('open', '');
                    }

                    var extracted = (respDiv.innerText || '').trim();

                    if (label === 'A' && !agentA) agentA = extracted;
                    if (label === 'B' && !agentB) agentB = extracted;
                }
            }
        }

        // ===== FALLBACK 3: Walk the indigo-bordered parent containers =====
        // The HTML structure is: div.border-indigo-600 > div > div.flex > [span.font-bold "A/B"] + div.border-gray-200
        if (!agentA || !agentB) {
            var indigoDivs = document.querySelectorAll('div.border-indigo-600, div[class*="border-indigo"]');
            for (var ig = 0; ig < indigoDivs.length; ig++) {
                var labelSpan = indigoDivs[ig].querySelector('span.font-bold');
                if (!labelSpan) continue;
                var lbl = (labelSpan.textContent || '').trim();

                var respContainer = indigoDivs[ig].querySelector('.border-gray-200, [class*="border-2"]:not([class*="border-indigo"])');
                if (!respContainer) respContainer = indigoDivs[ig];

                // Expand <details>
                var idets = respContainer.querySelectorAll('details');
                for (var idd = 0; idd < idets.length; idd++) {
                    idets[idd].setAttribute('open', '');
                }

                var txt = (respContainer.innerText || '').trim();
                if (lbl === 'A' && !agentA) agentA = txt;
                if (lbl === 'B' && !agentB) agentB = txt;
            }
        }

        return {
            initial: initialParts.join('\\n\\n'),
            agent_a: agentA || '',
            agent_b: agentB || '',
            marker_found: foundMarker,
            warning: (!agentA && !agentB) ? 'no_agents_found' : ''
        };
    """)

    if not result:
        print("Warning: extraction returned null")
        return "", "", ""

    if result.get('error'):
        print(f"Warning: extraction error: {result['error']}")
        return "", "", ""

    if result.get('warning'):
        print(f"Warning: {result['warning']}")

    print(f"  Marker found: {result.get('marker_found', 'N/A')}")

    initial = result.get('initial', '')
    agent_a = result.get('agent_a', '')
    agent_b = result.get('agent_b', '')

    print(f"  Initial conversation: {len(initial)} chars")
    print(f"  Agent A response: {len(agent_a)} chars")
    print(f"  Agent B response: {len(agent_b)} chars")

    # Debug: show first 200 chars of each part
    if agent_a:
        print(f"  Agent A preview: {agent_a[:200]}...")
    else:
        print("  WARNING: Agent A is EMPTY!")
    if agent_b:
        print(f"  Agent B preview: {agent_b[:200]}...")
    else:
        print("  WARNING: Agent B is EMPTY!")

    return initial, agent_a, agent_b


# ============== Navigation ==============

def scroll_to_bottom(driver):
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(SCROLL_DELAY)


def wait_for_submit_enabled(driver):
    print(f"\nWaiting for Submit button (up to {NEXT_BUTTON_WAIT} minutes)...")
    start = time.time()
    max_seconds = NEXT_BUTTON_WAIT * 60

    while time.time() - start < max_seconds:
        try:
            btn = driver.find_element(By.XPATH, '//button[@type="submit"]')
            if btn.is_enabled():
                print("Submit button is enabled!")
                return True
        except NoSuchElementException:
            pass
        time.sleep(NEXT_CHECK_INTERVAL)
        driver.execute_script("window.scrollBy(0, 100);")

    print("Max wait reached for Submit")
    return False


# ============== Comparison Form ==============

# Maps axis numbers to substrings likely found in the site's question headings
AXIS_QUESTIONS = [
    ("axis_1", "logic"),
    ("axis_2", "naming"),
    ("axis_3", "organization"),
    ("axis_4", "interface"),
    ("axis_5", "error"),
    ("axis_6", "documentation"),
    ("axis_7", "review"),
    ("overall", "better"),
]


def parse_comparison(compare_file):
    """Parse both_agent_compare.txt for axis ratings (1-8) and overall score."""
    if not compare_file.exists():
        return {}
    with open(compare_file, 'r', encoding='utf-8') as f:
        content = f.read()

    ratings = {}

    # Parse axis ratings: "Axis N (Name): Score" or "* Axis N (Name): Score"
    for m in re.finditer(r'Axis\s+(\d+)[^:]*?:\s*(\d+)', content):
        axis_num = int(m.group(1).strip())
        score = int(m.group(2).strip())
        if 1 <= axis_num <= 7 and 1 <= score <= 8:
            ratings[f'axis_{axis_num}'] = score

    # Parse overall preference: "Score: N" under "Overall Preference"
    overall_match = re.search(
        r'Overall\s+Preference.*?Score:\s*(\d+)',
        content, re.DOTALL | re.IGNORECASE
    )
    if overall_match:
        score = int(overall_match.group(1).strip())
        if 1 <= score <= 8:
            ratings['overall'] = score

    return ratings


def fill_comparison_form(driver, compare_file):
    """Fill the comparison form by clicking rating buttons (1-8) for each axis.
    Returns True if ratings were found and filled, False if no ratings found."""
    print("Filling comparison form...")
    ratings = parse_comparison(compare_file)

    if not ratings:
        print("Warning: No ratings found in comparison file")
        return False

    print(f"  Parsed {len(ratings)} ratings: {ratings}")

    # Strategy: Find each question section by heading text, then click the Nth button
    for key, question_substr in AXIS_QUESTIONS:
        if key not in ratings:
            print(f"  Skipping '{key}' — not found in eval output")
            continue

        score = ratings[key]
        if score < 1 or score > 8:
            print(f"  Warning: Invalid score {score} for '{key}', skipping")
            continue

        result = driver.execute_script("""
            var keyword = arguments[0].toLowerCase();
            var targetScore = arguments[1];
            var axisKey = arguments[2];

            // Helper: walk up from element to find ancestor with exactly 8 choice-buttons
            function findSection(el) {
                var node = el.parentElement;
                for (var depth = 0; depth < 15 && node; depth++) {
                    var btns = node.querySelectorAll('button.choice-button');
                    if (btns.length === 8) return {container: node, buttons: btns};
                    if (btns.length > 8) return null;  // hit outer wrapper, stop
                    node = node.parentElement;
                }
                return null;
            }

            // Strategy 1: Match span.text-sm axis labels (NOT button descriptions)
            var labelSpans = document.querySelectorAll('span.text-sm');
            for (var i = 0; i < labelSpans.length; i++) {
                // Skip button description spans (they have "w-max" class)
                if (labelSpans[i].classList.contains('w-max')) continue;
                // Skip spans that are inside a button
                if (labelSpans[i].closest('button')) continue;
                var lt = (labelSpans[i].textContent || '').trim();
                if (lt.length > 80) continue;
                if (lt.toLowerCase().indexOf(keyword) === -1) continue;

                var match = findSection(labelSpans[i]);
                if (match && match.buttons.length === 8) {
                    var idx = targetScore - 1;
                    if (idx >= 0 && idx < 8) {
                        match.buttons[idx].scrollIntoView({block: 'center'});
                        match.buttons[idx].click();
                        return 'clicked_' + idx + '_for_' + lt;
                    }
                }
            }

            // Strategy 2: Search ALL short-text elements (divs, spans, etc.)
            var allEls = document.querySelectorAll('h1,h2,h3,h4,h5,p,label,legend,div,span');
            for (var h = 0; h < allEls.length; h++) {
                if (allEls[h].classList.contains('w-max')) continue;
                if (allEls[h].classList.contains('choice-button')) continue;
                if (allEls[h].closest('button')) continue;
                // Only check direct text nodes to avoid matching parent containers
                var directText = '';
                for (var cn = 0; cn < allEls[h].childNodes.length; cn++) {
                    if (allEls[h].childNodes[cn].nodeType === 3)
                        directText += allEls[h].childNodes[cn].textContent;
                }
                directText = directText.trim();
                if (!directText || directText.length > 100) continue;
                if (directText.toLowerCase().indexOf(keyword) === -1) continue;

                var m2 = findSection(allEls[h]);
                if (m2 && m2.buttons.length === 8) {
                    var idx2 = targetScore - 1;
                    if (idx2 >= 0 && idx2 < 8) {
                        m2.buttons[idx2].scrollIntoView({block: 'center'});
                        m2.buttons[idx2].click();
                        return 'clicked_broad_' + idx2 + '_for_' + directText.substring(0, 40);
                    }
                }
            }

            // Strategy 3: Positional fallback (ONLY for "overall" / preference)
            // Finds ALL sections with exactly 8 choice-buttons and picks the LAST one.
            if (axisKey === 'overall') {
                var allSections = document.querySelectorAll('div');
                var lastSection = null;
                for (var s = 0; s < allSections.length; s++) {
                    var sec = allSections[s];
                    var secBtns = sec.querySelectorAll('button.choice-button');
                    if (secBtns.length === 8) lastSection = {container: sec, buttons: secBtns};
                }
                if (lastSection) {
                    var idx3 = targetScore - 1;
                    if (idx3 >= 0 && idx3 < 8) {
                        lastSection.buttons[idx3].scrollIntoView({block: 'center'});
                        lastSection.buttons[idx3].click();
                        return 'clicked_last_section_' + idx3;
                    }
                }
            }

            return 'not_found_for_' + keyword;
        """, question_substr, score, key)

        if result and result.startswith('clicked'):
            print(f"  Rating '{key}': {score} ({result})")
        else:
            print(f"  Warning: Could not click rating for '{key}': {result}")

        time.sleep(0.5)  # Brief pause between clicks

    print("Comparison form filled.")
    return True


def parse_close_preference_reason(reason_file):
    """Parse close_preference_reason.txt for the chosen reason and optional explanation.
    
    Expected format from Claude:
        REASON: similar_quality | unable_to_judge | other
        EXPLANATION: <text>   (only when REASON is 'other')
    """
    if not reason_file.exists():
        return None, None
    with open(reason_file, 'r', encoding='utf-8') as f:
        content = f.read()

    reason = None
    explanation = None

    # Match REASON line
    reason_match = re.search(
        r'REASON:\s*(similar_quality|unable_to_judge|other)',
        content, re.IGNORECASE
    )
    if reason_match:
        reason = reason_match.group(1).strip().lower()

    # Match EXPLANATION line (everything after "EXPLANATION:")
    explanation_match = re.search(
        r'EXPLANATION:\s*(.+)',
        content, re.DOTALL | re.IGNORECASE
    )
    if explanation_match:
        explanation = explanation_match.group(1).strip()
        # Clean up: take only the first meaningful paragraph
        explanation = explanation.split('\n\n')[0].strip()

    return reason, explanation


def fill_close_preference(driver, reason, explanation=None):
    """Fill the 'Why is this a close preference?' radio + optional textarea."""
    print(f"  Filling close preference: reason={reason}, has_explanation={bool(explanation)}")

    # Click the matching radio button by value attribute
    result = driver.execute_script("""
        var reason = arguments[0];
        var explanation = arguments[1];

        // Find and click the radio button with matching value
        var radios = document.querySelectorAll('input[name="closePreferenceReason"]');
        var clicked = false;
        for (var i = 0; i < radios.length; i++) {
            if (radios[i].value === reason) {
                radios[i].scrollIntoView({block: 'center'});
                radios[i].click();
                clicked = true;
                break;
            }
        }

        if (!clicked) {
            // Fallback: try clicking the label that contains the radio
            var labels = document.querySelectorAll('label');
            for (var j = 0; j < labels.length; j++) {
                var radio = labels[j].querySelector('input[name="closePreferenceReason"]');
                if (radio && radio.value === reason) {
                    labels[j].click();
                    clicked = true;
                    break;
                }
            }
        }

        if (!clicked) return 'radio_not_found_' + reason;

        // If reason is 'other' and we have an explanation, fill the textarea
        if (reason === 'other' && explanation) {
            // Wait a moment for textarea to appear
            var textarea = document.querySelector('textarea[placeholder*="close preference"]');
            if (!textarea) {
                // Broader search
                var allTextareas = document.querySelectorAll('textarea');
                for (var t = 0; t < allTextareas.length; t++) {
                    var ph = allTextareas[t].placeholder || '';
                    if (ph.toLowerCase().indexOf('preference') !== -1 || 
                        ph.toLowerCase().indexOf('describe') !== -1) {
                        textarea = allTextareas[t];
                        break;
                    }
                }
            }
            if (textarea) {
                textarea.scrollIntoView({block: 'center'});
                // Use native input setter to trigger React state updates
                var nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                nativeSetter.call(textarea, explanation);
                textarea.dispatchEvent(new Event('input', {bubbles: true}));
                textarea.dispatchEvent(new Event('change', {bubbles: true}));
                return 'filled_other_with_explanation';
            } else {
                return 'radio_clicked_but_textarea_not_found';
            }
        }

        return 'filled_' + reason;
    """, reason, explanation or "")

    print(f"  Close preference result: {result}")
    return result


# ============== Claude Control ==============

def send_claude_command(pty, cmd, wait_for_pattern, timeout=600):
    """Send a command to Claude and wait for completion via file monitoring."""
    print(f"\n[Claude] Sending: {cmd[:150]}...")
    pty.send(cmd)
    print(f"[Claude] Waiting for: {wait_for_pattern} (timeout={timeout}s)")
    found = pty.wait_for(wait_for_pattern, timeout=timeout)
    if found:
        print(f"[Claude] Detected: {wait_for_pattern}")
    else:
        print(f"[Claude] Timeout waiting for: {wait_for_pattern}")
    return found


def wait_for_eval_file(eval_file, label="", timeout_minutes=25):
    """Wait for an evaluation output file to appear."""
    timeout_seconds = timeout_minutes * 60
    print(f"Waiting for {eval_file.name} (up to {timeout_minutes} min)...")
    start = time.time()
    check = 0
    while time.time() - start < timeout_seconds:
        check += 1
        if eval_file.exists():
            size = eval_file.stat().st_size
            if size > 10:
                print(f"{eval_file.name} found! (after {check} checks, {(time.time()-start)/60:.1f} min)")
                return True
        if check % 5 == 0:
            elapsed = (time.time() - start) / 60
            print(f"  ... still waiting for {eval_file.name} ({elapsed:.1f} min elapsed)")
        time.sleep(30)
    print(f"Timeout waiting for {eval_file.name}")
    return False


# ============== File Operations ==============

def select_folder():
    data_dir = PROJECT_ROOT / "submissions" / "data"
    if not data_dir.exists():
        print(f"Error: Could not find '{data_dir}' directory.")
        return None
    folders = [d for d in data_dir.iterdir() if d.is_dir()]
    if not folders:
        print(f"No folders found in {data_dir}")
        return None

    print("\n--- Select a worker folder ---")
    for i, folder in enumerate(folders):
        print(f"[{i + 1}] {folder.name}")
    while True:
        choice = input("\nEnter number (or 'q' to quit): ").strip()
        if choice.lower() == 'q':
            return None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(folders):
                return folders[idx].name
            print("Invalid number.")
        except ValueError:
            print("Please enter a valid number.")


def run_empty_script():
    """Run evaluation/empty.py to clear both input/ and output/ folders."""
    empty_script = EVAL_DIR / "empty.py"
    if empty_script.exists():
        print(f"Running {empty_script}...")
        result = subprocess.run(
            [sys.executable, str(empty_script)],
            cwd=str(EVAL_DIR),
            capture_output=True, text=True
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"Warning: empty.py returned exit code {result.returncode}")
            if result.stderr:
                print(f"  stderr: {result.stderr}")
    else:
        print(f"Warning: {empty_script} not found, clearing manually...")
        for folder in [INPUT_DIR, OUTPUT_DIR]:
            if folder.exists():
                for f in folder.glob("*.txt"):
                    with open(f, 'w') as fp:
                        pass


def get_task_info(driver):
    """Extract task ID, worker, and stage UUID from the page header."""
    info = {'task_id': 'N/A', 'worker': 'N/A', 'stage_uuid': 'N/A'}
    try:
        p_elem = driver.find_element(By.XPATH, '//p[contains(@class, "text-sm") and contains(@class, "text-gray-500")]')
        text = p_elem.text
        if 'Task ID:' in text:
            parts = text.split('•')
            info['task_id'] = parts[0].replace('Task ID:', '').strip()
            if len(parts) > 1:
                info['worker'] = parts[1].replace('Worker:', '').strip()
    except Exception:
        pass
    try:
        uuid_elem = driver.find_element(By.XPATH, '//p[contains(@class, "text-xs") and contains(@class, "font-mono")]')
        uuid_text = uuid_elem.text
        if 'Stage UUID:' in uuid_text:
            info['stage_uuid'] = uuid_text.replace('Stage UUID:', '').strip()
    except Exception:
        pass
    return info


def save_task_start(task_info, folder_name):
    """Save task IDs immediately when a task starts (no time yet)."""
    submissions_dir = PROJECT_ROOT / "submissions" / "data" / folder_name
    submissions_dir.mkdir(parents=True, exist_ok=True)
    info_file = submissions_dir / "task_details.txt"

    next_num = 1
    if info_file.exists():
        content = info_file.read_text(encoding='utf-8')
        nums = re.findall(r'^(\d+)\)', content, re.MULTILINE)
        if nums:
            next_num = max(int(n) for n in nums) + 1

    task_id = task_info.get('task_id', 'N/A')
    worker = task_info.get('worker', 'N/A')
    stage_uuid = task_info.get('stage_uuid', 'N/A')

    entry = (
        f"{next_num}) Task ID: {task_id} \u2022 Worker: {worker}\n"
        f"Stage UUID: {stage_uuid}\n"
    )

    with open(info_file, 'a', encoding='utf-8') as f:
        f.write(entry)
    print(f"Task #{next_num} IDs saved to {info_file}")
    return next_num


def save_task_time(folder_name, elapsed_minutes):
    """Append the elapsed time to the last task entry (success only)."""
    submissions_dir = PROJECT_ROOT / "submissions" / "data" / folder_name
    info_file = submissions_dir / "task_details.txt"

    with open(info_file, 'a', encoding='utf-8') as f:
        f.write(f"Minutes: {elapsed_minutes}\n\n")
    print(f"Task time saved: {elapsed_minutes} min")


def remove_last_task_entry(folder_name):
    """Remove the last task entry from task_details.txt (when submit failed/duplicate UUID).
    This undoes the save_task_start call for a task that was never actually submitted."""
    submissions_dir = PROJECT_ROOT / "submissions" / "data" / folder_name
    info_file = submissions_dir / "task_details.txt"

    if not info_file.exists():
        return

    content = info_file.read_text(encoding='utf-8')
    # Find the last entry pattern: "N) Task ID: ...\nStage UUID: ...\n" possibly with "Minutes: ...\n\n"
    # We want to remove everything from the last "N)" to end
    entries = list(re.finditer(r'^\d+\)', content, re.MULTILINE))
    if not entries:
        return

    last_entry_start = entries[-1].start()
    trimmed = content[:last_entry_start].rstrip()
    if trimmed:
        trimmed += '\n'

    with open(info_file, 'w', encoding='utf-8') as f:
        f.write(trimmed)
    print(f"Removed last task entry from {info_file}")


def verify_submit_success(driver, old_stage_uuid, max_retries=3, retry_interval=15):
    """After clicking submit, verify the task actually changed by checking Stage UUID.
    If same UUID persists, re-click submit.
    Returns True if task transitioned (new UUID), False if stuck."""
    for attempt in range(1, max_retries + 1):
        print(f"  Verifying submission (attempt {attempt}/{max_retries})...")
        time.sleep(retry_interval)

        new_info = get_task_info(driver)
        new_uuid = new_info.get('stage_uuid', 'N/A')

        if new_uuid != old_stage_uuid:
            print(f"  ✓ Task changed! Old UUID: {old_stage_uuid[:16]}... → New UUID: {new_uuid[:16]}...")
            return True

        print(f"  Same UUID detected ({new_uuid[:16]}...) — submit may have failed.")

        if attempt < max_retries:
            # Re-click submit
            print(f"  Re-clicking Submit button...")
            try:
                submit_btn = driver.find_element(By.XPATH, '//button[@type="submit"]')
                if submit_btn.is_enabled():
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", submit_btn)
                    print(f"  Re-clicked Submit!")
                else:
                    print(f"  Submit button is disabled, trying fallback...")
                    fb = driver.find_element(By.XPATH, '//button[contains(., "Submit")]')
                    driver.execute_script("arguments[0].click();", fb)
            except NoSuchElementException:
                print(f"  No Submit button found for retry")

    print(f"  ✗ Submit verification failed after {max_retries} attempts.")
    return False


def click_skip_button(driver):
    """Click the Skip button to skip the current task on error."""
    try:
        skip_btn = driver.find_element(By.XPATH, '//button[contains(text(), "Skip")]')
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", skip_btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", skip_btn)
        print("Clicked Skip button!")
        time.sleep(3)
        return True
    except NoSuchElementException:
        try:
            skip_btn = driver.find_element(By.XPATH, '//button[contains(., "Skip")]')
            driver.execute_script("arguments[0].click();", skip_btn)
            print("Clicked Skip button (fallback)!")
            time.sleep(3)
            return True
        except NoSuchElementException:
            print("No Skip button found!")
            return False


# ============== Main ==============

def main():
    parser = argparse.ArgumentParser(description="AutoEval - CC Agentic Coding Labels Automation")
    parser.add_argument("--url", default=FEEDBACK_URL)
    parser.add_argument("--profile", default=CHROME_USER_DATA_PATH)
    args = parser.parse_args()

    print("=" * 60)
    print("AutoEval - CC Agentic Coding Labels (SINGLE-PAGE MODE)")
    print("=" * 60)
    print(f"Target URL: {args.url}")
    print(f"Input dir: {INPUT_DIR}")
    print(f"Output dir: {OUTPUT_DIR}")
    print("=" * 60)

    driver = None

    try:
        # ── One-time setup ──
        print("\n[1] Selecting worker folder...")
        folder_name = select_folder()
        if not folder_name:
            return

        # ── Setup Chrome ONCE ──
        print("\n[2] Setting up Chrome...")
        driver = setup_chrome_driver(args.profile if args.profile else None)

        # ── Navigate to target site ONCE ──
        print(f"\n[3] Navigating to {args.url}...")
        driver.get(args.url)

        task_count = 0

        # ════════════════════════════════════════
        #  MAIN LOOP — process tasks continuously
        # ════════════════════════════════════════
        while True:
            task_count += 1
            pty = None

            print("\n" + "█" * 60)
            print(f"  STARTING TASK #{task_count}")
            print("█" * 60)

            try:
                # ── Start timer ──
                task_start_time = time.time()

                # ── Clear input/output files ──
                print(f"\n[T{task_count}-1] Running evaluation/empty.py...")
                run_empty_script()

                # ── Wait for page to fully load ──
                print(f"\n[T{task_count}-2] Waiting for page to load...")
                wait_for_page_ready(driver)

                # Extract task info and save IDs immediately
                task_info = get_task_info(driver)
                save_task_start(task_info, folder_name)
                print(f"  Task ID: {task_info.get('task_id', 'N/A')}")

                # ══════════════════════════════════════
                #  EXTRACT: Conversation parts
                # ══════════════════════════════════════

                print(f"\n[T{task_count}-3] Extracting conversation parts...")
                initial_text, agent_a_text, agent_b_text = extract_conversation_parts(driver)

                INPUT_DIR.mkdir(parents=True, exist_ok=True)

                # Save initial conversation (all human + assistant turns before "Latest Comparison:")
                initial_file = INPUT_DIR / "initial_transcription.txt"
                with open(initial_file, 'w', encoding='utf-8') as f:
                    f.write(initial_text)
                print(f"Saved initial conversation to {initial_file} ({len(initial_text)} chars)")

                # Save Agent A response
                agent_a_file = INPUT_DIR / "agent_A_response.txt"
                with open(agent_a_file, 'w', encoding='utf-8') as f:
                    f.write(agent_a_text)
                print(f"Saved Agent A to {agent_a_file} ({len(agent_a_text)} chars)")

                # Save Agent B response
                agent_b_file = INPUT_DIR / "agent_B_response.txt"
                with open(agent_b_file, 'w', encoding='utf-8') as f:
                    f.write(agent_b_text)
                print(f"Saved Agent B to {agent_b_file} ({len(agent_b_text)} chars)")

                # Skip task if any input file is empty
                empty_files = []
                for fname, content in [
                    ("initial_transcription.txt", initial_text),
                    ("agent_A_response.txt", agent_a_text),
                    ("agent_B_response.txt", agent_b_text),
                ]:
                    if not content or not content.strip():
                        empty_files.append(fname)
                if empty_files:
                    print(f"\n[SKIP] Task {task_count} skipped: empty input file(s): {', '.join(empty_files)}")
                    remove_last_task_entry(folder_name)
                    click_skip_button(driver)
                    continue

                # ══════════════════════════════════════
                #  EVALUATE: Claude comparison (with retry)
                # ══════════════════════════════════════

                MAX_EVAL_RETRIES = 2
                eval_success = False

                for eval_attempt in range(1, MAX_EVAL_RETRIES + 1):
                    # Start fresh Claude CLI session
                    print(f"\n[T{task_count}-4] Starting Claude Code in new terminal (attempt {eval_attempt})...")
                    if pty:
                        pty.stop()
                        pty = None
                    pty = create_subprocess_pty(str(EVAL_DIR))

                    # Clear any stale output from previous attempt
                    compare_output = OUTPUT_DIR / "both_agent_compare.txt"
                    if compare_output.exists():
                        compare_output.unlink()

                    # Send single command with rules file reference + start working
                    print(f"\n[T{task_count}-5] Sending evaluation command to Claude...")
                    rules_path = "rules/both_agent_compare_rule.txt"
                    eval_msg = (
                        f"Read @{rules_path} for your evaluation instructions. "
                        "Then read the 3 input files from the input folder "
                        "(input/initial_transcription.txt, input/agent_A_response.txt, input/agent_B_response.txt), "
                        "evaluate both models across all 7 axes using the 1-8 scale as described in the rules, "
                        "and save your formatted output to output/both_agent_compare.txt. "
                        "Start working now. When completely done, output exactly: EVAL DONE"
                    )
                    send_claude_command(pty, eval_msg, "EVAL DONE", timeout=CLAUDE_EVAL_TIMEOUT)

                    wait_for_eval_file(compare_output, "Evaluation", timeout_minutes=EVAL_FILE_MAX_WAIT)

                    # Check if ratings were actually parsed
                    test_ratings = parse_comparison(compare_output)
                    if test_ratings:
                        print(f"  ✓ Evaluation produced {len(test_ratings)} ratings on attempt {eval_attempt}")
                        eval_success = True
                        break
                    else:
                        print(f"  ✗ No ratings found in evaluation output (attempt {eval_attempt}/{MAX_EVAL_RETRIES})")
                        if eval_attempt < MAX_EVAL_RETRIES:
                            print(f"  Restarting Claude CLI for retry...")
                            if pty:
                                pty.stop()
                                pty = None
                            # Clear output for retry
                            run_empty_script()
                            # Re-save input files (they were cleared by empty.py)
                            INPUT_DIR.mkdir(parents=True, exist_ok=True)
                            with open(INPUT_DIR / "initial_transcription.txt", 'w', encoding='utf-8') as f:
                                f.write(initial_text)
                            with open(INPUT_DIR / "agent_A_response.txt", 'w', encoding='utf-8') as f:
                                f.write(agent_a_text)
                            with open(INPUT_DIR / "agent_B_response.txt", 'w', encoding='utf-8') as f:
                                f.write(agent_b_text)

                if not eval_success:
                    print(f"  ✗ Evaluation failed after {MAX_EVAL_RETRIES} attempts. Skipping task...")
                    remove_last_task_entry(folder_name)
                    click_skip_button(driver)
                    continue

                # ══════════════════════════════════════
                #  FILL FORM: Rating buttons only
                # ══════════════════════════════════════

                print(f"\n[T{task_count}-7] Filling comparison form...")
                scroll_to_bottom(driver)
                form_filled = fill_comparison_form(driver, OUTPUT_DIR / "both_agent_compare.txt")

                if not form_filled:
                    print("  Form filling failed — no ratings. Skipping task...")
                    remove_last_task_entry(folder_name)
                    click_skip_button(driver)
                    continue

                # ══════════════════════════════════════
                #  CLOSE PREFERENCE: If overall is 4 or 5
                # ══════════════════════════════════════

                ratings = parse_comparison(OUTPUT_DIR / "both_agent_compare.txt")
                overall_score = ratings.get('overall', 0)

                if overall_score in (4, 5):
                    print(f"\n[T{task_count}-7b] Overall score is {overall_score} — handling close preference...")

                    # Delete any stale close_preference_reason.txt
                    close_pref_file = OUTPUT_DIR / "close_preference_reason.txt"
                    if close_pref_file.exists():
                        close_pref_file.unlink()

                    # Ask Claude for a close-preference reason
                    close_pref_msg = (
                        "The overall preference score you gave is " + str(overall_score) + " which indicates a close preference. "
                        "The feedback form is now asking: 'Why is this a close preference?' with these options:\n"
                        "1. similar_quality - The responses are nearly identical in quality\n"
                        "2. unable_to_judge - The responses differ, but I'm unable to judge which is better\n"
                        "3. other - Other (requires a short explanation)\n\n"
                        "Based on your evaluation, pick the most appropriate reason. "
                        "Save your answer to output/close_preference_reason.txt in this exact format:\n"
                        "REASON: <similar_quality OR unable_to_judge OR other>\n"
                        "EXPLANATION: <only if REASON is other, provide a 1-2 sentence explanation>\n\n"
                        "When completely done, output exactly: CLOSE_PREF DONE"
                    )
                    send_claude_command(pty, close_pref_msg, "CLOSE_PREF DONE", timeout=120)

                    # Wait for the file
                    wait_for_eval_file(close_pref_file, "Close Preference", timeout_minutes=3)
                    time.sleep(2)  # brief delay for file to flush

                    # Parse and fill
                    reason, explanation = parse_close_preference_reason(close_pref_file)
                    if reason:
                        print(f"  Close preference reason: {reason}")
                        if explanation:
                            print(f"  Explanation: {explanation[:100]}")
                        fill_close_preference(driver, reason, explanation)
                        time.sleep(1)
                    else:
                        print("  Warning: Could not parse close preference reason, defaulting to 'similar_quality'")
                        fill_close_preference(driver, "similar_quality")
                        time.sleep(1)
                else:
                    print(f"  Overall score {overall_score} — no close preference needed.")

                # ══════════════════════════════════════
                #  WAIT: 60-70 minutes before confirm
                # ══════════════════════════════════════

                wait_min = random.randint(SUBMIT_WAIT_MIN, SUBMIT_WAIT_MAX)
                print(f"\n[T{task_count}-8] Waiting {wait_min} minutes before confirm...")
                time.sleep(wait_min * 60)

                # ══════════════════════════════════════
                #  CONFIRM SELECTION (if present)
                # ══════════════════════════════════════

                print(f"\n[T{task_count}-9] Checking for 'Confirm selection' button...")
                confirm_clicked = False

                # Check if the button exists at all
                confirm_buttons = driver.find_elements(
                    By.XPATH, '//button[contains(., "Confirm selection")]'
                )
                if not confirm_buttons:
                    # Fallback: match by class bg-indigo-600 + "Confirm"
                    confirm_buttons = driver.find_elements(
                        By.XPATH, '//button[contains(@class, "bg-indigo-600") and contains(., "Confirm")]'
                    )

                if confirm_buttons:
                    confirm_btn = confirm_buttons[0]
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", confirm_btn)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", confirm_btn)
                    print("Clicked 'Confirm selection'!")
                    confirm_clicked = True

                    # Wait 10 seconds after confirm before submit
                    print(f"[T{task_count}-10] Waiting 10 seconds after confirm...")
                    time.sleep(10)
                else:
                    print("No 'Confirm selection' button found — skipping, submit should be enabled.")

                # ══════════════════════════════════════
                #  SUBMIT + VERIFY
                # ══════════════════════════════════════

                # Capture current stage UUID BEFORE submit for verification
                pre_submit_uuid = task_info.get('stage_uuid', 'N/A')

                print(f"\n[T{task_count}-SUBMIT] Final submission...")
                submit_xpath = '//button[@type="submit"]'
                submitted = False
                try:
                    submit_btn = driver.find_element(By.XPATH, submit_xpath)
                    if submit_btn.is_enabled():
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
                        time.sleep(FORM_INTERACTION_DELAY)
                        driver.execute_script("arguments[0].click();", submit_btn)
                        print("Clicked Submit!")
                        submitted = True
                    else:
                        print("Submit button found but disabled, waiting...")
                        for _ in range(12):  # Wait up to 60s
                            time.sleep(5)
                            submit_btn = driver.find_element(By.XPATH, submit_xpath)
                            if submit_btn.is_enabled():
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
                                time.sleep(FORM_INTERACTION_DELAY)
                                driver.execute_script("arguments[0].click();", submit_btn)
                                print("Clicked Submit!")
                                submitted = True
                                break
                except NoSuchElementException:
                    pass

                if not submitted:
                    # Fallback: try button containing "Submit" text in descendants
                    try:
                        submit_btn = driver.find_element(By.XPATH, '//button[contains(., "Submit")]')
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_btn)
                        time.sleep(FORM_INTERACTION_DELAY)
                        driver.execute_script("arguments[0].click();", submit_btn)
                        print("Clicked Submit (fallback)!")
                        submitted = True
                    except NoSuchElementException:
                        print("No Submit button found!")

                # ── Verify submission by checking UUID change ──
                if submitted and pre_submit_uuid != 'N/A':
                    submit_verified = verify_submit_success(driver, pre_submit_uuid)
                    if not submit_verified:
                        print("  ⚠ Submit verification FAILED — same stage UUID after retries.")
                        print("  Removing stale task entry...")
                        remove_last_task_entry(folder_name)
                        # Don't record time — move to next iteration which will retry
                        continue
                elif not submitted:
                    print("  Submit was never clicked — removing stale task entry...")
                    remove_last_task_entry(folder_name)
                    click_skip_button(driver)
                    continue

                # ── Save time ONLY on verified success ──
                elapsed_minutes = round((time.time() - task_start_time) / 60)
                save_task_time(folder_name, elapsed_minutes)

                print(f"\n{'=' * 60}")
                print(f"  TASK #{task_count} COMPLETE! ({elapsed_minutes} min)")
                print(f"{'=' * 60}")

            except Exception as e:
                print(f"\n\nError during task #{task_count}: {e}")
                import traceback
                traceback.print_exc()
                # Skip this task on the site
                print("Clicking Skip to move to next task...")
                try:
                    click_skip_button(driver)
                except Exception:
                    print("Warning: Could not click Skip button")

            finally:
                # ── Stop Claude after each task ──
                if pty:
                    print("Stopping Claude for this task...")
                    pty.stop()
                    pty = None

            # ── Wait for next task to load ──
            print(f"\nWaiting {PAGE_LOAD_WAIT}s for next task to load...")
            time.sleep(PAGE_LOAD_WAIT)

    except KeyboardInterrupt:
        print(f"\n\nAutomation stopped by user after {task_count} task(s).")
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            print("\nBrowser open. Close manually when done.")


if __name__ == "__main__":
    main()
