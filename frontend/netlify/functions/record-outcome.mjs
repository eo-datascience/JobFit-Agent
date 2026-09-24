// Recording an outcome from the site.
//
// The browser cannot write to the private state repository: a token that can do
// that would have to be in the page, where anyone could read it. So the token
// lives here instead, in a Netlify environment variable, and the browser only
// ever talks to this function.
//
// The function does not commit anything itself. It triggers the Record an
// outcome workflow that already exists, which checks out the state repository,
// runs the outcome monitor and commits the result. One code path records an
// outcome whether it came from the site or from the Actions tab.
//
// Required environment variables, set in Netlify:
//   GITHUB_TOKEN   fine grained token with Actions read and write on the code repository
//   GITHUB_REPO    for example eo-datascience/JobFit-Agent
//   RECORD_SECRET  a long random string, entered once in the browser

const OUTCOMES = new Set(['applied', 'response', 'interview', 'offer', 'rejected'])
const KEY_PATTERN = /^[a-z]+:[A-Za-z0-9_-]{1,64}$/

/** Compare without leaking how much of the secret was right through timing. */
function sameSecret(given, expected) {
  if (typeof given !== 'string' || given.length !== expected.length) return false
  let diff = 0
  for (let i = 0; i < expected.length; i++) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i)
  return diff === 0
}

const reply = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })

export default async (request) => {
  if (request.method !== 'POST') return reply(405, { error: 'Use POST.' })

  const { GITHUB_TOKEN, GITHUB_REPO, RECORD_SECRET } = process.env
  if (!GITHUB_TOKEN || !GITHUB_REPO || !RECORD_SECRET) {
    // Never name which one is missing: that is a hint to anyone probing.
    return reply(500, { error: 'Recording is not configured on this deployment.' })
  }

  let payload
  try {
    payload = await request.json()
  } catch {
    return reply(400, { error: 'Expected a JSON body.' })
  }

  const { key, outcome, secret } = payload ?? {}

  if (!sameSecret(secret, RECORD_SECRET)) {
    return reply(401, { error: 'That passphrase is not right.' })
  }
  if (!OUTCOMES.has(outcome)) {
    return reply(400, { error: 'Unknown outcome.' })
  }
  // Validated rather than trusted. This value becomes an argument to a workflow
  // that runs a command, so its shape is checked before it goes anywhere.
  if (typeof key !== 'string' || !KEY_PATTERN.test(key)) {
    return reply(400, { error: 'That does not look like a role key.' })
  }

  const response = await fetch(
    `https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/record-outcome.yml/dispatches`,
    {
      method: 'POST',
      headers: {
        authorization: `Bearer ${GITHUB_TOKEN}`,
        accept: 'application/vnd.github+json',
        'x-github-api-version': '2022-11-28',
        'content-type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main', inputs: { key, outcome } }),
    },
  )

  if (response.status === 204) {
    return reply(202, { status: 'recording', key, outcome })
  }

  // Whatever GitHub says stays in the logs. The reply says only that it failed,
  // because the detail can describe the token's permissions.
  console.error('Workflow dispatch failed', response.status, await response.text())
  return reply(502, { error: 'GitHub would not accept that. Check the run log.' })
}

export const config = { path: '/api/record-outcome' }
