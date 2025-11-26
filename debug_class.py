import inspect
import automated_release_notes
from automated_release_notes import AutomatedReleaseNotes

print("Checking AutomatedReleaseNotes class attributes:")
for name, member in inspect.getmembers(AutomatedReleaseNotes):
    print(f"  {name}: {type(member)}")

print("\nChecking for tabs in file:")
with open('automated_release_notes.py', 'r') as f:
    lines = f.readlines()
    for i, line in enumerate(lines):
        if '\t' in line:
            print(f"  Line {i+1} contains tab characters")

print("\nChecking create_release_note_for_story:")
if hasattr(AutomatedReleaseNotes, 'create_release_note_for_story'):
    print("  Found create_release_note_for_story")
else:
    print("  create_release_note_for_story NOT FOUND in class")

print("\nChecking save_release_notes_locally:")
if hasattr(AutomatedReleaseNotes, 'save_release_notes_locally'):
    print("  Found save_release_notes_locally")
else:
    print("  save_release_notes_locally NOT FOUND in class")
