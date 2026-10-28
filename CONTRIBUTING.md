# Contributing

Thanks for helping! Bug reports and ideas are the most useful thing you can send. Please use the issue templates, and include the panel version (bottom of the sidebar) and what the console or **Logs → panel/console.log** showed.

## Code contributions

Pull requests are welcome for bug fixes and small improvements. For anything big, open an issue first so we can agree on the approach.

Craftlehem Panel is licensed under the GPL-3.0. coldskiess also sells an optional add-on (Craftlehem Pro) that plugs into the panel. To keep that possible, by sending a pull request you agree that:

1. your contribution is licensed under the GPL-3.0, like the rest of the panel, and
2. coldskiess may also use your contribution under other terms, including in Craftlehem Pro.

If you're not comfortable with point 2, say so in the pull request and it won't be merged into code shared with Pro.

## Running it locally

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
PANEL_CONFIG=./dev-config.yml venv/bin/python run.py add-user admin admin
PANEL_CONFIG=./dev-config.yml venv/bin/python run.py
```

Point `servers[0].dir` in `dev-config.yml` at a test server folder. There's no build step. The frontend is plain HTML, CSS and JS in `static/`.
