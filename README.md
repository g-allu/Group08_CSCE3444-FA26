# CSCE3444_Project

Group 8

Project Idea: An app that translates ASL to English in real time to assist conversations
Team role:

1. Team lead : Gnaneswar
2. Frontend Developer : Tanya
3. Backend Developer : Sajol Kumar

Project Board Link: https://github.com/users/g-allu/projects/2

Current Status: Initial project planning and repository setup completed.

Intial recognition status: "A, B, C, L, Y"
Needs more testing of these letters.
Models has to be trained on the rest of the letters.

# Setup Instructions:

**NEED PYTHON 3.12 or Greater**

1. Clone the repository
   `git clone https://github.com/g-allu/Group08_CSCE3444-FA26.git`

2. Enter the folder and create a **virtual environment named `.venv`** using Python 3.12 or newer.

3. Run the following commands from the project folder. They use `.venv` directly, so activation is not required:

### macOS / Linux

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py --port 5001
```

### Windows (PowerShell or Command Prompt)

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py --port 5001
```

4. Open the **http://localhost:5001**, click start camera and allow camera access. Show one hand and hold supported letter infront of the camera. Click add letter to add to transcript. You can stop the camera wherenever you want.

5. To stop the app go to the terminal and press **Ctrl+C**
