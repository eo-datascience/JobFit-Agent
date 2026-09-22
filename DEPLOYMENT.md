# Deploying JobFit Agent

After this, the digest arrives every Monday morning on its own. Your laptop does
not need to be on.

## How it works

There are two repositories.

**JobFit-Agent** (public) holds the code only.

**jobfit-state** (private) holds everything personal: your CV, the roles already
sent, what was recommended, your application outcomes and the skill history.

Every Monday at 07:00 UTC, GitHub Actions checks out both, runs the weekly job,
and commits the updated state back to the private repository. Your laptop keeps
its own copy of the private repository, which is where you record outcomes.

The two sides never edit the same file, so syncing them can never conflict:

| Who writes it | Files |
|---|---|
| You, on your laptop | `cv.yml`, `data/outcomes.json`, `data/weights.json` |
| The Monday job | `data/sent_postings.json`, `data/recommendations.json`, `data/skill_history.json` |

## One time setup

Every command below runs in Windows Command Prompt. Replace `<parent folder>`
with the folder that contains your `jobfit-agent` code folder, and
`<your-username>` with your GitHub username.

### Step 1. Create the private repository

Go to github.com/new.

Set the name to exactly `jobfit-state`. The workflow looks for that name.

Select **Private**. This matters more than anything else in this guide.

Do not tick README, .gitignore or licence. Click **Create repository**.

### Step 2. Move your state into it

Open Command Prompt and go to the folder that contains your project:

```
cd "<parent folder>"
```

Create the state folder next to the code folder, and copy your CV and data in:

```
mkdir jobfit-state
copy jobfit-agent\cv.yml jobfit-state\
xcopy jobfit-agent\data jobfit-state\data\ /E /I
```

Then push it to the private repository:

```
cd jobfit-state
git init
git add .
git commit -m "Initial state"
git branch -M main
git remote add origin https://github.com/<your-username>/jobfit-state.git
git push -u origin main
```

Refresh the jobfit-state page on GitHub. You should see `cv.yml` and a `data`
folder, and the padlock showing it is private.

### Step 3. Point your laptop at it

Go back to the code folder and open your `.env`:

```
cd ..\jobfit-agent
notepad .env
```

Add this line at the bottom, then save:

```
JOBFIT_STATE_DIR=../jobfit-state
```

It is a relative path, meaning "the jobfit-state folder next to this one". That
avoids problems with the space in "JobFit Agent" and with Windows backslashes.

Check it worked. This should list your recorded roles, now read from the private
repository:

```
python run_outcomes.py list
```

### Step 4. Create a token for the workflow

The workflow needs permission to write to jobfit-state, and nothing else.

On GitHub go to **Settings**, then **Developer settings**, then **Personal access
tokens**, then **Fine-grained tokens**, then **Generate new token**.

Name: `jobfit-state-writer`

Expiration: one year. GitHub will email you before it expires.

Repository access: **Only select repositories**, then choose `jobfit-state`.

Permissions: under **Repository permissions**, set **Contents** to **Read and
write**. Leave everything else as it is.

Click **Generate token** and copy it straight away. It is only shown once.

### Step 5. Add the secrets

Go to your public **JobFit-Agent** repository on GitHub, then **Settings**, then
**Secrets and variables**, then **Actions**, then **New repository secret**.

Add these six, one at a time. The names must match exactly.

| Name | Value |
|---|---|
| `STATE_REPO_TOKEN` | the token from step 4 |
| `ADZUNA_APP_ID` | from your `.env` |
| `ADZUNA_APP_KEY` | from your `.env` |
| `REED_API_KEY` | from your `.env` |
| `RESEND_API_KEY` | from your `.env` |
| `DIGEST_TO_EMAIL` | the email address your Resend account uses |

Secrets are encrypted, never shown in logs, and not visible to anyone viewing the
public repository.

### Step 6. Push the code

```
git rm --cached data/skill_history.json
git add .
git commit -m "Deployment: scheduled weekly job with private state"
git push
```

The first line removes the old skill history from the public repository. The file
stays on your laptop; it just stops being published.

### Step 7. Test it by hand

On GitHub, open **JobFit-Agent**, then the **Actions** tab, then **Weekly digest**
on the left, then **Run workflow**.

Tick **Preview only** first and run it. This does everything except send the
email or record anything, so it is safe to repeat. Watch it go green.

Then run it again with Preview unticked. The digest should arrive, and a new
commit should appear in jobfit-state.

After that, it runs every Monday by itself.

### Step 8. Connect the site to Netlify

The weekly job commits a fresh snapshot to this repository every Monday, and
Netlify rebuilds the site whenever that happens. No Netlify token is needed
anywhere, because Netlify pulls from GitHub rather than the workflow pushing
to Netlify.

Sign in at netlify.com with GitHub, choose **Add new site**, then **Import an
existing project**, and pick the **JobFit-Agent** repository.

Netlify reads `netlify.toml` from the repository, so the build settings should
already be filled in: base `frontend`, command `npm ci && npm run build`,
publish directory `dist`. Leave them as they are and deploy.

The first build may show an empty state saying no snapshot has been published.
That is correct until the weekly job runs once. Trigger it by hand from the
Actions tab and the site fills in a minute later.

## Working on the site locally

```
cd frontend
npm install
npm run dev
```

The site reads `frontend/public/data/dashboard.json`. For real data, run
`python run_weekly.py --export-only` from the project root. For synthetic data
that needs no API keys, run `python scripts/make_sample_data.py`, which writes a
separate gitignored file that only the development server reads, so invented
postings can never reach the live site.

## Every week

When you apply to a role or hear back, record it on your laptop. Pull first so
you have the latest recommendations, and push afterwards so Monday's run sees it:

```
cd "<parent folder>\jobfit-state"
git pull
cd ..\jobfit-agent
python run_outcomes.py list
python run_outcomes.py record reed:12345678 applied
cd ..\jobfit-state
git add .
git commit -m "Outcomes"
git push
```

## Things worth knowing

**GitHub pauses schedules on quiet repositories.** If the public repository gets
no commits for 60 days, GitHub disables scheduled workflows on it. The weekly job
commits to jobfit-state, not here, so this can happen even while everything is
working. GitHub emails you first, and re-enabling it is one click in the Actions
tab. Any push to JobFit-Agent also resets the clock.

**Failures email you.** If a run fails, for example because a job board is down
or a key has expired, GitHub marks it red and emails you. A failed send never
marks roles as sent, so they are simply offered again the following week.

**The token expires after a year.** When it does, generate a new one as in step 4
and replace `STATE_REPO_TOKEN`.
