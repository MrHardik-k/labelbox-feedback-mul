import pyautogui
import random
import time

# Failsafe: moving your physical mouse to any of the 4 corners of your screen will abort the script
pyautogui.FAILSAFE = True

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

def main():
    print("Starting human-like random mouse script.")
    print("IMPORTANT: Drag your mouse to any corner of the screen to trigger the failsafe and stop the script, or press Ctrl+C in this terminal.")
    
    # Give the user a moment to switch windows if needed
    time.sleep(1) 

    try:
        while True:
            # Decide randomly what the "human" does next
            action = random.choices(
                ['move', 'scroll', 'idle'],
                weights=[0.2, 0.7, 0.1], # 60% chance to move, 30% scroll, 10% just wait
                k=1
            )[0]

            if action == 'move':
                human_like_mouse_move()
            elif action == 'scroll':
                human_like_scroll()
            elif action == 'idle':
                pass # Do nothing, just let the next sleep happen

            # Random pause between main actions (simulating reading, thinking, watching a video, etc.)
            random_sleep(1, 4)

    except KeyboardInterrupt:
        print("\nScript stopped manually via Ctrl+C.")
    except pyautogui.FailSafeException:
        print("\nFailsafe triggered! Script stopped because the mouse was moved to a screen corner.")

if __name__ == "__main__":
    main()