# AutoEval Configuration - Timing Settings

# Initial wait time (seconds) for page to fully load
PAGE_LOAD_WAIT = 30

# Wait time (minutes) for Next/Submit buttons to become enabled
NEXT_BUTTON_WAIT = 2

# Polling interval (seconds) when checking if Next button is enabled
NEXT_CHECK_INTERVAL = 15

# Pause (seconds) between form interactions
FORM_INTERACTION_DELAY = 3

# Wait time (seconds) after scrolling
SCROLL_DELAY = 2

# Chrome close wait time (seconds) after killing chrome process
CHROME_KILL_WAIT = 5

# Claude REPL initialization wait (seconds) after window opens
CLAUDE_INIT_WAIT = 30

# Claude evaluation timeout (seconds) - single eval step
CLAUDE_EVAL_TIMEOUT = 900

# Pre-submit wait range (minutes) — random.randint(min, max)
SUBMIT_WAIT_MIN = 60
SUBMIT_WAIT_MAX = 65

# Eval file poll interval (seconds)
EVAL_FILE_POLL_INTERVAL = 30

# Eval file max wait (minutes)
EVAL_FILE_MAX_WAIT = 10
