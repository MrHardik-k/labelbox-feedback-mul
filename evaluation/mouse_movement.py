import pyautogui
import random
import time
import threading

def random_sleep(min_time=1, max_time=5):
    """Pauses the script for a random amount of time to simulate reading or thinking."""
    time.sleep(random.uniform(min_time, max_time))

def human_like_mouse_move():
    """Moves the mouse to a random location on the screen with human-like acceleration/deceleration."""
    screen_width, screen_height = pyautogui.size()

    # Vertical margin to keep the cursor away from top/bottom edges and corners
    V_MARGIN = 100

    # X can use full width (left/right edges allowed), Y stays away from top/bottom
    dest_x = random.randint(0, screen_width - 1)
    dest_y = random.randint(V_MARGIN*2, screen_height - V_MARGIN)

    # Human movements vary in speed. Choose a duration between 0.5 and 2.5 seconds.
    duration = random.uniform(0.1, 0.5)

    # Easing functions make the movement curve naturally rather than strictly linear
    easing_functions = [
        pyautogui.easeInQuad,
        pyautogui.easeOutQuad,
        pyautogui.easeInOutQuad,
        pyautogui.easeInCubic,
        pyautogui.easeOutCubic,
        pyautogui.easeInOutCubic
    ]
    chosen_easing = random.choice(easing_functions)

    pyautogui.moveTo(dest_x, dest_y, duration=duration, tween=chosen_easing)

def human_like_scroll():
    """Scrolls the mouse wheel randomly in short bursts."""
    # Humans usually scroll in small bursts rather than one massive spin.
    bursts = random.randint(1, 4)
    amount = random.randint(-400, 400)
    for _ in range(bursts):
        # Negative is usually scroll down, positive is scroll up
        pyautogui.scroll(amount)
        # Tiny pause between scroll ticks
        time.sleep(random.uniform(0.1, 0.4))

# --- User mouse monitoring ---
user_active = False
user_last_move_time = time.time()
paused_for_user = False
MONITOR_INTERVAL = 0.1  # seconds
INACTIVITY_THRESHOLD = 3.0  # seconds to wait before resuming

def get_mouse_position():
    """Get current mouse position."""
    return pyautogui.position()

def monitor_user_mouse():
    """Background thread: detects if user is moving the mouse."""
    global user_active, user_last_move_time, paused_for_user
    prev_pos = get_mouse_position()
    while True:
        time.sleep(MONITOR_INTERVAL)
        curr_pos = get_mouse_position()
        if curr_pos != prev_pos:
            user_active = True
            user_last_move_time = time.time()
        else:
            user_active = False
        prev_pos = curr_pos

def start_monitoring():
    """Start the user mouse monitoring thread."""
    t = threading.Thread(target=monitor_user_mouse, daemon=True)
    t.start()
    return t

def main():
    global paused_for_user
    print("Starting human-like random mouse script.")
    print("IMPORTANT: Press Ctrl+C in this terminal to stop.")
    print("The script will pause when you move your mouse and resume after 3 seconds of inactivity.\n")

    # Start monitoring user mouse movement
    start_monitoring()

    # Give the user a moment to switch windows if needed
    time.sleep(1)

    try:
        while True:
            # Check if user is actively moving mouse
            if user_active:
                if not paused_for_user:
                    print("User mouse movement detected — pausing script.")
                    paused_for_user = True
                time.sleep(MONITOR_INTERVAL)
                continue

            # Resume if user stopped moving for INACTIVITY_THRESHOLD seconds
            if paused_for_user:
                elapsed = time.time() - user_last_move_time
                if elapsed >= INACTIVITY_THRESHOLD:
                    print("User inactive for 3 seconds — resuming script.")
                    paused_for_user = False
                else:
                    time.sleep(MONITOR_INTERVAL)
                    continue

            # Decide randomly what the "human" does next
            action = random.choices(
                ['move', 'scroll', 'idle'],
                weights=[0.5, 0.5, 0.0],
                k=1
            )[0]

            if action == 'move':
                human_like_mouse_move()
            elif action == 'scroll':
                human_like_scroll()
            elif action == 'idle':
                pass  # Do nothing, just let the next sleep happen

            # Random pause between main actions
            random_sleep(0.5, 2)

    except KeyboardInterrupt:
        print("\nScript stopped manually via Ctrl+C.")

if __name__ == "__main__":
    main()