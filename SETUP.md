# Setting up the Mentor check-in app (about 30 to 45 minutes the first time)

You will make three free accounts, upload the app's files, and connect them. You do not need to install anything or use a terminal.

**Use practice data only.** Do not put real Mentor information into this prototype.

## What each account does
| Account | What it is for |
|---|---|
| GitHub | Stores the app's files |
| Streamlit Community Cloud | Runs the app as a website |
| Supabase | Stores questions, answers, and users so they are not lost when the app sleeps |

## Part 1: GitHub (store the files)
1. Go to github.com and create a free account.
2. Click **New repository**. Name it `fotc-checkin`. Choose **Public** (it holds no secrets or real data; passwords go in Part 3). Tick **Add a README**, then **Create repository**.
3. On your computer, unzip `fotc_app.zip`.
4. In the repository, click **Add file > Upload files**. Drag in **everything inside the unzipped folder**, then click **Commit changes**.
   - These files must be at the top level of the repository: `app.py`, `db.py`, `auth.py`, `content.py`, `views.py`, `seed_content.json`, `requirements.txt`.
   - Folders and files that start with a dot (`.streamlit`, `.gitignore`) are hidden on some computers. The `.streamlit/config.toml` file only sets colors, so the app still works without it.

## Part 2: Supabase (store the data)
1. Go to supabase.com and create a free account. Click **New project**.
2. Name it, choose a region near you, and create a strong database password. **Save that password somewhere safe.**
3. Wait for the project to finish setting up.
4. Click **Connect** at the top of the project page and find the **Session pooler** connection string. It looks like `postgresql://postgres.xxxx:[YOUR-PASSWORD]@aws-0-....pooler.supabase.com:5432/postgres`. Copy it and replace `[YOUR-PASSWORD]` with your database password.
   - If your password contains symbols such as `@` or `#`, make a new, simpler password (letters and numbers) so the string works as written.
5. Free Supabase projects pause after a week with no activity and have no automatic backups. Open the app a few times a week while you are using it, and copy out anything you care about.

## Part 3: Streamlit Community Cloud (run the app)
1. Go to share.streamlit.io and sign in with your GitHub account.
2. Click **Create app**. Choose your `fotc-checkin` repository, branch `main`, and main file `app.py`.
3. Before deploying, open **Advanced settings > Secrets** and paste this, using your own values:
   ```
   DATABASE_URL = "paste-your-supabase-session-pooler-string-here"
   DEMO_PASSWORD = "choose-a-password-for-the-demo-accounts"
   ```
4. Click **Deploy**. The first start takes a few minutes while it installs packages.
5. When the app opens, sign in as `admin` with the password you chose in `DEMO_PASSWORD`.

If you skip the secrets, the app still runs on a temporary local database with the demo password `practice123`, but your edits disappear whenever the app restarts, and the login page shows the demo password to everyone.

## Part 4: First checks
1. Sign in as `admin` and open **Questions**. Change the wording of one question, click **Review and publish**, read the warning, and publish.
2. Sign out. Sign in as `mentor1` and take the check-in. You should see your new wording.
3. Test the microphone on a spoken question. Allow the browser's microphone request.
4. Sign back in as `admin` and open **Responses** to see the answers. Play a recording, then delete it.
5. Open **Activity log** to see what was recorded.

## Things to know
- Free Streamlit apps go to sleep after 12 hours without visitors. Anyone with access can wake the app with the button on the page.
- The demo accounts are `admin`, `leader`, `mentor1`, `mentor2` (exit interview), and `mentor3` (first-year Mentor). Add or remove people on the **People** page.
- `DEMO_PASSWORD` sets the demo accounts' password only the first time the app starts. After that, change passwords on the **People** page.
- Recordings stay in the database until an admin deletes them. Transcription and AI tagging are the next phase.
- Free hosting and databases are for the prototype only. Before real Mentor data goes in, Friends of the Children needs to approve the hosting, consent wording, access rules, backups, and data agreement.
- If something fails, copy the exact error message and send it to your helper.
