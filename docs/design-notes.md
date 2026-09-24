# Design notes

The reasoning behind the parts of JobFit Agent that are not obvious, and the
mistakes that shaped them. Written for anyone reading the code rather than for
someone deciding whether to.

For what the system is and how to run it, see the [README](../README.md).
For the twelve bugs found by running it against live data, see the
[engineering log](https://jobfit-agent.netlify.app/how-it-works#log).

### What it does

Every Monday, with no machine of mine running, the system pulls live postings from Reed and
Adzuna, removes the same role listed twice, turns away the ones that are not really data roles,
extracts the skills each remaining posting asks for, scores them against a CV, emails a shortlist,
and republishes the public dashboard above.

On the site you can pick a sample profile and watch every score change, or upload your own CV and
have it scored against this week's real roles. The file is read in your browser and never
uploaded, stored or sent anywhere.

The weekly email covers data roles only and stays that way. The site also carries a shallower
sweep of software engineering and product roles, so a visitor from either of those fields can
score their own CV too. Nothing from that sweep reaches the email, the forecasting or the
outcome monitor.

Almost every design decision here was forced by real data rather than planned. The
[engineering log](https://jobfit-agent.netlify.app/how-it-works#log) records twelve bugs that only
appeared once the system met live postings, each of which now has a test.

### Why two job sources

Reed and Adzuna are not used for redundancy. They do different jobs.

Reed is the only one of the two that can supply a complete job description,
which the extraction agent needs in order to parse requirements at all. Its
search endpoint returns only a snippet, so the full text is fetched separately
from its detail endpoint, one request per posting. Adzuna returns excerpts with
no detail endpoint, but exposes salary histograms and regional trend data that
Reed does not, which the forecasting agent needs. Adzuna salaries are frequently
modelled rather than employer stated, so postings carry a `salary_is_predicted`
flag and scoring weights a stated range above an inferred one.

Where the same role appears on both, the record carrying the full description
wins. This is asserted directly in the test suite rather than assumed.

### How extraction stays grounded

Skill detection is deterministic. Every skill is matched literally against the
posting text from a curated taxonomy, and the matched span is kept as evidence,
so a skill cannot be reported unless it genuinely appears. Named entity
recognition was considered and rejected, because general purpose NER models are
not trained on technical skill vocabulary and tag company names as skills.

The language model is reserved for judgements that need one, such as seniority
and whether a requirement is essential rather than desirable. Everything it
returns is checked against the source afterwards, and any skill it claims that
does not appear in the posting is dropped rather than trusted. A failed or
malformed model response leaves the deterministic extraction intact and sets a
rejection flag, so a broken API call never costs a posting.

Keyword search returns roles that merely mention the search terms. An "AI
Creative Director" matched a search for "data scientist" because its text was
saturated with the word AI, yet named no technical tooling at all. A relevance
gate now classifies each posting as in domain or out of domain, using the title
first and the extracted skills as a fallback. Out of domain postings stay in the
database, because the forecasting agent benefits from a wider view of the
market, but they never reach fit scoring or the weekly digest and never cost a
model call.

Postings carry a confidence tier. Reed postings with a full description are
extracted at full confidence. Adzuna excerpts are extracted on a reduced basis
and marked partial, which tells the scoring agent that a missing skill proves
nothing rather than counting against the role.

### How scoring works

Four weighted components: skills at 0.45, seniority at 0.25, salary at 0.15 and
location at 0.15. Essential skills count for more than desirable ones, because
missing a stated requirement is a different thing from missing a bonus.

Adjacent experience earns partial credit through explicit skill families. A
candidate who knows Databricks is not a Snowflake match, but they are much
closer than someone who knows neither, and the two sit in the same warehouse
family. The original design called for sentence transformer embeddings here.
That was dropped, because both the CV and the posting are already normalised
through the same taxonomy, so synonyms match exactly and embeddings would have
added a 90MB download and a CI dependency for no gain. Families also have the
advantage that a partial match can be explained in a sentence, where an
embedding similarity of 0.73 cannot.

On a partial extraction the skills component is removed entirely and its weight
is redistributed across the others, because an Adzuna excerpt that never
mentions Python is not a role that does not want Python.

That redistribution creates a trap, and running the agent on live postings
exposed it. Seniority, salary and location are all easy to score highly on, so
spreading the skills weight across them inflates provisional scores. Two
excerpt only postings scored 95 and pushed a Reed role with five of six skills
matched down to third place. Knowing less was producing a better score.

Provisional scores are therefore ranked in a separate tier and can never
outrank a fully analysed role, however high the number. Tiering is used rather
than an arbitrary discount because the honest claim is not that a provisional
score should be marked down by some amount, only that it is not comparable in
the first place.

Every line of the explanation is built from a field the scoring step computed.
Nothing in it is generated, so the explanation and the score cannot drift apart.

### How forecasting avoids inventing a trend

A new deployment has no history, so nothing can be forecast until the pipeline
has run weekly for a month or more. History is therefore reconstructed from the
dates postings were published, which job boards supply and which cover roughly
the last one to two months.

That reconstruction carries an artefact that would have invalidated every
result. Older postings get filled and delisted, so the number surviving from a
given week falls the further back you look. Counting mentions per week would
show every skill rising toward the present, in every run, regardless of what
the market was doing. The series therefore records the share of each week's
postings mentioning a skill rather than the raw count, which is unaffected by
how many of that week's postings are still listed.

Weeks with fewer than eight surviving postings are dropped, because two
postings makes every skill either nought or fifty percent.

The first live run of this agent was wrong in three separate ways, and each is
now covered by a regression test. The dropped weeks were being put back as
zeros by the gap filling written for recorded snapshots, so ten real
measurements became thirty five weeks of mostly invented zeros. Gap filling is
correct for real weekly runs, where a missing skill genuinely had no demand,
and wrong for reconstructed history, where a missing week simply could not be
measured. It now applies only to the former.

The run also happened on a Monday, so the current week held roughly one day of
postings and most skills had not appeared in it yet. That partial week was
being read as current demand, which made almost everything look as though it
had collapsed. The week in progress is now excluded, and the baseline is a
trailing three week mean rather than the single latest point.

Finally, a skill with no recent mentions was being reported as rising by one
hundred percent, which has no meaning. Growth from zero is now labelled as
emerging, without a figure.

A second live run found one more. Kubernetes was reported as rising by 155
percent at three percent of postings, which on this volume is roughly one
posting a week. The guard that rejects thin skills required five mentions, but
in reconstructed mode it was summing percentage shares rather than counting
postings, and eight weeks at three percent sums to twenty four. The guard now
counts the real postings behind a skill and requires twenty four of them before
a share trend is reported.

Share series are also classified and displayed in percentage points rather than
relative change. On a small base a single extra posting clears any percentage
threshold, which is how one listing became a 155 percent surge.

A third run then reported Python falling twenty points in a month, from 38 to
18 percent of postings, which is not a plausible market move. One of the nine
usable weeks was from January, eight months before the others. Postings that
survive that long are not a random sample of their week: they are
disproportionately the roles nobody could fill, which skew specialist and
senior. Share corrects for how many postings survive, but not for which ones,
so that week carried a different skill mix and dragged every trend line toward
it. The linear fallback compounded this by regressing on list position rather
than elapsed time, placing January beside July as if they were consecutive.

Reconstruction now only looks back twelve weeks, and regression uses real
elapsed time. Reproducing the run with a steady 38 percent share plus one stale
week gave a twelve point fall before the fix and no change after it.

This is the limit of reconstructed history. It can correct for survivorship in
volume but not fully in composition, which is why recorded snapshots replace it
as soon as enough of them exist.

The fourth run swung the other way entirely, with every major skill rising by
ten to eighteen points. When every skill moves in the same direction by a
similar amount, the cause is the denominator rather than the skills. Full Reed
descriptions yield eight or ten skills each, while Adzuna excerpts yield one or
two, so as the proportion of excerpts in a week changed, every skill's share
moved with it. Only fully described postings now contribute to the share.

The report also checks itself. If at least 85 percent of trending skills move
the same way at once, it warns that this is more likely a shift in the data than
in demand. Real markets rarely move every skill together, and this check would
have flagged both the falling run and the rising one.

Observation frequency and forecast frequency are both weekly, so the mismatch
that ruins forecasts elsewhere cannot arise here. Where Prophet is not
installed, which is common on Windows given its compiled backend, the agent
degrades to a least squares trend and labels the result rather than producing
nothing.

### How the digest acts safely without approval

The digest is the first agent that acts rather than reports. It emails a ranked
shortlist every week with no approval step, so the failure modes that matter
are the ones a person would never notice.

A posting is recorded as sent only after the send succeeds. Recording first
would mean a failed send permanently hides those roles with no trace of why,
which for a tool meant to surface opportunities is the worst possible failure.
A corrupted record of sent postings fails loudly rather than being treated as
empty, since that would resend everything.

Every value from a job board is escaped before it enters the email, and links
are only rendered for http and https addresses. Titles and company names come
from APIs this system does not control.

An empty digest is not sent. An email saying nothing new trains the reader to
ignore the sender, which undermines the weeks when something matters.

Provisional roles appear in their own section with greyed scores, so a high
number built without a skills comparison cannot be read as a stronger match
than a fully analysed role above it. The email uses table layout rather than
inline styling, because Outlook and several webmail clients ignore the latter.

Email is sent through Resend by default. SendGrid was the original choice, but
it retired its permanent free plan in May 2025, leaving a sixty day trial and
then a paid plan, which does not suit a job that sends one email a week
indefinitely. Resend has a permanent free tier of three thousand emails a month.
Every provider sits behind the same Sender interface, so the switch required
one new class and no changes anywhere else in the agent. SendGrid remains
available as an alternative.

Without a verified domain, Resend sends from its shared test address, which
only delivers to the email the account was created with. For a digest sent to
its own author that costs nothing, and the error message says so explicitly if
the recipient is set to anyone else.

Both providers are called over plain HTTP rather than through their SDKs, so
every send path is tested with the same mock transport as the job board
clients, with no key and no network.

### The public dashboard

Every run publishes a snapshot that a React and TypeScript site renders: this
week's postings as a narrowing funnel, a filterable list of roles with the
reasoning behind each score, what the market is asking for, and a written record
of the twelve bugs that real data exposed.

Visitors choose a sample profile, and every figure recalculates, including the
funnel and which field's roles are shown. The scoring is the real scorer, so a
junior data scientist and a junior product manager get genuinely different
shortlists from the same week's postings.

Visitors can also upload their own CV and have it scored against the same live
roles. The file is read, parsed and scored entirely in the browser using the
PDF and Word parsers loaded on demand, and is never uploaded, stored or sent
anywhere. To keep the two implementations honest, the taxonomy, the skill
categories and the weights are published in the snapshot and read by the
browser, so only the arithmetic exists twice, and a test asserts the published
rules still match the ones the agent uses.

Nothing personal reaches it. The export takes postings, extractions and public
sample profiles, and is never handed a real CV, the roles already sent, or any
application outcome, so privacy is a property of the function's inputs rather
than something to remember. Full job descriptions are not republished either.
None of the sample profiles carries a salary floor, since a real one is private.

### Deployment

The digest runs every Monday on GitHub Actions, with no machine of mine
involved. See [DEPLOYMENT.md](../DEPLOYMENT.md) for setup.

The design problem was memory. The system remembers which roles it has sent,
what it recommended, application outcomes and skill history, and a scheduled
runner starts from a blank machine every time. That memory also has to be shared
with a laptop, where outcomes are recorded, and some of it is private, since it
records where the candidate applied and how each application went.

State therefore lives in a separate private repository. This public repository
holds code only, and the scheduled job checks out both, then commits changes
back to the private one. That separates code from personal data structurally,
rather than relying on remembering what not to commit, and every week's state
becomes a versioned commit with a full history of what was recommended and when.

The laptop and the scheduled job never write the same file, so syncing between
them cannot conflict. The candidate owns the CV, outcomes and weights; the
scheduled job owns the sent record, recommendations and skill history.

The weekly job fetches postings once and feeds every step from that fetch.
Running the forecast and the digest separately would have made roughly four
hundred redundant Reed requests a week. It also exits non zero when nothing was
ingested, so a week where both job boards were down fails visibly instead of
passing green with no email sent.

## Notes on quotas

Adzuna's free tier is roughly 1,000 calls a month, about 33 a day. Its calls are
batched for trend data rather than polled per posting, and Reed carries the per
posting detail. The wider sweep across software engineering and product is
fetched shallower than the primary field for the same reason: each posting costs
one Reed detail call.
