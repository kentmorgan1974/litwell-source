# Contributing to Litwell

Thanks for your interest. Litwell is a small, free, open-source tool; fixes and improvements are welcome.

## Ground rules

- **Free only.** No paid APIs or subscriptions. Optional features may use free keys (USPTO, EPO, NCBI, OpenAlex).
- **Works on Windows and Mac with nothing extra to install.** Optional features (such as AI triage) must fail gracefully with a one-line note in the Status box.
- **General purpose.** Nothing specific to a company, client or person. No email addresses, API keys, tokens or personal paths in code, defaults, tests or examples.
- **Private by design.** Queries go only to the public sources the user ticks; nothing is collected.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m unittest discover -s tests
python app.py
```

## Making a change

1. Keep the tests passing and add one for what you change. Tests are offline (fake sources), so they run in about a second.
2. Every change that affects users bumps `__version__` in `litsearch/__init__.py` and adds an entry to `CHANGELOG.md`.
3. New source files carry the two-line license header used by the others.
4. If you change a column or scoring rule, update the Glossary in `litsearch/excel_writer.py` and the guide (`docs/guide/`).
5. Open a pull request describing what changed and how you checked it.

## Reporting a problem

Open an issue with what you searched (the fields and ticked sources), what you expected, and the lines from the Status box. Please do not paste API keys.

## License

By contributing you agree that your contribution is licensed under the Apache License, Version 2.0, like the rest of the project.
