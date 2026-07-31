# HackerOne

- Read the current program policy; it owns exact assets, rates, exclusions,
  tester identity, and request marker format.
- Resolve the HackerOne username from local configuration. Use the
  `{username}@wearehackerone.com` alias only when that program requires it.
- Apply the required request marker to CLI and browser traffic; never invent a
  header format when the program states one.
- Default reviewer-facing reports to English.
- Package one self-contained vulnerability per directory.
- Keep internal finding IDs, credentials, complete tokens, unrelated recon, and
  absolute operator paths out of submissions.
- Every evidence path named in a report must exist inside that package.
- Load validation and reporting Skills only during SHIP.
