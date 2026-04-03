import time
import re
import os
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

# --- Configuration ---
FORM_URL = os.getenv("FORM_URL")
DATA_FOLDER = "data" 
CHROME_PROFILE_PATH = os.getenv("CHROME_USER_DATA_PATH")
GLOBAL_EMAIL = os.getenv("GLOBAL_EMAIL")
GLOBAL_DISCORD = os.getenv("GLOBAL_DISCORD")

def select_file_to_process():
    """Scans the data directory and lets the user choose a file."""
    base_dir = Path(DATA_FOLDER)
    
    if not base_dir.exists() or not base_dir.is_dir():
        print(f"\n❌ Error: Could not find a folder named '{DATA_FOLDER}' in the current directory.")
        return None

    available_files = list(base_dir.rglob("*.txt"))

    if not available_files:
        print(f"\n❌ No .txt files found anywhere inside the '{DATA_FOLDER}' folder.")
        return None

    print("\n📂 --- Available Task Files ---")
    for i, file_path in enumerate(available_files):
        # Displays only the parent folder name (e.g., 'arpil' instead of the full path)
        folder_name = file_path.parent.name
        print(f"[{i + 1}] {folder_name}")

    while True:
        choice = input("\n👉 Enter the number of the file you want to process (or 'q' to quit): ")
        
        if choice.lower() == 'q':
            return "quit"
            
        try:
            index = int(choice) - 1
            if 0 <= index < len(available_files):
                return available_files[index]
            else:
                print("⚠️ Invalid number. Please select a number from the list.")
        except ValueError:
            print("⚠️ Please enter a valid number.")

def process_tasks(target_file):
    # Verify .env variables loaded properly
    if not GLOBAL_EMAIL or not GLOBAL_DISCORD:
        print("❌ Error: GLOBAL_EMAIL or GLOBAL_DISCORD is missing from your .env file.")
        return

    print(f"\nReading data from: {target_file}")
    
    with open(target_file, 'r', encoding='utf-8') as file:
        text = file.read()
    
    # Updated Regex to handle varied spaces, optional parenthesis, and exact block formats
    pattern = r"(\d+)[\s\)]*(\(✔️\))?[\s\)]*Task ID:\s*([a-f0-9\-]+).*?Worker:\s*([\w.-]+@[\w.-]+).*?Stage UUID:\s*([a-f0-9\-]+).*?Minute[s]?\s*:\s*(\d+)"
    matches = list(re.finditer(pattern, text, re.IGNORECASE | re.DOTALL))
    
    pending_tasks = []
    for match in matches:
        if not match.group(2): # If missing the checkmark, it is pending
            pending_tasks.append({
                'task_num': match.group(1),
                'task_id': match.group(3),
                'data': [
                    GLOBAL_EMAIL,
                    match.group(4), # Worker email
                    GLOBAL_DISCORD,
                    match.group(3), # Task ID
                    match.group(5), # Stage UUID
                    match.group(6)  # Minutes
                ]
            })
            
    if not pending_tasks:
        print("✅ All tasks in this file are already marked with (✔️). Returning to menu...")
        return

    print(f"Found {len(pending_tasks)} pending task(s) to process.")
    
    # --- Chrome Kill Prompt to prevent crashes ---
    print("\n⚠️ Selenium requires Chrome to be completely closed to use your personal profile.")
    kill_choice = input("👉 Close all existing Chrome windows now? (y/n): ")
    if kill_choice.lower() == 'y':
        print("Force closing Chrome...")
        os.system("taskkill /F /IM chrome.exe") 
        time.sleep(5) # Give Windows a couple of seconds to release the profile file locks
    else:
        print("Skipping... (Note: The script may crash if Chrome is still running in the background)")
    # ---------------------------------------------

    chrome_options = Options()
    chrome_options.add_argument(f"user-data-dir={CHROME_PROFILE_PATH}")
    
    # --- NEW: Anti-Crash Flags ---
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--remote-allow-origins=*")
    chrome_options.add_argument("--disable-gpu") # Often helps prevent visual crashes on Windows
    chrome_options.add_argument("--disable-extensions") # Disables extensions that might interrupt Selenium
    # -----------------------------
    
    print("Launching Chrome...")
    driver = webdriver.Chrome(options=chrome_options) 
    
    try:
        for index, task in enumerate(pending_tasks):
            print(f"\n--- Processing Task {task['task_num']} ({index + 1} of {len(pending_tasks)} pending) ---")
            
            driver.get(FORM_URL)
            
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "input[type='text'], input[type='email'], textarea"))
            )
            
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='email'], input[type='number'], textarea")
            visible_inputs = [inp for inp in inputs if inp.is_displayed()]

            for i, value in enumerate(task['data']):
                if i < len(visible_inputs) and value:
                    visible_inputs[i].click() 
                    visible_inputs[i].clear()
                    visible_inputs[i].send_keys(value)
                    time.sleep(0.2) 
            
            print(f"Task {task['task_num']} populated in browser.")
            
            input("👉 Submit the form in your browser, then press ENTER here to mark it as done...")

            # Dynamically replace the specific task to add the checkmark
            with open(target_file, 'r', encoding='utf-8') as f:
                current_text = f.read()

            # Captures the number and any following parentheses/spaces, then inserts (✔️) before Task ID
            replace_pattern = rf"({task['task_num']}[\s\)]*)(Task ID:\s*{task['task_id']})"
            updated_text = re.sub(replace_pattern, r"\1(✔️) \2", current_text, count=1, flags=re.IGNORECASE)

            with open(target_file, 'w', encoding='utf-8') as f:
                f.write(updated_text)

            print(f"✅ Task {task['task_num']} updated with (✔️) in {target_file.name}")

    finally:
        print("Closing browser...")
        driver.quit()

if __name__ == "__main__":
    # Main loop so the script doesn't end after one file
    while True:
        selected_file = select_file_to_process()
        if selected_file == "quit" or selected_file is None:
            print("\nExiting script. Goodbye!")
            break
        
        process_tasks(selected_file)
        time.sleep(1) # Brief pause before showing the menu again