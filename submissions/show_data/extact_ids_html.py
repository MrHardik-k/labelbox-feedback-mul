from bs4 import BeautifulSoup

def extract_tasks_to_file(input_html_file, output_txt_file):
    # Read the HTML file
    try:
        with open(input_html_file, 'r', encoding='utf-8') as file:
            html_content = file.read()
    except FileNotFoundError:
        print(f"Error: Could not find '{input_html_file}'. Please make sure the file exists.")
        return

    # Parse the HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Find all table rows
    rows = soup.find_all('tr')
    
    tasks = []
    count = 1
    
    for row in rows:
        cells = row.find_all('td')
        
        # We only want rows that actually contain task data (at least 6 columns)
        if len(cells) >= 6:
            # 1. Extract Date (First column, first div)
            date_div = cells[0].find('div', class_='font-medium')
            if not date_div:
                continue
            date = date_div.text.strip()
            
            # 2. Extract Status (Fifth column, span)
            status_span = cells[4].find('span')
            if not status_span:
                continue
            status = status_span.text.strip()
            
            # 3. Extract Task ID (Sixth column, button title attribute)
            button = cells[5].find('button')
            if not button or not button.has_attr('title'):
                continue
                
            title_text = button['title']
            if "Copy Task ID:" in title_text:
                # Split the text to just get the ID part
                task_id = title_text.split("Copy Task ID:")[1].strip()
                
                # Format the output exactly as requested
                task_entry = f"{count}\n- {date}\n- {status}\n- {task_id}\n"
                tasks.append(task_entry)
                count += 1

    # Write the formatted data to the output text file
    with open(output_txt_file, 'w', encoding='utf-8') as output_file:
        output_file.write("\n".join(tasks))
        
    print(f"Success! Extracted {count - 1} tasks and saved them to '{output_txt_file}'.")

# Run the function
# Make sure your HTML is saved in 'input.html' in the same directory
extract_tasks_to_file('input.html', 'submitted_ids.txt')