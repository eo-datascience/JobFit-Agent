// A sample CV, so anyone can see the feature work without having a data CV.
//
// The most likely visitor to this page is a recruiter, and most recruiters do
// not have a data CV to hand. Without this they upload their own, correctly
// get nothing, and never see what the page actually does.
//
// The person is invented. The skills are ordinary for a junior data role, so
// the matches that come back are realistic rather than flattering.

export const SAMPLE_CV_NAME = 'a sample junior data CV'

export const SAMPLE_CV = `
Sam Whitfield
Junior Data Analyst, London

Summary
Junior analyst with two years of experience turning messy operational data into
reporting that teams actually use. Comfortable owning a question end to end,
from pulling the data to presenting what it means.

Experience

Data Analyst, Harbourline Logistics, 2024 to present
Rebuilt weekly depot reporting in SQL and Power BI, replacing a manual
spreadsheet process that took a day each week.
Wrote Python scripts using pandas and NumPy to clean and join delivery records
from three separate systems.
Built a simple forecasting model with scikit-learn to flag depots likely to
miss their service targets, and reported results to operations managers.
Ran A/B testing on two versions of a driver notification and reported the
outcome with confidence intervals.

Junior Analyst, Fenwick Retail Group, 2023 to 2024
Used SQL and Excel for sales and stock reporting across two hundred stores.
Automated a monthly reconciliation in Python, cutting it from six hours to
twenty minutes.
Version controlled analysis in Git and documented it for the wider team.

Education
BSc Mathematics and Statistics, 2023

Skills
Python, SQL, pandas, NumPy, scikit-learn, Power BI, Excel, Git, Statistics,
A/B testing, data cleaning, reporting
`.trim()
