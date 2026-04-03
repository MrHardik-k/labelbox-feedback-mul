import os

# Folders to process
folders = ["input", "output"]

for folder in folders:
    if os.path.exists(folder):
        for filename in os.listdir(folder):
            if filename.endswith(".txt"):
                file_path = os.path.join(folder, filename)
                
                # Empty the file
                with open(file_path, "w") as f:
                    pass
                
                print(f"Emptied: {file_path}")
    else:
        print(f"Folder not found: {folder}")

print("Done!")