import re
import csv
import os

# ==========================================
# FILE PATH VARIABLES - Automatically resolved
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SUBMITTED_IDS_FILE = os.path.join(BASE_DIR, 'submitted_ids.txt')
HARDIK_FILE = os.path.join(BASE_DIR, "..", 'data', 'hardik', 'task_details.txt')
ARPIL_FILE = os.path.join(BASE_DIR, "..", 'data', 'arpil', 'task_details.txt')
SUJAL_FILE = os.path.join(BASE_DIR, "..", 'data', 'sujal', 'task_details.txt')
OUTPUT_FILE = os.path.join(BASE_DIR, 'combined_tasks.csv')
# ==========================================

def parse_worker_file(filepath, worker_name):
    """Parses a worker's text file and extracts Task ID, Stage UUID, and Minutes."""
    worker_data = {}
    if not os.path.exists(filepath):
        print(f"⚠️ Warning: File not found: {filepath}")
        return worker_data

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Regex pattern updated to catch both "Minute" and "Minutes" (the 's?' makes the 's' optional)
    pattern = r"Task ID:\s*([a-f0-9\-]{36}).*?\nStage UUID:\s*([a-f0-9\-]{36})\nMinutes?\s*:\s*(\d+)"
    matches = re.finditer(pattern, content, re.IGNORECASE)
    
    for match in matches:
        task_id = match.group(1).strip()
        worker_data[task_id] = {
            'Worker': worker_name,
            'Stage UUID': match.group(2).strip(),
            'Minutes': match.group(3).strip()
        }
    return worker_data

def parse_submitted_ids(filepath):
    """Parses the main submitted IDs file to get Date, Status, and Task ID."""
    submitted_data = []
    if not os.path.exists(filepath):
        print(f"⚠️ Warning: File not found: {filepath}")
        return submitted_data

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Regex pattern to capture Seq Number, Date, Status, and Task ID
    pattern = r"(\d+)\n-\s*(.*?)\n-\s*(.*?)\n-\s*([a-f0-9\-]{36})"
    matches = re.finditer(pattern, content)
    
    for match in matches:
        submitted_data.append({
            'ID Num': match.group(1).strip(),
            'Date': match.group(2).strip(),
            'Status': match.group(3).strip(),
            'Task ID': match.group(4).strip()
        })
    return submitted_data

def main():
    # 1. Parse worker files
    print("Parsing worker files...")
    all_worker_tasks = {}
    all_worker_tasks.update(parse_worker_file(HARDIK_FILE, 'Hardik'))
    all_worker_tasks.update(parse_worker_file(ARPIL_FILE, 'Arpil'))
    all_worker_tasks.update(parse_worker_file(SUJAL_FILE, 'Sujal'))

    # 2. Parse submitted IDs file
    print("Parsing submitted IDs...")
    submitted_tasks_list = parse_submitted_ids(SUBMITTED_IDS_FILE)
    
    # Convert submitted list to a dictionary keyed by Task ID for easy lookup
    submitted_tasks_dict = {task['Task ID']: task for task in submitted_tasks_list}

    if not submitted_tasks_list and not all_worker_tasks:
        print("❌ Error: No tasks found in any files. Check your file paths.")
        return

    # 3. Two-Way Correlation: Get EVERY unique Task ID from both sources
    print("Correlating data from all sources...")
    all_unique_task_ids = set(submitted_tasks_dict.keys()).union(set(all_worker_tasks.keys()))
    
    combined_results = []
    
    for task_id in all_unique_task_ids:
        # Grab data if it exists in either dictionary
        sub_info = submitted_tasks_dict.get(task_id, {})
        worker_info = all_worker_tasks.get(task_id, {})
        
        combined_row = {
            'Task ID': task_id,
            'ID Num': sub_info.get('ID Num', 'N/A (Not in Submitted)'),
            'Date': sub_info.get('Date', 'N/A'),
            'Status': sub_info.get('Status', 'N/A'),
            'Worker': worker_info.get('Worker', 'Unassigned/Not Found'),
            'Minutes': worker_info.get('Minutes', 'N/A'),
            'Stage UUID': worker_info.get('Stage UUID', 'N/A')
        }
        
        combined_results.append(combined_row)

    # Sort results so the numbered ones appear first, followed by the "Not in Submitted" ones
    def sort_key(row):
        id_num = row['ID Num']
        if id_num.isdigit():
            return (0, int(id_num))
        return (1, id_num)
        
    combined_results.sort(key=sort_key)

    # 4. Export to CSV
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    # Reordered fieldnames to make it read nicely in Excel
    fieldnames = ['ID Num', 'Worker', 'Status', 'Minutes', 'Date', 'Task ID', 'Stage UUID']
    
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in combined_results:
            writer.writerow(row)

    print(f"\n✅ Success! Correlated a total of {len(combined_results)} unique tasks.")
    print(f"Data has been saved to:\n{OUTPUT_FILE}")

if __name__ == "__main__":
    main()